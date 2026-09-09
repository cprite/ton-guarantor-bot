"""Entry points: /start, the main menu, help and language."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from guarantor.bot.callbacks import LangCB, MenuCB
from guarantor.bot.deps import Deps
from guarantor.bot.handlers.shared import answer, report, show_deal, show_menu
from guarantor.bot.keyboards import back_only, languages, main_menu
from guarantor.bot.render import deal_rows, escrow_link, fee_text
from guarantor.bot.texts import t
from guarantor.codes import normalize_code
from guarantor.errors import GuarantorError

router = Router(name="common")


@router.message(CommandStart(deep_link=True))
async def start_deep_link(
    message: Message, command: CommandObject, state: FSMContext, deps: Deps, locale: str
) -> None:
    """``t.me/bot?start=deal_XXXXXXXX`` opens straight into that deal."""
    await state.clear()
    payload = (command.args or "").removeprefix("deal_")
    code = normalize_code(payload)
    if code is None or message.from_user is None:
        await show_menu(message, locale)
        return

    try:
        deal = await deps.engine.get_deal(code)
        if deal is None:
            await answer(message, t(locale, "err_not_found"), main_menu(locale))
            return
        if deal.side_of(message.from_user.id) is None:
            deal = await deps.engine.join_deal(code, message.from_user.id, message.from_user.username)
        await show_deal(deps, message, deal, message.from_user.id, locale)
    except GuarantorError as exc:
        await report(message, locale, exc)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, locale: str) -> None:
    await state.clear()
    await show_menu(message, locale)


@router.callback_query(MenuCB.filter(F.action == "root"))
async def menu_root(call: CallbackQuery, state: FSMContext, locale: str) -> None:
    await state.clear()
    await show_menu(call, locale)


@router.message(Command("help"))
@router.callback_query(MenuCB.filter(F.action == "help"))
async def help_handler(event: Message | CallbackQuery, deps: Deps, locale: str) -> None:
    settings = deps.settings
    await answer(
        event,
        t(
            locale,
            "help",
            escrow=deps.escrow_address,
            explorer=escrow_link(deps),
            network=settings.ton_network,
            fee=fee_text(deps),
        ),
        back_only(locale),
    )


@router.message(Command("deals"))
@router.callback_query(MenuCB.filter(F.action == "deals"))
async def my_deals(event: Message | CallbackQuery, deps: Deps, locale: str) -> None:
    user = event.from_user
    if user is None:
        return
    deals = await deps.engine.deals_of(user.id)
    if not deals:
        await answer(event, t(locale, "my_deals_empty"), back_only(locale))
        return
    await answer(event, t(locale, "my_deals", rows=deal_rows(deals, locale)), back_only(locale))


@router.message(Command("lang"))
@router.callback_query(MenuCB.filter(F.action == "lang"))
async def choose_language(event: Message | CallbackQuery, locale: str) -> None:
    await answer(event, t(locale, "lang_prompt"), languages())


@router.callback_query(LangCB.filter())
async def set_language(call: CallbackQuery, callback_data: LangCB, deps: Deps) -> None:
    if call.from_user is None:
        return
    await deps.storage.set_locale(call.from_user.id, callback_data.locale)
    await answer(call, t(callback_data.locale, "lang_set"), main_menu(callback_data.locale))
