"""Safe HTTP retries shared by durable paid-provider adapters.

Create POSTs are only repeatable after an explicit 429 rejection. A transport
failure or server error may follow acceptance, so those creates are never replayed.
"""
from __future__ import annotations

import asyncio
from asyncio import sleep
from email.utils import parsedate_to_datetime
import inspect
import math
import random
import re
import time

import httpx


class RequestNotSent(httpx.TimeoutException):
    """The request deadline elapsed before an HTTP dispatch."""


TRANSIENT = {408, 429, 500, 502, 503, 504}
_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")
_UNITS = {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}


def _seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _duration(value):
    seconds = _seconds(value)
    if seconds is not None:
        return seconds
    text = value.strip().lower()
    parts = list(_DURATION.finditer(text))
    if not parts or "".join(part.group() for part in parts) != text:
        return None
    return sum(float(part[1]) * _UNITS[part[2]] for part in parts)


def _header_delay(headers):
    """Return a server-specified minimum wait, without persisting raw headers."""
    waits = [0.0]
    retry_after = headers.get("retry-after")
    if retry_after:
        seconds = _seconds(retry_after)
        if seconds is None:
            try:
                seconds = max(0, parsedate_to_datetime(retry_after).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                pass
        if seconds is not None and math.isfinite(seconds):
            waits.append(seconds)
    for name in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "ratelimit-reset",
                 "x-ratelimit-reset", "x-rate-limit-reset"):
        value = headers.get(name)
        if value is None:
            continue
        remaining_name = name.replace("reset", "remaining")
        remaining = _seconds(headers.get(remaining_name))
        if remaining is not None and remaining > 0:
            continue
        seconds = _duration(value)
        if seconds is None or not math.isfinite(seconds):
            continue
        # OpenAI uses durations, while common x-ratelimit-reset headers use
        # Unix timestamps. Standard RateLimit-Reset is a relative duration.
        if name in {"x-ratelimit-reset", "x-rate-limit-reset"} and seconds > 1_000_000_000:
            seconds = max(0, seconds - time.time())
        waits.append(seconds)
    return max(waits)


async def _controller_call(controller, name, *args):
    result = getattr(controller, name)(*args)
    if inspect.isawaitable(result):
        await result


def _record(job, *, method, attempt, delay, retrying, response=None, error=None):
    event = {"method": method, "attempt": attempt, "delay_seconds": delay, "retrying": retrying}
    if response is not None:
        event["status_code"] = response.status_code
    if error is not None:
        event["error_type"] = type(error).__name__
    job.save(retry_events=[*job.state.get("retry_events", []), event])
    return event


async def request(client, method, url, *, job, settings, deadline=None, **kwargs) -> httpx.Response:
    """Request with bounded safe retries; ``deadline`` is an optional Unix time.

    The adapter checkpoints submission intent and interprets the final response.
    This helper clears that intent on exit only when no create can be in flight.
    Only status codes and exception types enter retry_events: URLs, request and
    response bodies, headers, and exception messages can contain credentials.
    """
    method = method.upper()
    idempotent = method == "GET" or (method == "POST" and httpx.URL(url).path.rstrip("/").endswith("/cancel"))
    attempts = max(1, int(settings.get("retry_attempts", 4)))
    base = max(0.0, float(settings.get("retry_backoff_base_seconds", 1)))
    cap = max(0.0, float(settings.get("retry_backoff_max_seconds", 30)))
    controller = getattr(job, "rate_controller", None)
    previous_response = None
    previous_error = None
    create = method == "POST" and not idempotent
    possibly_sent = False

    try:
        for attempt in range(1, attempts + 1):
            remaining = None if deadline is None else deadline - time.time()
            try:
                if remaining is not None and remaining <= 0:
                    raise TimeoutError
                if controller is not None:
                    async with asyncio.timeout(remaining):
                        await _controller_call(controller, "wait_ready")
                if deadline is not None and time.time() >= deadline:
                    raise TimeoutError
            except TimeoutError:
                if previous_response is not None:
                    return previous_response
                if previous_error is not None:
                    raise previous_error
                raise RequestNotSent("Provider rate gate exceeded request deadline before dispatch") from None

            request_kwargs = dict(kwargs)
            if deadline is not None:
                remaining = max(.001, deadline - time.time())
                timeout = request_kwargs.get("timeout", 60)
                if isinstance(timeout, (int, float)):
                    request_kwargs["timeout"] = min(timeout, remaining)
            response, error = None, None
            try:
                # Once control enters the HTTP client, a cancelled or failed create
                # can have reached the provider even without a received response.
                possibly_sent = True
                response = await client.request(method, url, **request_kwargs)
                if create and response.status_code == 429:
                    possibly_sent = False
            except httpx.TransportError as exc:
                if not idempotent:
                    raise
                error = exc
            if response is not None:
                if controller is not None:
                    await _controller_call(controller, "observe_headers", response.headers)
                if response.status_code not in (TRANSIENT if idempotent else {429}):
                    return response

            ceiling = min(cap, base * 2 ** min(attempt - 1, 30))
            delay = random.uniform(ceiling / 2, ceiling)
            if response is not None:
                delay = max(delay, _header_delay(response.headers))
            rate_limited = response is not None and response.status_code == 429
            if rate_limited and controller is not None:
                await _controller_call(controller, "rate_limited", delay)
            retrying = attempt < attempts and (deadline is None or time.time() + delay < deadline)
            event = _record(job, method=method, attempt=attempt, delay=delay, retrying=retrying,
                            response=response, error=error)
            # The durable checkpoint itself can consume the remaining time. Do not
            # begin a wait that can no longer fit after that disk write.
            if retrying and deadline is not None and time.time() + delay >= deadline:
                retrying = event["retrying"] = False
                job.save(retry_events=job.state["retry_events"])
            if not retrying:
                if error is not None:
                    raise error
                return response
            previous_response, previous_error = response, error
            if not (rate_limited and controller is not None):
                await sleep(delay)
        raise AssertionError("retry loop did not return or raise")
    finally:
        # This also runs when an outer asyncio.timeout cancels a rate-gate or
        # backoff wait. A create is retryable only if no POST may be in flight;
        # an explicit 429 establishes that safety again for the next attempt.
        if create and not possibly_sent and job.state.get("submission_unknown"):
            job.save(submission_unknown=False)
