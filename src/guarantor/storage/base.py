"""The storage contract the engine depends on.

Kept to a protocol so a deployment can swap SQLite for Postgres without the
engine noticing, and so tests can run against an in-memory database.
"""

from __future__ import annotations

from typing import Protocol

from guarantor.models import Deal, DealStatus


class Storage(Protocol):
    """Durable home for deals and for the watcher's place in the chain."""

    async def start(self) -> None:
        """Open the database and apply the schema."""

    async def close(self) -> None: ...

    async def put_deal(self, deal: Deal) -> None:
        """Insert or replace a deal, refreshing its derived indexes."""

    async def get_deal(self, code: str) -> Deal | None: ...

    async def list_deals_for_user(self, user_id: int, *, limit: int = 20) -> list[Deal]:
        """Deals the user takes part in, newest first."""

    async def count_active_for_user(self, user_id: int) -> int:
        """How many non-terminal deals the user is currently in."""

    async def list_by_status(self, statuses: list[DealStatus], *, limit: int = 100) -> list[Deal]:
        """Deals in any of the given states, oldest first."""

    async def find_by_nft(self, nft_address: str) -> Deal | None:
        """The deal currently expecting this NFT item, if any."""

    async def find_by_jetton_wallet(self, wallet_address: str) -> list[Deal]:
        """Deals expecting jettons through this escrow jetton wallet."""

    async def mark_transfer_seen(self, key: str) -> bool:
        """Record a transfer key. Returns ``False`` if it was already seen."""

    async def get_locale(self, user_id: int) -> str | None:
        """The language this user picked, if they ever picked one."""

    async def set_locale(self, user_id: int, locale: str) -> None: ...

    async def get_cursor(self, name: str) -> int: ...

    async def set_cursor(self, name: str, value: int) -> None: ...

    async def stats(self) -> dict[str, int]:
        """Deal counts per status, for the operator dashboard."""
