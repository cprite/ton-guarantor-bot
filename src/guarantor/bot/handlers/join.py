"""Joining a deal and acting on it once it is running."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from guarantor.bot.callbacks import DealCB, MenuCB
from guarantor.bot.deps import Deps
from guarantor.bot.handlers.shared import answer, report, show_deal, show_menu
from guarantor.bot.keyboards import back_only
from guarantor.bot.texts import t
from guarantor.codes import normalize_code
from guarantor.errors import GuarantorError

router = Router(name="join")


class Join(StatesGroup):
    code = State()


@router.callback_query(MenuCB.filter(F.action == "join"))
async def ask_code(call: CallbackQuery, state: FSMContext, locale: str) -> None:
    await state.set_state(Join.code)
    await answer(call, t(locale, "join_ask_code"), back_only(locale))


@router.message(Join.code)
async def enter_code(message: Message, state: FSMContext, deps: Deps, locale: str) -> None:
    await state.clear()
    if message.from_user is None:
        return

    code = normalize_code(message.text or "")
    if code is None:
        await answer(message, t(locale, "err_not_found"))
        await show_menu(message, locale)
        return

    try:
        deal = await deps.engine.get_deal(code)
        if deal is None:
            await answer(message, t(locale, "err_not_found"))
            await show_menu(message, locale)
            return
        if deal.side_of(message.from_user.id) is None:
            deal = await deps.engine.join_deal(code, message.from_user.id, message.from_user.username)
        await show_deal(deps, message, deal, message.from_user.id, locale)
    except GuarantorError as exc:
        await report(message, locale, exc)


@router.callback_query(DealCB.filter(F.action == "accept"))
async def accept(call: CallbackQuery, callback_data: DealCB, deps: Deps, locale: str) -> None:
    if call.from_user is None:
        return
    try:
        deal = await deps.engine.accept_deal(callback_data.code, call.from_user.id)
    except GuarantorError as exc:
        await report(call, locale, exc)
        return
    await show_deal(deps, call, deal, call.from_user.id, locale)


@router.callback_query(DealCB.filter(F.action == "decline"))
async def decline(call: CallbackQuery, callback_data: DealCB, deps: Deps, locale: str) -> None:
    if call.from_user is None:
        return
    try:
        await deps.engine.cancel_deal(callback_data.code, call.from_user.id)
    except GuarantorError as exc:
        await report(call, locale, exc)
        return
    await show_menu(call, locale)


@router.callback_query(DealCB.filter(F.action == "received"))
async def confirm_received(call: CallbackQuery, callback_data: DealCB, deps: Deps, locale: str) -> None:
    if call.from_user is None:
        return
    try:
        deal = await deps.engine.confirm_offchain(callback_data.code, call.from_user.id)
    except GuarantorError as exc:
        await report(call, locale, exc)
        return
    await show_deal(deps, call, deal, call.from_user.id, locale)


@router.callback_query(DealCB.filter(F.action == "dispute"))
async def open_dispute(call: CallbackQuery, callback_data: DealCB, deps: Deps, locale: str) -> None:
    if call.from_user is None:
        return
    try:
        deal = await deps.engine.dispute(callback_data.code, call.from_user.id)
    except GuarantorError as exc:
        await report(call, locale, exc)
        return
    await show_deal(deps, call, deal, call.from_user.id, locale)


@router.callback_query(DealCB.filter(F.action == "show"))
async def show(call: CallbackQuery, callback_data: DealCB, deps: Deps, locale: str) -> None:
    if call.from_user is None:
        return
    deal = await deps.engine.get_deal(callback_data.code)
    if deal is None:
        await answer(call, t(locale, "err_not_found"))
        return
    await show_deal(deps, call, deal, call.from_user.id, locale)
