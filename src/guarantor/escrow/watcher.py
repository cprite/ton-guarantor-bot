"""Two background loops that keep deals moving without anyone pressing a button.

The **poller** reads the escrow wallet's incoming transactions and hands each
one to the engine. It remembers its position with a logical-time cursor, so a
restart resumes exactly where it stopped instead of replaying or skipping.

The **sweeper** does the work that is driven by the clock rather than by money
arriving: expiring deals nobody funded, refunding the ones that timed out, and
reconciling payouts that were in flight when the process last died.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from guarantor.config import Settings
from guarantor.escrow.engine import EscrowEngine
from guarantor.storage.base import Storage
from guarantor.ton.client import TonGateway, TonUnavailable
from guarantor.ton.deposits import parse_transaction

log = logging.getLogger(__name__)

CURSOR_NAME = "escrow_lt"
PAGE_SIZE = 100
#: Cap on pages fetched in one poll, so catching up after a long outage does
#: not turn into an unbounded burst of API calls.
MAX_PAGES = 20


class ChainWatcher:
    """Owns the poll and sweep loops for one escrow wallet."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        gateway: TonGateway,
        engine: EscrowEngine,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._gateway = gateway
        self._engine = engine
        self._tasks: list[asyncio.Task[None]] = []

    async def prime(self) -> None:
        """On a fresh database, start from now rather than replaying history."""
        if await self._storage.get_cursor(CURSOR_NAME) > 0:
            return
        try:
            recent = await self._gateway.get_transactions(self._engine.escrow_address, limit=1)
        except TonUnavailable as exc:
            log.warning("could not prime the watcher cursor: %s", exc)
            return
        if recent:
            await self._storage.set_cursor(CURSOR_NAME, recent[0].lt)
            log.info("watcher primed at lt=%s", recent[0].lt)

    async def start(self) -> None:
        await self.prime()
        await self.recover()
        settings = self._settings
        self._tasks = [
            asyncio.create_task(
                self._loop(self.poll_once, settings.poll_interval_seconds), name="poll"
            ),
            asyncio.create_task(
                self._loop(self.sweep_once, settings.sweep_interval_seconds), name="sweep"
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def recover(self) -> None:
        """Settle the fate of payouts that were in flight at shutdown."""
        for deal in await self._engine.pending_settlements():
            try:
                await self._engine.reconcile(deal)
            except Exception:
                log.exception("could not reconcile deal %s on startup", deal.code)

    async def poll_once(self) -> int:
        """Credit every new incoming transfer. Returns how many were credited."""
        cursor = await self._storage.get_cursor(CURSOR_NAME)
        transactions = await self._fetch_since(cursor)
        if not transactions:
            return 0

        credited = 0
        highest = cursor
        # Oldest first, so a deal funded by two transfers sees them in order.
        for tx in sorted(transactions, key=lambda t: t.lt):
            highest = max(highest, tx.lt)
            transfer = parse_transaction(tx, self._engine.escrow_address)
            if transfer is None:
                continue
            try:
                if await self._engine.credit_transfer(transfer) is not None:
                    credited += 1
            except Exception:
                log.exception("failed to credit transfer %s", transfer.tx_hash[:16])
                await self._alert(f"could not credit transfer {transfer.tx_hash}")

        if highest > cursor:
            await self._storage.set_cursor(CURSOR_NAME, highest)
        return credited

    async def sweep_once(self) -> None:
        """Time-driven maintenance: expiries, refunds and reconciliation."""
        await self._engine.expire_due()
        for deal in await self._engine.pending_settlements():
            try:
                await self._engine.reconcile(deal)
            except Exception:
                log.exception("could not reconcile deal %s", deal.code)

    async def _fetch_since(self, cursor: int) -> list:
        """Page backwards from the tip until we reach the cursor."""
        collected: list = []
        from_lt: int | None = None
        for _ in range(MAX_PAGES):
            batch = await self._gateway.get_transactions(
                self._engine.escrow_address,
                limit=PAGE_SIZE,
                from_lt=from_lt,
                to_lt=cursor or None,
            )
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            oldest = min(tx.lt for tx in batch)
            if cursor and oldest <= cursor:
                break
            from_lt = oldest - 1
        return collected

    async def _loop(self, step, interval: float) -> None:
        while True:
            try:
                await step()
            except asyncio.CancelledError:
                raise
            except TonUnavailable as exc:
                log.warning("%s: %s", step.__name__, exc)
            except Exception:
                log.exception("unhandled error in %s", step.__name__)
            await asyncio.sleep(interval)

    async def _alert(self, message: str) -> None:
        with contextlib.suppress(Exception):
            await self._engine.alert(message)
