"""Address parsing and comparison.

TON addresses have several textual forms for the same account (bounceable,
non-bounceable, testnet-flagged, raw). Comparing the strings is a bug; the
identity of an account is ``(workchain, hash)``. Everything stored in the
database goes through :func:`canonical` so lookups stay stable.
"""

from __future__ import annotations

from typing import Any

from pytoniq_core import Address

from guarantor.errors import AddressError

#: ``ton_core`` re-exports this very class, but under its own name, so the
#: annotation is widened to keep both import paths type-checkable.
AddressLike = Address | str | Any


def parse(value: AddressLike) -> Address:
    """Parse any textual TON address form.

    :raises AddressError: if the value is not a valid address.
    """
    if isinstance(value, Address):
        return value
    try:
        return Address(value.strip())
    except Exception as exc:  # pytoniq raises a family of parse errors
        raise AddressError(f"{value!r} is not a valid TON address") from exc


def canonical(value: AddressLike) -> str:
    """Return the raw ``workchain:hash`` form used as a database key."""
    address = parse(value)
    return address.to_str(is_user_friendly=False)


def friendly(value: AddressLike, *, testnet: bool = False, bounceable: bool = True) -> str:
    """Return the user-friendly base64 form shown in chat messages."""
    return parse(value).to_str(
        is_user_friendly=True,
        is_url_safe=True,
        is_bounceable=bounceable,
        is_test_only=testnet,
    )


def same(left: AddressLike | None, right: AddressLike | None) -> bool:
    """Compare two addresses by account identity rather than by spelling."""
    if left is None or right is None:
        return False
    try:
        return canonical(left) == canonical(right)
    except AddressError:
        return False


def shorten(value: AddressLike, keep: int = 6) -> str:
    """Abbreviate an address for inline display."""
    text = friendly(value)
    return f"{text[:keep]}…{text[-keep:]}"
