"""Offline contract tests for the Responses REST adapter."""
import asyncio
import json
import time
from dataclasses import dataclass, field

import httpx
import pytest

from crest.providers import openai


@dataclass
class FakeJob:
    directory: object
    state: dict = field(default_factory=dict)
    key: str = "test-job"

    def save(self, **changes):
        self.state.update(changes)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "state.json").write_text(json.dumps(self.state))


def completed(**changes):
    result = {
        "id": "resp_123", "status": "completed", "model": "gpt-6.1-sol",
        "service_tier": "default", "error": None, "incomplete_details": None,
        "output": [{"type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": "A full answer.",
                                 "annotations": [{"type": "url_citation", "url": "https://example.org/source", "title": "Source"}]}]}],
        "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 100},
                  "output_tokens": 300, "output_tokens_details": {"reasoning_tokens": 100}, "total_tokens": 1300},
    }
    result.update(changes)
    return result


@pytest.fixture(autouse=True)
def no_http_retry_wait(monkeypatch):
    from crest.providers import http
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(http, "sleep", sleep)
    return delays


class Gate:
    """Rate-controller stub; subclasses decide how ``wait_ready`` blocks."""

    async def wait_ready(self):
        pass

    async def observe_headers(self, headers):
        pass

    async def rate_limited(self, delay):
        pass


def invoke(handler, job, settings=None, *, judge=False):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await (openai.judge if judge else openai.generate)(
                "Exact prompt", settings or {"poll_interval_seconds": 0}, job, client=client)
    return asyncio.run(run())


@pytest.mark.parametrize("remote_id", ["resp_123", None])
def test_resume_uses_saved_terminal_response_without_another_request(tmp_path, remote_id):
    raw = completed()
    job = FakeJob(tmp_path, {"remote_id": remote_id, "submission_unknown": remote_id is None,
                             "raw": raw, "submitted_at": 0})
    result = invoke(lambda request: pytest.fail("Saved completion must not make HTTP requests"), job)
    assert result["text"] == "A full answer."
    assert job.state["remote_id"] == "resp_123"
    assert job.state["submission_unknown"] is False


@pytest.mark.parametrize("requests, calls, cost", [
    (5, 5, .05467), (None, None, None), (-1, None, None), (True, None, None), ("5", None, None)])
def test_reported_web_search_usage_overrides_missing_actions_only_when_valid(requests, calls, cost):
    raw = completed(tool_usage={"web_search": {"num_requests": requests}})
    raw["output"].append({"type": "web_search_call", "status": "completed"})  # No action: unknown on its own.
    usage, priced = openai._account(raw)
    assert usage["web_search_calls"] == calls
    assert priced == (None if cost is None else pytest.approx(cost))


def test_resume_does_not_accept_saved_response_for_another_remote_id(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_current", "raw": completed()})
    raw = completed(id="resp_current", output=[{"type": "message", "status": "completed",
                                               "content": [{"type": "output_text", "text": "Current answer"}]}])
    assert invoke(lambda request: httpx.Response(200, json=raw), job)["text"] == "Current answer"


@pytest.mark.parametrize("response", [httpx.Response(404, json={"error": "expired"}),
                                      httpx.Response(200, json={"error": "invalid response"}),
                                      httpx.Response(200, json=completed(id="another-response"))])
def test_retrieval_error_preserves_last_response_evidence(tmp_path, response):
    raw = completed(status="in_progress")
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "raw": raw})
    with pytest.raises((httpx.HTTPError, openai.ProviderError)):
        invoke(lambda request: response, job)
    assert job.state["raw"] == raw
    assert "poll_raw" in job.state


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_terminal_failure_preserves_normalized_paid_receipt(tmp_path, status):
    job = FakeJob(tmp_path)
    raw = completed(status=status)
    with pytest.raises(openai.ProviderError, match="status"):
        invoke(lambda request: httpx.Response(200, json=raw), job)
    assert job.state["raw"] == raw
    receipt = job.state["provider_result"]
    assert receipt["cost_usd"] == pytest.approx(.00467)
    assert receipt["usage"]["cached_input_tokens"] == 200
    assert receipt["raw"] == raw
    with pytest.raises(openai.ProviderError):
        invoke(lambda request: pytest.fail("Saved terminal failure must not be refetched"), job)


def test_create_checkpoints_id_before_poll_and_preserves_full_result(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            payload = json.loads(request.content)
            assert job.state["submission_unknown"] is True
            assert payload["input"] == "Exact prompt"
            assert payload["model"] == "gpt-6.1-sol"
            assert payload["background"] is True and payload["store"] is True
            assert payload["service_tier"] == "default"
            assert payload["reasoning"] == {"effort": "high"}
            assert payload["max_output_tokens"] == 40000
            assert payload["max_tool_calls"] == 25
            assert payload["tools"] == [{"type": "web_search"}]
            return httpx.Response(200, json={"id": "resp_123", "status": "queued"})
        assert json.loads((tmp_path / "state.json").read_text())["remote_id"] == "resp_123"
        return httpx.Response(200, json=completed())

    result = invoke(handler, job)
    assert calls == [("POST", "/v1/responses"), ("GET", "/v1/responses/resp_123")]
    assert result["text"] == "A full answer."
    assert result["citations"] == [{"url": "https://example.org/source", "title": "Source"}]
    assert result["raw"] == completed()
    assert job.state["remote_status"] == "completed"
    assert job.state["submission_unknown"] is False


def _missing_id():
    raw = completed()
    del raw["id"]
    return raw


def _disconnect(request):
    raise httpx.ReadTimeout("connection lost after submission", request=request)


@pytest.mark.parametrize("respond, saved_raw", [
    (_disconnect, None),
    (lambda request: httpx.Response(500, json={"error": {"message": "server failure"}}), {"error": {"message": "server failure"}}),
    (lambda request: httpx.Response(200, json=_missing_id()), _missing_id()),
], ids=["transport", "server_error", "missing_id"])
def test_ambiguous_submission_is_preserved_and_never_reposted(tmp_path, respond, saved_raw):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return respond(request)

    with pytest.raises(openai.ProviderError, match="unknown"):
        invoke(handler, job)
    assert job.state["submission_unknown"] is True
    assert job.state.get("raw") == saved_raw
    with pytest.raises(openai.ProviderError, match="unknown"):
        invoke(handler, job)
    assert calls == ["POST"]


@pytest.mark.parametrize("changes, error", [
    # Terminal failures: test_terminal_failure_preserves_normalized_paid_receipt.
    ({"status": "success"}, "status|completed"), ({"status": None}, "status|completed"),
    ({"output": []}, "empty|text"), ({"error": {"code": "server_error"}}, "error"),
], ids=["inexact_status", "missing_status", "empty_output", "error_payload"])
def test_only_an_exact_errorless_nonempty_completion_can_succeed(tmp_path, changes, error):
    job = FakeJob(tmp_path)
    raw = completed(**changes)
    with pytest.raises(Exception, match=error):
        invoke(lambda request: httpx.Response(200, json=raw), job)
    assert job.state["raw"] == raw


def test_research_requires_search_requests_full_sources_and_bills_only_search_actions(tmp_path):
    source = {"type": "url", "url": "https://example.org/research-source"}
    raw = completed()
    raw["output"] += [
        {"type": "web_search_call", "action": {"type": "open_page"}},
        {"type": "web_search_call", "action": {"type": "find_in_page"}},
        {"type": "web_search_call", "action": {"type": "search", "sources": [source]}},
    ]

    def handler(request):
        payload = json.loads(request.content)
        assert payload["tool_choice"] == "required"
        assert payload["include"] == ["web_search_call.action.sources"]
        return httpx.Response(200, json=raw)

    result = invoke(handler, FakeJob(tmp_path))
    assert result["raw"]["output"][-1]["action"]["sources"] == [source]
    assert result["usage"]["input_tokens"] == 1000
    assert result["usage"]["cached_input_tokens"] == 200
    assert result["usage"]["cache_write_tokens"] == 100
    assert result["usage"]["output_tokens"] == 300  # Includes the 100 reasoning tokens already.
    assert result["usage"]["reasoning_tokens"] == 100
    assert result["usage"]["web_search_calls"] == 1
    assert result["cost_usd"] == pytest.approx(0.01467)
    assert result["cost_estimated"] is True


@pytest.mark.parametrize("changes, settings", [
    *[({"usage": usage}, None) for usage in (None, {}, {"input_tokens": 1000}, {"output_tokens": 10})],
    ({"model": "other-model"}, {"model": "other-model"}),  # An unknown model has no invented price.
], ids=["no_usage", "empty_usage", "input_only", "output_only", "unknown_model"])
def test_missing_essential_usage_or_unknown_model_keeps_cost_unknown(tmp_path, changes, settings):
    result = invoke(lambda request: httpx.Response(200, json=completed(**changes)), FakeJob(tmp_path), settings)
    assert result["cost_usd"] is None
    assert result["warnings"]


def test_completed_create_checkpoints_id_atomically_and_prices_long_context_for_full_request(tmp_path):
    class CrashOnIdSave(FakeJob):
        def save(self, **changes):
            if isinstance(changes.get("raw"), dict) and changes["raw"].get("id") and not changes.get("remote_id") and not self.state.get("remote_id"):
                raise AssertionError("raw response was saved before its recoverable id")
            super().save(**changes)

    raw = completed(usage={"input_tokens": 300000, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                           "output_tokens": 1000, "output_tokens_details": {"reasoning_tokens": 500}})
    result = invoke(lambda request: httpx.Response(200, json=raw), CrashOnIdSave(tmp_path))
    assert result["text"]
    assert result["cost_usd"] == pytest.approx(1.215)


def test_failed_cancellation_stays_explicit_and_resumable(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10,
                             "raw": {"id": "resp_123", "status": "in_progress"}})
    with pytest.raises(TimeoutError):
        invoke(lambda request: httpx.Response(200, json={"id": "resp_123", "status": "in_progress"})
               if request.method == "GET" else httpx.Response(503, json={"error": "unavailable"}),
               job, {"timeout_seconds": 0})
    assert job.state["cancel_status"] == "unknown"
    assert job.state["remote_id"] == "resp_123"
    assert job.state.get("remote_status") != "cancelled"
    assert job.state["cancel_raw"] == {"error": "unavailable"}


def test_observed_budget_overrun_cancels_active_response(tmp_path):
    raw = completed(status="in_progress", usage={"input_tokens": 1000000,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}, "output_tokens": 1000000})
    job = FakeJob(tmp_path)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"id": "resp_123", "status": "cancelled"})
        return httpx.Response(200, json=raw)

    with pytest.raises(Exception, match="budget"):
        invoke(handler, job)
    assert paths[-1] == "/v1/responses/resp_123/cancel"
    assert job.state["cancel_reason"] == "budget"


def test_judge_uses_strict_binary_schema_and_no_tools(tmp_path):
    from crest.judging import SCHEMA
    verdict = {"reason": "A is more creative.", "winner": "A"}

    def handler(request):
        payload = json.loads(request.content)
        assert payload["text"]["format"] == {"type": "json_schema", "name": "crest_verdict", "strict": True, "schema": SCHEMA}
        assert payload["reasoning"] == {"effort": "high"}
        assert payload["max_output_tokens"] == 12000
        assert not payload.get("tools")
        assert "tool_choice" not in payload and "include" not in payload
        raw = completed()
        raw["output"][0]["content"][0]["text"] = json.dumps(verdict)
        return httpx.Response(200, json=raw)

    result = invoke(handler, FakeJob(tmp_path), judge=True)
    assert json.loads(result["text"]) == verdict


def test_explicit_rejection_is_not_marked_as_accepted_submission(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(Exception, match="400"):
        invoke(lambda request: httpx.Response(400, json={"error": "bad parameter"}), job)
    assert job.state["submission_unknown"] is False
    assert "remote_id" not in job.state


def test_completed_over_budget_retains_answer_and_reports_overrun(tmp_path):
    result = invoke(lambda request: httpx.Response(200, json=completed()), FakeJob(tmp_path), {"budget_usd": 0.0001})
    assert result["text"] == "A full answer."
    assert any("exceeded" in warning for warning in result["warnings"])


def test_timeout_cancellation_records_status_keeps_partial_estimate_and_resume_reconciles_by_get(tmp_path):
    raw = completed(status="in_progress")
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10, "raw": raw})
    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        return httpx.Response(200, json=raw if request.method == "GET" else {"id": "resp_123", "status": "cancelled"})

    with pytest.raises(TimeoutError):
        invoke(handler, job, {"timeout_seconds": 0})
    assert paths == [("GET", "/v1/responses/resp_123"), ("POST", "/v1/responses/resp_123/cancel")]
    assert job.state["cancel_requested"] is True
    assert job.state["cancel_status"] == "cancelled"
    assert job.state["remote_status"] == "cancelled"
    assert job.state["pre_cancel_raw"] == raw
    assert job.state["observed_cost_usd"] == pytest.approx(.00467)
    assert job.state["observed_cost_scope"] == "partial_pre_cancel"
    assert job.state["observed_usage"]["cached_input_tokens"] == 200
    assert job.state.get("provider_result", {}).get("cost_usd") is None
    methods = []
    def reconciled(request):
        methods.append(request.method)
        return httpx.Response(200, json=completed())
    assert invoke(reconciled, job)["text"] == "A full answer."
    assert methods == ["GET"]
    assert job.state["observed_cost_usd"] == pytest.approx(.00467)


@pytest.mark.parametrize("remote_id", ["resp_123", None])
def test_unpriced_saved_terminal_receipt_can_reconcile_without_reposting(tmp_path, remote_id):
    raw = {"id": "resp_123", "status": "cancelled"}
    job = FakeJob(tmp_path, {"remote_id": remote_id, "submission_unknown": remote_id is None, "raw": raw,
                             "pre_cancel_raw": completed(status="in_progress")})
    methods = []
    def reconcile(request):
        methods.append(request.method)
        return httpx.Response(200, json=completed(status="cancelled"))
    with pytest.raises(openai.ProviderError):
        invoke(reconcile, job)
    assert methods == ["GET"]
    assert job.state["provider_result"]["cost_usd"] == pytest.approx(.00467)
    assert job.state["observed_cost_usd"] == pytest.approx(.00467)
    assert job.state["observed_cost_scope"] == "partial_pre_cancel"


def test_unknown_search_action_keeps_cost_unknown(tmp_path):
    raw = completed()
    raw["output"].append({"type": "web_search_call"})
    result = invoke(lambda request: httpx.Response(200, json=raw), FakeJob(tmp_path))
    assert result["cost_usd"] is None
    assert result["usage"]["web_search_calls"] is None


@pytest.mark.parametrize("submitted_at", [None, time.time() - 10000], ids=["fresh", "after_deadline"])
def test_exhausted_retrieval_retries_keep_id_without_cancelling_and_resume(tmp_path, submitted_at):
    job = FakeJob(tmp_path, {"remote_id": "resp_123"} | ({"submitted_at": submitted_at} if submitted_at else {}))
    calls = []

    def unavailable(request):
        calls.append(request.method)
        return httpx.Response(503, json={"error": "retry later"})

    with pytest.raises(httpx.HTTPStatusError):
        invoke(unavailable, job, {"timeout_seconds": 1})
    assert calls == ["GET"] * 4
    assert job.state["remote_id"] == "resp_123"
    assert job.state["poll_raw"] == {"error": "retry later"}
    assert not job.state.get("cancel_requested")
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json=completed())

    assert invoke(handler, job)["text"]
    assert methods == ["GET"]


def test_deadline_reached_during_poll_interval_cancels_before_next_get(tmp_path):
    methods = []

    def handler(request):
        methods.append((request.method, request.url.path))
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"id": "resp_123", "status": "cancelled"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "resp_123", "status": "queued"})
        return httpx.Response(200, json=completed())

    with pytest.raises(TimeoutError):
        invoke(handler, FakeJob(tmp_path), {"timeout_seconds": .01, "poll_interval_seconds": 1})
    assert methods == [("POST", "/v1/responses"), ("POST", "/v1/responses/resp_123/cancel")]


def test_retrieval_timeout_at_deadline_requests_cancellation(tmp_path):
    job = FakeJob(tmp_path)

    def handler(request):
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"id": "resp_123", "status": "cancelled"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "resp_123", "status": "queued"})
        time.sleep(.02)
        raise httpx.ReadTimeout("retrieval timed out", request=request)

    with pytest.raises(TimeoutError):
        invoke(handler, job, {"timeout_seconds": .01, "poll_interval_seconds": 0})
    assert job.state["cancel_status"] == "cancelled"


@pytest.mark.parametrize("state", [
    {"submission_unknown": True},
    {"submitted_at": time.time() - 10000, "raw": {"id": "resp_123", "status": "queued"}},
], ids=["unknown_flag_with_id", "after_deadline"])
def test_resume_with_saved_remote_id_retrieves_without_submitting_or_cancelling(tmp_path, state):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", **state})
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=completed())

    result = invoke(handler, job, {"timeout_seconds": 1})
    assert result["text"] == "A full answer."
    assert calls == [("GET", "/v1/responses/resp_123")]
    assert job.state["remote_status"] == "completed"
    assert job.state["raw"] == completed()
    assert not job.state.get("cancel_requested")


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

    assert invoke(handler, job)["text"] == "A full answer."
    assert calls == ["POST", "POST"]
    assert job.state["submission_unknown"] is False
    assert len(no_http_retry_wait) == 1


def test_retry_final_rate_limit_is_a_known_rejected_submission(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429, json={"error": "rate limited"})

    with pytest.raises(openai.ProviderError, match="rejected"):
        invoke(handler, job)
    assert calls == ["POST"] * 4
    assert job.state["submission_unknown"] is False
    assert job.state["submission_http_status"] == 429


def test_retry_expired_resume_can_recover_get_service_unavailable(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10000})
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503, json={"error": "temporary"}) if len(calls) == 1 else httpx.Response(200, json=completed())

    assert invoke(handler, job, {"timeout_seconds": 1})["text"] == "A full answer."
    assert calls == ["GET", "GET"]
    assert not job.state.get("cancel_requested")


def test_retry_does_not_replay_create_after_rate_limit_followed_by_ambiguous_failure(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429 if len(calls) == 1 else 503, json={"error": "temporary"})

    with pytest.raises(openai.ProviderError, match="unknown"):
        invoke(handler, job)
    assert calls == ["POST", "POST"]
    assert job.state["submission_unknown"] is True
    with pytest.raises(openai.ProviderError, match="unknown"):
        invoke(handler, job)
    assert calls == ["POST", "POST"]


def test_retry_create_rate_limit_longer_than_deadline_remains_known_rejection(tmp_path, no_http_retry_wait):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(429, headers={"Retry-After": "5"}, json={"error": "limited"})

    with pytest.raises(openai.ProviderError, match="rejected"):
        invoke(handler, job, {"timeout_seconds": .01})
    assert calls == ["POST"]
    assert job.state["submission_unknown"] is False
    assert no_http_retry_wait == []


def test_retry_cancellation_recovers_without_losing_original_remote_state(tmp_path):
    running = {"id": "resp_123", "status": "in_progress"}
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 100})
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json=running)
        if calls.count("POST") == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"id": "resp_123", "status": "cancelled"})

    with pytest.raises(TimeoutError):
        invoke(handler, job, {"timeout_seconds": 1})
    assert calls == ["GET", "POST", "POST"]
    assert job.state["pre_cancel_raw"] == running
    assert job.state["cancel_status"] == "cancelled"


def test_unsent_rate_gate_timeout_can_be_retried_as_a_fresh_create(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    class SlowGate(Gate):
        blocked = True

        async def wait_ready(self):
            if self.blocked:
                await asyncio.sleep(.04)

    job.rate_controller = SlowGate()

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=completed())

    with pytest.raises((openai.ProviderError, TimeoutError)):
        invoke(handler, job, {"timeout_seconds": .01})
    assert calls == []
    assert job.state["submission_unknown"] is False
    job.rate_controller.blocked = False
    assert invoke(handler, job, {"timeout_seconds": .01})["text"] == "A full answer."
    assert calls == ["POST"]


@pytest.mark.parametrize("after_rejection", [False, True])
def test_cancellation_while_waiting_to_create_keeps_submission_retryable(tmp_path, after_rejection):
    job = FakeJob(tmp_path)
    calls = []

    async def exercise():
        waiting = asyncio.Event()

        class BlockingGate(Gate):
            count = 0

            async def wait_ready(self):
                self.count += 1
                if not after_rejection or self.count == 2:
                    waiting.set()
                    await asyncio.Future()

        job.rate_controller = BlockingGate()

        def handler(request):
            calls.append(request.method)
            if after_rejection and len(calls) == 1:
                return httpx.Response(429, json={"error": "limited"})
            return httpx.Response(200, json=completed())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(openai.generate("prompt", {}, job, client=client))
            await asyncio.wait_for(waiting.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == (["POST"] if after_rejection else [])
            assert job.state["submission_unknown"] is False
            job.rate_controller = None
            assert (await openai.generate("prompt", {}, job, client=client))["text"] == "A full answer."

    asyncio.run(exercise())
    assert calls == ["POST"] * (2 if after_rejection else 1)


def test_cancellation_after_create_dispatch_stays_ambiguous_and_never_reposts(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    async def exercise():
        dispatched = asyncio.Event()

        async def handler(request):
            calls.append(request.method)
            dispatched.set()
            await asyncio.Future()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(openai.generate("prompt", {}, job, client=client))
            await asyncio.wait_for(dispatched.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert job.state["submission_unknown"] is True
            with pytest.raises(openai.ProviderError, match="unknown"):
                await openai.generate("prompt", {}, job, client=client)

    asyncio.run(exercise())
    assert calls == ["POST"]


@pytest.mark.parametrize(
    "input_tokens,cached_tokens,cache_write_tokens,output_tokens,expected_cost",
    [
        (1000, 0, 0, 1000, .06),
        (1000, 200, 100, 300, .02345),
        (1000, 1000, 0, 0, .001),
        (1000, 0, 1000, 0, .0125),
        (272000, 2000, 1000, 1000, 2.7545),
        (300000, 20000, 10000, 1000, 5.765),
    ],
)
def test_astra_judge_billing_uses_exact_standard_cache_and_context_rates(
    tmp_path, input_tokens, cached_tokens, cache_write_tokens, output_tokens, expected_cost
):
    raw = completed(model="gpt-6-astra", usage={
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached_tokens, "cache_write_tokens": cache_write_tokens},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": output_tokens // 2},
        "total_tokens": input_tokens + output_tokens,
    })

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-6-astra"
        assert payload["reasoning"] == {"effort": "high"}
        assert payload["service_tier"] == "default"
        assert not payload.get("tools")
        return httpx.Response(200, json=raw)

    result = invoke(handler, FakeJob(tmp_path), {"model": "gpt-6-astra", "reasoning_effort": "high"}, judge=True)
    assert result["cost_usd"] == pytest.approx(expected_cost)
    assert result["cost_estimated"] is True
    assert result["usage"]["cached_input_tokens"] == cached_tokens
    assert result["usage"]["cache_write_tokens"] == cache_write_tokens
    assert result["usage"]["output_tokens"] == output_tokens
    assert result["raw"] == raw


@pytest.mark.parametrize("changes", [
    {"model": "unrecognized-model"},
    {"service_tier": "fast"},
    {"usage": None},
    {"usage": {"input_tokens": 1000}},
])
def test_astra_billing_keeps_unsupported_or_missing_price_inputs_unknown(tmp_path, changes):
    raw = completed(model="gpt-6-astra")
    raw.update(changes)
    result = invoke(lambda request: httpx.Response(200, json=raw), FakeJob(tmp_path),
                    {"model": "gpt-6-astra"}, judge=True)
    assert result["cost_usd"] is None
    assert any("Cost unknown" in warning for warning in result["warnings"])


RANGE = {"poll_interval_seconds": 0, "budget_usd": 4.0, "budget_floor_usd": .02, "max_research_rounds": 3,
         "continuation_prompt": "Spent {spent} of {floor}-{ceiling}; keep to {max_words} words.", "answer_word_limit": 600}


def test_research_rounds_continue_until_the_budget_floor(tmp_path):
    submissions = []
    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            submissions.append(body)
            return httpx.Response(200, json=completed(id=f"resp_{len(submissions)}", output=[{"type": "message", "status": "completed",
                "content": [{"type": "output_text", "text": f"Round {len(submissions)} answer", "annotations": [
                    {"type": "url_citation", "url": f"https://example.org/{len(submissions)}", "title": "S"}]}]}]))
        pytest.fail("background polling is unnecessary for a completed submission")
    job = FakeJob(tmp_path)
    result = invoke(handler, job, RANGE)
    # Each round costs (700*2 + 200*.1 + 100*2.5 + 300*10) / 1e6 = $0.00467; the $0.02 floor is never reached, so the round cap ends it.
    assert len(submissions) == 3 and result["usage"]["rounds"] == 3
    assert submissions[1]["previous_response_id"] == "resp_1" and submissions[2]["previous_response_id"] == "resp_2"
    assert submissions[1]["input"].startswith("Spent 0.00 of 0.02-4.00; keep to 600 words.")
    assert "previous_response_id" not in submissions[0]
    assert result["text"] == "Round 3 answer"
    assert [c["url"] for c in result["citations"]] == [f"https://example.org/{i}" for i in (1, 2, 3)]
    assert result["cost_usd"] == pytest.approx(3 * .00467)
    assert len(result["raw"]["previous_rounds"]) == 2 and result["raw"]["id"] == "resp_3"
    assert any("3 research rounds" in w for w in result["warnings"]) and any("below the $0.02 budget floor" in w for w in result["warnings"])
    assert len(job.state["rounds"]) == 2 and job.state["remote_id"] == "resp_3"


def test_research_rounds_stop_once_the_floor_is_reached_and_resume_mid_round(tmp_path):
    first = completed(id="resp_1")
    job = FakeJob(tmp_path, {"rounds": [first], "remote_id": "resp_2", "raw": completed(id="resp_2", status="in_progress"),
                             "submitted_at": time.time()})
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=completed(id="resp_2", output=[{"type": "message", "status": "completed",
                                                                        "content": [{"type": "output_text", "text": "Final"}]}]))
    result = invoke(handler, job, RANGE | {"budget_floor_usd": .009})
    assert calls == [("GET", "/v1/responses/resp_2")]  # The in-flight second round is retrieved, not resubmitted.
    assert result["text"] == "Final" and result["usage"]["rounds"] == 2
    assert result["cost_usd"] == pytest.approx(2 * .00467) and not any("below the" in w for w in result["warnings"])


def test_saved_completed_response_is_returned_without_a_key_or_client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "raw": completed()})
    assert asyncio.run(openai.generate("Exact prompt", {}, job))["text"] == "A full answer."


def test_soft_cap_flags_an_overrun_without_cancelling(tmp_path):
    over = {"input_tokens": 1000000, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}, "output_tokens": 1000000}
    polls = []

    def handler(request):
        polls.append(request.url.path)
        assert not request.url.path.endswith("/cancel")
        return httpx.Response(200, json=completed(status="in_progress", usage=over) if len(polls) < 3 else completed(usage=over))

    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"poll_interval_seconds": 0, "budget_cap": "soft"})
    assert result["text"] and job.state["budget_exceeded"] is True and "cancel_reason" not in job.state
    assert any("soft cap" in warning for warning in result["warnings"])


@pytest.mark.parametrize("second", ["disconnect", "rejected"])
def test_failed_later_round_keeps_earlier_answer_with_truthful_total(tmp_path, second):
    posts = []

    def handler(request):
        posts.append(json.loads(request.content))
        if len(posts) == 1:
            return httpx.Response(200, json=completed(id="resp_1"))
        if second == "disconnect":
            raise httpx.ReadTimeout("connection lost after submission", request=request)
        return httpx.Response(400, json={"error": {"message": "bad parameter"}})

    job = FakeJob(tmp_path)
    result = invoke(handler, job, RANGE)
    assert len(posts) == 2 and result["text"] == "A full answer."
    if second == "disconnect":
        # The second submission may have been accepted and billed: the total is unknown.
        assert job.state["submission_unknown"] is True
        assert result["cost_usd"] is None and result["cost_estimated"] is False
        assert any("unknown outcome" in warning for warning in result["warnings"])
        replay = invoke(lambda request: pytest.fail("ambiguous later round must not repost"), job, RANGE)
        assert replay["text"] == result["text"] and replay["cost_usd"] is None
    else:
        # An explicit rejection is unbilled: the earlier round's total stays known.
        assert job.state["submission_unknown"] is False
        assert result["cost_usd"] == pytest.approx(.00467)


def test_unanswerable_earlier_round_receipt_is_unknown_after_ambiguous_later_round(tmp_path):
    empty = completed(id="resp_1")
    empty["output"][0]["content"][0]["text"] = " "

    def handler(request):
        if request.url.path.endswith("/responses") and json.loads(request.content).get("previous_response_id"):
            raise httpx.ReadTimeout("connection lost after submission", request=request)
        return httpx.Response(200, json=empty)

    job = FakeJob(tmp_path)
    with pytest.raises(openai.ProviderError, match="empty answer text"):
        invoke(handler, job, RANGE)
    # The failure receipt must not price only round 1 while round 2 may have been billed.
    assert job.state["submission_unknown"] is True
    assert job.state["provider_result"]["cost_usd"] is None
    assert job.state["provider_result"]["cost_estimated"] is False
