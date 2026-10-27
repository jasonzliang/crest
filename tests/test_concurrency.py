import asyncio
from email.utils import formatdate

import pytest

from crest.concurrency import AdaptiveLimiter


def test_active_jobs_are_bounded_and_release_after_errors():
    async def run():
        limiter = AdaptiveLimiter(3, initial=3)
        high_water = 0

        async def job(number):
            nonlocal high_water
            async with limiter.slot():
                high_water = max(high_water, limiter.snapshot()['active'])
                await asyncio.sleep(.005)
                if number == 2:
                    raise RuntimeError('failed job')

        results = await asyncio.gather(*(job(n) for n in range(15)), return_exceptions=True)
        assert high_water == 3
        assert sum(isinstance(result, RuntimeError) for result in results) == 1
        assert limiter.snapshot() == {
            'current': 3, 'maximum': 3, 'active': 0, 'rate_limit_events': 0,
        }

    asyncio.run(run())


def test_two_successes_increase_capacity_until_ceiling():
    async def run():
        limiter = AdaptiveLimiter(4)
        observed = []
        for _ in range(9):
            await limiter.succeeded()
            observed.append(limiter.snapshot()['current'])
        assert observed == [1, 2, 2, 3, 3, 4, 4, 4, 4]

    asyncio.run(run())


def test_rate_limit_halves_capacity_and_resets_success_streak():
    async def run():
        limiter = AdaptiveLimiter(7, initial=7)
        await limiter.succeeded()
        await limiter.rate_limited(0)
        assert limiter.snapshot()['current'] == 3
        await limiter.succeeded()
        assert limiter.snapshot()['current'] == 3
        await limiter.succeeded()
        assert limiter.snapshot()['current'] == 4
        for _ in range(4):
            await limiter.rate_limited(0)
        assert limiter.snapshot()['current'] == 1
        assert limiter.snapshot()['rate_limit_events'] == 5

    asyncio.run(run())


def test_cooldown_blocks_slots_and_readiness_without_blocking_event_loop():
    async def run():
        limiter = AdaptiveLimiter(4, initial=4)
        await limiter.rate_limited(.04)
        start = asyncio.get_running_loop().time()
        entered = []

        async def job():
            async with limiter.slot():
                entered.append(asyncio.get_running_loop().time() - start)

        jobs = [asyncio.create_task(job()) for _ in range(3)]
        ready = asyncio.create_task(limiter.wait_ready())
        await asyncio.sleep(.005)
        assert not entered
        assert not ready.done()
        await asyncio.wait_for(asyncio.gather(*jobs, ready), 1)
        assert min(entered) >= .03

    asyncio.run(run())


def test_new_cooldown_extends_waiters_and_shorter_one_cannot_clear_it():
    async def run():
        limiter = AdaptiveLimiter(1)
        await limiter.rate_limited(.025)
        start = asyncio.get_running_loop().time()
        ready = asyncio.create_task(limiter.wait_ready())
        await asyncio.sleep(.01)
        await limiter.rate_limited(.05)
        await limiter.rate_limited(0)
        await asyncio.wait_for(ready, 1)
        assert asyncio.get_running_loop().time() - start >= .05

    asyncio.run(run())


def test_cancelling_active_and_waiting_jobs_does_not_leak_slots():
    async def run():
        limiter = AdaptiveLimiter(1)
        entered = asyncio.Event()

        async def holder():
            async with limiter.slot():
                entered.set()
                await asyncio.Event().wait()

        active = asyncio.create_task(holder())
        await entered.wait()
        waiting = asyncio.create_task(holder())
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert limiter.snapshot()['active'] == 1
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        assert limiter.snapshot()['active'] == 0
        async with asyncio.timeout(1):
            async with limiter.slot():
                assert limiter.snapshot()['active'] == 1

    asyncio.run(run())


@pytest.mark.parametrize('headers', [
    {'Retry-After': '.03'},
    {'X-RateLimit-Remaining-Requests': '0', 'X-RateLimit-Reset-Requests': '30ms'},
    {'x-ratelimit-remaining-tokens': '0', 'x-ratelimit-reset-tokens': '.03s'},
    {'x-ratelimit-remaining-requests': '0', 'x-ratelimit-reset-requests': '.0005m'},
    {'x-ratelimit-remaining-tokens': '0', 'x-ratelimit-reset-tokens': '.000008333333333h'},
    {'x-ratelimit-remaining-requests': '0', 'x-ratelimit-reset-requests': '0m.03s'},
])
def test_headers_proactively_delay_requests(headers):
    async def run():
        limiter = AdaptiveLimiter(3, initial=3)
        await limiter.observe_headers(headers)
        start = asyncio.get_running_loop().time()
        await asyncio.wait_for(limiter.wait_ready(), 1)
        assert asyncio.get_running_loop().time() - start >= .02
        assert limiter.snapshot()['current'] == 3
        assert limiter.snapshot()['rate_limit_events'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('header', ['Retry-After', 'x-ratelimit-reset-requests'])
def test_http_date_headers_use_wall_time_to_set_monotonic_cooldown(monkeypatch, header):
    monkeypatch.setattr('crest.concurrency.time.time', lambda: 1234567890.97)

    async def run():
        limiter = AdaptiveLimiter(1)
        headers = {header: formatdate(1234567891, usegmt=True),
                   'x-ratelimit-remaining-requests': '0'}
        await limiter.observe_headers(headers)
        start = asyncio.get_running_loop().time()
        await asyncio.wait_for(limiter.wait_ready(), 1)
        assert asyncio.get_running_loop().time() - start >= .02

    asyncio.run(run())


def test_nonexhausted_and_malformed_headers_do_not_pause():
    async def run():
        limiter = AdaptiveLimiter(1)
        for headers in [
            {'x-ratelimit-remaining-requests': '1', 'x-ratelimit-reset-requests': '1h'},
            {'x-ratelimit-remaining-tokens': 'invalid', 'x-ratelimit-reset-tokens': '1h'},
            {'x-ratelimit-remaining-requests': '0', 'x-ratelimit-reset-requests': 'invalid'},
            {'retry-after': 'nan'}, {'retry-after': 'inf'}, {'retry-after': '-5'},
        ]:
            await limiter.observe_headers(headers)
            await asyncio.wait_for(limiter.wait_ready(), .1)

    asyncio.run(run())


@pytest.mark.parametrize('maximum,initial', [(0, 1), (-1, 1), (2, 0), (2, 3)])
def test_invalid_capacity_is_rejected(maximum, initial):
    with pytest.raises(ValueError):
        AdaptiveLimiter(maximum, initial)
