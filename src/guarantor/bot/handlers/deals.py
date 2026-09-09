"""Commands that act on a deal you are already part of."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from guarantor.bot.deps import Deps
from guarantor.bot.handlers.shared import answer, report, show_deal
from guarantor.bot.texts import t
from guarantor.codes import normalize_code
from guarantor.errors import GuarantorError

router = Router(name="deals")


@router.message(Command("deal"))
async def show_one(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    code = normalize_code(command.args or "")
    if code is None or message.from_user is None:
        await answer(message, t(locale, "err_not_found"))
        return
    deal = await deps.engine.get_deal(code)
    if deal is None:
        await answer(message, t(locale, "err_not_found"))
        return
    await show_deal(deps, message, deal, message.from_user.id, locale)


@router.message(Command("address"))
async def set_address(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    """``/address <code> <wallet>`` — only needed for an off-chain leg."""
    parts = (command.args or "").split()
    if len(parts) != 2 or message.from_user is None:
        await answer(message, t(locale, "need_payout_address", code="<code>"))
        return
    code = normalize_code(parts[0])
    if code is None:
        await answer(message, t(locale, "err_not_found"))
        return
    try:
        await deps.engine.set_payout_address(code, message.from_user.id, parts[1])
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await answer(message, t(locale, "address_saved", code=code))


@router.message(Command("cancel"))
async def cancel(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    code = normalize_code(command.args or "")
    if code is None or message.from_user is None:
        await answer(message, t(locale, "err_not_found"))
        return
    try:
        deal = await deps.engine.cancel_deal(code, message.from_user.id)
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await answer(message, t(locale, "cancelled", code=deal.code, reason=""))


@router.message(Command("dispute"))
async def dispute(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if not parts or message.from_user is None:
        await answer(message, t(locale, "err_not_found"))
        return
    code = normalize_code(parts[0])
    if code is None:
        await answer(message, t(locale, "err_not_found"))
        return
    reason = parts[1] if len(parts) > 1 else None
    try:
        deal = await deps.engine.dispute(code, message.from_user.id, reason)
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await answer(message, t(locale, "disputed", code=deal.code))
