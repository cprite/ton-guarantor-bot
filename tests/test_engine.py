"""End-to-end behaviour of the escrow state machine, with the chain faked out."""

from __future__ import annotations

import time

import pytest
from tests.conftest import (
    ALICE_WALLET,
    BOB_WALLET,
    JETTON_MASTER,
    JETTON_WALLET,
    NFT_ITEM,
    jetton_transfer,
    nft_transfer,
    ton_transfer,
)

from guarantor.codes import deposit_memo
from guarantor.errors import DealError, DealStateError, InsufficientEscrowBalance, NotAParticipant
from guarantor.escrow.events import Event
from guarantor.models import AssetKind, DealStatus, SideRole

ALICE, BOB, STRANGER = 111, 222, 333
TEN_TON = 10 * 10**9


async def open_ton_for_nft(engine):
    """Alice offers 10 TON for Bob's NFT, and Bob accepts."""
    give = engine.make_ton_asset("10")
    want = await engine.make_nft_asset(NFT_ITEM)
    deal = await engine.create_deal(ALICE, "alice", give, want)
    await engine.join_deal(deal.code, BOB, "bob")
    return await engine.accept_deal(deal.code, BOB)


# ------------------------------------------------------------------ creation


async def test_a_new_deal_starts_open_and_only_binds_its_creator(engine):
    deal = await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("1"), await engine.make_nft_asset(NFT_ITEM)
    )
    assert deal.status is DealStatus.OPEN
    assert deal.a.user_id == ALICE and deal.a.accepted
    assert deal.b.user_id is None


async def test_you_cannot_trade_with_yourself(engine):
    deal = await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("1"), await engine.make_nft_asset(NFT_ITEM)
    )
    with pytest.raises(DealError):
        await engine.join_deal(deal.code, ALICE, "alice")


async def test_identical_legs_are_refused(engine):
    with pytest.raises(DealError):
        await engine.create_deal(
            ALICE, "alice", engine.make_ton_asset("1"), engine.make_ton_asset("1")
        )


async def test_two_offchain_legs_are_refused(engine):
    with pytest.raises(DealError):
        await engine.create_deal(
            ALICE,
            "alice",
            engine.make_offchain_asset("a steam key"),
            engine.make_offchain_asset("a discord account"),
        )


async def test_active_deal_limit_is_enforced(engine, settings):
    settings.max_active_deals_per_user = 1
    await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("1"), await engine.make_nft_asset(NFT_ITEM)
    )
    with pytest.raises(DealError):
        await engine.create_deal(
            ALICE, "alice", engine.make_ton_asset("2"), await engine.make_nft_asset(NFT_ITEM)
        )


# ------------------------------------------------------------ authorisation


async def test_a_stranger_cannot_accept_someone_elses_deal(engine):
    deal = await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("1"), await engine.make_nft_asset(NFT_ITEM)
    )
    await engine.join_deal(deal.code, BOB, "bob")
    with pytest.raises(NotAParticipant):
        await engine.accept_deal(deal.code, STRANGER)


async def test_the_creator_cannot_accept_on_the_counterpartys_behalf(engine):
    deal = await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("1"), await engine.make_nft_asset(NFT_ITEM)
    )
    await engine.join_deal(deal.code, BOB, "bob")
    with pytest.raises(DealError):
        await engine.accept_deal(deal.code, ALICE)


async def test_a_stranger_cannot_cancel_or_dispute(engine):
    deal = await open_ton_for_nft(engine)
    with pytest.raises(NotAParticipant):
        await engine.cancel_deal(deal.code, STRANGER)
    with pytest.raises(NotAParticipant):
        await engine.dispute(deal.code, STRANGER)


# ----------------------------------------------------------------- deposits


async def test_accepting_moves_the_deal_to_awaiting_deposits_and_prices_the_fee(engine):
    deal = await open_ton_for_nft(engine)
    assert deal.status is DealStatus.AWAITING_DEPOSITS
    assert deal.fee_nano == 100_000_000  # 1% of 10 TON
    assert deal.a.fee_deduction == 100_000_000
    assert deal.expires_at > time.time()


async def test_a_ton_deposit_is_matched_by_its_memo(engine):
    deal = await open_ton_for_nft(engine)
    memo = deposit_memo(deal.code, "A")
    updated = await engine.credit_transfer(ton_transfer(memo, TEN_TON, ALICE_WALLET))
    assert updated is not None
    assert updated.a.funded is True
    assert updated.a.payout_address == ALICE_WALLET
    assert updated.status is DealStatus.AWAITING_DEPOSITS  # Bob has not paid yet


async def test_a_short_ton_deposit_does_not_fund_the_side(engine):
    deal = await open_ton_for_nft(engine)
    memo = deposit_memo(deal.code, "A")
    updated = await engine.credit_transfer(ton_transfer(memo, TEN_TON // 2, ALICE_WALLET))
    assert updated is not None and updated.a.funded is False

    updated = await engine.credit_transfer(ton_transfer(memo, TEN_TON // 2, ALICE_WALLET, lt=2))
    assert updated is not None and updated.a.funded is True


async def test_the_same_transfer_is_never_credited_twice(engine):
    deal = await open_ton_for_nft(engine)
    memo = deposit_memo(deal.code, "A")
    transfer = ton_transfer(memo, TEN_TON, ALICE_WALLET)
    await engine.credit_transfer(transfer)
    assert await engine.credit_transfer(transfer) is None

    stored = await engine.get_deal(deal.code)
    assert len(stored.a.deposits) == 1


async def test_a_transfer_without_a_memo_is_reported_not_credited(engine, notifier):
    await open_ton_for_nft(engine)
    assert await engine.credit_transfer(ton_transfer("thanks", TEN_TON)) is None
    assert Event.UNMATCHED_TRANSFER in notifier.kinds()


async def test_an_nft_is_matched_by_the_item_that_sent_it(engine):
    await open_ton_for_nft(engine)
    updated = await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))
    assert updated is not None
    assert updated.b.funded is True
    assert updated.b.payout_address == BOB_WALLET


async def test_an_unrelated_nft_is_not_credited(engine):
    await open_ton_for_nft(engine)
    other_item = "0:" + "9" * 64
    assert await engine.credit_transfer(nft_transfer(other_item, BOB_WALLET)) is None


# ---------------------------------------------------------------- settlement


async def test_a_fully_funded_deal_settles_both_legs_in_one_message(engine, wallet):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    settled = await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))

    assert settled.status is DealStatus.SETTLING
    assert settled.settlement is not None
    assert len(wallet.sent) == 1

    payouts = {destination: asset for _, asset, destination, _ in wallet.sent[0]}
    assert payouts[BOB_WALLET].kind is AssetKind.TON
    assert payouts[BOB_WALLET].amount == TEN_TON - 100_000_000  # fee withheld
    assert payouts[ALICE_WALLET].kind is AssetKind.NFT
    assert payouts[ALICE_WALLET].nft_address == NFT_ITEM


async def test_reconcile_completes_a_settlement_the_chain_accepted(engine, wallet, notifier):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    settling = await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))

    wallet.applied = True
    done = await engine.reconcile(settling)
    assert done.status is DealStatus.COMPLETED
    assert done.settlement.confirmed is True
    assert Event.COMPLETED in notifier.kinds()


async def test_an_expired_external_message_is_rebuilt_rather_than_abandoned(engine, wallet):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    settling = await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))

    wallet.applied = False  # the message expired without being applied
    retried = await engine.reconcile(settling)
    assert retried.status is DealStatus.SETTLING
    assert len(wallet.sent) == 2
    assert retried.settle_attempts == 2


async def test_a_payout_that_never_lands_is_escalated_to_a_human(engine, wallet, notifier):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    current = await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))

    wallet.applied = False
    for _ in range(10):
        current = await engine.reconcile(current)
        if current.status is DealStatus.FAILED:
            break

    assert current.status is DealStatus.FAILED
    assert Event.FAILED in notifier.kinds()


async def test_reconcile_waits_while_the_outcome_is_still_unknown(engine, wallet):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    settling = await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))

    wallet.applied = None
    unchanged = await engine.reconcile(settling)
    assert unchanged.status is DealStatus.SETTLING
    assert len(wallet.sent) == 1


# -------------------------------------------------------- expiry and refunds


async def test_an_unjoined_deal_is_cancelled_once_it_expires(engine, storage):
    deal = await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("1"), await engine.make_nft_asset(NFT_ITEM)
    )
    deal.expires_at = int(time.time()) - 1
    await storage.put_deal(deal)

    await engine.expire_due()
    assert (await engine.get_deal(deal.code)).status is DealStatus.CANCELLED


async def test_a_half_funded_deal_is_refunded_to_the_wallet_that_paid(engine, storage, wallet):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))

    stale = await engine.get_deal(deal.code)
    stale.expires_at = int(time.time()) - 1
    await storage.put_deal(stale)

    await engine.expire_due()
    refunding = await engine.get_deal(deal.code)
    assert refunding.status is DealStatus.REFUNDING

    refund = wallet.sent[-1]
    assert len(refund) == 1
    _, asset, destination, _ = refund[0]
    assert destination == ALICE_WALLET
    assert asset.amount == TEN_TON  # the fee is only charged on a completed deal


async def test_an_expired_deal_nobody_funded_is_just_cancelled(engine, storage, wallet):
    deal = await open_ton_for_nft(engine)
    stale = await engine.get_deal(deal.code)
    stale.expires_at = int(time.time()) - 1
    await storage.put_deal(stale)

    await engine.expire_due()
    assert (await engine.get_deal(deal.code)).status is DealStatus.CANCELLED
    assert wallet.sent == []


async def test_cancelling_is_refused_once_money_is_in_escrow(engine):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    with pytest.raises(DealStateError):
        await engine.cancel_deal(deal.code, ALICE)


# --------------------------------------------------------------- arbitration


async def test_a_disputed_deal_stops_moving(engine):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    disputed = await engine.dispute(deal.code, ALICE, "he went quiet")
    assert disputed.status is DealStatus.DISPUTED
    assert disputed.dispute_reason == "he went quiet"

    # Deposits arriving after a dispute are reported, not credited.
    assert await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET)) is None


async def test_the_operator_can_award_everything_to_one_side(engine, wallet):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    await engine.dispute(deal.code, ALICE)

    awarded = await engine.award(deal.code, SideRole.A)
    assert awarded.status is DealStatus.SETTLING
    _, asset, destination, _ = wallet.sent[-1][0]
    assert destination == ALICE_WALLET
    assert asset.amount == TEN_TON - 100_000_000


# ------------------------------------------------------------------ jettons


async def test_a_jetton_leg_is_matched_by_the_escrow_jetton_wallet(engine):
    give = await engine.make_jetton_asset(JETTON_MASTER, "1.5")
    assert give.jetton_decimals == 6 and give.amount == 1_500_000
    assert give.jetton_wallet == JETTON_WALLET

    deal = await engine.create_deal(ALICE, "alice", give, engine.make_ton_asset("5"))
    await engine.join_deal(deal.code, BOB, "bob")
    await engine.accept_deal(deal.code, BOB)

    memo = deposit_memo(deal.code, "A")
    updated = await engine.credit_transfer(
        jetton_transfer(JETTON_WALLET, ALICE_WALLET, 1_500_000, memo)
    )
    assert updated is not None and updated.a.funded is True


# ----------------------------------------------------------------- off-chain


async def test_an_offchain_leg_is_closed_by_the_counterparty_confirming(engine, wallet):
    give = engine.make_ton_asset("2")
    want = engine.make_offchain_asset("a Steam key for Portal 2")
    deal = await engine.create_deal(ALICE, "alice", give, want)
    await engine.join_deal(deal.code, BOB, "bob")
    await engine.accept_deal(deal.code, BOB)

    # Bob has no on-chain deposit, so he has to say where his TON should land.
    await engine.set_payout_address(deal.code, BOB, BOB_WALLET)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), 2 * 10**9, ALICE_WALLET))

    settled = await engine.confirm_offchain(deal.code, ALICE)
    assert settled.status is DealStatus.SETTLING
    _, asset, destination, _ = wallet.sent[-1][0]
    assert destination == BOB_WALLET
    assert asset.amount == 2 * 10**9 - 50_000_000  # the 0.05 TON minimum fee


async def test_only_the_receiving_party_can_confirm_an_offchain_leg(engine):
    deal = await engine.create_deal(
        ALICE, "alice", engine.make_ton_asset("2"), engine.make_offchain_asset("a key")
    )
    await engine.join_deal(deal.code, BOB, "bob")
    await engine.accept_deal(deal.code, BOB)
    # Bob's own leg is the off-chain one; he cannot mark it as received himself.
    with pytest.raises(DealError):
        await engine.confirm_offchain(deal.code, BOB)


# ------------------------------------------------- safety around live payouts


async def test_a_second_payout_is_refused_while_the_first_is_undecided(engine, wallet):
    deal = await open_ton_for_nft(engine)
    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))
    assert len(wallet.sent) == 1

    # An operator reaching for /refundeal mid-settlement must not double-spend.
    with pytest.raises(DealStateError):
        await engine.refund(deal.code)
    with pytest.raises(DealStateError):
        await engine.settle(deal.code)
    assert len(wallet.sent) == 1


async def test_a_funded_deal_that_could_not_pay_out_is_retried_by_the_sweeper(engine, wallet):
    deal = await open_ton_for_nft(engine)
    wallet.funded_enough = False  # the escrow has no gas left

    await engine.credit_transfer(ton_transfer(deposit_memo(deal.code, "A"), TEN_TON, ALICE_WALLET))
    with pytest.raises(InsufficientEscrowBalance):
        await engine.credit_transfer(nft_transfer(NFT_ITEM, BOB_WALLET))

    stuck = await engine.get_deal(deal.code)
    assert stuck.status is DealStatus.FUNDED
    assert wallet.sent == []

    wallet.funded_enough = True  # operator tops the escrow up
    await engine.expire_due()

    assert (await engine.get_deal(deal.code)).status is DealStatus.SETTLING
    assert len(wallet.sent) == 1
