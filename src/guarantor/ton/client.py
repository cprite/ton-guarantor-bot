"""The single seam between the bot and whichever TON API it is pointed at.

``tonutils`` already abstracts toncenter, tonapi and liteservers behind one
protocol for reads, get-methods and message broadcast. What it does not cover
is jetton metadata, which every indexer exposes through its own REST shape, so
that one lookup is done here directly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from pytoniq_core.tlb.transaction import Transaction
from ton_core import NetworkGlobalID
from tonutils.clients import TonapiClient, ToncenterClient
from tonutils.clients.protocol import ClientProtocol
from tonutils.contracts import JettonMasterStandard, NFTItemStandard

from guarantor.config import Settings
from guarantor.errors import GuarantorError
from guarantor.ton import addresses as addr

log = logging.getLogger(__name__)

_METADATA_BASE = {
    ("toncenter", False): "https://toncenter.com/api/v3",
    ("toncenter", True): "https://testnet.toncenter.com/api/v3",
    ("tonapi", False): "https://tonapi.io/v2",
    ("tonapi", True): "https://testnet.tonapi.io/v2",
}


class TonUnavailable(GuarantorError):
    """The configured TON API could not be reached or answered with an error."""


@dataclass(frozen=True, slots=True)
class JettonInfo:
    """The minimum a deal needs to quote a jetton amount correctly."""

    master: str
    symbol: str
    decimals: int


def build_client(settings: Settings) -> ClientProtocol:
    """Instantiate the tonutils client described by the configuration."""
    network = NetworkGlobalID.TESTNET if settings.is_testnet else NetworkGlobalID.MAINNET
    kwargs = {
        "api_key": settings.ton_api_key,
        "base_url": settings.ton_api_base_url,
        "timeout": settings.ton_request_timeout,
    }
    if settings.ton_provider == "tonapi":
        return TonapiClient(network, **kwargs)  # type: ignore[arg-type]
    return ToncenterClient(network, **kwargs)  # type: ignore[arg-type]


class TonGateway:
    """Read-side access to the chain, plus the metadata lookups deals need."""

    def __init__(self, settings: Settings, client: ClientProtocol) -> None:
        self._settings = settings
        self._client = client
        self._session: aiohttp.ClientSession | None = None
        self._jetton_cache: dict[str, JettonInfo] = {}
        self._lock = asyncio.Lock()

    @property
    def client(self) -> ClientProtocol:
        return self._client

    @property
    def testnet(self) -> bool:
        return self._settings.is_testnet

    async def start(self) -> None:
        await self._client.connect()
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self._settings.ton_request_timeout)
        )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        await self._client.close()

    async def get_transactions(
        self,
        address: str,
        *,
        limit: int = 100,
        from_lt: int | None = None,
        to_lt: int | None = None,
    ) -> list[Transaction]:
        """Newest-first transactions of an account, from ``from_lt`` down to ``to_lt``."""
        try:
            # ``ton_core`` re-exports pytoniq's Transaction under its own
            # name; same class at runtime, different stub.
            transactions: list[Any] = await self._client.get_transactions(
                address, limit=limit, from_lt=from_lt, to_lt=to_lt
            )
            return transactions
        except Exception as exc:
            raise TonUnavailable(f"could not read transactions of {addr.shorten(address)}: {exc}") from exc

    async def nft_owner(self, nft_address: str) -> str | None:
        """Current owner of an NFT item, or ``None`` if it cannot be read."""
        try:
            item: Any = await NFTItemStandard.from_address(self._client, nft_address)
        except Exception as exc:
            log.warning("cannot read NFT %s: %s", addr.shorten(nft_address), exc)
            return None
        owner = item.owner_address
        return addr.canonical(owner) if owner is not None else None

    async def jetton_wallet_of(self, master: str, owner: str) -> str:
        """Address of ``owner``'s wallet for the given jetton master."""
        try:
            master_contract: Any = await JettonMasterStandard.from_address(self._client, master)
            wallet = await master_contract.get_wallet_address(owner)
        except Exception as exc:
            raise TonUnavailable(
                f"could not resolve the jetton wallet for {addr.shorten(master)}: {exc}"
            ) from exc
        return addr.canonical(wallet)

    async def jetton_info(self, master: str) -> JettonInfo:
        """Symbol and decimals of a jetton, cached for the process lifetime.

        Decimals are mandatory: quoting an amount with the wrong scale would
        move a thousand times too much or too little.
        """
        key = addr.canonical(master)
        async with self._lock:
            cached = self._jetton_cache.get(key)
            if cached is not None:
                return cached

        info = await self._fetch_jetton_info(key)
        async with self._lock:
            self._jetton_cache[key] = info
        return info

    async def _fetch_jetton_info(self, master: str) -> JettonInfo:
        if self._session is None:
            raise TonUnavailable("TON gateway is not started")

        base = _METADATA_BASE[(self._settings.ton_provider, self.testnet)]
        if self._settings.ton_provider == "tonapi":
            url = f"{base}/jettons/{addr.friendly(master, testnet=self.testnet)}"
            headers = (
                {"Authorization": f"Bearer {self._settings.ton_api_key}"}
                if self._settings.ton_api_key
                else {}
            )
            payload = await self._get_json(url, headers)
            metadata = payload.get("metadata") or {}
            decimals = metadata.get("decimals")
            symbol = metadata.get("symbol")
        else:
            url = f"{base}/jetton/masters"
            headers = {"X-API-Key": self._settings.ton_api_key} if self._settings.ton_api_key else {}
            payload = await self._get_json(
                url, headers, params={"address": addr.friendly(master, testnet=self.testnet), "limit": "1"}
            )
            masters = payload.get("jetton_masters") or []
            if not masters:
                raise TonUnavailable(f"{addr.shorten(master)} is not a known jetton master")
            content = masters[0].get("jetton_content") or {}
            decimals = content.get("decimals")
            symbol = content.get("symbol")

        if decimals is None:
            raise TonUnavailable(
                f"{addr.shorten(master)} does not publish its decimals; "
                "this jetton cannot be traded safely"
            )
        return JettonInfo(
            master=master,
            symbol=str(symbol) if symbol else addr.shorten(master, keep=4),
            decimals=int(decimals),
        )

    async def _get_json(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert self._session is not None
        try:
            async with self._session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    raise TonUnavailable(f"{url} answered {response.status}")
                return await response.json()
        except aiohttp.ClientError as exc:
            raise TonUnavailable(f"{url} is unreachable: {exc}") from exc
