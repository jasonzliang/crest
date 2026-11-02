"""Offline contract tests for the Anthropic Messages adapter."""
import asyncio
import json
from dataclasses import dataclass, field

import httpx
import pytest

from crest.providers import anthropic


@dataclass
class FakeJob:
    directory: object
    state: dict = field(default_factory=dict)
    key: str = "test-job"

    def save(self, **changes):
        self.state.update(changes)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "state.json").write_text(json.dumps(self.state))


def sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def turn(text="A full answer.", *, stop="end_turn", model="claude-sonnet-5-5", searches=2, citation=True, tool=True):
    """A complete streamed message: optional server tool use, one cited text block, terminal delta."""
    events = [{"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
               "content": [], "usage": {"input_tokens": 1000, "cache_creation_input_tokens": 200,
                                        "cache_read_input_tokens": 500, "output_tokens": 1}}}]
    index = 0
    if tool:
        events += [{"type": "content_block_start", "index": 0, "content_block": {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {}}},
                   {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"query": "cool'}},
                   {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": ' homes"}'}},
                   {"type": "content_block_stop", "index": 0},
                   {"type": "content_block_start", "index": 1, "content_block": {"type": "web_search_tool_result", "tool_use_id": "srv_1",
                    "content": [{"type": "web_search_result", "url": "https://example.org/a", "title": "A", "encrypted_content": "SECRET", "page_age": None}],
                    "cache_control": {"type": "ephemeral"}}},
                   {"type": "content_block_stop", "index": 1}]
        index = 2
    events += [{"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
               {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}}]
    if citation:
        events.append({"type": "content_block_delta", "index": index, "delta": {"type": "citations_delta", "citation": {
            "type": "web_search_result_location", "url": "https://example.org/a", "title": "A", "cited_text": "x", "encrypted_index": "IDX"}}})
    events += [{"type": "content_block_stop", "index": index},
               {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 300, "server_tool_use": {"web_search_requests": searches, "web_fetch_requests": 1}}},
               {"type": "message_stop"}]
    return events


def stream_response(events, status=200):
    return httpx.Response(status, content=sse(events), headers={"content-type": "text/event-stream"})


def invoke(handler, job, settings=None, *, judge=False):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await (anthropic.judge if judge else anthropic.generate)(
                "Exact prompt", settings or {}, job, client=client)
    return asyncio.run(run())


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_generate_assembles_text_citations_usage_and_cost(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == anthropic.API_VERSION
        assert "anthropic-beta" not in request.headers
        return stream_response(turn())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"max_web_searches": 7, "max_web_fetches": 3, "effort": "max", "max_output_tokens": 5000})
    payload = requests[0]
    assert payload["model"] == "claude-sonnet-5-5" and payload["stream"] is True
    assert payload["output_config"] == {"effort": "max"} and payload["max_tokens"] == 5000
    assert payload["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 7},
                                {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}]
    assert payload["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Exact prompt", "cache_control": {"type": "ephemeral"}}]}]
    assert result["text"] == "A full answer."
    assert result["citations"] == [{"url": "https://example.org/a", "title": "A"}]
    assert result["usage"]["input_tokens"] == 1000 and result["usage"]["output_tokens"] == 300
    assert result["usage"]["web_search_calls"] == 2 and result["usage"]["web_fetch_calls"] == 1
    # (1000*2 + 500*.10 + 200*2.50 + 300*10) / 1e6 + 2 searches * $0.01
    assert result["cost_usd"] == pytest.approx(.00555 + .02)
    assert result["model"] == "claude-sonnet-5-5" and result["cost_estimated"] is True
    saved = json.dumps(job.state)
    assert "SECRET" not in saved and "IDX" not in saved
    assert job.state["submission_unknown"] is False and job.state["remote_status"] == "end_turn"


def test_pause_turn_continuation_echoes_full_assistant_content_and_bills_every_turn(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(turn("Partial.", stop="pause_turn") if len(requests) == 1 else turn("Final.", tool=False, citation=False))
    result = invoke(handler, FakeJob(tmp_path))
    assert len(requests) == 2
    echoed = requests[1]["messages"]
    assert echoed[0]["content"][0]["text"] == "Exact prompt" and echoed[1]["role"] == "assistant"
    assert "cache_control" in echoed[0]["content"][0]  # Still the latest user turn.
    assert echoed[1]["content"][0]["input"] == {"query": "cool homes"}
    assert echoed[1]["content"][1]["content"][0]["encrypted_content"] == "SECRET"
    assert result["text"] == "Partial.\n\nFinal."
    assert result["usage"]["turns"] == 2
    assert result["cost_usd"] == pytest.approx(2 * (.00555 + .02))
    assert any("2 server turns" in w for w in result["warnings"])


def test_too_many_pauses_fail_with_a_receipt(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="max_continuations"):
        invoke(lambda request: stream_response(turn(stop="pause_turn")), job, {"max_continuations": 1})
    assert job.state["provider_result"]["usage"]["turns"] == 2
    assert job.state["provider_result"]["cost_usd"] == pytest.approx(2 * (.00555 + .02))


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_terminal_failures_preserve_the_priced_receipt(tmp_path, stop):
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match=stop):
        invoke(lambda request: stream_response(turn(stop=stop)), job)
    assert job.state["provider_result"]["cost_usd"] == pytest.approx(.00555 + .02)
    assert job.state["submission_unknown"] is False


def test_rate_limit_rejection_is_retried_once_safe_and_counted(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"type": "rate_limit_error"}}, headers={"retry-after": "0"})
        return stream_response(turn())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"retry_backoff_base_seconds": 0, "retry_backoff_max_seconds": 0})
    assert result["text"] == "A full answer." and len(calls) == 2
    assert job.state["retry_events"][0]["status_code"] == 429 and job.state["retry_events"][0]["retrying"] is True


def test_explicit_rejection_is_never_retried(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "bad"}})
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="HTTP 400"):
        invoke(handler, job)
    assert len(calls) == 1 and job.state["submission_unknown"] is False


def test_unknown_submission_refuses_a_second_paid_request(tmp_path):
    job = FakeJob(tmp_path, {"submission_unknown": True})
    with pytest.raises(anthropic.ProviderError, match="refusing"):
        invoke(lambda request: pytest.fail("must not submit"), job)


def test_saved_terminal_turns_are_reused_without_requests(tmp_path):
    first = invoke(lambda request: stream_response(turn()), FakeJob(tmp_path / "a"))
    job = FakeJob(tmp_path / "b", {"raw": first["raw"]})
    again = invoke(lambda request: pytest.fail("saved receipt must not make requests"), job)
    assert again["text"] == first["text"] and again["cost_usd"] == pytest.approx(first["cost_usd"])


def test_saved_paused_turns_restart_and_keep_their_billed_cost(tmp_path):
    paused_turn = {"model": "claude-sonnet-5-5", "stop_reason": "pause_turn", "content": [], "_usage_final": True,
                   "usage": {"input_tokens": 1000, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 500,
                             "output_tokens": 300, "server_tool_use": {"web_search_requests": 2}}}
    job = FakeJob(tmp_path, {"raw": {"turns": [paused_turn]}})
    result = invoke(lambda request: stream_response(turn()), job)
    assert result["text"] == "A full answer." and result["usage"]["turns"] == 1
    assert job.state["interrupted_attempts"][0]["error"] == "abandoned paused exchange"
    assert result["cost_usd"] == pytest.approx(2 * (.00555 + .02))  # The abandoned turn is still billed.
    assert any("their estimate is included" in w for w in result["warnings"])


def test_budget_stops_further_server_turns(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="budget ceiling exceeded"):
        invoke(lambda request: stream_response(turn(stop="pause_turn")), job, {"budget_usd": .02})
    assert job.state["budget_exceeded"] is True and job.state["provider_result"]["cost_usd"] == pytest.approx(.00555 + .02)


def test_overloaded_error_before_content_is_retried_and_after_content_is_an_interruption(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return stream_response(turn()[:1] + [{"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}])
        return stream_response(turn())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"retry_backoff_base_seconds": 0, "retry_backoff_max_seconds": 0})
    assert result["text"] == "A full answer." and len(calls) == 2
    assert "interrupted_attempts" not in job.state and "overloaded" in job.state["last_rejection"]
    events = turn()
    late = events[:4] + [{"type": "error", "error": {"type": "api_error", "message": "mid-stream"}}]
    job = FakeJob(tmp_path / "late")
    with pytest.raises(anthropic.StreamInterrupted):
        invoke(lambda request: stream_response(late), job, {"retry_attempts": 2})
    assert len(job.state["interrupted_attempts"]) == 2  # Retried in place once, then surfaced.


def test_thinking_blocks_pings_and_the_fetch_switch(tmp_path):
    events = turn(tool=False, citation=False)
    thinking = [{"type": "ping"},
                {"type": "content_block_start", "index": 5, "content_block": {"type": "thinking", "thinking": ""}},
                {"type": "content_block_delta", "index": 5, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
                {"type": "content_block_delta", "index": 5, "delta": {"type": "signature_delta", "signature": "sig"}},
                {"type": "content_block_stop", "index": 5},
                {"type": "content_block_delta", "index": 9, "delta": {"type": "text_delta", "text": "orphan"}}]
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(events[:1] + thinking + events[1:])
    result = invoke(handler, FakeJob(tmp_path), {"web_fetch": False})
    assert result["text"] == "A full answer."
    assert result["raw"]["turns"][0]["content"][0] == {"type": "thinking", "thinking": "hmm", "signature": "sig"}
    assert [tool["name"] for tool in requests[0]["tools"]] == ["web_search"]


def test_message_delta_without_usage_leaves_the_cost_unknown(tmp_path):
    events = [e if e["type"] != "message_delta" else {"type": "message_delta", "delta": e["delta"]} for e in turn()]
    result = invoke(lambda request: stream_response(events), FakeJob(tmp_path))
    assert result["cost_usd"] is None and result["cost_estimated"] is False


class BrokenStream(httpx.AsyncByteStream):
    def __init__(self, head):
        self.head = head
    async def __aiter__(self):
        yield self.head
        raise httpx.ReadError("connection reset")


def test_interrupted_stream_is_recorded_and_its_cost_carried_into_the_retry(tmp_path):
    events = turn()
    head = sse(events[:2])  # message_start and the first block: generation had begun.
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, stream=BrokenStream(head), headers={"content-type": "text/event-stream"})
        return stream_response(events)
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.StreamInterrupted):
        invoke(handler, job, {"retry_attempts": 1})  # No in-place retry: the failure surfaces.
    assert job.state["submission_unknown"] is False
    assert len(job.state["interrupted_attempts"]) == 1
    # Only input-side usage was known when the stream broke; output is unknown, so cost is None.
    assert job.state["interrupted_attempts"][0]["cost_usd"] is None
    result = invoke(handler, job)  # A later run retries and carries the unknown charge.
    assert result["text"] == "A full answer."
    assert result["usage"]["interrupted_attempts"] == 1
    assert result["cost_usd"] is None  # An unpriced earlier attempt keeps the total honest.
    assert any("their charges are unknown" in w for w in result["warnings"])


def test_interrupted_turn_is_retried_in_place_within_the_same_exchange(tmp_path):
    events = turn()
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, stream=BrokenStream(sse(events[:4])), headers={"content-type": "text/event-stream"})
        return stream_response(events)
    job = FakeJob(tmp_path)
    result = invoke(handler, job)
    assert len(calls) == 2 and calls[0]["messages"] == calls[1]["messages"]
    assert result["text"] == "A full answer." and len(job.state["interrupted_attempts"]) == 1
    assert result["cost_usd"] is None  # The broken attempt was billed for an unknown amount.


def test_interrupted_attempts_stop_after_the_retry_budget(tmp_path):
    job = FakeJob(tmp_path, {"interrupted_attempts": [{"cost_usd": .1}, {"cost_usd": .1}]})
    with pytest.raises(anthropic.ProviderError, match="interrupted 2 times"):
        invoke(lambda request: pytest.fail("must not submit"), job, {"retry_attempts": 2})


def test_judge_uses_json_schema_output_without_tools_and_fable_rates(tmp_path):
    requests = []
    verdict = json.dumps({"reason": "A compares both answers fully.", "winner": "A"})
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(turn(verdict, model="claude-fable-5-1", tool=False, citation=False, searches=0))
    result = invoke(handler, FakeJob(tmp_path), {"model": "claude-fable-5-1", "effort": "high"}, judge=True)
    payload = requests[0]
    assert "tools" not in payload
    assert payload["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": anthropic.JUDGE_SCHEMA}}
    assert json.loads(result["text"])["winner"] == "A"
    # (1000*10 + 500*.25 + 200*12.50 + 300*50) / 1e6, no searches
    assert result["cost_usd"] == pytest.approx((10000 + 125 + 2500 + 15000) / 1e6)
    assert result["warnings"] == []


def test_refusal_fallback_flag_sets_parameter_and_beta_header(tmp_path):
    seen = {}
    def handler(request):
        seen["beta"] = request.headers.get("anthropic-beta")
        seen["fallbacks"] = json.loads(request.content).get("fallbacks")
        return stream_response(turn())
    invoke(handler, FakeJob(tmp_path), {"refusal_fallback": True})
    assert seen == {"beta": anthropic.FALLBACK_BETA, "fallbacks": "default"}


def test_unknown_model_leaves_cost_unknown_with_a_warning(tmp_path):
    result = invoke(lambda request: stream_response(turn(model="claude-opus-9")), FakeJob(tmp_path))
    assert result["cost_usd"] is None and result["cost_estimated"] is False
    assert any("Cost unknown" in w for w in result["warnings"])


def test_research_rounds_rewrite_the_answer_until_the_budget_floor(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(turn(f"Round {len(requests)}", citation=len(requests) == 1))
    settings = {"budget_usd": 4.0, "budget_floor_usd": .04, "max_research_rounds": 5, "answer_word_limit": 600,
                "continuation_prompt": "Spent {spent}; floor {floor}; ceiling {ceiling}; {max_words} words."}
    result = invoke(handler, FakeJob(tmp_path), settings)
    # One turn costs $0.02555, so the second round crosses the $0.04 floor.
    assert len(requests) == 2 and result["text"] == "Round 2"
    assert requests[1]["messages"][1]["role"] == "assistant" and requests[1]["messages"][1]["content"][1]["content"][0]["encrypted_content"] == "SECRET"
    assert requests[1]["messages"][2]["content"][0]["text"] == "Spent 0.03; floor 0.04; ceiling 4.00; 600 words."
    assert requests[1]["messages"][2]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert requests[1]["messages"][0] == {"role": "user", "content": "Exact prompt"}  # Only the latest user turn is marked.
    assert "cache_control" not in json.dumps(requests[1]["messages"][1])
    assert result["citations"] == [{"url": "https://example.org/a", "title": "A"}]  # Kept from the first round.
    assert result["cost_usd"] == pytest.approx(2 * (.00555 + .02))
    assert any("2 research rounds" in w for w in result["warnings"])
    assert result["raw"]["turns"][0]["_round"] == 1 and result["raw"]["turns"][1]["_round"] == 2


def test_research_rounds_respect_the_round_cap(tmp_path):
    requests = []
    def handler(request):
        requests.append(1)
        return stream_response(turn(f"Round {len(requests)}"))
    settings = {"budget_floor_usd": 3.9, "max_research_rounds": 2, "continuation_prompt": "{spent} {floor} {ceiling}"}
    result = invoke(handler, FakeJob(tmp_path), settings)
    assert len(requests) == 2 and result["text"] == "Round 2"
    assert any("below the $3.90 budget floor" in w for w in result["warnings"])


def test_server_tool_use_stop_continues_the_turn_like_a_pause(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            events = turn("", stop="tool_use", citation=False)
            return stream_response([e for e in events if not (e["type"] == "content_block_delta" and e["delta"].get("type") == "text_delta")])
        return stream_response(turn(tool=False, citation=False))
    result = invoke(handler, FakeJob(tmp_path))
    assert len(requests) == 2 and requests[1]["messages"][1]["role"] == "assistant"
    assert result["text"] == "A full answer." and result["usage"]["turns"] == 2


def test_a_failed_later_round_keeps_the_earlier_answer(tmp_path):
    requests = []
    def handler(request):
        requests.append(1)
        if len(requests) == 1:
            return stream_response(turn("Round 1 answer"))
        return stream_response(turn("truncated", stop="max_tokens", tool=False, citation=False))
    settings = {"budget_floor_usd": 3.9, "max_research_rounds": 3, "continuation_prompt": "{spent} {floor} {ceiling}"}
    result = invoke(handler, FakeJob(tmp_path), settings)
    assert result["text"] == "Round 1 answer" and result["usage"]["turns"] == 2
    assert any("previous round's answer is kept" in w for w in result["warnings"])


def test_budget_overrun_during_a_later_round_keeps_the_earlier_answer(tmp_path):
    requests = []
    def handler(request):
        requests.append(1)
        # Round 1 costs $0.0256; the second round pauses after a $0.0556 turn, passing the $0.06 ceiling.
        return stream_response(turn("Round 1 answer") if len(requests) == 1 else turn("partial", stop="pause_turn", citation=False, searches=5))
    settings = {"budget_usd": .06, "budget_floor_usd": .05, "max_research_rounds": 3, "continuation_prompt": "{spent} {floor} {ceiling}"}
    job = FakeJob(tmp_path)
    result = invoke(handler, job, settings)
    assert len(requests) == 2 and result["text"] == "Round 1 answer"
    assert job.state["budget_exceeded"] is True and result["cost_usd"] == pytest.approx(.00555 + .02 + .00555 + .05)
    assert any("exceeded the $0.06 budget ceiling" in w for w in result["warnings"])
    assert any("previous round's answer is kept" in w for w in result["warnings"])


def test_soft_cap_continues_past_the_budget_and_flags_it(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        return stream_response(turn(text="Searching further.", stop="pause_turn") if len(calls) == 1 else turn())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"budget_usd": .02, "budget_cap": "soft"})
    assert result["text"].endswith("A full answer.") and len(calls) == 2  # The paused turn resumed instead of stopping.
    assert job.state["budget_exceeded"] is True
    assert any("soft cap" in warning for warning in result["warnings"])
