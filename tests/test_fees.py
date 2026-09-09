from decimal import Decimal

import pytest

from guarantor.config import Settings
from guarantor.escrow.fees import FeeError, plan_fee
from guarantor.models import Asset, AssetKind, SideRole

TON = lambda amount: Asset(kind=AssetKind.TON, amount=amount)  # noqa: E731
NFT = Asset(kind=AssetKind.NFT, nft_address="0:" + "1" * 64)


def make(**kwargs) -> Settings:
    base = dict(bot_token="1:t", admin_ids="1", fee_percent=Decimal("1.0"), fee_min_ton=Decimal("0.05"))
    return Settings(**{**base, **kwargs})


def test_percentage_is_deducted_from_the_ton_leg():
    plan = plan_fee({SideRole.A: TON(10 * 10**9), SideRole.B: NFT}, make())
    assert plan.total_nano == 100_000_000
    assert plan.deduct[SideRole.A] == 100_000_000
    assert plan.payout_amount(SideRole.A, TON(10 * 10**9)) == 9_900_000_000
    assert plan.required_deposit(SideRole.A, TON(10 * 10**9)) == 10 * 10**9


def test_minimum_fee_applies_to_small_deals():
    plan = plan_fee({SideRole.A: TON(10**9), SideRole.B: NFT}, make(fee_percent=Decimal("0.1")))
    assert plan.total_nano == 50_000_000  # the 0.05 TON floor, not 0.001


def test_sender_pays_means_a_bigger_deposit():
    settings = make(fee_payer="sender")
    plan = plan_fee({SideRole.A: TON(10 * 10**9), SideRole.B: NFT}, settings)
    assert plan.deduct == {}
    assert plan.required_deposit(SideRole.A, TON(10 * 10**9)) == 10_100_000_000
    assert plan.payout_amount(SideRole.A, TON(10 * 10**9)) == 10 * 10**9


def test_split_halves_the_fee_between_both_ends():
    plan = plan_fee({SideRole.A: TON(10 * 10**9), SideRole.B: NFT}, make(fee_payer="split"))
    assert plan.deduct[SideRole.A] + plan.surcharge[SideRole.A] == plan.total_nano


def test_two_ton_legs_share_the_fee_proportionally():
    plan = plan_fee({SideRole.A: TON(3 * 10**9), SideRole.B: TON(10**9)}, make())
    assert sum(plan.deduct.values()) == plan.total_nano
    assert plan.deduct[SideRole.A] > plan.deduct[SideRole.B]


def test_deals_without_a_ton_leg_are_free_by_default():
    assert plan_fee({SideRole.A: NFT, SideRole.B: NFT}, make()).total_nano == 0


def test_deals_without_a_ton_leg_can_be_charged_as_a_deposit():
    settings = make(fee_no_ton_leg="require_deposit", fee_flat_ton=Decimal("0.2"))
    plan = plan_fee({SideRole.A: NFT, SideRole.B: NFT}, settings)
    assert plan.total_nano == 200_000_000
    assert sum(plan.surcharge.values()) == 200_000_000


def test_a_deal_too_small_for_its_fee_is_refused():
    with pytest.raises(FeeError):
        plan_fee({SideRole.A: TON(1000), SideRole.B: NFT}, make())
