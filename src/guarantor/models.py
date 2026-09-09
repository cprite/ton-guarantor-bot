"""The domain model: assets, sides, deals and their life cycle.

These objects are plain dataclasses that round-trip through JSON, so the
storage layer never has to know what a deal is made of.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from guarantor.codes import deposit_memo
from guarantor.money import TON_DECIMALS, format_ton, format_units


class AssetKind(StrEnum):
    """What one side of a deal puts up."""

    TON = "ton"
    JETTON = "jetton"
    NFT = "nft"
    OFFCHAIN = "offchain"

    @property
    def is_onchain(self) -> bool:
        return self is not AssetKind.OFFCHAIN


class SideRole(StrEnum):
    """``A`` created the deal, ``B`` joined it."""

    A = "A"
    B = "B"

    @property
    def other(self) -> SideRole:
        return SideRole.B if self is SideRole.A else SideRole.A


class DealStatus(StrEnum):
    """Where a deal sits in its life cycle.

    The only terminal states are ``COMPLETED``, ``CANCELLED``, ``REFUNDED``
    and ``FAILED``; everything else is expected to move on its own.
    """

    OPEN = "open"                      # created, waiting for a counterparty
    AWAITING_DEPOSITS = "awaiting"     # both parties agreed, funds not in yet
    FUNDED = "funded"                  # both deposits confirmed on-chain
    SETTLING = "settling"              # payout external message sent
    COMPLETED = "completed"
    CANCELLED = "cancelled"            # abandoned before any money moved
    EXPIRED = "expired"                # deposit deadline passed
    REFUNDING = "refunding"            # refund external message sent
    REFUNDED = "refunded"
    DISPUTED = "disputed"              # awaiting operator arbitration
    FAILED = "failed"                  # needs a human; funds still in escrow

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES

    @property
    def accepts_deposits(self) -> bool:
        return self is DealStatus.AWAITING_DEPOSITS


_TERMINAL_STATUSES = frozenset(
    {
        DealStatus.COMPLETED,
        DealStatus.CANCELLED,
        DealStatus.REFUNDED,
        DealStatus.FAILED,
    }
)


@dataclass(slots=True)
class Asset:
    """One leg of a deal.

    Exactly one group of fields is meaningful per :attr:`kind`: ``amount`` for
    TON, ``amount`` plus the jetton fields for a jetton, ``nft_address`` for an
    NFT, and ``description`` for anything settled outside the chain.
    """

    kind: AssetKind
    amount: int = 0
    jetton_master: str | None = None
    jetton_symbol: str | None = None
    jetton_decimals: int = TON_DECIMALS
    #: Escrow's own jetton wallet for :attr:`jetton_master`, resolved once when
    #: the deal is created so the watcher can match incoming notifications.
    jetton_wallet: str | None = None
    nft_address: str | None = None
    description: str | None = None

    @property
    def decimals(self) -> int:
        return TON_DECIMALS if self.kind is not AssetKind.JETTON else self.jetton_decimals

    def human(self) -> str:
        """A short description suitable for a chat message."""
        match self.kind:
            case AssetKind.TON:
                return format_ton(self.amount)
            case AssetKind.JETTON:
                return format_units(self.amount, self.jetton_decimals, self.jetton_symbol or "jetton")
            case AssetKind.NFT:
                return f"NFT {self.nft_address}"
            case AssetKind.OFFCHAIN:
                return self.description or "off-chain item"
        raise AssertionError(f"unhandled asset kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "amount": self.amount,
            "jetton_master": self.jetton_master,
            "jetton_symbol": self.jetton_symbol,
            "jetton_decimals": self.jetton_decimals,
            "jetton_wallet": self.jetton_wallet,
            "nft_address": self.nft_address,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Asset:
        return cls(
            kind=AssetKind(raw["kind"]),
            amount=int(raw.get("amount", 0)),
            jetton_master=raw.get("jetton_master"),
            jetton_symbol=raw.get("jetton_symbol"),
            jetton_decimals=int(raw.get("jetton_decimals", TON_DECIMALS)),
            jetton_wallet=raw.get("jetton_wallet"),
            nft_address=raw.get("nft_address"),
            description=raw.get("description"),
        )


@dataclass(slots=True)
class Deposit:
    """A confirmed incoming transfer credited to one side of a deal."""

    tx_hash: str
    lt: int
    at: int
    sender: str
    kind: AssetKind
    amount: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "lt": self.lt,
            "at": self.at,
            "sender": self.sender,
            "kind": self.kind.value,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Deposit:
        return cls(
            tx_hash=raw["tx_hash"],
            lt=int(raw["lt"]),
            at=int(raw["at"]),
            sender=raw["sender"],
            kind=AssetKind(raw["kind"]),
            amount=int(raw["amount"]),
        )


@dataclass(slots=True)
class Side:
    """One party: who they are, what they owe, and what has arrived."""

    role: SideRole
    asset: Asset
    user_id: int | None = None
    username: str | None = None
    accepted: bool = False
    funded: bool = False
    #: Extra plain TON this side must deposit on top of its asset, used when
    #: the service fee cannot be deducted from a TON leg.
    extra_ton_required: int = 0
    extra_ton_paid: int = 0
    #: Nanotons withheld from this side's TON leg when it is paid out.
    fee_deduction: int = 0
    #: Where this side's payout goes. Derived from the address that funded the
    #: deal, so we never ask a user to type an address they might mistype.
    payout_address: str | None = None
    deposits: list[Deposit] = field(default_factory=list)
    #: For an off-chain leg: the counterparty pressed "I received it".
    offchain_confirmed: bool = False

    def memo(self, code: str) -> str:
        return deposit_memo(code, self.role.value)

    @property
    def asset_delivered(self) -> bool:
        """Has the asset itself (ignoring any fee top-up) arrived?"""
        if not self.asset.kind.is_onchain:
            return self.offchain_confirmed
        received = sum(d.amount for d in self.deposits if d.kind is self.asset.kind)
        if self.asset.kind is AssetKind.NFT:
            return received >= 1
        return received >= self.asset.amount

    @property
    def fee_settled(self) -> bool:
        return self.extra_ton_paid >= self.extra_ton_required

    @property
    def is_ready(self) -> bool:
        return self.asset_delivered and self.fee_settled

    @property
    def payout_amount(self) -> int:
        """What the counterparty receives for this side's asset, after fees."""
        return max(self.asset.amount - self.fee_deduction, 0)

    @property
    def refundable_ton(self) -> int:
        """Total nanotons this side sent in, to be returned on a refund."""
        return sum(d.amount for d in self.deposits if d.kind is AssetKind.TON)

    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return f"id{self.user_id}" if self.user_id else f"side {self.role.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "asset": self.asset.to_dict(),
            "user_id": self.user_id,
            "username": self.username,
            "accepted": self.accepted,
            "funded": self.funded,
            "extra_ton_required": self.extra_ton_required,
            "extra_ton_paid": self.extra_ton_paid,
            "fee_deduction": self.fee_deduction,
            "payout_address": self.payout_address,
            "deposits": [d.to_dict() for d in self.deposits],
            "offchain_confirmed": self.offchain_confirmed,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Side:
        return cls(
            role=SideRole(raw["role"]),
            asset=Asset.from_dict(raw["asset"]),
            user_id=raw.get("user_id"),
            username=raw.get("username"),
            accepted=bool(raw.get("accepted", False)),
            funded=bool(raw.get("funded", False)),
            extra_ton_required=int(raw.get("extra_ton_required", 0)),
            extra_ton_paid=int(raw.get("extra_ton_paid", 0)),
            fee_deduction=int(raw.get("fee_deduction", 0)),
            payout_address=raw.get("payout_address"),
            deposits=[Deposit.from_dict(d) for d in raw.get("deposits", [])],
            offchain_confirmed=bool(raw.get("offchain_confirmed", False)),
        )


@dataclass(slots=True)
class Settlement:
    """Bookkeeping for the external message that moves money out of escrow.

    Recorded *before* the message is broadcast so a crash mid-send can be
    reconciled against the chain instead of paying twice.
    """

    kind: str  # "settle" | "refund"
    seqno: int
    msg_hash: str
    sent_at: int
    confirmed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "seqno": self.seqno,
            "msg_hash": self.msg_hash,
            "sent_at": self.sent_at,
            "confirmed": self.confirmed,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settlement:
        return cls(
            kind=raw["kind"],
            seqno=int(raw["seqno"]),
            msg_hash=raw["msg_hash"],
            sent_at=int(raw["sent_at"]),
            confirmed=bool(raw.get("confirmed", False)),
            error=raw.get("error"),
        )


@dataclass(slots=True)
class Deal:
    """A two-sided escrow deal."""

    code: str
    status: DealStatus
    a: Side
    b: Side
    fee_nano: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    #: Unix time after which unfunded deals are refunded and closed.
    expires_at: int = 0
    settlement: Settlement | None = None
    settle_attempts: int = 0
    dispute_reason: str | None = None
    note: str | None = None

    def side(self, role: SideRole) -> Side:
        return self.a if role is SideRole.A else self.b

    def side_of(self, user_id: int) -> Side | None:
        for side in (self.a, self.b):
            if side.user_id == user_id:
                return side
        return None

    @property
    def sides(self) -> tuple[Side, Side]:
        return (self.a, self.b)

    @property
    def both_accepted(self) -> bool:
        return self.a.accepted and self.b.accepted

    @property
    def both_ready(self) -> bool:
        return self.a.is_ready and self.b.is_ready

    @property
    def has_any_deposit(self) -> bool:
        return any(side.deposits for side in self.sides)

    def touch(self) -> None:
        self.updated_at = int(time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status.value,
            "a": self.a.to_dict(),
            "b": self.b.to_dict(),
            "fee_nano": self.fee_nano,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "settlement": self.settlement.to_dict() if self.settlement else None,
            "settle_attempts": self.settle_attempts,
            "dispute_reason": self.dispute_reason,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Deal:
        settlement = raw.get("settlement")
        return cls(
            code=raw["code"],
            status=DealStatus(raw["status"]),
            a=Side.from_dict(raw["a"]),
            b=Side.from_dict(raw["b"]),
            fee_nano=int(raw.get("fee_nano", 0)),
            created_at=int(raw["created_at"]),
            updated_at=int(raw["updated_at"]),
            expires_at=int(raw.get("expires_at", 0)),
            settlement=Settlement.from_dict(settlement) if settlement else None,
            settle_attempts=int(raw.get("settle_attempts", 0)),
            dispute_reason=raw.get("dispute_reason"),
            note=raw.get("note"),
        )
