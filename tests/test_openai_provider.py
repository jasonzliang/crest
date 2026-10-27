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
    with pytest.raises(openai.ProviderError):
        invoke(lambda request: httpx.Response(200, json=raw), job)
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


def test_resume_saved_remote_id_never_submits(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submission_unknown": True})
    requests = []

    def handler(request):
        requests.append(request.method)
        return httpx.Response(200, json=completed())

    assert invoke(handler, job)["text"] == "A full answer."
    assert requests == ["GET"]


def test_ambiguous_network_failure_blocks_a_second_post(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        raise httpx.ReadTimeout("connection lost after submission", request=request)

    with pytest.raises(Exception, match="submission.*unknown|ambiguous"):
        invoke(handler, job)
    assert job.state["submission_unknown"] is True
    with pytest.raises(Exception, match="submission.*unknown|ambiguous"):
        invoke(handler, job)
    assert calls == ["POST"]


@pytest.mark.parametrize("status", ["failed", "cancelled", "incomplete", "success", None])
def test_only_exact_completed_status_can_succeed(tmp_path, status):
    job = FakeJob(tmp_path)
    raw = completed(status=status)
    with pytest.raises(Exception, match="status|completed"):
        invoke(lambda request: httpx.Response(200, json=raw), job)
    assert job.state["raw"] == raw


def test_empty_completed_response_is_an_error(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(Exception, match="empty|text"):
        invoke(lambda request: httpx.Response(200, json=completed(output=[])), job)


def test_billing_subtracts_cached_and_write_tokens_and_counts_search_only(tmp_path):
    raw = completed()
    raw["output"] += [
        {"type": "web_search_call", "action": {"type": "search"}},
        {"type": "web_search_call", "action": {"type": "open_page"}},
        {"type": "web_search_call", "action": {"type": "find_in_page"}},
    ]
    result = invoke(lambda request: httpx.Response(200, json=raw), FakeJob(tmp_path))
    assert result["usage"]["input_tokens"] == 1000
    assert result["usage"]["cached_input_tokens"] == 200
    assert result["usage"]["cache_write_tokens"] == 100
    assert result["usage"]["output_tokens"] == 300  # Includes the 100 reasoning tokens already.
    assert result["usage"]["reasoning_tokens"] == 100
    assert result["usage"]["web_search_calls"] == 1
    assert result["cost_usd"] == pytest.approx(0.01467)
    assert result["cost_estimated"] is True


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": 1000}, {"output_tokens": 10}])
def test_missing_essential_usage_keeps_cost_unknown(tmp_path, usage):
    result = invoke(lambda request: httpx.Response(200, json=completed(usage=usage)), FakeJob(tmp_path))
    assert result["cost_usd"] is None
    assert result["warnings"]


def test_long_context_premium_applies_to_full_request(tmp_path):
    raw = completed(usage={"input_tokens": 300000, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                           "output_tokens": 1000, "output_tokens_details": {"reasoning_tokens": 500}})
    result = invoke(lambda request: httpx.Response(200, json=raw), FakeJob(tmp_path))
    assert result["cost_usd"] == pytest.approx(1.215)


def test_unknown_model_has_no_invented_price(tmp_path):
    result = invoke(lambda request: httpx.Response(200, json=completed(model="other-model")),
                    FakeJob(tmp_path), {"model": "other-model"})
    assert result["cost_usd"] is None


def test_timeout_attempts_cancellation_and_records_its_actual_status(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10,
                             "raw": {"id": "resp_123", "status": "in_progress"}})
    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        status = "in_progress" if request.method == "GET" else "cancelled"
        return httpx.Response(200, json={"id": "resp_123", "status": status})

    with pytest.raises(TimeoutError):
        invoke(handler, job, {"timeout_seconds": 0})
    assert paths == [("GET", "/v1/responses/resp_123"), ("POST", "/v1/responses/resp_123/cancel")]
    assert job.state["cancel_requested"] is True
    assert job.state["cancel_status"] == "cancelled"
    assert job.state["remote_status"] == "cancelled"


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


def test_server_error_submission_is_preserved_and_not_repeated(tmp_path):
    job = FakeJob(tmp_path)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(500, json={"error": {"message": "server failure"}})

    with pytest.raises(Exception):
        invoke(handler, job)
    assert job.state["raw"] == {"error": {"message": "server failure"}}
    assert job.state["submission_unknown"] is True
    with pytest.raises(Exception):
        invoke(handler, job)
    assert calls == ["POST"]


def test_judge_uses_strict_binary_schema_and_no_tools(tmp_path):
    from crest.judging import SCHEMA
    verdict = {name: {"reason": "A is more creative.", "winner": "A"} for name in ("new", "useful", "surprising")}

    def handler(request):
        payload = json.loads(request.content)
        assert payload["text"]["format"] == {"type": "json_schema", "name": "crest_verdict", "strict": True, "schema": SCHEMA}
        assert payload["reasoning"] == {"effort": "medium"}
        assert payload["max_output_tokens"] == 12000
        assert not payload.get("tools")
        assert "tool_choice" not in payload and "include" not in payload
        raw = completed()
        raw["output"][0]["content"][0]["text"] = json.dumps(verdict)
        return httpx.Response(200, json=raw)

    result = invoke(handler, FakeJob(tmp_path), judge=True)
    assert json.loads(result["text"]) == verdict


def test_response_with_id_is_checkpointed_in_one_atomic_write(tmp_path):
    class CrashOnIdSave(FakeJob):
        def save(self, **changes):
            if isinstance(changes.get("raw"), dict) and changes["raw"].get("id") and not changes.get("remote_id") and not self.state.get("remote_id"):
                raise AssertionError("raw response was saved before its recoverable id")
            super().save(**changes)

    job = CrashOnIdSave(tmp_path)
    assert invoke(lambda request: httpx.Response(200, json=completed()), job)["text"]


def test_missing_id_submission_preserves_raw_and_remains_ambiguous(tmp_path):
    raw = completed()
    del raw["id"]
    job = FakeJob(tmp_path)
    with pytest.raises(Exception, match="unknown|id"):
        invoke(lambda request: httpx.Response(200, json=raw), job)
    assert job.state["raw"] == raw
    assert job.state["submission_unknown"] is True
    with pytest.raises(Exception, match="unknown"):
        invoke(lambda request: pytest.fail("Must not submit twice"), job)


def test_explicit_rejection_is_not_marked_as_accepted_submission(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(Exception, match="400"):
        invoke(lambda request: httpx.Response(400, json={"error": "bad parameter"}), job)
    assert job.state["submission_unknown"] is False
    assert "remote_id" not in job.state


def test_completed_status_with_error_payload_is_rejected(tmp_path):
    with pytest.raises(Exception, match="error"):
        invoke(lambda request: httpx.Response(200, json=completed(error={"code": "server_error"})), FakeJob(tmp_path))


def test_completed_over_budget_retains_answer_and_reports_overrun(tmp_path):
    result = invoke(lambda request: httpx.Response(200, json=completed()), FakeJob(tmp_path), {"budget_usd": 0.0001})
    assert result["text"] == "A full answer."
    assert any("exceeded" in warning for warning in result["warnings"])


def test_cancellation_preserves_response_observed_before_cancel(tmp_path):
    raw = completed(status="in_progress")
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10, "raw": raw})
    with pytest.raises(TimeoutError):
        invoke(lambda request: httpx.Response(200, json=raw if request.method == "GET"
               else {"id": "resp_123", "status": "cancelled"}), job, {"timeout_seconds": 0})
    assert job.state["pre_cancel_raw"] == raw


def test_cancellation_keeps_partial_estimate_and_resume_reconciles_by_get(tmp_path):
    raw = completed(status="in_progress")
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10, "raw": raw})
    with pytest.raises(TimeoutError):
        invoke(lambda request: httpx.Response(200, json=raw if request.method == "GET"
               else {"id": "resp_123", "status": "cancelled"}), job, {"timeout_seconds": 0})
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


def test_retrieval_failure_keeps_id_and_can_resume(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123"})
    with pytest.raises(httpx.HTTPStatusError):
        invoke(lambda request: httpx.Response(503, json={"error": "retry later"}), job)
    assert job.state["remote_id"] == "resp_123"
    assert job.state["poll_raw"] == {"error": "retry later"}
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


def test_resume_after_deadline_retrieves_completed_answer_without_cancellation(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10000,
                             "raw": {"id": "resp_123", "status": "queued"}})
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


def test_research_requires_search_and_requests_full_sources(tmp_path):
    source = {"type": "url", "url": "https://example.org/research-source"}

    def handler(request):
        payload = json.loads(request.content)
        assert payload["tool_choice"] == "required"
        assert payload["include"] == ["web_search_call.action.sources"]
        raw = completed()
        raw["output"].append({"type": "web_search_call", "action": {"type": "search", "sources": [source]}})
        return httpx.Response(200, json=raw)

    result = invoke(handler, FakeJob(tmp_path))
    assert result["raw"]["output"][-1]["action"]["sources"] == [source]


def test_failed_expired_resume_retrieval_preserves_job_without_cancelling_unknown_state(tmp_path):
    job = FakeJob(tmp_path, {"remote_id": "resp_123", "submitted_at": time.time() - 10000})
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503, json={"error": "temporarily unavailable"})

    with pytest.raises(httpx.HTTPStatusError):
        invoke(handler, job, {"timeout_seconds": 1})
    assert calls == ["GET"] * 4
    assert job.state["remote_id"] == "resp_123"
    assert not job.state.get("cancel_requested")


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
