"""Adaptive job concurrency and shared, nonblocking provider cooldowns."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import re
import time


def _delay(value: str) -> float:
    """Accept seconds, compound reset durations, or an HTTP date."""
    value = str(value).strip()
    try:
        seconds = float(value)
    except ValueError:
        compact = re.sub(r'\s+', '', value.lower())
        parts = list(re.finditer(r'(\d+(?:\.\d+)?|\.\d+)(ms|s|m|h)', compact))
        if parts and ''.join(part[0] for part in parts) == compact:
            units = {'ms': .001, 's': 1, 'm': 60, 'h': 3600}
            seconds = sum(float(part[1]) * units[part[2]] for part in parts)
        else:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = date.timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


class AdaptiveLimiter:
    """Grow by one per two completed jobs; halve after rate limiting.

    State changes are synchronous on the owning event loop, including slot
    release, so task cancellation cannot interrupt cleanup. Header observations
    pause new work without counting as a rate-limit event or reducing capacity.
    """

    def __init__(self, maximum: int, initial: int = 1):
        if maximum < 1 or not 1 <= initial <= maximum:
            raise ValueError('Require 1 <= initial <= maximum')
        self._maximum = maximum
        self._current = initial
        self._active = 0
        self._successes = 0
        self._rate_limit_events = 0
        self._cooldown_until = 0.0
        self._changed = asyncio.Event()

    def _notify(self) -> None:
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def _cool_down(self, delay: float) -> None:
        if math.isfinite(delay) and delay > 0:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + delay)
            self._notify()

    async def _wait(self, delay: float | None = None) -> None:
        try:
            await asyncio.wait_for(self._changed.wait(), delay)
        except TimeoutError:
            pass

    async def wait_ready(self) -> None:
        """Wait for the shared cooldown, including extensions while waiting."""
        while (delay := self._cooldown_until - time.monotonic()) > 0:
            await self._wait(delay)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Reserve a job slot after both capacity and cooldown allow it."""
        while True:
            delay = self._cooldown_until - time.monotonic()
            if delay <= 0 and self._active < self._current:
                self._active += 1
                break
            await self._wait(delay if delay > 0 else None)
        try:
            yield
        finally:
            self._active -= 1
            self._notify()

    async def succeeded(self) -> None:
        """Record one completed, uncached job; cache hits must not call this."""
        self._successes += 1
        if self._successes >= 2:
            self._successes = 0
            self._current = min(self._maximum, self._current + 1)
            self._notify()

    async def rate_limited(self, delay: float) -> None:
        self._current = max(1, self._current // 2)
        self._successes = 0
        self._rate_limit_events += 1
        self._cool_down(delay)
        self._notify()

    async def observe_headers(self, headers: Mapping[str, str]) -> None:
        """Honor Retry-After and exhausted OpenAI request/token budgets."""
        headers = {str(key).lower(): value for key, value in headers.items()}
        delay = _delay(headers.get('retry-after', ''))
        for resource in ('requests', 'tokens'):
            remaining = headers.get(f'x-ratelimit-remaining-{resource}', '')
            try:
                exhausted = float(remaining) <= 0
            except (TypeError, ValueError):
                exhausted = False
            if exhausted:
                delay = max(delay, _delay(headers.get(f'x-ratelimit-reset-{resource}', '')))
        self._cool_down(delay)

    def snapshot(self) -> dict[str, int]:
        return {'current': self._current, 'maximum': self._maximum,
                'active': self._active, 'rate_limit_events': self._rate_limit_events}
