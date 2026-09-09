"""Typed callback payloads.

Deliberately narrow: a callback carries *what* to do and *which deal*, never
*who* is doing it. The engine derives identity from the Telegram user attached
to the update, so a forged callback cannot act on somebody else's behalf.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="mn"):
    action: str  # root | create | join | deals | help | lang


class AssetCB(CallbackData, prefix="as"):
    step: str  # give | want
    kind: str  # ton | jetton | nft | offchain


class DealCB(CallbackData, prefix="dl"):
    action: str  # accept | decline | cancel | received | dispute | show
    code: str


class LangCB(CallbackData, prefix="lc"):
    locale: str
