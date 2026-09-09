"""Inline keyboards, built per locale."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from guarantor.bot.callbacks import AssetCB, DealCB, LangCB, MenuCB
from guarantor.bot.texts import LOCALES, t
from guarantor.models import AssetKind


def main_menu(locale: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t(locale, "btn_create"), callback_data=MenuCB(action="create"))
    builder.button(text=t(locale, "btn_join"), callback_data=MenuCB(action="join"))
    builder.button(text=t(locale, "btn_deals"), callback_data=MenuCB(action="deals"))
    builder.button(text=t(locale, "btn_help"), callback_data=MenuCB(action="help"))
    builder.button(text=t(locale, "btn_lang"), callback_data=MenuCB(action="lang"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def back_only(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(locale, "btn_back"), callback_data=MenuCB(action="root").pack())]
        ]
    )


def asset_kinds(
    locale: str, step: str, *, allow_offchain: bool, exclude: AssetKind | None = None
) -> InlineKeyboardMarkup:
    """Asset picker. ``exclude`` drops the kind already chosen for the other leg
    when it could only produce a meaningless trade."""
    builder = InlineKeyboardBuilder()
    for kind, label in (
        (AssetKind.TON, "asset_ton"),
        (AssetKind.JETTON, "asset_jetton"),
        (AssetKind.NFT, "asset_nft"),
        (AssetKind.OFFCHAIN, "asset_offchain"),
    ):
        if kind is AssetKind.OFFCHAIN and (not allow_offchain or exclude is AssetKind.OFFCHAIN):
            continue
        builder.button(text=t(locale, label), callback_data=AssetCB(step=step, kind=kind.value))
    builder.button(text=t(locale, "btn_back"), callback_data=MenuCB(action="root"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def deal_terms(locale: str, code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t(locale, "btn_accept"), callback_data=DealCB(action="accept", code=code))
    builder.button(text=t(locale, "btn_decline"), callback_data=DealCB(action="decline", code=code))
    builder.adjust(2)
    return builder.as_markup()


def deal_actions(
    locale: str, code: str, *, can_confirm_offchain: bool = False, can_dispute: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_confirm_offchain:
        builder.button(text=t(locale, "btn_received"), callback_data=DealCB(action="received", code=code))
    if can_dispute:
        builder.button(text=t(locale, "btn_dispute"), callback_data=DealCB(action="dispute", code=code))
    builder.button(text=t(locale, "btn_refresh"), callback_data=DealCB(action="show", code=code))
    builder.button(text=t(locale, "btn_back"), callback_data=MenuCB(action="root"))
    builder.adjust(1)
    return builder.as_markup()


def languages() -> InlineKeyboardMarkup:
    names = {"en": "English", "ru": "Русский"}
    builder = InlineKeyboardBuilder()
    for code in LOCALES:
        builder.button(text=names.get(code, code), callback_data=LangCB(locale=code))
    builder.adjust(2)
    return builder.as_markup()
