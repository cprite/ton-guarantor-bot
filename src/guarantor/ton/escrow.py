"""The hot wallet that holds deposits and pays them out.

Sending money is the one place where a crash can cost real funds, so the flow
is deliberately explicit: pick a ``seqno``, pin a ``valid_until``, persist both
*before* broadcasting, and afterwards decide what happened by looking at the
wallet's seqno rather than at whether our HTTP call returned.

Because the bot is the wallet's only signer, ``seqno`` advancing past the one
we signed means our message — and nothing else — was accepted. If the seqno is
unchanged once ``valid_until`` has passed, the message can never be applied and
is safe to rebuild.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from ton_core import WalletV4Params, WalletV5Params
from tonutils.clients.protocol import ClientProtocol
from tonutils.contracts import (
    BaseMessageBuilder,
    JettonTransferBuilder,
    NFTTransferBuilder,
    TONTransferBuilder,
    WalletV4R2,
    WalletV5R1,
)

from guarantor.config import Settings
from guarantor.errors import InsufficientEscrowBalance, SettlementError
from guarantor.models import Asset, AssetKind
from guarantor.money import format_ton
from guarantor.ton import addresses as addr

log = logging.getLogger(__name__)

#: How long a signed external message stays valid. Long enough to survive an
#: API hiccup, short enough that a stuck deal recovers within a few minutes.
EXTERNAL_MESSAGE_TTL = 120

_WALLET_CLASSES = {"v4r2": WalletV4R2, "v5r1": WalletV5R1}
_PARAM_CLASSES = {"v4r2": WalletV4Params, "v5r1": WalletV5Params}


@dataclass(frozen=True, slots=True)
class SentMessage:
    """What was signed, so a restart can work out whether it landed."""

    seqno: int
    msg_hash: str
    valid_until: int
    sent_at: int


class EscrowWallet:
    """Signs and broadcasts payouts from the operator's escrow wallet."""

    def __init__(self, settings: Settings, wallet: WalletV4R2 | WalletV5R1) -> None:
        self._settings = settings
        self._wallet = wallet
        self._params_class = _PARAM_CLASSES[settings.escrow_wallet_version]
        # Reading the seqno and signing against it must be atomic: two
        # coroutines that both sign for seqno N produce two messages of which
        # the network silently applies one.
        self._send_lock = asyncio.Lock()

    @classmethod
    async def open(cls, settings: Settings, client: ClientProtocol) -> EscrowWallet:
        """Derive the escrow wallet from the configured seed phrase."""
        wallet_class = _WALLET_CLASSES[settings.escrow_wallet_version]
        wallet, _public, _private, _mnemonic = wallet_class.from_mnemonic(  # type: ignore[attr-defined]
            client, settings.mnemonic_words
        )
        return cls(settings, wallet)

    @property
    def address(self) -> str:
        return addr.canonical(self._wallet.address)

    def friendly_address(self) -> str:
        return addr.friendly(self._wallet.address, testnet=self._settings.is_testnet)

    @property
    def max_messages(self) -> int:
        return int(self._wallet.MAX_MESSAGES)

    async def seqno(self) -> int:
        """Current wallet seqno; ``0`` for a wallet that is not deployed yet."""
        await self._wallet.refresh()
        if not self._wallet.is_active:
            return 0
        return await self._wallet.seqno()

    async def balance(self) -> int:
        await self._wallet.refresh()
        return int(self._wallet.balance or 0)

    def build_payout(self, asset: Asset, destination: str, comment: str | None = None) -> BaseMessageBuilder:
        """Build the message that hands ``asset`` to ``destination``.

        :raises SettlementError: for an asset the chain cannot move, which the
            engine is expected to have filtered out already.
        """
        match asset.kind:
            case AssetKind.TON:
                return TONTransferBuilder(destination=destination, amount=asset.amount, body=comment)
            case AssetKind.NFT:
                if asset.nft_address is None:
                    raise SettlementError("NFT leg has no item address")
                return NFTTransferBuilder(
                    destination=destination,
                    nft_address=asset.nft_address,
                    response_address=self._wallet.address,
                    forward_payload=comment,
                    forward_amount=1,
                    amount=self._settings.nft_payout_gas_nano,
                )
            case AssetKind.JETTON:
                if asset.jetton_master is None:
                    raise SettlementError("jetton leg has no master address")
                return JettonTransferBuilder(
                    destination=destination,
                    jetton_amount=asset.amount,
                    jetton_master_address=asset.jetton_master,
                    jetton_wallet_address=asset.jetton_wallet,
                    response_address=self._wallet.address,
                    forward_payload=comment,
                    amount=self._settings.jetton_payout_gas_nano,
                )
            case AssetKind.OFFCHAIN:
                raise SettlementError("an off-chain leg cannot be paid out by the escrow")
        raise AssertionError(f"unhandled asset kind {asset.kind!r}")

    def gas_cost(self, assets: list[Asset]) -> int:
        """TON the escrow spends from its own balance to forward these assets."""
        total = 0
        for asset in assets:
            if asset.kind is AssetKind.NFT:
                total += self._settings.nft_payout_gas_nano
            elif asset.kind is AssetKind.JETTON:
                total += self._settings.jetton_payout_gas_nano
        return total

    async def ensure_balance(self, required: int) -> None:
        """Refuse to start a payout the wallet cannot afford to finish.

        :raises InsufficientEscrowBalance: if paying would eat the gas reserve.
        """
        available = await self.balance()
        needed = required + self._settings.escrow_min_reserve_nano
        if available < needed:
            raise InsufficientEscrowBalance(
                f"escrow holds {format_ton(available)} but needs "
                f"{format_ton(needed)} (payout + reserve)"
            )

    async def send(self, messages: list[BaseMessageBuilder]) -> SentMessage:
        """Sign and broadcast one external message carrying ``messages``.

        The returned record must be persisted before this coroutine's result is
        acted upon, so that :meth:`was_applied` can adjudicate after a crash.
        """
        if not messages:
            raise SettlementError("nothing to send")
        if len(messages) > self.max_messages:
            raise SettlementError(
                f"{len(messages)} messages exceed the {self.max_messages} "
                f"supported by wallet {self._settings.escrow_wallet_version}"
            )

        async with self._send_lock:
            seqno = await self.seqno()
            valid_until = int(time.time()) + EXTERNAL_MESSAGE_TTL
            params = self._params_class(seqno=seqno, valid_until=valid_until)

            external = await self._wallet.batch_transfer_message(messages, params)  # type: ignore[arg-type]
            record = SentMessage(
                seqno=seqno,
                msg_hash=external.normalized_hash,
                valid_until=valid_until,
                sent_at=int(time.time()),
            )
        log.info("escrow sent external message seqno=%s hash=%s", record.seqno, record.msg_hash[:16])
        return record

    async def was_applied(self, record: SentMessage) -> bool | None:
        """Has a previously signed message been accepted by the network?

        :return: ``True`` if applied, ``False`` if it expired unapplied and may
            be rebuilt, ``None`` while the outcome is still undecided.
        """
        current = await self.seqno()
        if current > record.seqno:
            return True
        if int(time.time()) > record.valid_until + 10:
            return False
        return None
