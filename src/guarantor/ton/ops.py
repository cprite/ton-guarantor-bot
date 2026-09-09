"""Message body parsing for the standards the escrow understands.

The escrow only ever needs to *read* three shapes of incoming body: a plain
text comment (TEP-74 ``op = 0``), an NFT ``ownership_assigned`` (TEP-62) and a
jetton ``transfer_notification`` (TEP-74). Anything else is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytoniq_core import Address, Cell, Slice

OP_TEXT_COMMENT = 0x00000000
OP_NFT_TRANSFER = 0x5FCC3D14
OP_NFT_OWNERSHIP_ASSIGNED = 0x05138D91
OP_JETTON_TRANSFER = 0x0F8A7EA5
OP_JETTON_TRANSFER_NOTIFICATION = 0x7362D09C
OP_EXCESSES = 0xD53276DB


def read_op(body: Cell | None) -> int | None:
    """Peek at the 32-bit operation code of a message body."""
    if body is None:
        return None
    slice_ = body.begin_parse()
    if slice_.remaining_bits < 32:
        return None
    return slice_.preload_uint(32)


def read_comment(body: Cell | None) -> str | None:
    """Return the text comment of a body, or ``None`` if there is not one."""
    if body is None:
        return None
    slice_ = body.begin_parse()
    if slice_.remaining_bits < 32:
        return None
    if slice_.load_uint(32) != OP_TEXT_COMMENT:
        return None
    return _load_text(slice_)


def read_forward_comment(slice_: Slice) -> str | None:
    """Read the ``forward_payload:(Either Cell ^Cell)`` tail as a comment.

    Wallets put the payload inline when it fits and in a reference when it does
    not, so both shapes have to be handled.
    """
    try:
        if slice_.remaining_bits < 1:
            return None
        in_ref = slice_.load_bit()
        payload = slice_.load_ref().begin_parse() if in_ref else slice_
    except Exception:
        return None

    try:
        if payload.remaining_bits < 32:
            return None
        if payload.load_uint(32) != OP_TEXT_COMMENT:
            return None
        return _load_text(payload)
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class OwnershipAssigned:
    """``ownership_assigned`` sent by an NFT item once escrow owns it."""

    query_id: int
    previous_owner: Address
    comment: str | None


@dataclass(frozen=True, slots=True)
class JettonNotification:
    """``transfer_notification`` sent by escrow's own jetton wallet."""

    query_id: int
    amount: int
    sender: Address
    comment: str | None


def parse_ownership_assigned(body: Cell | None) -> OwnershipAssigned | None:
    """Parse an NFT ``ownership_assigned`` body, or return ``None``."""
    if body is None:
        return None
    try:
        slice_ = body.begin_parse()
        if slice_.remaining_bits < 32 + 64:
            return None
        if slice_.load_uint(32) != OP_NFT_OWNERSHIP_ASSIGNED:
            return None
        query_id = slice_.load_uint(64)
        previous_owner = slice_.load_address()
    except Exception:
        return None
    if previous_owner is None:
        return None
    return OwnershipAssigned(query_id, previous_owner, read_forward_comment(slice_))


def parse_jetton_notification(body: Cell | None) -> JettonNotification | None:
    """Parse a jetton ``transfer_notification`` body, or return ``None``."""
    if body is None:
        return None
    try:
        slice_ = body.begin_parse()
        if slice_.remaining_bits < 32 + 64:
            return None
        if slice_.load_uint(32) != OP_JETTON_TRANSFER_NOTIFICATION:
            return None
        query_id = slice_.load_uint(64)
        amount = slice_.load_coins() or 0
        sender = slice_.load_address()
    except Exception:
        return None
    if sender is None:
        return None
    return JettonNotification(query_id, amount, sender, read_forward_comment(slice_))


def _load_text(slice_: Slice) -> str | None:
    """Read a snake-encoded string, tolerating malformed tails."""
    try:
        text = slice_.load_snake_string()
    except Exception:
        return None
    return text or None
