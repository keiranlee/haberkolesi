"""Application-wide request spacing for Gemini API calls."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional


class AsyncRequestGate:
    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        *,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if min_interval <= 0:
            raise ValueError("min_interval must be greater than zero")
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self.wall_clock = wall_clock
        self._lock = asyncio.Lock()
        self._last_started: Optional[float] = None
        self._last_started_at: Optional[datetime] = None

    async def acquire(self) -> float:
        async with self._lock:
            if self._last_started is not None:
                elapsed = self.clock() - self._last_started
                delay = self.min_interval - elapsed
                if delay > 0:
                    await self.sleep(delay)
            started_at = self.clock()
            self._last_started = started_at
            self._last_started_at = self.wall_clock()
            return started_at

    def status(self):
        next_allowed_at = None
        if self._last_started_at is not None:
            next_allowed_at = self._last_started_at + timedelta(
                seconds=self.min_interval
            )
        return {
            "last_started_at": self._last_started_at,
            "next_allowed_at": next_allowed_at,
        }
