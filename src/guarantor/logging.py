"""Logging setup, deliberately boring."""

from __future__ import annotations

import logging
import sys


def configure(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # aiogram narrates every update at INFO; that buries our own events.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
