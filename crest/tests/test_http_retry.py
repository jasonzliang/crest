"""Offline tests for retry safety at the actual HTTP boundary."""
import asyncio
import importlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import httpx
import pytest


@dataclass
class Job:
    state: dict = field(default_factory=dict)

    def save(self, **changes):
        self.state.update(changes)


def exercise(handler, *, method="GET", url="https://provider.example/jobs/one",
             settings=None, job=None, deadline=None, **kwargs):
    async def run():
        module = importlib.import_module("crest.providers.http")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.request(client, method, url, job=job or Job(),
                                        settings=settings or {}, deadline=deadline, **kwargs)
    return asyncio.run(run())


@pytest.fixture
def clock(monkeypatch):
    module = importlib.import_module("crest.providers.http")
    current = [1_700_000_000.0]
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        current[0] += delay

    monkeypatch.setattr(module, "sleep", sleep)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: current[0]))
    monkeypatch.setattr(module.random, "uniform", lambda low, high: high)
    return current, sleeps


def test_create_retries_explicit_rate_rejection_without_recording_secrets(clock):
    current, sleeps = clock
    job = Job({"submission_unknown": True})
    calls = []

    def handler(request):
        calls.append(request)
        assert job.state["submission_unknown"] is True
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "42"}, json={"error": "secret-body"})
        return httpx.Response(200, json={"id": "paid-one"})

    result = exercise(handler, method="POST", url="https://provider.example/jobs?key=secret-query",
                      job=job, headers={"Authorization": "Bearer secret-header"}, json={"input": "secret-prompt"})
    assert result.json() == {"id": "paid-one"}
    assert len(calls) == 2
    assert sleeps == [42]
    events = job.state["retry_events"]
    assert events[0]["status_code"] == 429
    assert events[0]["delay_seconds"] == 42
    assert "secret" not in json.dumps(events)


@pytest.mark.parametrize("headers, expected", [
    ({"x-ratelimit-reset-requests": "1m2s", "x-ratelimit-reset-tokens": "1250ms"}, 62),
    ({"x-ratelimit-reset": "1700000070"}, 70),
    ({"ratelimit-reset": "45"}, 45),
    ({"retry-after": "Tue, 14 Nov 2023 22:14:00 GMT"}, 40),
])
def test_provider_reset_headers_set_minimum_retry_wait(clock, headers, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers=headers) if len(calls) == 1 else httpx.Response(200)

    assert exercise(handler).status_code == 200
    assert clock[1] == [expected]


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
@pytest.mark.parametrize("method, path", [("GET", "/jobs/one"), ("POST", "/jobs/one/cancel")])
def test_idempotent_requests_recover_from_transient_http_failure(clock, status, method, path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status if len(calls) == 1 else 200)

    assert exercise(handler, method=method, url="https://provider.example" + path).status_code == 200
    assert len(calls) == 2
    assert clock[1] == [1]


@pytest.mark.parametrize("status", [400, 401, 403, 408, 500, 502, 503, 504])
def test_create_never_retries_auth_bad_request_or_ambiguous_failure(clock, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    assert exercise(handler, method="POST", url="https://provider.example/jobs").status_code == status
    assert len(calls) == 1
    assert clock[1] == []


def test_create_transport_failure_is_never_retried(clock):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("ambiguous paid request", request=request)

    with pytest.raises(httpx.ReadTimeout):
        exercise(handler, method="POST", url="https://provider.example/jobs")
    assert len(calls) == 1
    assert clock[1] == []


def test_get_transport_failure_retries_until_default_four_total_attempts(clock):
    calls = []
    job = Job()

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("secret transport details", request=request)

    with pytest.raises(httpx.ConnectError):
        exercise(handler, job=job)
    assert len(calls) == 4
    assert clock[1] == [1, 2, 4]
    assert "secret" not in json.dumps(job.state["retry_events"])


def test_retry_limit_and_backoff_cap_apply_to_all_attempts(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    assert exercise(handler, settings={"retry_attempts": 7, "retry_backoff_base_seconds": 10}).status_code == 503
    assert len(calls) == 7
    assert clock[1] == [10, 20, 30, 30, 30, 30]


def test_retry_wait_does_not_exceed_remaining_deadline(clock):
    calls = []
    job = Job()

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"})

    assert exercise(handler, method="POST", job=job, deadline=clock[0][0] + 5).status_code == 429
    assert len(calls) == 1
    assert clock[1] == []
    assert job.state["retry_events"][-1]["retrying"] is False


def test_shared_rate_controller_handles_429_wait_without_local_double_sleep(clock):
    calls = []
    actions = []

    class Controller:
        async def wait_ready(self):
            actions.append("ready")

        async def observe_headers(self, headers):
            actions.append(("headers", headers.get("retry-after")))

        async def rate_limited(self, delay):
            actions.append(("limited", delay))

    job = Job()
    job.rate_controller = Controller()

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3"}) if len(calls) == 1 else httpx.Response(200)

    assert exercise(handler, job=job).status_code == 200
    assert actions == ["ready", ("headers", "3"), ("limited", 3), "ready", ("headers", None)]
    assert clock[1] == []


def test_shared_rate_controller_receives_final_rate_limit_for_other_jobs(clock):
    actions = []

    class Controller:
        async def wait_ready(self):
            actions.append("ready")

        def observe_headers(self, headers):
            pass

        def rate_limited(self, delay):
            actions.append(delay)

    job = Job()
    job.rate_controller = Controller()
    assert exercise(lambda r: httpx.Response(429, headers={"Retry-After": "3"}), job=job,
                    settings={"retry_attempts": 1}).status_code == 429
    assert actions == ["ready", 3]


def test_shared_gate_deadline_after_rejected_create_does_not_send_another_post(clock):
    calls = []

    class Controller:
        ready_count = 0

        async def wait_ready(self):
            self.ready_count += 1
            if self.ready_count > 1:
                await asyncio.sleep(10)

        async def observe_headers(self, headers):
            pass

        async def rate_limited(self, delay):
            pass

    job = Job()
    job.rate_controller = Controller()

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429)

    assert exercise(handler, method="POST", job=job, deadline=clock[0][0] + .01,
                    settings={"retry_backoff_base_seconds": 0}).status_code == 429
    assert calls == ["POST"]


def test_server_error_still_uses_local_backoff_with_shared_controller(clock):
    calls = []

    class Controller:
        async def wait_ready(self):
            pass

        async def observe_headers(self, headers):
            pass

        async def rate_limited(self, delay):
            pytest.fail("503 is not a rate-limit rejection")

    job = Job()
    job.rate_controller = Controller()

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503 if len(calls) == 1 else 200)

    assert exercise(handler, job=job).status_code == 200
    assert clock[1] == [1]


def test_retry_events_accumulate_across_poll_calls(clock):
    job = Job({"retry_events": [{"method": "POST", "attempt": 1, "status_code": 429}]})
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503 if len(calls) == 1 else 200)

    assert exercise(handler, job=job).status_code == 200
    assert [event["status_code"] for event in job.state["retry_events"]] == [429, 503]


def test_checkpoint_time_cannot_make_retry_sleep_exceed_deadline(clock):
    calls = []

    class SlowCheckpointJob(Job):
        def save(self, **changes):
            super().save(**changes)
            clock[0][0] += 10

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429)

    assert exercise(handler, method="POST", job=SlowCheckpointJob(), deadline=clock[0][0] + 5).status_code == 429
    assert calls == ["POST"]
    assert clock[1] == []


def test_non_exhausted_token_reset_does_not_delay_a_request_rate_limit(clock):
    calls = []

    def handler(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(429, headers={"x-ratelimit-remaining-requests": "0",
                                                "x-ratelimit-reset-requests": "2s",
                                                "x-ratelimit-remaining-tokens": "10000",
                                                "x-ratelimit-reset-tokens": "1h"})
        return httpx.Response(200)

    assert exercise(handler).status_code == 200
    assert clock[1] == [2]


def test_shared_gate_that_returns_after_deadline_cannot_send_a_request(clock):
    calls = []

    class Controller:
        async def wait_ready(self):
            clock[0][0] += 10

        async def observe_headers(self, headers):
            pass

        async def rate_limited(self, delay):
            pass

    job = Job()
    job.rate_controller = Controller()

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200)

    with pytest.raises(httpx.TimeoutException):
        exercise(handler, job=job, deadline=clock[0][0] + 5)
    assert calls == []
