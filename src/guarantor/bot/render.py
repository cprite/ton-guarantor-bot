"""Turning deals into the messages people actually read.

Deposit instructions are the highest-stakes text this bot produces: if the
address, the amount or the comment is wrong, money goes somewhere it cannot be
recovered from. They are therefore built in one place, from the stored deal,
with a wallet deep link so nobody has to retype anything.
"""

from __future__ import annotations

from datetime import UTC, datetime

from guarantor.bot.deps import Deps
from guarantor.bot.texts import t
from guarantor.models import Asset, AssetKind, Deal, Side
from guarantor.money import format_ton, format_units
from guarantor.ton import addresses as addr
from guarantor.ton.links import explorer_account, explorer_tx, transfer_link


def asset_text(asset: Asset) -> str:
    """Short human description of one leg."""
    if asset.kind is AssetKind.NFT and asset.nft_address:
        return f"NFT {addr.shorten(asset.nft_address)}"
    return asset.human()


def deadline_text(timestamp: int) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def duration_text(seconds: int) -> str:
    if seconds >= 86_400:
        return f"{seconds // 86_400} d"
    if seconds >= 3_600:
        return f"{seconds // 3_600} h"
    return f"{max(seconds // 60, 1)} min"


def fee_text(deps: Deps, deal: Deal | None = None) -> str:
    if deal is not None:
        return format_ton(deal.fee_nano) if deal.fee_nano else "0 TON"
    settings = deps.settings
    return f"{settings.fee_percent}% (min {format_ton(settings.fee_min_nano)})"


def deposit_instructions(deps: Deps, deal: Deal, side: Side, locale: str) -> str:
    """Everything one party has to do, in the order they have to do it."""
    testnet = deps.settings.is_testnet
    escrow = addr.friendly(deps.escrow_address, testnet=testnet)
    memo = side.memo(deal.code)
    blocks: list[str] = []

    match side.asset.kind:
        case AssetKind.TON:
            total = side.asset.amount + side.extra_ton_required
            blocks.append(
                t(
                    locale,
                    "instr_ton",
                    amount=format_ton(total),
                    address=escrow,
                    memo=memo,
                    link=transfer_link(deps.escrow_address, total, memo, testnet=testnet),
                )
            )
        case AssetKind.JETTON:
            blocks.append(
                t(
                    locale,
                    "instr_jetton",
                    amount=format_units(
                        side.asset.amount, side.asset.jetton_decimals, side.asset.jetton_symbol or ""
                    ),
                    address=escrow,
                    memo=memo,
                )
            )
        case AssetKind.NFT:
            blocks.append(
                t(
                    locale,
                    "instr_nft",
                    nft=addr.friendly(side.asset.nft_address or "", testnet=testnet),
                    address=escrow,
                    memo=memo,
                )
            )
        case AssetKind.OFFCHAIN:
            blocks.append(t(locale, "instr_offchain", what=asset_text(side.asset)))

    if side.asset.kind is not AssetKind.TON and side.extra_ton_required > 0:
        blocks.append(
            t(
                locale,
                "instr_surcharge",
                amount=format_ton(side.extra_ton_required - side.extra_ton_paid),
            )
        )

    counterparty = deal.side(side.role.other)
    blocks.append(t(locale, "instr_waiting_peer", what=asset_text(counterparty.asset)))
    return "\n\n".join(blocks)


def deposit_message(deps: Deps, deal: Deal, side: Side, locale: str) -> str:
    return t(
        locale,
        "deposit_header",
        code=deal.code,
        deadline=deadline_text(deal.expires_at),
        instructions=deposit_instructions(deps, deal, side, locale),
    )


def terms_message(deps: Deps, deal: Deal, side: Side, locale: str) -> str:
    """The deal as it looks from one side: what they give, what they get."""
    counterparty = deal.side(side.role.other)
    return t(
        locale,
        "deal_terms",
        code=deal.code,
        give=asset_text(side.asset),
        want=asset_text(counterparty.asset),
        fee=fee_text(deps, deal),
    )


def deal_rows(deals: list[Deal], locale: str) -> str:
    return "\n".join(
        t(
            locale,
            "deal_row",
            code=deal.code,
            status=deal.status.value,
            give=asset_text(deal.a.asset),
            want=asset_text(deal.b.asset),
        )
        for deal in deals
    )


def escrow_link(deps: Deps) -> str:
    return explorer_account(deps.escrow_address, testnet=deps.settings.is_testnet)


def tx_link(deps: Deps, tx_hash: str) -> str:
    return explorer_tx(tx_hash, testnet=deps.settings.is_testnet)
