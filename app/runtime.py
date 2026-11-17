"""Runtime control signals used by owner-only operational commands."""
from __future__ import annotations

import asyncio


class RuntimeControl:
    def __init__(self) -> None:
        self.restart_event = asyncio.Event()

    def request_restart(self) -> None:
        self.restart_event.set()
