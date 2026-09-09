"""Building a deal, one question at a time.

The half-built deal lives in the FSM context, not in the database: nothing is
persisted until both legs are valid, so an abandoned conversation leaves no
half-formed deal for the watcher to trip over.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from guarantor.bot.callbacks import AssetCB, MenuCB
from guarantor.bot.deps import Deps
from guarantor.bot.handlers.shared import answer, report, show_menu
from guarantor.bot.keyboards import asset_kinds, back_only
from guarantor.bot.render import asset_text, duration_text
from guarantor.bot.texts import t
from guarantor.errors import GuarantorError
from guarantor.models import Asset, AssetKind
from guarantor.ton.links import deal_link

router = Router(name="create")


class Create(StatesGroup):
    """Steps of the creation wizard.

    ``give`` is what the creator hands over, ``want`` is what they expect back.
    """

    give_value = State()
    give_jetton_amount = State()
    want_value = State()
    want_jetton_amount = State()


@router.callback_query(MenuCB.filter(F.action == "create"))
async def start_create(call: CallbackQuery, state: FSMContext, deps: Deps, locale: str) -> None:
    await state.clear()
    await answer(
        call,
        t(locale, "choose_give"),
        asset_kinds(locale, "give", allow_offchain=deps.settings.allow_offchain_assets),
    )


@router.callback_query(AssetCB.filter())
async def pick_kind(
    call: CallbackQuery, callback_data: AssetCB, state: FSMContext, deps: Deps, locale: str
) -> None:
    """Ask for whatever this asset kind needs to be fully specified."""
    kind = AssetKind(callback_data.kind)
    step = callback_data.step
    await state.update_data({f"{step}_kind": kind.value})

    match kind:
        case AssetKind.TON:
            await state.set_state(Create.give_value if step == "give" else Create.want_value)
            await answer(call, t(locale, "ask_ton_amount"), back_only(locale))
        case AssetKind.NFT:
            await state.set_state(Create.give_value if step == "give" else Create.want_value)
            await answer(call, t(locale, "ask_nft_address"), back_only(locale))
        case AssetKind.OFFCHAIN:
            await state.set_state(Create.give_value if step == "give" else Create.want_value)
            await answer(call, t(locale, "ask_offchain"), back_only(locale))
        case AssetKind.JETTON:
            await state.set_state(Create.give_value if step == "give" else Create.want_value)
            await answer(call, t(locale, "ask_jetton_master"), back_only(locale))


@router.message(Create.give_value)
async def give_value(message: Message, state: FSMContext, deps: Deps, locale: str) -> None:
    await _consume_value(message, state, deps, locale, step="give")


@router.message(Create.want_value)
async def want_value(message: Message, state: FSMContext, deps: Deps, locale: str) -> None:
    await _consume_value(message, state, deps, locale, step="want")


@router.message(Create.give_jetton_amount)
async def give_jetton_amount(message: Message, state: FSMContext, deps: Deps, locale: str) -> None:
    await _consume_jetton_amount(message, state, deps, locale, step="give")


@router.message(Create.want_jetton_amount)
async def want_jetton_amount(message: Message, state: FSMContext, deps: Deps, locale: str) -> None:
    await _consume_jetton_amount(message, state, deps, locale, step="want")


# --------------------------------------------------------------------- steps


async def _consume_value(
    message: Message, state: FSMContext, deps: Deps, locale: str, *, step: str
) -> None:
    data = await state.get_data()
    kind = AssetKind(data[f"{step}_kind"])
    text = (message.text or "").strip()

    try:
        if kind is AssetKind.JETTON:
            # For a jetton the first answer is the master; the amount follows,
            # once we know how many decimals it has.
            info = await deps.engine.jetton_info(text)
            await state.update_data({f"{step}_master": text})
            await state.set_state(
                Create.give_jetton_amount if step == "give" else Create.want_jetton_amount
            )
            await answer(
                message,
                t(locale, "ask_jetton_amount", symbol=info.symbol, decimals=info.decimals),
                back_only(locale),
            )
            return

        asset = await _build_simple_asset(deps, kind, text)
    except GuarantorError as exc:
        await report(message, locale, exc)
        return

    await _store_and_advance(message, state, deps, locale, step, asset)


async def _consume_jetton_amount(
    message: Message, state: FSMContext, deps: Deps, locale: str, *, step: str
) -> None:
    data = await state.get_data()
    try:
        asset = await deps.engine.make_jetton_asset(data[f"{step}_master"], (message.text or "").strip())
    except GuarantorError as exc:
        await report(message, locale, exc)
        return
    await _store_and_advance(message, state, deps, locale, step, asset)


async def _build_simple_asset(deps: Deps, kind: AssetKind, text: str) -> Asset:
    match kind:
        case AssetKind.TON:
            return deps.engine.make_ton_asset(text)
        case AssetKind.NFT:
            return await deps.engine.make_nft_asset(text)
        case AssetKind.OFFCHAIN:
            return deps.engine.make_offchain_asset(text)
    raise AssertionError(f"unexpected kind {kind!r}")


async def _store_and_advance(
    message: Message, state: FSMContext, deps: Deps, locale: str, step: str, asset: Asset
) -> None:
    await state.update_data({f"{step}_asset": asset.to_dict()})

    if step == "give":
        await state.set_state(None)
        await answer(
            message,
            t(locale, "choose_want"),
            asset_kinds(
                locale,
                "want",
                allow_offchain=deps.settings.allow_offchain_assets,
                exclude=asset.kind if asset.kind is AssetKind.OFFCHAIN else None,
            ),
        )
        return

    await _finish(message, state, deps, locale)


async def _finish(message: Message, state: FSMContext, deps: Deps, locale: str) -> None:
    data = await state.get_data()
    await state.clear()
    if message.from_user is None:
        return

    give = Asset.from_dict(data["give_asset"])
    want = Asset.from_dict(data["want_asset"])
    try:
        deal = await deps.engine.create_deal(
            message.from_user.id, message.from_user.username, give, want
        )
    except GuarantorError as exc:
        await report(message, locale, exc)
        await show_menu(message, locale)
        return

    await answer(
        message,
        t(
            locale,
            "deal_created",
            code=deal.code,
            give=asset_text(give),
            want=asset_text(want),
            link=deal_link(deps.bot_username, deal.code),
            ttl=duration_text(deps.settings.open_deal_ttl_seconds),
        ),
        back_only(locale),
    )
