"""Cross-cutting concerns applied to every update."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from guarantor.bot.deps import Deps
from guarantor.bot.texts import supported, t


class LocaleMiddleware(BaseMiddleware):
    """Resolve the user's language once and hand it to the handler.

    A stored preference wins; otherwise we take Telegram's own
    ``language_code``, and fall back to the operator's default.
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        locale = self._deps.settings.default_locale
        if user is not None:
            stored = await self._deps.storage.get_locale(user.id)
            locale = stored or supported(user.language_code) or locale
        data["locale"] = supported(locale)
        data["deps"] = self._deps
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """A per-user token bucket.

    An escrow bot invites automated probing, and every handler touches either
    the database or a TON API. Refusing early is cheaper than rate-limiting
    downstream.
    """

    def __init__(self, rate_per_second: float, burst: int = 5) -> None:
        self._rate = rate_per_second
        self._burst = burst
        self._tokens: dict[int, tuple[float, float]] = defaultdict(lambda: (float(burst), time.monotonic()))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        tokens, last = self._tokens[user.id]
        now = time.monotonic()
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        if tokens < 1.0:
            self._tokens[user.id] = (tokens, now)
            await _refuse(event, data.get("locale"))
            return None

        self._tokens[user.id] = (tokens - 1.0, now)
        return await handler(event, data)


async def _refuse(event: TelegramObject, locale: str | None) -> None:
    message = t(locale, "err_rate")
    if isinstance(event, CallbackQuery):
        await event.answer(message, show_alert=False)
    elif isinstance(event, Message):
        await event.answer(message)
