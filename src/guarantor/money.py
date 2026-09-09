"""Exact decimal arithmetic for on-chain amounts.

Every amount inside the bot is an integer in the asset's smallest unit
(nanotons for TON, ``10 ** decimals`` units for a jetton). Floats are never
used: a rounding error here is somebody's money.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from guarantor.errors import AmountError

TON_DECIMALS = 9
NANO = 10**TON_DECIMALS

#: Amounts above this are almost certainly a typo rather than a real deal.
MAX_UNITS = 10**30


def to_units(amount: Decimal | int | str, decimals: int = TON_DECIMALS) -> int:
    """Convert a human amount to the asset's smallest integer unit."""
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    scaled = value * (Decimal(10) ** decimals)
    if scaled != scaled.to_integral_value():
        raise AmountError(f"amount has more than {decimals} decimal places")
    return int(scaled)


def from_units(value: int, decimals: int = TON_DECIMALS) -> Decimal:
    """Convert an integer amount in smallest units back to a human amount."""
    return Decimal(value) / (Decimal(10) ** decimals)


def parse_amount(text: str, decimals: int = TON_DECIMALS) -> int:
    """Parse user input such as ``"1,5"`` or ``"0.05"`` into smallest units.

    :raises AmountError: if the text is not a positive number, carries more
        precision than the asset supports, or is implausibly large.
    """
    cleaned = text.strip().replace(",", ".").replace(" ", "").replace(" ", "")
    if not cleaned:
        raise AmountError("empty amount")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise AmountError(f"{text!r} is not a number") from exc
    if not value.is_finite():
        raise AmountError("amount must be finite")
    if value <= 0:
        raise AmountError("amount must be greater than zero")

    units = to_units(value, decimals)
    if units > MAX_UNITS:
        raise AmountError("amount is implausibly large")
    return units


def format_units(value: int, decimals: int = TON_DECIMALS, symbol: str = "") -> str:
    """Render an integer amount for humans, trimming trailing zeros."""
    text = format(from_units(value, decimals), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text} {symbol}".strip()


def format_ton(value: int) -> str:
    """Render nanotons as a ``TON`` amount."""
    return format_units(value, TON_DECIMALS, "TON")
