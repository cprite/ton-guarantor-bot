"""The escrow state machine.

This module owns every transition a deal can make and is the only place that
moves money. Two invariants shape the code:

* **Authorisation comes from the database, never from the message.** The old
  version of this bot passed user IDs through Telegram callback data, which any
  user could forge. Here a caller supplies its own Telegram ID and the engine
  looks up what that ID is allowed to do.
* **Nothing is paid out twice.** Deposits are credited under a per-deal lock
  and de-duplicated by transaction key; payouts pin a wallet ``seqno`` that is
  persisted before broadcast, so a crash mid-send is resolved by asking the
  chain rather than by guessing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from guarantor.codes import new_deal_code, parse_memo
from guarantor.config import Settings
from guarantor.errors import (
    AddressError,
    DealError,
    DealNotFound,
    DealStateError,
    NotAParticipant,
    SettlementError,
)
from guarantor.escrow.events import Event, Notifier, NullNotifier
from guarantor.escrow.fees import plan_fee
from guarantor.models import (
    Asset,
    AssetKind,
    Deal,
    DealStatus,
    Deposit,
    Settlement,
    Side,
    SideRole,
)
from guarantor.money import format_ton, parse_amount
from guarantor.storage.base import Storage
from guarantor.ton import addresses as addr
from guarantor.ton.client import JettonInfo, TonGateway
from guarantor.ton.deposits import IncomingTransfer, TransferKind
from guarantor.ton.escrow import EXTERNAL_MESSAGE_TTL, EscrowWallet, SentMessage

log = logging.getLogger(__name__)

#: How many times a payout is rebuilt after its external message expires
#: before the deal is handed to a human.
MAX_SETTLE_ATTEMPTS = 5


class EscrowEngine:
    """Creates, funds, settles and refunds deals."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        gateway: TonGateway,
        wallet: EscrowWallet,
        notifier: Notifier | None = None,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._gateway = gateway
        self._wallet = wallet
        self._notifier = notifier or NullNotifier()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------------ setup

    def set_notifier(self, notifier: Notifier) -> None:
        self._notifier = notifier

    @property
    def escrow_address(self) -> str:
        return self._wallet.address

    @property
    def settings(self) -> Settings:
        return self._settings

    # ----------------------------------------------------------------- assets

    def make_ton_asset(self, text: str) -> Asset:
        """Build a TON leg from user input such as ``"2.5"``."""
        amount = parse_amount(text)
        if amount < self._settings.min_deposit_nano:
            raise DealError(f"the smallest tradable amount is {format_ton(self._settings.min_deposit_nano)}")
        return Asset(kind=AssetKind.TON, amount=amount)

    async def jetton_info(self, master: str) -> JettonInfo:
        """Symbol and decimals of a jetton, so the bot can ask for an amount."""
        return await self._gateway.jetton_info(addr.canonical(master))

    async def make_jetton_asset(self, master: str, amount_text: str) -> Asset:
        """Build a jetton leg, resolving decimals and escrow's jetton wallet.

        Both lookups happen now rather than at deposit time: an unknown jetton
        must fail while a person is still looking at the screen, not once their
        tokens are already in the escrow.
        """
        master_address = addr.canonical(master)
        info = await self._gateway.jetton_info(master_address)
        amount = parse_amount(amount_text, info.decimals)
        wallet = await self._gateway.jetton_wallet_of(master_address, self._wallet.address)
        return Asset(
            kind=AssetKind.JETTON,
            amount=amount,
            jetton_master=master_address,
            jetton_symbol=info.symbol,
            jetton_decimals=info.decimals,
            jetton_wallet=wallet,
        )

    async def make_nft_asset(self, nft_address: str) -> Asset:
        """Build an NFT leg after checking the item actually exists on-chain."""
        item = addr.canonical(nft_address)
        owner = await self._gateway.nft_owner(item)
        if owner is None:
            raise DealError("that address is not a readable NFT item on this network")
        if addr.same(owner, self._wallet.address):
            raise DealError("the escrow already owns that NFT; it cannot be part of a new deal")
        return Asset(kind=AssetKind.NFT, nft_address=item)

    def make_offchain_asset(self, description: str) -> Asset:
        """Build a leg the chain cannot verify, settled by the parties."""
        if not self._settings.allow_offchain_assets:
            raise DealError("this operator does not accept off-chain items")
        text = description.strip()
        if not 3 <= len(text) <= 400:
            raise DealError("describe the item in 3 to 400 characters")
        return Asset(kind=AssetKind.OFFCHAIN, description=text)

    # ------------------------------------------------------------ life cycle

    async def create_deal(
        self, user_id: int, username: str | None, give: Asset, want: Asset
    ) -> Deal:
        """Open a deal where the creator gives ``give`` and wants ``want``."""
        if give.kind is AssetKind.OFFCHAIN and want.kind is AssetKind.OFFCHAIN:
            raise DealError("at least one side of a deal must be something the escrow can hold")
        if _same_asset(give, want):
            raise DealError("both sides of the deal are the same thing")

        active = await self._storage.count_active_for_user(user_id)
        if active >= self._settings.max_active_deals_per_user:
            raise DealError(
                f"you already have {active} open deals; finish one before starting another"
            )

        # Reject a fee the deal cannot carry before showing anyone a code.
        plan_fee({SideRole.A: give, SideRole.B: want}, self._settings)

        now = int(time.time())
        deal = Deal(
            code=await self._unique_code(),
            status=DealStatus.OPEN,
            a=Side(role=SideRole.A, asset=give, user_id=user_id, username=username, accepted=True),
            b=Side(role=SideRole.B, asset=want),
            created_at=now,
            updated_at=now,
            expires_at=now + self._settings.open_deal_ttl_seconds,
        )
        await self._storage.put_deal(deal)
        log.info("deal %s created by %s", deal.code, user_id)
        return deal

    async def join_deal(self, code: str, user_id: int, username: str | None) -> Deal:
        """Attach a counterparty to an open deal."""
        async with self._lock(code):
            deal = await self._require(code)
            if deal.status is not DealStatus.OPEN:
                raise DealStateError(_status_complaint(deal))
            if deal.a.user_id == user_id:
                raise DealError("you cannot take both sides of your own deal")
            if deal.expires_at and deal.expires_at < time.time():
                raise DealStateError("this deal has expired")

            active = await self._storage.count_active_for_user(user_id)
            if active >= self._settings.max_active_deals_per_user:
                raise DealError(f"you already have {active} open deals")

            deal.b.user_id = user_id
            deal.b.username = username
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.DEAL_JOINED, deal)
        return deal

    async def accept_deal(self, code: str, user_id: int) -> Deal:
        """The counterparty agrees; the deal starts waiting for deposits."""
        async with self._lock(code):
            deal = await self._require(code)
            side = self._participant(deal, user_id)
            if deal.status is not DealStatus.OPEN:
                raise DealStateError(_status_complaint(deal))
            if side.role is not SideRole.B:
                raise DealError("only the joining party accepts a deal")

            side.accepted = True
            plan = plan_fee({SideRole.A: deal.a.asset, SideRole.B: deal.b.asset}, self._settings)
            deal.fee_nano = plan.total_nano
            for role in (SideRole.A, SideRole.B):
                target = deal.side(role)
                target.fee_deduction = plan.deduct.get(role, 0)
                target.extra_ton_required = plan.surcharge.get(role, 0)

            deal.status = DealStatus.AWAITING_DEPOSITS
            deal.expires_at = int(time.time()) + self._settings.deposit_timeout_seconds
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.DEAL_ACCEPTED, deal)
        return deal

    async def set_payout_address(self, code: str, user_id: int, address: str) -> Deal:
        """Tell the escrow where to send this side's payout.

        Only needed for a side whose own leg is off-chain: everyone else's
        payout address is taken from the wallet that funded the deal.
        """
        async with self._lock(code):
            deal = await self._require(code)
            side = self._participant(deal, user_id)
            if side.asset.kind.is_onchain:
                raise DealError("your payout address is taken from the wallet you deposit with")
            if deal.status not in (DealStatus.OPEN, DealStatus.AWAITING_DEPOSITS):
                raise DealStateError(_status_complaint(deal))
            try:
                side.payout_address = addr.canonical(address)
            except AddressError as exc:
                raise DealError(str(exc)) from exc
            deal.touch()
            await self._storage.put_deal(deal)
        return deal

    async def cancel_deal(self, code: str, user_id: int) -> Deal:
        """Abandon a deal. Only allowed while no money has moved."""
        async with self._lock(code):
            deal = await self._require(code)
            self._participant(deal, user_id)
            if deal.status not in (DealStatus.OPEN, DealStatus.AWAITING_DEPOSITS):
                raise DealStateError(_status_complaint(deal))
            if deal.has_any_deposit:
                raise DealStateError(
                    "funds are already in escrow; wait for the deadline to refund them, "
                    "or open a dispute"
                )
            deal.status = DealStatus.CANCELLED
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.CANCELLED, deal, by=user_id)
        return deal

    async def confirm_offchain(self, code: str, user_id: int) -> Deal:
        """Confirm that the counterparty's off-chain item was received."""
        async with self._lock(code):
            deal = await self._require(code)
            side = self._participant(deal, user_id)
            counterparty = deal.side(side.role.other)
            if counterparty.asset.kind.is_onchain:
                raise DealError("the other side's item is on-chain; the escrow verifies it itself")
            if deal.status is not DealStatus.AWAITING_DEPOSITS:
                raise DealStateError(_status_complaint(deal))
            counterparty.offchain_confirmed = True
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.SIDE_FUNDED, deal, role=counterparty.role.value)
        return await self._settle_if_ready(code)

    async def dispute(self, code: str, user_id: int, reason: str | None = None) -> Deal:
        """Freeze a deal and hand it to the operator."""
        async with self._lock(code):
            deal = await self._require(code)
            self._participant(deal, user_id)
            if deal.status not in (DealStatus.AWAITING_DEPOSITS, DealStatus.FUNDED):
                raise DealStateError(_status_complaint(deal))
            deal.status = DealStatus.DISPUTED
            deal.dispute_reason = (reason or "").strip()[:500] or None
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.DISPUTED, deal, by=user_id)
        return deal

    # -------------------------------------------------------------- deposits

    async def credit_transfer(self, transfer: IncomingTransfer) -> Deal | None:
        """Credit one incoming transfer to whichever deal was expecting it.

        Returns the affected deal, or ``None`` when nothing matched — which is
        reported to the operator rather than silently swallowed.
        """
        if not await self._storage.mark_transfer_seen(transfer.key):
            return None  # already credited on an earlier poll

        match = await self._match(transfer)
        if match is None:
            log.warning(
                "unmatched transfer of %s from %s (%s)",
                transfer.amount,
                addr.shorten(transfer.depositor),
                transfer.tx_hash[:16],
            )
            await self._emit(Event.UNMATCHED_TRANSFER, None, transfer=transfer)
            return None

        code, role = match
        async with self._lock(code):
            deal = await self._storage.get_deal(code)
            if deal is None:
                return None
            if not deal.status.accepts_deposits:
                log.warning("transfer for deal %s arrived in state %s", code, deal.status)
                await self._emit(Event.UNMATCHED_TRANSFER, deal, transfer=transfer)
                return None

            side = deal.side(role)
            self._apply_transfer(side, transfer)
            was_funded = side.funded
            side.funded = side.is_ready
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.DEPOSIT_CREDITED, deal, role=role.value, transfer=transfer)
        if side.funded and not was_funded:
            await self._emit(Event.SIDE_FUNDED, deal, role=role.value)
        return await self._settle_if_ready(code)

    def _apply_transfer(self, side: Side, transfer: IncomingTransfer) -> None:
        """Record a transfer against a side and re-derive what it still owes."""
        kind = {
            TransferKind.TON: AssetKind.TON,
            TransferKind.NFT: AssetKind.NFT,
            TransferKind.JETTON: AssetKind.JETTON,
        }[transfer.kind]

        side.deposits.append(
            Deposit(
                tx_hash=transfer.tx_hash,
                lt=transfer.lt,
                at=transfer.at,
                sender=transfer.depositor,
                kind=kind,
                amount=transfer.amount,
            )
        )
        if side.payout_address is None:
            side.payout_address = transfer.depositor

        # Plain TON first covers the TON leg itself, then any fee surcharge.
        ton_received = sum(d.amount for d in side.deposits if d.kind is AssetKind.TON)
        owed_as_asset = side.asset.amount if side.asset.kind is AssetKind.TON else 0
        side.extra_ton_paid = max(ton_received - owed_as_asset, 0)

    async def _match(self, transfer: IncomingTransfer) -> tuple[str, SideRole] | None:
        """Work out which deal and which side a transfer belongs to.

        NFTs and jettons are matched by the contract that sent the message,
        which no third party can forge; plain TON is matched by the deposit
        memo, which is why every deposit instruction carries one.
        """
        if transfer.kind is TransferKind.NFT:
            deal = await self._storage.find_by_nft(transfer.source)
            if deal is None:
                return None
            for side in deal.sides:
                if side.asset.kind is AssetKind.NFT and addr.same(side.asset.nft_address, transfer.source):
                    return deal.code, side.role
            return None

        if transfer.kind is TransferKind.JETTON:
            return await self._match_jetton(transfer)

        if transfer.value_nano < self._settings.min_deposit_nano:
            return None
        if not transfer.comment:
            return None
        parsed = parse_memo(transfer.comment)
        if parsed is None:
            return None
        code, role_name = parsed
        deal = await self._storage.get_deal(code)
        if deal is None:
            return None
        return code, SideRole(role_name)

    async def _match_jetton(self, transfer: IncomingTransfer) -> tuple[str, SideRole] | None:
        candidates = await self._storage.find_by_jetton_wallet(transfer.source)
        if not candidates:
            return None

        if transfer.comment:
            parsed = parse_memo(transfer.comment)
            if parsed is not None:
                code, role_name = parsed
                role = SideRole(role_name)
                for deal in candidates:
                    if deal.code == code and deal.side(role).asset.jetton_wallet == transfer.source:
                        return code, role

        # No usable memo: only safe when exactly one deal is waiting for this
        # jetton. Otherwise the operator has to sort it out by hand.
        waiting = [
            (deal.code, side.role)
            for deal in candidates
            for side in deal.sides
            if side.asset.jetton_wallet == transfer.source and not side.asset_delivered
        ]
        return waiting[0] if len(waiting) == 1 else None

    # -------------------------------------------------------------- payouts

    async def _settle_if_ready(self, code: str) -> Deal:
        deal = await self._require(code)
        if deal.status is not DealStatus.AWAITING_DEPOSITS or not deal.both_ready:
            return deal

        async with self._lock(code):
            deal = await self._require(code)
            if deal.status is not DealStatus.AWAITING_DEPOSITS or not deal.both_ready:
                return deal
            deal.status = DealStatus.FUNDED
            deal.touch()
            await self._storage.put_deal(deal)

        await self._emit(Event.DEAL_FUNDED, deal)
        return await self.settle(code)

    async def settle(self, code: str) -> Deal:
        """Pay both sides out. Safe to call again after a crash."""
        async with self._lock(code):
            deal = await self._require(code)
            if deal.status not in (DealStatus.FUNDED, DealStatus.SETTLING):
                raise DealStateError(_status_complaint(deal))
            _require_no_payout_in_flight(deal)
            messages = self._build_settlement_messages(deal)
            return await self._dispatch(deal, messages, kind="settle")

    async def refund(self, code: str, *, reason: str | None = None) -> Deal:
        """Return every deposit to the wallet it came from."""
        async with self._lock(code):
            deal = await self._require(code)
            if deal.status in (DealStatus.COMPLETED, DealStatus.REFUNDED):
                raise DealStateError(_status_complaint(deal))
            _require_no_payout_in_flight(deal)
            messages = self._build_refund_messages(deal)
            if not messages:
                deal.status = DealStatus.CANCELLED
                deal.note = reason
                deal.touch()
                await self._storage.put_deal(deal)
                await self._emit(Event.CANCELLED, deal, reason=reason)
                return deal
            deal.note = reason
            return await self._dispatch(deal, messages, kind="refund")

    async def award(self, code: str, winner: SideRole) -> Deal:
        """Arbitration outcome: give everything in escrow to one party."""
        async with self._lock(code):
            deal = await self._require(code)
            if deal.status.is_terminal:
                raise DealStateError(_status_complaint(deal))
            _require_no_payout_in_flight(deal)
            destination = deal.side(winner).payout_address
            if destination is None:
                raise SettlementError(
                    f"side {winner.value} has no payout address; ask them to send /address first"
                )
            messages = []
            for side in deal.sides:
                if side.asset.kind.is_onchain and side.asset_delivered:
                    payout = _payout_asset(side)
                    messages.append(
                        self._wallet.build_payout(payout, destination, f"Deal {deal.code} — arbitration")
                    )
            if not messages:
                raise SettlementError("there is nothing in escrow to award")
            deal.note = f"awarded to side {winner.value} by the operator"
            return await self._dispatch(deal, messages, kind="settle")

    def _build_settlement_messages(self, deal: Deal) -> list:
        """Each side's asset goes to the other side's payout address."""
        messages = []
        for side in deal.sides:
            if not side.asset.kind.is_onchain:
                continue
            recipient = deal.side(side.role.other).payout_address
            if recipient is None:
                raise SettlementError(
                    f"side {side.role.other.value} has no payout address to receive "
                    f"{side.asset.human()}"
                )
            messages.append(
                self._wallet.build_payout(
                    _payout_asset(side), recipient, f"Deal {deal.code} — settled"
                )
            )

        fee_wallet = self._settings.fee_wallet
        if fee_wallet and deal.fee_nano >= self._settings.min_deposit_nano:
            messages.append(
                self._wallet.build_payout(
                    Asset(kind=AssetKind.TON, amount=deal.fee_nano),
                    addr.canonical(fee_wallet),
                    f"Deal {deal.code} — fee",
                )
            )
        return messages

    def _build_refund_messages(self, deal: Deal) -> list:
        """Everything a side put in goes back to the wallet that sent it."""
        messages = []
        for side in deal.sides:
            destination = side.payout_address
            if destination is None:
                continue

            if side.asset.kind is AssetKind.TON:
                amount = side.refundable_ton
                if amount >= self._settings.min_deposit_nano:
                    messages.append(
                        self._wallet.build_payout(
                            Asset(kind=AssetKind.TON, amount=amount),
                            destination,
                            f"Deal {deal.code} — refund",
                        )
                    )
                continue

            if side.asset.kind.is_onchain and side.asset_delivered:
                messages.append(
                    self._wallet.build_payout(
                        side.asset,
                        destination,
                        f"Deal {deal.code} — refund",
                    )
                )
            surcharge = side.extra_ton_paid
            if surcharge >= self._settings.min_deposit_nano:
                messages.append(
                    self._wallet.build_payout(
                        Asset(kind=AssetKind.TON, amount=surcharge),
                        destination,
                        f"Deal {deal.code} — fee refund",
                    )
                )
        return messages

    async def _dispatch(self, deal: Deal, messages: list, *, kind: str) -> Deal:
        """Persist the intent, broadcast it, and record what was signed."""
        if len(messages) > self._wallet.max_messages:
            raise SettlementError(
                f"this deal needs {len(messages)} outgoing messages but wallet "
                f"{self._settings.escrow_wallet_version} carries {self._wallet.max_messages}"
            )
        await self._wallet.ensure_balance(self._gas_for(deal))

        deal.status = DealStatus.SETTLING if kind == "settle" else DealStatus.REFUNDING
        deal.settle_attempts += 1
        deal.touch()
        await self._storage.put_deal(deal)
        await self._emit(Event.SETTLING if kind == "settle" else Event.REFUNDING, deal)

        try:
            sent = await self._wallet.send(messages)
        except Exception as exc:
            log.exception("broadcast failed for deal %s", deal.code)
            deal.note = f"broadcast failed: {exc}"
            deal.touch()
            await self._storage.put_deal(deal)
            raise SettlementError(str(exc)) from exc

        deal.settlement = Settlement(
            kind=kind, seqno=sent.seqno, msg_hash=sent.msg_hash, sent_at=sent.sent_at
        )
        deal.touch()
        await self._storage.put_deal(deal)
        return deal

    def _gas_for(self, deal: Deal) -> int:
        return self._wallet.gas_cost([side.asset for side in deal.sides])

    # ------------------------------------------------------- reconciliation

    async def reconcile(self, deal: Deal) -> Deal:
        """Decide the fate of a deal whose payout is in flight.

        Called on startup and by the sweeper. Asks the wallet whether the
        message we signed was applied, retries the ones that expired unapplied,
        and escalates anything that keeps failing.
        """
        record = deal.settlement
        if record is None or record.confirmed:
            return deal

        sent = SentMessage(
            seqno=record.seqno,
            msg_hash=record.msg_hash,
            valid_until=record.sent_at + EXTERNAL_MESSAGE_TTL,
            sent_at=record.sent_at,
        )
        outcome = await self._wallet.was_applied(sent)
        if outcome is None:
            return deal

        async with self._lock(deal.code):
            fresh = await self._require(deal.code)
            if fresh.settlement is None or fresh.settlement.confirmed:
                return fresh

            if outcome:
                fresh.settlement.confirmed = True
                fresh.status = (
                    DealStatus.COMPLETED if fresh.settlement.kind == "settle" else DealStatus.REFUNDED
                )
                fresh.touch()
                await self._storage.put_deal(fresh)
                await self._emit(
                    Event.COMPLETED if fresh.status is DealStatus.COMPLETED else Event.REFUNDED,
                    fresh,
                )
                return fresh

            if fresh.settle_attempts >= MAX_SETTLE_ATTEMPTS:
                fresh.status = DealStatus.FAILED
                fresh.note = "payout could not be broadcast; funds are still in escrow"
                fresh.touch()
                await self._storage.put_deal(fresh)
                await self._emit(Event.FAILED, fresh)
                return fresh

            kind = fresh.settlement.kind
            fresh.settlement = None
            fresh.status = DealStatus.FUNDED if kind == "settle" else DealStatus.EXPIRED
            fresh.touch()
            await self._storage.put_deal(fresh)

        log.info("retrying %s for deal %s", kind, deal.code)
        return await (self.settle(deal.code) if kind == "settle" else self.refund(deal.code))

    async def expire_due(self) -> None:
        """Close deals nobody joined and refund deals nobody finished funding."""
        now = int(time.time())

        for deal in await self._storage.list_by_status([DealStatus.OPEN]):
            if not deal.expires_at or deal.expires_at >= now:
                continue
            async with self._lock(deal.code):
                fresh = await self._storage.get_deal(deal.code)
                if fresh is None or fresh.status is not DealStatus.OPEN:
                    continue
                fresh.status = DealStatus.CANCELLED
                fresh.note = "nobody joined before the deal expired"
                fresh.touch()
                await self._storage.put_deal(fresh)
            await self._emit(Event.CANCELLED, fresh, reason=fresh.note)

        for deal in await self._storage.list_by_status([DealStatus.AWAITING_DEPOSITS]):
            if not deal.expires_at or deal.expires_at >= now:
                continue
            async with self._lock(deal.code):
                fresh = await self._storage.get_deal(deal.code)
                if fresh is None or fresh.status is not DealStatus.AWAITING_DEPOSITS:
                    continue
                fresh.status = DealStatus.EXPIRED
                fresh.touch()
                await self._storage.put_deal(fresh)
            await self._emit(Event.EXPIRED, fresh)

        for deal in await self._storage.list_by_status([DealStatus.EXPIRED]):
            try:
                await self.refund(deal.code, reason="deposit deadline passed")
            except DealError:
                continue
            except SettlementError as exc:
                log.error("refund of %s failed: %s", deal.code, exc)
                await self._emit(Event.OPERATOR_ALERT, deal, error=str(exc))

        # A deal can reach FUNDED and still fail to pay out — an empty escrow,
        # an API outage, a missing payout address. Keep trying instead of
        # leaving both parties' funds parked.
        for deal in await self._storage.list_by_status([DealStatus.FUNDED]):
            try:
                await self.settle(deal.code)
            except DealError:
                continue
            except SettlementError as exc:
                log.error("settlement of %s failed: %s", deal.code, exc)
                await self._emit(Event.OPERATOR_ALERT, deal, error=str(exc))

    async def pending_settlements(self) -> list[Deal]:
        return await self._storage.list_by_status([DealStatus.SETTLING, DealStatus.REFUNDING])

    # -------------------------------------------------------------- helpers

    async def get_deal(self, code: str) -> Deal | None:
        return await self._storage.get_deal(code)

    async def deals_of(self, user_id: int, limit: int = 20) -> list[Deal]:
        return await self._storage.list_deals_for_user(user_id, limit=limit)

    async def stats(self) -> dict[str, int]:
        return await self._storage.stats()

    async def escrow_balance(self) -> int:
        return await self._wallet.balance()

    async def manual_payout(self, destination: str, amount_nano: int, comment: str) -> str:
        """Send TON straight out of escrow. The operator's escape hatch.

        Used to return a transfer that matched no deal, or to unstick a deal
        the automation gave up on. Deliberately not tied to any deal record:
        the operator is accountable for the destination they type.
        """
        message = self._wallet.build_payout(
            Asset(kind=AssetKind.TON, amount=amount_nano), addr.canonical(destination), comment
        )
        await self._wallet.ensure_balance(amount_nano)
        sent = await self._wallet.send([message])
        log.warning(
            "manual payout of %s to %s (seqno %s)",
            format_ton(amount_nano),
            addr.shorten(destination),
            sent.seqno,
        )
        return sent.msg_hash

    async def alert(self, message: str) -> None:
        """Surface an operational problem to whoever is running the bot."""
        await self._emit(Event.OPERATOR_ALERT, None, error=message)

    def _lock(self, code: str) -> asyncio.Lock:
        return self._locks[code]

    async def _require(self, code: str) -> Deal:
        deal = await self._storage.get_deal(code)
        if deal is None:
            raise DealNotFound(f"no deal with code {code}")
        return deal

    @staticmethod
    def _participant(deal: Deal, user_id: int) -> Side:
        side = deal.side_of(user_id)
        if side is None:
            raise NotAParticipant("you are not a party to this deal")
        return side

    async def _unique_code(self) -> str:
        for _ in range(10):
            code = new_deal_code()
            if await self._storage.get_deal(code) is None:
                return code
        raise DealError("could not allocate a deal code; try again")

    async def _emit(self, event: Event, deal: Deal | None, **context: object) -> None:
        try:
            await self._notifier.notify(event, deal, **context)
        except Exception:  # a broken chat must never stall an on-chain payout
            log.exception("notifier failed on %s", event)


def _payout_asset(side: Side) -> Asset:
    """The side's asset as it leaves escrow, with any fee already withheld."""
    if side.asset.kind is not AssetKind.TON:
        return side.asset
    return Asset(kind=AssetKind.TON, amount=side.payout_amount)


def _same_asset(left: Asset, right: Asset) -> bool:
    if left.kind is not right.kind:
        return False
    if left.kind is AssetKind.NFT:
        return addr.same(left.nft_address, right.nft_address)
    if left.kind is AssetKind.JETTON:
        return addr.same(left.jetton_master, right.jetton_master) and left.amount == right.amount
    if left.kind is AssetKind.TON:
        return left.amount == right.amount
    return False


def _require_no_payout_in_flight(deal: Deal) -> None:
    """Refuse to sign a second payout while the first is undecided.

    Reconciliation clears the record once the chain has answered, so this only
    ever blocks the genuinely dangerous window.
    """
    record = deal.settlement
    if record is not None and not record.confirmed:
        raise DealStateError(
            f"deal {deal.code} already has a {record.kind} in flight (seqno {record.seqno}); "
            "wait for it to settle or expire"
        )


def _status_complaint(deal: Deal) -> str:
    return f"deal {deal.code} is {deal.status.value} and cannot do that now"
