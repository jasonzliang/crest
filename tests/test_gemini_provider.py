"""Offline contract tests for Gemini's Interactions transport."""

import asyncio
import copy
import importlib
import json
import time

import httpx
import pytest


class FakeJob:
    def __init__(self, directory, **state):
        self.key = "gemini-test"
        self.directory = directory
        self.state = state
        self.checkpoints = []

    def save(self, **changes):
        self.state.update(changes)
        self.checkpoints.append(copy.deepcopy(self.state))


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "offline-test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def completed(text="Full research answer", **overrides):
    value = {
        "id": "research-1", "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
        "usage": {
            "total_input_tokens": 1000, "total_cached_tokens": 100,
            "total_output_tokens": 200, "total_thought_tokens": 50,
            "total_tool_use_tokens": 0, "total_tokens": 1250,
            "grounding_tool_count": [{"type": "google_search", "count": 2}],
        },
    }
    value.update(overrides)
    return value


def run(handler, job, *, method="generate", settings=None):
    async def exercise():
        module = importlib.import_module("crest.providers.gemini")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await getattr(module, method)(
                "exact prompt", {"poll_interval_seconds": 0, "timeout_seconds": 10, **(settings or {})},
                job, client=client,
            )
    return asyncio.run(exercise())


def test_research_request_uses_standard_agent_and_checkpoints_before_poll(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        assert request.headers["x-goog-api-key"] == "offline-test-key"
        if request.method == "POST":
            assert request.url.path == "/v1beta/interactions"
            assert json.loads(request.content) == {
                "input": "exact prompt", "agent": "deep-research-preview-04-2026",
                "background": True, "store": True,
                "agent_config": {"type": "deep-research", "thinking_summaries": "none",
                                 "visualization": "off", "collaborative_planning": False},
            }
            assert job.state["submission_unknown"] is True
            return httpx.Response(200, json={"id": "research-1", "status": "in_progress"})
        assert job.state["remote_id"] == "research-1"
        assert job.state["submission_unknown"] is False
        assert request.url.path == "/v1beta/interactions/research-1"
        return httpx.Response(200, json=completed())

    result = run(handler, job)
    assert calls == ["POST", "GET"]
    assert result["text"] == "Full research answer"
    assert result["model"] == "gemini-3.1-pro-preview"
    assert job.state["raw"] == result["raw"] == completed()
    assert any("target" in warning.lower() for warning in result["warnings"])


def test_resume_retrieves_durable_remote_id_without_resubmitting(tmp_path):
    job = FakeJob(tmp_path, remote_id="research-1", submitted_at=time.time())
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json=completed())
    assert run(handler, job)["text"] == "Full research answer"


def test_expired_resume_recovers_completed_paid_answer_before_enforcing_timeout(tmp_path):
    job = FakeJob(tmp_path, remote_id="research-1", submitted_at=time.time() - 100)
    calls = []
    raw = completed()
    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=raw)
    result = run(handler, job, settings={"timeout_seconds": 1})
    assert calls == [("GET", "/v1beta/interactions/research-1")]
    assert result["text"] == "Full research answer"
    assert job.state["raw"] == raw
    assert job.state["remote_status"] == "completed"


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled", "requires_action", "unknown", None])
def test_only_exact_completed_is_successful(tmp_path, status):
    job = FakeJob(tmp_path)
    raw = completed(status=status)
    with pytest.raises(RuntimeError, match="status"):
        run(lambda request: httpx.Response(200, json=raw), job, settings={"timeout_seconds": .02})
    assert job.state["raw"] == raw


def test_submission_disconnect_is_durable_and_never_reposts(tmp_path):
    job = FakeJob(tmp_path)
    calls = []
    def handler(request):
        calls.append(request.method)
        raise httpx.ReadError("connection lost after upload", request=request)
    with pytest.raises(httpx.ReadError):
        run(handler, job)
    assert job.state["submission_unknown"] is True
    with pytest.raises(RuntimeError, match="submission.*unknown|unknown.*submission"):
        run(handler, job)
    assert calls == ["POST"]


@pytest.mark.parametrize("response", [httpx.Response(503, text="unavailable"),
                                      httpx.Response(200, json={"status": "in_progress"}),
                                      httpx.Response(200, text="not JSON")])
def test_ambiguous_submission_response_prevents_duplicate_paid_call(tmp_path, response):
    job = FakeJob(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        return response
    with pytest.raises((RuntimeError, ValueError, httpx.HTTPStatusError)):
        run(handler, job)
    assert job.state["submission_unknown"] is True
    with pytest.raises(RuntimeError, match="unknown"):
        run(handler, job)
    assert len(calls) == 1


def test_poll_failure_keeps_remote_id_for_resume(tmp_path):
    job = FakeJob(tmp_path)
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "research-1", "status": "in_progress"})
        raise httpx.ReadError("poll disconnected", request=request)
    with pytest.raises(httpx.ReadError):
        run(handler, job)
    assert job.state["remote_id"] == "research-1"
    assert run(lambda r: httpx.Response(200, json=completed()), job)["text"]


@pytest.mark.parametrize("active_status", ["in_progress", "queued"])
def test_timeout_uses_durable_elapsed_time_and_cancels(tmp_path, active_status):
    job = FakeJob(tmp_path, remote_id="research-1", submitted_at=time.time() - 100)
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"id": "research-1", "status": active_status})
        return httpx.Response(200, json={"id": "research-1", "status": "cancelled"})
    with pytest.raises(TimeoutError):
        run(handler, job, settings={"timeout_seconds": 1})
    assert calls == [("GET", "/v1beta/interactions/research-1"),
                     ("POST", "/v1beta/interactions/research-1/cancel")]
    assert job.state["remote_status"] == "cancelled"


def test_answer_excludes_echoed_user_text_and_reasoning_extracts_citations(tmp_path):
    raw = completed(steps=[
        {"type": "user_input", "content": [{"type": "text", "text": "injected echo"}]},
        {"type": "thought", "content": [{"type": "text", "text": "private thought"}]},
        {"type": "model_output", "content": [
            {"type": "thought", "text": "more thought"},
            {"type": "text", "text": "Entire final report", "annotations": [
                {"type": "url_citation", "url": "https://example.org/paper", "title": "Paper"},
                {"type": "url_citation", "url": "https://example.org/paper", "title": "Paper"},
            ]},
        ]},
    ])
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path))
    assert result["text"] == "Entire final report"
    assert result["citations"] == [{"url": "https://example.org/paper", "title": "Paper"}]


def test_legacy_outputs_text_remains_supported(tmp_path):
    raw = completed(outputs=[{"type": "text", "text": "Legacy final answer"}])
    raw.pop("steps")
    assert run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path))["text"] == "Legacy final answer"


def test_empty_or_thought_only_output_fails(tmp_path):
    with pytest.raises(RuntimeError, match="empty|text"):
        run(lambda r: httpx.Response(200, json=completed(steps=[
            {"type": "thought", "content": [{"type": "text", "text": "only thinking"}]}
        ])), FakeJob(tmp_path))


def test_usage_keeps_separate_reasoning_and_unknown_costs_honest(tmp_path):
    result = run(lambda r: httpx.Response(200, json=completed()), FakeJob(tmp_path))
    assert result["usage"]["input_tokens"] == 1000
    assert result["usage"]["cached_input_tokens"] == 100
    assert result["usage"]["output_tokens"] == 200
    assert result["usage"]["reasoning_tokens"] == 50
    assert result["usage"]["tool_use_tokens"] == 0
    assert result["usage"]["search_queries"] == 2
    # Agent loop contexts are unknown: use the higher published tier and
    # undiscounted searches for a conservative estimate.
    assert result["cost_usd"] == pytest.approx((900 * 4 + 100 * .4 + 250 * 18) / 1_000_000 + 2 * .014)
    assert result["cost_estimated"] is True
    assert any("upper" in warning for warning in result["warnings"])
    unknown = run(lambda r: httpx.Response(200, json=completed(usage={})), FakeJob(tmp_path))
    assert unknown["cost_usd"] is None
    assert unknown["usage"]["input_tokens"] is None


def test_research_missing_search_usage_leaves_cost_unknown(tmp_path):
    raw = completed()
    raw["usage"].pop("grounding_tool_count")
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path))
    assert result["cost_usd"] is None
    assert result["cost_estimated"] is False


def test_research_completed_budget_overrun_is_preserved(tmp_path):
    raw = completed()
    raw["usage"]["total_input_tokens"] = 2_000_000
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path))
    assert result["cost_usd"] > 5
    assert any("exceed" in warning.lower() for warning in result["warnings"])


def test_running_research_over_budget_attempts_cancellation_and_keeps_usage(tmp_path):
    raw = completed(status="in_progress")
    raw["usage"]["total_input_tokens"] = 2_000_000
    job = FakeJob(tmp_path)
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"id": "research-1", "status": "cancelled"})
        return httpx.Response(200, json=raw)
    with pytest.raises(RuntimeError, match="budget"):
        run(handler, job, settings={"timeout_seconds": .02})
    assert calls == ["/v1beta/interactions", "/v1beta/interactions/research-1/cancel"]
    assert job.state["observed_cost_usd"] > 5
    assert job.state["observed_usage"]["input_tokens"] == 2_000_000
    assert job.state["budget_exceeded"] is True
    assert job.state["raw"] == raw


def test_judge_request_is_structured_json_without_tools(tmp_path):
    from crest.judging import SCHEMA
    verdict = {c: {"reason": "A develops a stronger idea than B", "winner": "A"}
               for c in ("new", "useful", "surprising")}
    def handler(request):
        body = json.loads(request.content)
        assert body == {
            "input": "exact prompt", "model": "gemini-3.1-pro-preview",
            "background": True, "store": True,
            "generation_config": {"thinking_level": "high", "max_output_tokens": 12000},
            "response_format": {"type": "text", "mime_type": "application/json", "schema": SCHEMA},
        }
        raw = completed(json.dumps(verdict), model="gemini-3.1-pro-preview")
        raw["usage"]["grounding_tool_count"] = []
        return httpx.Response(200, json=raw)
    result = run(handler, FakeJob(tmp_path), method="judge")
    assert json.loads(result["text"]) == verdict
    # Interactions reports output and thought separately; each is billed once.
    assert result["cost_usd"] == pytest.approx((900 * 2 + 100 * .2 + 250 * 12) / 1_000_000)
    assert result["cost_estimated"] is True


@pytest.mark.parametrize("body", [{"error": {"message": "invalid request"}}, "invalid request"])
def test_definite_bad_request_can_be_retried_without_unknown_submission(tmp_path, body):
    job = FakeJob(tmp_path)
    def handler(request):
        if isinstance(body, str):
            return httpx.Response(400, text=body)
        return httpx.Response(400, json=body)
    with pytest.raises(httpx.HTTPStatusError):
        run(handler, job)
    assert job.state["submission_unknown"] is False


def test_timeout_cancellation_failure_preserves_last_response(tmp_path):
    job = FakeJob(tmp_path)
    running = {"id": "research-1", "status": "in_progress"}
    def handler(request):
        if request.url.path.endswith("/cancel"):
            raise httpx.ReadError("cancellation lost", request=request)
        return httpx.Response(200, json=running)
    with pytest.raises(TimeoutError):
        run(handler, job, settings={"timeout_seconds": .01, "poll_interval_seconds": 1})
    assert job.state["raw"] == running
    assert job.state["remote_id"] == "research-1"
    assert job.state["cancellation_error"]["type"] == "ReadError"


def test_judge_unexpected_tool_usage_is_not_silently_underpriced(tmp_path):
    result = run(lambda r: httpx.Response(200, json=completed()), FakeJob(tmp_path), method="judge")
    assert result["cost_usd"] is None
    assert result["usage"]["search_queries"] == 2


def test_judge_long_context_rate_counts_reasoning_once(tmp_path):
    raw = completed(model="gemini-3.1-pro-preview")
    raw["usage"].update(total_input_tokens=200001, total_cached_tokens=1, grounding_tool_count=[])
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path), method="judge")
    assert result["cost_usd"] == pytest.approx((200000 * 4 + .4 + 250 * 18) / 1_000_000)


def test_completed_response_with_missing_thought_usage_has_unknown_judge_cost(tmp_path):
    raw = completed()
    raw["usage"].pop("total_thought_tokens")
    raw["usage"]["grounding_tool_count"] = []
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path), method="judge")
    assert result["cost_usd"] is None
    assert result["cost_estimated"] is False


@pytest.mark.parametrize("resume", [False, True])
def test_argon_queued_submission_resume_and_poll_complete_without_resubmission(tmp_path, resume):
    from crest.judging import SCHEMA
    verdict = {criterion: {"reason": "A develops the clearer idea", "winner": "A"}
               for criterion in ("new", "useful", "surprising")}
    job = FakeJob(tmp_path, **({"remote_id": "research-1", "submitted_at": time.time()} if resume else {}))
    calls = []
    statuses = iter(["queued", "queued", "in_progress", "completed"])

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == "gemini-4-argon"
            assert body["generation_config"] == {"thinking_level": "high", "max_output_tokens": 32768}
            assert body["response_format"]["schema"] == SCHEMA
            assert "tools" not in body
        status = next(statuses)
        raw = completed(json.dumps(verdict), status=status, model="gemini-4-argon", created="2026-10-26T12:00:00Z")
        raw["usage"]["grounding_tool_count"] = []
        return httpx.Response(200, json=raw)

    result = run(handler, job, method="judge", settings={"model": "gemini-4-argon", "max_output_tokens": 32768})
    assert calls == (["GET"] * 4 if resume else ["POST", "GET", "GET", "GET"])
    assert json.loads(result["text"]) == verdict
    assert job.state["remote_status"] == "completed"


@pytest.mark.parametrize("created,input_rate,cached_rate,output_rate,pricing_date", [
    ("2026-11-30T23:59:59Z", 2, .1, 10, "2026-11-30"),
    ("2026-12-01T00:00:00Z", 4, .2, 20, "2026-12-01"),
    ("2026-12-01T00:30:00+01:00", 2, .1, 10, "2026-11-30"),
])
@pytest.mark.parametrize("inputs", [1000, 200001])
def test_argon_dated_single_context_price_bills_reasoning_once(
    tmp_path, created, input_rate, cached_rate, output_rate, pricing_date, inputs,
):
    raw = completed(model="gemini-4-argon", created=created)
    raw["usage"].update(total_input_tokens=inputs, grounding_tool_count=[])
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path), method="judge",
                 settings={"model": "gemini-4-argon"})
    assert result["cost_usd"] == pytest.approx(
        ((inputs - 100) * input_rate + 100 * cached_rate + (200 + 50) * output_rate) / 1_000_000
    )
    assert result["cost_estimated"] is True
    assert result["pricing_date"] == pricing_date
    assert result["pricing_date_source"] == "response.created"
    assert result["usage"]["output_tokens"] == 200
    assert result["usage"]["reasoning_tokens"] == 50


@pytest.mark.parametrize("created", [None, "invalid timestamp"])
def test_argon_missing_creation_date_records_explicit_utc_pricing_fallback(tmp_path, monkeypatch, created):
    module = importlib.import_module("crest.providers.gemini")
    monkeypatch.setattr(module.time, "time", lambda: 1796083200.0)  # 2026-12-01 UTC
    raw = completed(model="gemini-4-argon", created=created)
    raw["usage"]["grounding_tool_count"] = []
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path), method="judge",
                 settings={"model": "gemini-4-argon"})
    assert result["pricing_date"] == "2026-12-01"
    assert result["pricing_date_source"] == "processing_date_utc"
    assert result["cost_usd"] == pytest.approx((900 * 4 + 100 * .2 + 250 * 20) / 1_000_000)
    assert any("creation" in warning.lower() for warning in result["warnings"])


def test_unknown_judge_model_remains_unpriced(tmp_path):
    raw = completed(model="gemini-unknown", created="2026-11-30T00:00:00Z")
    raw["usage"]["grounding_tool_count"] = []
    result = run(lambda r: httpx.Response(200, json=raw), FakeJob(tmp_path), method="judge",
                 settings={"model": "gemini-unknown"})
    assert result["cost_usd"] is None
    assert result["cost_estimated"] is False


def test_gemini_key_fallback_and_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "fallback-key")
    def handler(request):
        assert request.headers["x-goog-api-key"] == "fallback-key"
        return httpx.Response(200, json=completed())
    assert run(handler, FakeJob(tmp_path))["text"]
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ValueError, match="GOOGLE_API_KEY|GEMINI_API_KEY"):
        run(handler, FakeJob(tmp_path))


@pytest.fixture(autouse=True)
def no_http_retry_wait(monkeypatch):
    from crest.providers import http
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(http, "sleep", sleep)
    return delays


def test_retry_create_rate_limit_keeps_submission_intent_until_acceptance(tmp_path, no_http_retry_wait):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        assert job.state["submission_unknown"] is True
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"}, json={"error": "rate limited"})
        assert job.state["retry_events"][0]["status_code"] == 429
        return httpx.Response(200, json=completed())

    assert run(handler, job)["text"] == "Full research answer"
    assert calls == ["POST", "POST"]
    assert job.state["submission_unknown"] is False
    assert len(no_http_retry_wait) == 1


def test_retry_final_rate_limit_is_a_known_rejected_submission(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429, json={"error": "rate limited"})

    with pytest.raises(httpx.HTTPStatusError):
        run(handler, job)
    assert calls == ["POST"] * 4
    assert job.state["submission_unknown"] is False


def test_retry_expired_resume_can_recover_get_service_unavailable(tmp_path):
    job = FakeJob(tmp_path, remote_id="research-1", submitted_at=time.time() - 10000)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503, json={"error": "temporary"}) if len(calls) == 1 else httpx.Response(200, json=completed())

    assert run(handler, job, settings={"timeout_seconds": 1})["text"] == "Full research answer"
    assert calls == ["GET", "GET"]
    assert "cancellation" not in job.state


def test_retry_does_not_replay_create_after_rate_limit_followed_by_ambiguous_failure(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429 if len(calls) == 1 else 503, json={"error": "temporary"})

    with pytest.raises(httpx.HTTPStatusError):
        run(handler, job)
    assert calls == ["POST", "POST"]
    assert job.state["submission_unknown"] is True
    with pytest.raises(RuntimeError, match="unknown"):
        run(handler, job)
    assert calls == ["POST", "POST"]


def test_retry_create_rate_limit_longer_than_deadline_remains_known_rejection(tmp_path, no_http_retry_wait):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429, headers={"Retry-After": "5"}, json={"error": "limited"})

    with pytest.raises(httpx.HTTPStatusError):
        run(handler, job, settings={"timeout_seconds": .01})
    assert calls == ["POST"]
    assert job.state["submission_unknown"] is False
    assert no_http_retry_wait == []


def test_retry_cancellation_recovers_without_losing_original_remote_state(tmp_path):
    running = {"id": "research-1", "status": "in_progress"}
    job = FakeJob(tmp_path, remote_id="research-1", submitted_at=time.time() - 100)
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json=running)
        if calls.count("POST") == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"id": "research-1", "status": "cancelled"})

    with pytest.raises(TimeoutError):
        run(handler, job, settings={"timeout_seconds": 1})
    assert calls == ["GET", "POST", "POST"]
    assert job.state["raw"] == running
    assert job.state["remote_status"] == "cancelled"


def test_unsent_rate_gate_timeout_can_be_retried_as_a_fresh_create(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    class Gate:
        blocked = True

        async def wait_ready(self):
            if self.blocked:
                await asyncio.sleep(.04)

        async def observe_headers(self, headers):
            pass

        async def rate_limited(self, delay):
            pass

    job.rate_controller = Gate()

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=completed())

    with pytest.raises((httpx.TimeoutException, TimeoutError)):
        run(handler, job, settings={"timeout_seconds": .01})
    assert calls == []
    assert job.state["submission_unknown"] is False
    job.rate_controller.blocked = False
    assert run(handler, job, settings={"timeout_seconds": .01})["text"] == "Full research answer"
    assert calls == ["POST"]


@pytest.mark.parametrize("after_rejection", [False, True])
def test_cancellation_while_waiting_to_create_keeps_submission_retryable(tmp_path, after_rejection):
    module = importlib.import_module("crest.providers.gemini")
    job = FakeJob(tmp_path)
    calls = []

    async def exercise():
        waiting = asyncio.Event()

        class Gate:
            count = 0

            async def wait_ready(self):
                self.count += 1
                if not after_rejection or self.count == 2:
                    waiting.set()
                    await asyncio.Future()

            async def observe_headers(self, headers):
                pass

            async def rate_limited(self, delay):
                pass

        job.rate_controller = Gate()

        def handler(request):
            calls.append(request.method)
            if after_rejection and len(calls) == 1:
                return httpx.Response(429, json={"error": "limited"})
            return httpx.Response(200, json=completed())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(module.generate("prompt", {}, job, client=client))
            await asyncio.wait_for(waiting.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == (["POST"] if after_rejection else [])
            assert job.state["submission_unknown"] is False
            job.rate_controller = None
            assert (await module.generate("prompt", {}, job, client=client))["text"] == "Full research answer"

    asyncio.run(exercise())
    assert calls == ["POST"] * (2 if after_rejection else 1)


def test_cancellation_after_create_dispatch_stays_ambiguous_and_never_reposts(tmp_path):
    module = importlib.import_module("crest.providers.gemini")
    job = FakeJob(tmp_path)
    calls = []

    async def exercise():
        dispatched = asyncio.Event()

        async def handler(request):
            calls.append(request.method)
            dispatched.set()
            await asyncio.Future()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(module.generate("prompt", {}, job, client=client))
            await asyncio.wait_for(dispatched.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert job.state["submission_unknown"] is True
            with pytest.raises(RuntimeError, match="unknown"):
                await module.generate("prompt", {}, job, client=client)

    asyncio.run(exercise())
    assert calls == ["POST"]


def test_outer_timeout_cancelling_create_gate_keeps_unsent_submission_retryable(tmp_path, monkeypatch):
    module = importlib.import_module("crest.providers.gemini")
    from crest.providers.http import request as real_request
    job = FakeJob(tmp_path)
    calls = []

    class Gate:
        async def wait_ready(self):
            await asyncio.Future()

        async def observe_headers(self, headers):
            pass

        async def rate_limited(self, delay):
            pass

    async def request_without_inner_deadline(*args, **kwargs):
        # Let the adapter's outer asyncio.timeout be the sole cancellation
        # source while retaining the actual HTTP helper's dispatch tracking.
        kwargs["deadline"] = None
        return await real_request(*args, **kwargs)

    monkeypatch.setattr(module, "request", request_without_inner_deadline)
    job.rate_controller = Gate()

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=completed())

    with pytest.raises(TimeoutError):
        run(handler, job, settings={"timeout_seconds": .01})
    assert calls == []
    assert job.state["submission_unknown"] is False
    job.rate_controller = None
    assert run(handler, job, settings={"timeout_seconds": .01})["text"] == "Full research answer"
    assert calls == ["POST"]
