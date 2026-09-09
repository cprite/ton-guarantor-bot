"""Helpers every router needs."""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from guarantor.bot.deps import Deps
from guarantor.bot.keyboards import deal_actions, deal_terms, main_menu
from guarantor.bot.render import deposit_message, terms_message
from guarantor.bot.texts import t
from guarantor.errors import GuarantorError
from guarantor.models import Deal, DealStatus

log = logging.getLogger(__name__)

Target = Message | CallbackQuery


async def answer(target: Target, text: str, markup=None) -> None:
    """Reply in place, whether we were called from a message or a button."""
    if isinstance(target, CallbackQuery):
        await target.answer()
        if target.message is not None and not isinstance(target.message, InaccessibleMessage):
            try:
                await target.message.edit_text(
                    text, reply_markup=markup, disable_web_page_preview=True
                )
                return
            except Exception:
                # The message may be identical or too old to edit; send a new one.
                await target.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
                return
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def show_menu(target: Target, locale: str) -> None:
    await answer(target, t(locale, "menu"), main_menu(locale))


async def report(target: Target, locale: str, error: Exception) -> None:
    """Show a domain error to the user; log anything unexpected."""
    if isinstance(error, GuarantorError):
        await answer(target, t(locale, "err_generic", error=str(error)))
        return
    log.exception("unhandled error in a handler")
    await answer(target, t(locale, "err_generic", error="internal error"))


async def show_deal(deps: Deps, target: Target, deal: Deal, user_id: int, locale: str) -> None:
    """Render a deal from the viewer's own side, with the right buttons."""
    side = deal.side_of(user_id)
    if side is None:
        await answer(target, t(locale, "err_not_found"))
        return

    if deal.status is DealStatus.OPEN and side.role.value == "B":
        await answer(target, terms_message(deps, deal, side, locale), deal_terms(locale, deal.code))
        return

    if deal.status is DealStatus.AWAITING_DEPOSITS:
        counterparty = deal.side(side.role.other)
        awaiting_offchain = not counterparty.asset.kind.is_onchain and not counterparty.offchain_confirmed
        await answer(
            target,
            deposit_message(deps, deal, side, locale),
            deal_actions(
                locale,
                deal.code,
                can_confirm_offchain=awaiting_offchain,
                can_dispute=True,
            ),
        )
        return

    await answer(
        target,
        terms_message(deps, deal, side, locale) + f"\n\nStatus: <b>{deal.status.value}</b>",
        deal_actions(locale, deal.code, can_dispute=deal.status is DealStatus.FUNDED),
    )
