"""Deal codes and the deposit memos derived from them.

A deal code is the only thing a party has to share to join a deal, so it is
generated from :mod:`secrets` and drawn from an alphabet without look-alike
characters. Eight characters over a 32-symbol alphabet is 2**40 — far beyond
brute force through the Telegram API's rate limits.
"""

from __future__ import annotations

import re
import secrets

#: Crockford-style alphabet: no ``I``, ``O``, ``0`` or ``1``.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

MEMO_PREFIX = "G"
_MEMO_RE = re.compile(rf"^{MEMO_PREFIX}-([{ALPHABET}]{{{CODE_LENGTH}}})-([AB])$")


def new_deal_code() -> str:
    """Return a fresh, unguessable deal code."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(text: str) -> str | None:
    """Normalise user input into a deal code, or ``None`` if it is not one.

    Accepts lower case and stray spaces or dashes, because people retype codes
    from another chat by hand.
    """
    candidate = text.strip().upper().replace(" ", "").replace("-", "")
    if len(candidate) != CODE_LENGTH:
        return None
    if any(char not in ALPHABET for char in candidate):
        return None
    return candidate


def deposit_memo(code: str, role: str) -> str:
    """Return the transfer comment a party must attach to its deposit."""
    return f"{MEMO_PREFIX}-{code}-{role.upper()}"


def parse_memo(text: str) -> tuple[str, str] | None:
    """Parse a deposit comment back into ``(code, role)``, or ``None``."""
    match = _MEMO_RE.match(text.strip().upper())
    if match is None:
        return None
    return match.group(1), match.group(2)
