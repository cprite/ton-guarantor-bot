"""Operator commands: inspection, arbitration and the manual escape hatch.

Every handler here sits behind :class:`IsAdmin`, which checks the Telegram user
against ``ADMIN_IDS``. The router is registered first so these commands are
never intercepted by a conversation state.
"""

from __future__ import annotations

import json

from aiogram import Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message

from guarantor.bot.deps import Deps
from guarantor.bot.handlers.shared import answer, report
from guarantor.bot.texts import t
from guarantor.codes import normalize_code
from guarantor.errors import DealError, GuarantorError
from guarantor.models import SideRole
from guarantor.money import format_ton, parse_amount

router = Router(name="admin")


class IsAdmin(BaseFilter):
    """Passes only for a Telegram user listed in ``ADMIN_IDS``."""

    async def __call__(self, message: Message, deps: Deps) -> bool:
        return message.from_user is not None and deps.is_admin(message.from_user.id)


router.message.filter(IsAdmin())


@router.message(Command("admin"))
async def usage(message: Message, locale: str) -> None:
    await answer(message, t(locale, "admin_usage"))


@router.message(Command("stats"))
async def stats(message: Message, deps: Deps, locale: str) -> None:
    counts = await deps.engine.stats()
    try:
        balance = format_ton(await deps.engine.escrow_balance())
    except Exception as exc:
        balance = f"unavailable ({exc})"
    rows = "\n".join(f"{status}: {count}" for status, count in sorted(counts.items())) or "no deals yet"
    await answer(
        message,
        t(
            locale,
            "admin_stats",
            escrow=deps.escrow_address,
            balance=balance,
            network=deps.settings.ton_network,
            rows=rows,
        ),
    )


@router.message(Command("inspect"))
async def inspect(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    code = normalize_code(command.args or "")
    deal = await deps.engine.get_deal(code) if code else None
    if deal is None:
        await answer(message, t(locale, "err_not_found"))
        return
    dump = json.dumps(deal.to_dict(), indent=2, ensure_ascii=False)
    await answer(message, t(locale, "admin_deal", code=deal.code, dump=dump[:3500]))


@router.message(Command("release"))
async def release(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    """Force a normal settlement, e.g. after resolving a dispute in nobody's favour."""
    code = normalize_code(command.args or "")
    if code is None:
        await answer(message, t(locale, "err_not_found"))
        return
    try:
        deal = await deps.engine.settle(code)
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await answer(message, t(locale, "admin_done", result=f"{deal.code} -> {deal.status.value}"))


@router.message(Command("award"))
async def award(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    """``/award <code> <A|B>`` — hand everything in escrow to one party."""
    parts = (command.args or "").split()
    if len(parts) != 2:
        await answer(message, t(locale, "admin_usage"))
        return
    code = normalize_code(parts[0])
    role_text = parts[1].strip().upper()
    if code is None or role_text not in ("A", "B"):
        await answer(message, t(locale, "admin_usage"))
        return
    try:
        deal = await deps.engine.award(code, SideRole(role_text))
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await answer(message, t(locale, "admin_done", result=f"{deal.code} -> side {role_text}"))


@router.message(Command("refundeal"))
async def refund(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    code = normalize_code(command.args or "")
    if code is None:
        await answer(message, t(locale, "err_not_found"))
        return
    try:
        deal = await deps.engine.refund(code, reason="refunded by the operator")
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await answer(message, t(locale, "admin_done", result=f"{deal.code} -> {deal.status.value}"))


@router.message(Command("payout"))
async def payout(message: Message, command: CommandObject, deps: Deps, locale: str) -> None:
    """``/payout <address> <amount>`` — send TON out of escrow by hand."""
    parts = (command.args or "").split()
    if len(parts) != 2:
        await answer(message, t(locale, "admin_usage"))
        return
    try:
        amount = parse_amount(parts[1])
        digest = await deps.engine.manual_payout(parts[0], amount, "manual payout")
    except (GuarantorError, DealError) as exc:
        await report(message, locale, exc)
        return
    await answer(
        message, t(locale, "admin_done", result=f"{format_ton(amount)} sent, msg {digest[:16]}")
    )
