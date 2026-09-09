"""Turn raw account transactions into the deposits the engine reasons about.

The escrow wallet sees three interesting kinds of incoming message:

* a plain TON transfer carrying a text comment,
* an NFT item announcing that escrow is now its owner,
* escrow's own jetton wallet announcing that jettons arrived.

Everything else — bounced messages, excess refunds, unrelated dust — is
discarded here so the engine never has to think about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pytoniq_core import Address
from pytoniq_core.tlb.transaction import InternalMsgInfo, Transaction

from guarantor.ton import addresses as addr
from guarantor.ton.ops import (
    parse_jetton_notification,
    parse_ownership_assigned,
    read_comment,
)


class TransferKind(StrEnum):
    TON = "ton"
    NFT = "nft"
    JETTON = "jetton"


@dataclass(frozen=True, slots=True)
class IncomingTransfer:
    """A single incoming transfer, normalised for the escrow engine.

    :param source: the account that sent the message to escrow. For an NFT
        this is the item contract, for a jetton it is escrow's jetton wallet —
        which is exactly what the matcher needs to identify the asset.
    :param depositor: the human-facing counterparty: who actually paid. This
        is the address a refund or payout goes back to.
    """

    tx_hash: str
    lt: int
    at: int
    kind: TransferKind
    source: str
    depositor: str
    value_nano: int
    amount: int
    comment: str | None

    @property
    def key(self) -> str:
        """Stable identity for de-duplication across restarts and reorgs."""
        return f"{self.lt}:{self.tx_hash}"


def parse_transaction(tx: Transaction, escrow: Address | str) -> IncomingTransfer | None:
    """Extract the incoming transfer from a transaction, if there is one.

    Returns ``None`` for transactions that carry nothing the escrow can credit.
    """
    message = tx.in_msg
    if message is None:
        return None

    info = message.info
    if not isinstance(info, InternalMsgInfo):
        return None  # external messages are our own outgoing sends
    if info.bounced:
        return None  # a bounce is money coming back, not a deposit
    if info.src is None or not addr.same(info.dest, escrow):
        return None

    tx_hash = tx.cell.hash.hex()
    source = addr.canonical(info.src)
    value = int(info.value_coins or 0)
    body = message.body

    assigned = parse_ownership_assigned(body)
    if assigned is not None:
        return IncomingTransfer(
            tx_hash=tx_hash,
            lt=tx.lt,
            at=tx.now,
            kind=TransferKind.NFT,
            source=source,
            depositor=addr.canonical(assigned.previous_owner),
            value_nano=value,
            amount=1,
            comment=assigned.comment,
        )

    notification = parse_jetton_notification(body)
    if notification is not None:
        return IncomingTransfer(
            tx_hash=tx_hash,
            lt=tx.lt,
            at=tx.now,
            kind=TransferKind.JETTON,
            source=source,
            depositor=addr.canonical(notification.sender),
            value_nano=value,
            amount=notification.amount,
            comment=notification.comment,
        )

    if value <= 0:
        return None

    return IncomingTransfer(
        tx_hash=tx_hash,
        lt=tx.lt,
        at=tx.now,
        kind=TransferKind.TON,
        source=source,
        depositor=source,
        value_nano=value,
        amount=value,
        comment=read_comment(body),
    )
