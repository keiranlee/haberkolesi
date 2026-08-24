import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from rate_limiter import AsyncRequestGate


class FakeClock:
    def __init__(self):
        self.current = 0.0
        self.sleep_calls = []

    def now(self):
        return self.current

    async def sleep(self, seconds):
        self.sleep_calls.append(seconds)
        await asyncio.sleep(0)
        self.current += seconds


@pytest.mark.asyncio
async def test_gate_starts_requests_at_least_15_seconds_apart():
    clock = FakeClock()
    gate = AsyncRequestGate(15.0, clock.now, clock.sleep)

    starts = [await gate.acquire(), await gate.acquire(), await gate.acquire()]

    assert starts == [0.0, 15.0, 30.0]
    assert clock.sleep_calls == [15.0, 15.0]


@pytest.mark.asyncio
async def test_gate_serializes_simultaneous_callers():
    clock = FakeClock()
    gate = AsyncRequestGate(15.0, clock.now, clock.sleep)
    first = await gate.acquire()

    second, third = await asyncio.gather(gate.acquire(), gate.acquire())

    assert [first, second, third] == [0.0, 15.0, 30.0]


def test_gate_rejects_non_positive_interval():
    with pytest.raises(ValueError, match="greater than zero"):
        AsyncRequestGate(0)


@pytest.mark.asyncio
async def test_gate_exposes_real_next_allowed_request_time():
    clock = FakeClock()
    wall_now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    gate = AsyncRequestGate(
        15.0,
        clock.now,
        clock.sleep,
        wall_clock=lambda: wall_now,
    )

    await gate.acquire()

    assert gate.status() == {
        "last_started_at": wall_now,
        "next_allowed_at": wall_now + timedelta(seconds=15),
    }
