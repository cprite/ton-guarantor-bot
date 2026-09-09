"""Wiring: build every component, start the loops, shut them down cleanly."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from guarantor.bot.deps import Deps
from guarantor.bot.handlers import build_router
from guarantor.bot.middlewares import LocaleMiddleware, ThrottleMiddleware
from guarantor.bot.notify import TelegramNotifier
from guarantor.config import Settings
from guarantor.escrow.engine import EscrowEngine
from guarantor.escrow.watcher import ChainWatcher
from guarantor.money import format_ton
from guarantor.storage import SqliteStorage
from guarantor.ton.client import TonGateway, build_client
from guarantor.ton.escrow import EscrowWallet

log = logging.getLogger(__name__)


class Application:
    """Everything the bot is made of, with a start and a stop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = SqliteStorage(settings.database_path)
        self.client = build_client(settings)
        self.gateway = TonGateway(settings, self.client)
        self.bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dispatcher = Dispatcher(storage=MemoryStorage())
        self.engine: EscrowEngine | None = None
        self.watcher: ChainWatcher | None = None
        self.deps: Deps | None = None

    async def setup(self) -> Deps:
        self.settings.validate_runtime()
        await self.storage.start()
        await self.gateway.start()

        wallet = await EscrowWallet.open(self.settings, self.client)
        self.engine = EscrowEngine(self.settings, self.storage, self.gateway, wallet)

        me = await self.bot.get_me()
        self.deps = Deps(
            settings=self.settings,
            storage=self.storage,
            engine=self.engine,
            escrow_address=wallet.address,
            bot_username=me.username or "",
        )
        self.engine.set_notifier(TelegramNotifier(self.bot, self.deps))

        self.dispatcher.update.outer_middleware(LocaleMiddleware(self.deps))
        self.dispatcher.update.outer_middleware(
            ThrottleMiddleware(self.settings.rate_limit_per_second)
        )
        self.dispatcher.include_router(build_router())

        self.watcher = ChainWatcher(self.settings, self.storage, self.gateway, self.engine)
        await self._report_readiness(wallet)
        return self.deps

    async def run(self) -> None:
        deps = await self.setup()
        assert self.watcher is not None
        await self.watcher.start()
        try:
            await self.dispatcher.start_polling(
                self.bot,
                deps=deps,
                allowed_updates=["message", "callback_query"],
            )
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.watcher is not None:
            await self.watcher.stop()
        await self.gateway.close()
        await self.storage.close()
        await self.bot.session.close()

    async def _report_readiness(self, wallet: EscrowWallet) -> None:
        """Say out loud what the operator is about to run, and warn if it is
        under-funded — an escrow with no gas cannot forward an NFT."""
        log.info("network: %s", self.settings.ton_network)
        log.info("escrow wallet: %s", wallet.friendly_address())
        try:
            balance = await wallet.balance()
        except Exception as exc:
            log.warning("could not read the escrow balance: %s", exc)
            return
        log.info("escrow balance: %s", format_ton(balance))
        if balance < self.settings.escrow_min_reserve_nano:
            log.warning(
                "escrow balance is below the %s reserve; payouts of NFTs and "
                "jettons will be refused until it is topped up",
                format_ton(self.settings.escrow_min_reserve_nano),
            )
