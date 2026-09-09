"""The poller's bookkeeping: where it resumes from, and what it credits."""

from __future__ import annotations

from tests.conftest import NFT_ITEM
from tests.test_ton_parsing import comment_body, transaction

from guarantor.codes import deposit_memo
from guarantor.escrow.watcher import CURSOR_NAME, PAGE_SIZE, ChainWatcher
from guarantor.models import DealStatus

TEN_TON = 10 * 10**9


class ReplayGateway:
    """Serves a fixed ledger the way a TON API would: newest first."""

    def __init__(self, transactions: list) -> None:
        self.transactions = transactions
        self.calls: list[tuple[int | None, int | None]] = []

    async def get_transactions(self, address, *, limit=100, from_lt=None, to_lt=None):
        self.calls.append((from_lt, to_lt))
        rows = sorted(self.transactions, key=lambda t: t.lt, reverse=True)
        if from_lt is not None:
            rows = [t for t in rows if t.lt <= from_lt]
        if to_lt:
            rows = [t for t in rows if t.lt > to_lt]
        return rows[:limit]


def ton_tx(memo: str, amount: int, lt: int):
    return transaction(comment_body(memo), value=amount, lt=lt)


async def make_deal(engine):
    deal = await engine.create_deal(
        111, "alice", engine.make_ton_asset("10"), await engine.make_nft_asset(NFT_ITEM)
    )
    await engine.join_deal(deal.code, 222, "bob")
    return await engine.accept_deal(deal.code, 222)


async def test_priming_skips_history_on_a_fresh_database(settings, storage, engine):
    gateway = ReplayGateway([ton_tx("old", 1, lt=500)])
    watcher = ChainWatcher(settings, storage, gateway, engine)

    await watcher.prime()
    assert await storage.get_cursor(CURSOR_NAME) == 500

    assert await watcher.poll_once() == 0


async def test_polling_credits_new_transfers_and_advances_the_cursor(settings, storage, engine):
    deal = await make_deal(engine)
    memo = deposit_memo(deal.code, "A")
    gateway = ReplayGateway([ton_tx(memo, TEN_TON, lt=900)])
    watcher = ChainWatcher(settings, storage, gateway, engine)

    assert await watcher.poll_once() == 1
    assert await storage.get_cursor(CURSOR_NAME) == 900

    funded = await engine.get_deal(deal.code)
    assert funded.a.funded is True


async def test_polling_twice_does_not_credit_the_same_transfer_again(settings, storage, engine):
    deal = await make_deal(engine)
    memo = deposit_memo(deal.code, "A")
    gateway = ReplayGateway([ton_tx(memo, TEN_TON // 2, lt=900)])
    watcher = ChainWatcher(settings, storage, gateway, engine)

    await watcher.poll_once()
    assert await watcher.poll_once() == 0

    stored = await engine.get_deal(deal.code)
    assert len(stored.a.deposits) == 1


async def test_a_backlog_is_paged_through_rather_than_truncated(settings, storage, engine):
    deal = await make_deal(engine)
    memo = deposit_memo(deal.code, "A")
    # One real deposit buried under more filler than a single page can hold.
    ledger = [ton_tx("noise", 10**8, lt=lt) for lt in range(1, PAGE_SIZE + 40)]
    ledger.append(ton_tx(memo, TEN_TON, lt=PAGE_SIZE + 100))
    gateway = ReplayGateway(ledger)
    watcher = ChainWatcher(settings, storage, gateway, engine)

    assert await watcher.poll_once() == 1
    assert len(gateway.calls) > 1
    assert (await engine.get_deal(deal.code)).a.funded is True


async def test_the_sweeper_expires_and_reconciles(settings, storage, engine, wallet):
    deal = await make_deal(engine)
    stale = await engine.get_deal(deal.code)
    stale.expires_at = 1
    await storage.put_deal(stale)

    watcher = ChainWatcher(settings, storage, ReplayGateway([]), engine)
    await watcher.sweep_once()

    assert (await engine.get_deal(deal.code)).status is DealStatus.CANCELLED
