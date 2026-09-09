"""Turning engine events into Telegram messages.

The engine has no idea Telegram exists; this adapter knows who to tell and in
which language. Delivery failures are swallowed on purpose — a blocked bot must
never stop an on-chain payout from completing.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from guarantor.bot.deps import Deps
from guarantor.bot.keyboards import deal_actions
from guarantor.bot.render import asset_text, deposit_message, escrow_link
from guarantor.bot.texts import supported, t
from guarantor.escrow.events import Event
from guarantor.models import AssetKind, Deal, Side, SideRole
from guarantor.money import format_ton, format_units
from guarantor.ton import addresses as addr

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Implements :class:`~guarantor.escrow.events.Notifier` over aiogram."""

    def __init__(self, bot: Bot, deps: Deps) -> None:
        self._bot = bot
        self._deps = deps

    async def notify(self, event: Event, deal: Deal | None, **context: Any) -> None:
        try:
            await self._dispatch(event, deal, context)
        except Exception:
            log.exception("failed to deliver %s", event)

    # ------------------------------------------------------------------ core

    async def _dispatch(self, event: Event, deal: Deal | None, ctx: dict[str, Any]) -> None:
        match event:
            case Event.DEAL_JOINED:
                assert deal is not None
                await self._to_side(deal.a, "joined_notice", code=deal.code, who=deal.b.display_name())
            case Event.DEAL_ACCEPTED:
                assert deal is not None
                await self._send_deposit_instructions(deal)
            case Event.DEPOSIT_CREDITED:
                assert deal is not None
                await self._deposit_credited(deal, ctx)
            case Event.SIDE_FUNDED:
                assert deal is not None
                role = SideRole(ctx["role"])
                await self._to_both(deal, "side_funded", code=deal.code, who=deal.side(role).display_name())
            case Event.DEAL_FUNDED:
                assert deal is not None
                await self._to_both(deal, "deal_funded", code=deal.code)
            case Event.SETTLING:
                assert deal is not None
                await self._to_both(deal, "settling", code=deal.code)
            case Event.COMPLETED:
                assert deal is not None
                await self._completed(deal)
            case Event.CANCELLED:
                assert deal is not None
                await self._to_both(deal, "cancelled", code=deal.code, reason=ctx.get("reason") or "")
            case Event.EXPIRED:
                assert deal is not None
                await self._to_both(deal, "expired", code=deal.code)
            case Event.REFUNDING:
                assert deal is not None
                await self._to_both(deal, "refunding", code=deal.code)
            case Event.REFUNDED:
                assert deal is not None
                await self._to_both(deal, "refunded", code=deal.code)
            case Event.DISPUTED:
                assert deal is not None
                await self._to_both(deal, "disputed", code=deal.code)
                await self._to_admins(
                    "admin_dispute",
                    code=deal.code,
                    who=str(ctx.get("by", "?")),
                    reason=deal.dispute_reason or "—",
                )
            case Event.FAILED:
                assert deal is not None
                await self._to_both(deal, "failed", code=deal.code)
                note = deal.note or "payout failed"
                await self._to_admins("admin_alert", error=f"deal {deal.code}: {note}")
            case Event.UNMATCHED_TRANSFER:
                await self._unmatched(ctx)
            case Event.OPERATOR_ALERT:
                await self._to_admins("admin_alert", error=str(ctx.get("error", "")))

    # ------------------------------------------------------------- renderers

    async def _send_deposit_instructions(self, deal: Deal) -> None:
        for side in deal.sides:
            if side.user_id is None:
                continue
            locale = await self._locale(side.user_id)
            if not side.asset.kind.is_onchain and side.payout_address is None:
                await self._send(side.user_id, t(locale, "need_payout_address", code=deal.code))
            counterparty_offchain = not deal.side(side.role.other).asset.kind.is_onchain
            await self._send(
                side.user_id,
                deposit_message(self._deps, deal, side, locale),
                markup=deal_actions(
                    locale,
                    deal.code,
                    can_confirm_offchain=counterparty_offchain,
                    can_dispute=True,
                ),
            )

    async def _deposit_credited(self, deal: Deal, ctx: dict[str, Any]) -> None:
        transfer = ctx.get("transfer")
        role = SideRole(ctx["role"])
        side = deal.side(role)
        amount = _credited_amount(side, transfer)
        await self._to_both(
            deal,
            "deposit_credited",
            code=deal.code,
            amount=amount,
            who=side.display_name(),
        )

    async def _completed(self, deal: Deal) -> None:
        link = escrow_link(self._deps)
        for side in deal.sides:
            if side.user_id is None:
                continue
            locale = await self._locale(side.user_id)
            received = asset_text(deal.side(side.role.other).asset)
            await self._send(
                side.user_id,
                t(locale, "completed", code=deal.code, received=received, explorer=link),
            )

    async def _unmatched(self, ctx: dict[str, Any]) -> None:
        transfer = ctx.get("transfer")
        if transfer is None:
            return
        await self._to_admins(
            "admin_unmatched",
            amount=format_ton(transfer.value_nano),
            sender=addr.friendly(transfer.depositor, testnet=self._deps.settings.is_testnet),
            comment=transfer.comment or "—",
            tx=transfer.tx_hash,
        )

    # --------------------------------------------------------------- plumbing

    async def _to_side(self, side: Side, key: str, **kwargs: Any) -> None:
        if side.user_id is None:
            return
        locale = await self._locale(side.user_id)
        await self._send(side.user_id, t(locale, key, **kwargs))

    async def _to_both(self, deal: Deal, key: str, **kwargs: Any) -> None:
        for side in deal.sides:
            await self._to_side(side, key, **kwargs)

    async def _to_admins(self, key: str, **kwargs: Any) -> None:
        for admin_id in self._deps.settings.admin_id_set:
            locale = await self._locale(admin_id)
            await self._send(admin_id, t(locale, key, **kwargs))

    async def _locale(self, user_id: int) -> str:
        stored = await self._deps.storage.get_locale(user_id)
        return supported(stored or self._deps.settings.default_locale)

    async def _send(self, chat_id: int, text: str, markup: Any = None) -> None:
        try:
            await self._bot.send_message(
                chat_id, text, reply_markup=markup, disable_web_page_preview=True
            )
        except TelegramAPIError as exc:
            log.info("cannot message %s: %s", chat_id, exc)


def _credited_amount(side: Side, transfer: Any) -> str:
    if transfer is None:
        return "—"
    if side.asset.kind is AssetKind.JETTON and transfer.kind == "jetton":
        return format_units(transfer.amount, side.asset.jetton_decimals, side.asset.jetton_symbol or "")
    if transfer.kind == "nft":
        return "NFT"
    return format_ton(transfer.value_nano)
