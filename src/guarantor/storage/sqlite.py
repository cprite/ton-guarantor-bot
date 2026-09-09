"""SQLite implementation of :class:`~guarantor.storage.base.Storage`.

A deal is stored as its JSON document plus the handful of columns the bot
actually queries on. That keeps the schema stable as the model grows, while
still letting the watcher find "which deal is waiting for this NFT?" with an
index rather than a table scan.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiosqlite

from guarantor.models import AssetKind, Deal, DealStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    code            TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    user_a          INTEGER,
    user_b          INTEGER,
    nft_a           TEXT,
    nft_b           TEXT,
    jetton_wallet_a TEXT,
    jetton_wallet_b TEXT,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_status     ON deals (status, expires_at);
CREATE INDEX IF NOT EXISTS idx_deals_user_a     ON deals (user_a);
CREATE INDEX IF NOT EXISTS idx_deals_user_b     ON deals (user_b);
CREATE INDEX IF NOT EXISTS idx_deals_nft_a      ON deals (nft_a);
CREATE INDEX IF NOT EXISTS idx_deals_nft_b      ON deals (nft_b);
CREATE INDEX IF NOT EXISTS idx_deals_jwallet_a  ON deals (jetton_wallet_a);
CREATE INDEX IF NOT EXISTS idx_deals_jwallet_b  ON deals (jetton_wallet_b);

CREATE TABLE IF NOT EXISTS seen_transfers (
    key        TEXT PRIMARY KEY,
    seen_at    INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS user_locales (
    user_id INTEGER PRIMARY KEY,
    locale  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cursors (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

_ACTIVE_STATUSES = tuple(s.value for s in DealStatus if not s.is_terminal)


class SqliteStorage:
    """Single-file storage. WAL mode keeps the watcher and the bot out of each
    other's way while still giving one consistent view of a deal."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("storage is not started")
        return self._db

    async def put_deal(self, deal: Deal) -> None:
        row = (
            deal.code,
            deal.status.value,
            deal.created_at,
            deal.updated_at,
            deal.expires_at,
            deal.a.user_id,
            deal.b.user_id,
            _nft(deal, "a"),
            _nft(deal, "b"),
            _jetton_wallet(deal, "a"),
            _jetton_wallet(deal, "b"),
            json.dumps(deal.to_dict(), separators=(",", ":")),
        )
        async with self._write_lock:
            await self._conn.execute(
                """
                INSERT INTO deals (code, status, created_at, updated_at, expires_at,
                                   user_a, user_b, nft_a, nft_b,
                                   jetton_wallet_a, jetton_wallet_b, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at,
                    user_a=excluded.user_a,
                    user_b=excluded.user_b,
                    nft_a=excluded.nft_a,
                    nft_b=excluded.nft_b,
                    jetton_wallet_a=excluded.jetton_wallet_a,
                    jetton_wallet_b=excluded.jetton_wallet_b,
                    payload=excluded.payload
                """,
                row,
            )
            await self._conn.commit()

    async def get_deal(self, code: str) -> Deal | None:
        async with self._conn.execute("SELECT payload FROM deals WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
        return _load(row)

    async def list_deals_for_user(self, user_id: int, *, limit: int = 20) -> list[Deal]:
        async with self._conn.execute(
            """
            SELECT payload FROM deals
            WHERE user_a = ? OR user_b = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [deal for row in rows if (deal := _load(row)) is not None]

    async def count_active_for_user(self, user_id: int) -> int:
        placeholders = ",".join("?" * len(_ACTIVE_STATUSES))
        async with self._conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM deals
            WHERE (user_a = ? OR user_b = ?) AND status IN ({placeholders})
            """,
            (user_id, user_id, *_ACTIVE_STATUSES),
        ) as cur:
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def list_by_status(self, statuses: list[DealStatus], *, limit: int = 100) -> list[Deal]:
        if not statuses:
            return []
        placeholders = ",".join("?" * len(statuses))
        async with self._conn.execute(
            f"SELECT payload FROM deals WHERE status IN ({placeholders}) ORDER BY updated_at ASC LIMIT ?",
            (*[s.value for s in statuses], limit),
        ) as cur:
            rows = await cur.fetchall()
        return [deal for row in rows if (deal := _load(row)) is not None]

    async def find_by_nft(self, nft_address: str) -> Deal | None:
        async with self._conn.execute(
            """
            SELECT payload FROM deals
            WHERE (nft_a = ? OR nft_b = ?) AND status = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (nft_address, nft_address, DealStatus.AWAITING_DEPOSITS.value),
        ) as cur:
            row = await cur.fetchone()
        return _load(row)

    async def find_by_jetton_wallet(self, wallet_address: str) -> list[Deal]:
        async with self._conn.execute(
            """
            SELECT payload FROM deals
            WHERE (jetton_wallet_a = ? OR jetton_wallet_b = ?) AND status = ?
            ORDER BY created_at ASC
            """,
            (wallet_address, wallet_address, DealStatus.AWAITING_DEPOSITS.value),
        ) as cur:
            rows = await cur.fetchall()
        return [deal for row in rows if (deal := _load(row)) is not None]

    async def mark_transfer_seen(self, key: str) -> bool:
        async with self._write_lock:
            cursor = await self._conn.execute(
                "INSERT OR IGNORE INTO seen_transfers (key) VALUES (?)", (key,)
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def get_locale(self, user_id: int) -> str | None:
        async with self._conn.execute(
            "SELECT locale FROM user_locales WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return str(row["locale"]) if row else None

    async def set_locale(self, user_id: int, locale: str) -> None:
        async with self._write_lock:
            await self._conn.execute(
                """
                INSERT INTO user_locales (user_id, locale) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET locale=excluded.locale
                """,
                (user_id, locale),
            )
            await self._conn.commit()

    async def get_cursor(self, name: str) -> int:
        async with self._conn.execute("SELECT value FROM cursors WHERE name = ?", (name,)) as cur:
            row = await cur.fetchone()
        return int(row["value"]) if row else 0

    async def set_cursor(self, name: str, value: int) -> None:
        async with self._write_lock:
            await self._conn.execute(
                """
                INSERT INTO cursors (name, value) VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET value=excluded.value
                """,
                (name, value),
            )
            await self._conn.commit()

    async def stats(self) -> dict[str, int]:
        async with self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM deals GROUP BY status"
        ) as cur:
            rows = await cur.fetchall()
        return {row["status"]: int(row["n"]) for row in rows}


def _load(row: aiosqlite.Row | None) -> Deal | None:
    if row is None:
        return None
    return Deal.from_dict(json.loads(row["payload"]))


def _nft(deal: Deal, role: str) -> str | None:
    asset = (deal.a if role == "a" else deal.b).asset
    return asset.nft_address if asset.kind is AssetKind.NFT else None


def _jetton_wallet(deal: Deal, role: str) -> str | None:
    asset = (deal.a if role == "a" else deal.b).asset
    return asset.jetton_wallet if asset.kind is AssetKind.JETTON else None
