"""How the operator's commission is computed and who ends up paying it.

The fee is always denominated in TON. Where it comes from depends on the deal:

* If either leg is TON, the fee is taken out of that flow. ``FEE_PAYER``
  decides whether it is deducted from the payout (``receiver``), added to the
  deposit (``sender``), or halved between the two (``split``).
* If neither leg is TON — an NFT traded for an NFT, say — there is nothing to
  deduct from. ``FEE_NO_TON_LEG`` then either waives the fee (``skip``) or asks
  each side for a small separate TON deposit (``require_deposit``).

Everything is integer nanoton arithmetic; the fee is rounded down so a deal is
never short by a rounding unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from guarantor.config import Settings
from guarantor.errors import DealError
from guarantor.models import Asset, AssetKind, SideRole
from guarantor.money import format_ton


class FeeError(DealError):
    """The deal is too small to carry the configured fee."""


@dataclass(slots=True)
class FeePlan:
    """The commission for one deal, and how it is collected."""

    total_nano: int = 0
    #: Nanotons withheld from the TON payout of this side's asset.
    deduct: dict[SideRole, int] = field(default_factory=dict)
    #: Extra TON this side must deposit on top of its asset.
    surcharge: dict[SideRole, int] = field(default_factory=dict)

    def payout_amount(self, role: SideRole, asset: Asset) -> int:
        """What the counterparty actually receives for ``asset``."""
        if asset.kind is not AssetKind.TON:
            return asset.amount
        return asset.amount - self.deduct.get(role, 0)

    def required_deposit(self, role: SideRole, asset: Asset) -> int:
        """Total TON this side must send, asset plus any surcharge."""
        base = asset.amount if asset.kind is AssetKind.TON else 0
        return base + self.surcharge.get(role, 0)


def plan_fee(assets: dict[SideRole, Asset], settings: Settings) -> FeePlan:
    """Work out the commission for a deal made of these two legs.

    :raises FeeError: if the fee would consume a TON leg entirely.
    """
    ton_roles = [role for role, asset in assets.items() if asset.kind is AssetKind.TON]

    if not ton_roles:
        return _plan_without_ton_leg(settings)

    base = sum(assets[role].amount for role in ton_roles)
    fee = _percentage_of(base, settings.fee_percent)
    fee = max(fee, settings.fee_min_nano)

    plan = FeePlan(total_nano=fee)
    for role, share in _split_proportionally(fee, {r: assets[r].amount for r in ton_roles}).items():
        _assign(plan, role, share, settings.fee_payer)

    for role in ton_roles:
        remaining = assets[role].amount - plan.deduct.get(role, 0)
        if remaining < settings.min_deposit_nano:
            raise FeeError(
                f"a {format_ton(assets[role].amount)} leg is too small for a "
                f"{format_ton(fee)} fee; the recipient would get {format_ton(max(remaining, 0))}"
            )
    return plan


def _plan_without_ton_leg(settings: Settings) -> FeePlan:
    if settings.fee_no_ton_leg == "skip":
        return FeePlan()
    fee = settings.fee_flat_nano
    if fee <= 0:
        return FeePlan()
    half = fee // 2
    return FeePlan(
        total_nano=fee,
        surcharge={SideRole.A: fee - half, SideRole.B: half},
    )


def _assign(plan: FeePlan, role: SideRole, share: int, payer: str) -> None:
    if share <= 0:
        return
    match payer:
        case "sender":
            plan.surcharge[role] = plan.surcharge.get(role, 0) + share
        case "split":
            half = share // 2
            plan.deduct[role] = plan.deduct.get(role, 0) + half
            plan.surcharge[role] = plan.surcharge.get(role, 0) + (share - half)
        case _:  # "receiver"
            plan.deduct[role] = plan.deduct.get(role, 0) + share


def _percentage_of(amount: int, percent: Decimal) -> int:
    if amount <= 0 or percent <= 0:
        return 0
    value = (Decimal(amount) * percent / Decimal(100)).to_integral_value(rounding=ROUND_DOWN)
    return int(value)


def _split_proportionally(total: int, weights: dict[SideRole, int]) -> dict[SideRole, int]:
    """Divide ``total`` across weighted roles, giving any remainder to the first."""
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        return {}
    order = sorted(weights)
    shares = {role: total * weights[role] // weight_sum for role in order}
    shares[order[0]] += total - sum(shares.values())
    return shares
