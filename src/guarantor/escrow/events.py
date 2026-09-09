"""Events the engine emits so the bot can tell people what happened.

The engine never imports aiogram: it announces facts, and whoever is listening
decides how to render them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from guarantor.models import Deal


class Event(StrEnum):
    DEAL_JOINED = "deal_joined"
    DEAL_ACCEPTED = "deal_accepted"
    DEPOSIT_CREDITED = "deposit_credited"
    SIDE_FUNDED = "side_funded"
    DEAL_FUNDED = "deal_funded"
    SETTLING = "settling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    DISPUTED = "disputed"
    FAILED = "failed"
    UNMATCHED_TRANSFER = "unmatched_transfer"
    OPERATOR_ALERT = "operator_alert"


class Notifier(Protocol):
    """Receives engine events. Implementations must never raise."""

    async def notify(self, event: Event, deal: Deal | None, **context: Any) -> None: ...


class NullNotifier:
    """Drops every event. Useful in tests and in one-off scripts."""

    async def notify(self, event: Event, deal: Deal | None, **context: Any) -> None:
        return None
