"""Persistence. Deals outlive the process, so nothing lives only in memory."""

from guarantor.storage.base import Storage
from guarantor.storage.sqlite import SqliteStorage

__all__ = ["SqliteStorage", "Storage"]
