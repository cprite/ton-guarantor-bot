"""Deep links: what a party taps to pay, and where anyone can verify a tx."""

from __future__ import annotations

from urllib.parse import quote

from guarantor.ton import addresses as addr


def transfer_link(destination: str, amount_nano: int, comment: str, *, testnet: bool = False) -> str:
    """A ``ton://`` link that pre-fills address, amount and comment.

    Every major TON wallet handles this scheme, so the party never copies an
    address by hand — the single most common way to lose funds.
    """
    target = addr.friendly(destination, testnet=testnet)
    return f"ton://transfer/{target}?amount={amount_nano}&text={quote(comment)}"


def explorer_account(address: str, *, testnet: bool = False) -> str:
    host = "testnet.tonviewer.com" if testnet else "tonviewer.com"
    return f"https://{host}/{addr.friendly(address, testnet=testnet)}"


def explorer_tx(tx_hash: str, *, testnet: bool = False) -> str:
    host = "testnet.tonviewer.com" if testnet else "tonviewer.com"
    return f"https://{host}/transaction/{tx_hash}"


def deal_link(bot_username: str, code: str) -> str:
    """A ``t.me`` link that opens the bot straight into this deal."""
    return f"https://t.me/{bot_username}?start=deal_{code}"
