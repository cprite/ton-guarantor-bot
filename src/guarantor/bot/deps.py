"""What every handler needs, assembled once at start-up."""

from __future__ import annotations

from dataclasses import dataclass

from guarantor.config import Settings
from guarantor.escrow.engine import EscrowEngine
from guarantor.storage.base import Storage


@dataclass(slots=True)
class Deps:
    settings: Settings
    storage: Storage
    engine: EscrowEngine
    escrow_address: str
    bot_username: str

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.settings.admin_id_set
