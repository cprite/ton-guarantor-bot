"""Fixtures: a real engine over a real database, with the chain faked out.

Only the two boundaries that touch the network are replaced. Everything else —
the state machine, the fee maths, the storage — is the production code, so the
tests fail when the real behaviour changes.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import pytest

from guarantor.config import Settings
from guarantor.errors import InsufficientEscrowBalance
from guarantor.escrow.engine import EscrowEngine
from guarantor.escrow.events import Event
from guarantor.models import Asset, AssetKind
from guarantor.storage import SqliteStorage
from guarantor.ton.client import JettonInfo
from guarantor.ton.deposits import IncomingTransfer, TransferKind
from guarantor.ton.escrow import SentMessage

ESCROW = "0:" + "e" * 64
ALICE_WALLET = "0:" + "a" * 64
BOB_WALLET = "0:" + "b" * 64
NFT_ITEM = "0:" + "1" * 64
JETTON_MASTER = "0:" + "2" * 64
JETTON_WALLET = "0:" + "3" * 64


class FakeGateway:
    """Answers the three chain questions the engine asks while building a deal."""

    def __init__(self) -> None:
        self.nft_owners: dict[str, str] = {NFT_ITEM: ALICE_WALLET}

    async def jetton_info(self, master: str) -> JettonInfo:
        return JettonInfo(master=master, symbol="TEST", decimals=6)

    async def jetton_wallet_of(self, master: str, owner: str) -> str:
        return JETTON_WALLET

    async def nft_owner(self, nft_address: str) -> str | None:
        return self.nft_owners.get(nft_address)


class FakeWallet:
    """Records what would have been broadcast instead of broadcasting it."""

    def __init__(self) -> None:
        self.address = ESCROW
        self.max_messages = 4
        self.seqno_value = 5
        self.sent: list[list[tuple[str, Asset, str, str | None]]] = []
        self.applied: bool | None = True
        self.balance_value = 100 * 10**9
        self.funded_enough = True

    def build_payout(self, asset: Asset, destination: str, comment: str | None = None):
        return ("payout", asset, destination, comment)

    def gas_cost(self, assets: list[Asset]) -> int:
        return sum(50_000_000 for a in assets if a.kind in (AssetKind.NFT, AssetKind.JETTON))

    async def ensure_balance(self, required: int) -> None:
        if not self.funded_enough:
            raise InsufficientEscrowBalance("escrow is out of gas")

    async def balance(self) -> int:
        return self.balance_value

    async def send(self, messages: list[Any]) -> SentMessage:
        self.sent.append(messages)
        record = SentMessage(
            seqno=self.seqno_value,
            msg_hash=f"hash{self.seqno_value}",
            valid_until=int(time.time()) + 120,
            sent_at=int(time.time()),
        )
        self.seqno_value += 1
        return record

    async def was_applied(self, record: SentMessage) -> bool | None:
        return self.applied


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[tuple[Event, str | None]] = []

    async def notify(self, event: Event, deal: Any, **context: Any) -> None:
        self.events.append((event, deal.code if deal is not None else None))

    def kinds(self) -> list[Event]:
        return [event for event, _ in self.events]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="1:test",
        admin_ids="42",
        escrow_mnemonic=" ".join(["word"] * 24),
        ton_network="testnet",
        fee_percent=Decimal("1.0"),
        fee_min_ton=Decimal("0.05"),
        deposit_timeout_seconds=3600,
        open_deal_ttl_seconds=86400,
        database_path=":memory:",
    )


@pytest.fixture
async def storage() -> SqliteStorage:
    store = SqliteStorage(":memory:")
    await store.start()
    yield store
    await store.close()


@pytest.fixture
def wallet() -> FakeWallet:
    return FakeWallet()


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
async def engine(settings, storage, gateway, wallet, notifier) -> EscrowEngine:
    return EscrowEngine(settings, storage, gateway, wallet, notifier)


def ton_transfer(comment: str, amount: int, sender: str = ALICE_WALLET, lt: int = 1) -> IncomingTransfer:
    return IncomingTransfer(
        tx_hash=f"tx{lt}",
        lt=lt,
        at=int(time.time()),
        kind=TransferKind.TON,
        source=sender,
        depositor=sender,
        value_nano=amount,
        amount=amount,
        comment=comment,
    )


def nft_transfer(item: str, previous_owner: str, lt: int = 2) -> IncomingTransfer:
    return IncomingTransfer(
        tx_hash=f"tx{lt}",
        lt=lt,
        at=int(time.time()),
        kind=TransferKind.NFT,
        source=item,
        depositor=previous_owner,
        value_nano=50_000_000,
        amount=1,
        comment=None,
    )


def jetton_transfer(
    wallet_address: str, sender: str, amount: int, comment: str | None, lt: int = 3
) -> IncomingTransfer:
    return IncomingTransfer(
        tx_hash=f"tx{lt}",
        lt=lt,
        at=int(time.time()),
        kind=TransferKind.JETTON,
        source=wallet_address,
        depositor=sender,
        value_nano=50_000_000,
        amount=amount,
        comment=comment,
    )
