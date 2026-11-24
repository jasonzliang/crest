"""Offline contract tests for the Anthropic Messages adapter."""
import asyncio
import copy
import json
import sys
from dataclasses import dataclass, field
from types import ModuleType

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


def answer(text="A full answer.", *, model=None, **kwargs):
    """A final turn with no server search, tool use, or citation (Opus unless stated)."""
    return turn(text, model=model or OPUS, searches=0, tool=False, citation=False, **kwargs)


def stream_response(events, status=200):
    return httpx.Response(status, content=sse(events), headers={"content-type": "text/event-stream"})


def invoke(handler, job, settings=None, *, judge=False, prompt="Exact prompt"):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await (anthropic.judge if judge else anthropic.generate)(
                prompt, settings or {}, job, client=client)
    return asyncio.run(run())


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "BOOTSTRAP_RETRY_DELAY_S", 0)
    async def offline_tool(name, arguments, *, client=None):
        return bootstrap_evidence()
    install_client_tool(monkeypatch, offline_tool)


def test_generate_assembles_text_citations_usage_and_cost(tmp_path):
    events = turn()
    index = next(i for i, e in enumerate(events) if e.get("delta", {}).get("type") == "citations_delta")
    # A citations_delta without a citation is skipped rather than recorded or rejected.
    events.insert(index, {"type": "content_block_delta", "index": events[index]["index"], "delta": {"type": "citations_delta"}})
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == anthropic.API_VERSION
        assert "anthropic-beta" not in request.headers
        return stream_response(events)
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"model": "claude-sonnet-5-5", "max_web_searches": 7, "max_web_fetches": 3, "effort": "max", "max_output_tokens": 5000})
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


@pytest.mark.parametrize("base, url", [(None, "https://api.anthropic.com/v1/messages"),
                                       ("https://proxy.example/v1", "https://proxy.example/v1/messages")],
                         ids=["native", "gateway"])
def test_rate_limit_rejection_is_retried_once_on_the_same_route_and_counted(tmp_path, base, url):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"type": "rate_limit_error"}}, headers={"retry-after": "0"})
        return stream_response(turn(model=OPUS if base else SONNET))
    job = FakeJob(tmp_path)
    settings = {"retry_attempts": 2, "retry_backoff_base_seconds": 0, "retry_backoff_max_seconds": 0}
    result = invoke(handler, job, settings | ({"api_base": base} if base else {}))
    assert result["text"] == "A full answer." and calls == [url] * 2
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
        return stream_response(answer(verdict, model="claude-fable-5-1"))
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


@pytest.mark.parametrize("events", [
    turn(model="claude-opus-9"),
    [e if e["type"] != "message_delta" else {"type": "message_delta", "delta": e["delta"]} for e in turn()],
], ids=["unknown_model", "message_delta_without_usage"])
def test_unpriceable_turn_leaves_cost_unknown_with_a_warning(tmp_path, events):
    result = invoke(lambda request: stream_response(events), FakeJob(tmp_path))
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


OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
SONNET_PROXY_RATES = {"input": 2.2, "cached_input": .11, "cache_write_5m": 2.75, "output": 11, "web_search": 0}
PROXY_RATES = {"input": 4.4, "cached_input": .22, "cache_write_5m": 5.5, "output": 22, "web_search": .01}


@pytest.mark.parametrize("judge", [False, True])
def test_default_native_research_and_judge_are_opus_high_without_bootstrap(tmp_path, monkeypatch, judge):
    forbid_client_tools(monkeypatch, "server research and judges must not bootstrap")
    seen = []
    def handler(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        seen.append(json.loads(request.content))
        return stream_response(turn(model=OPUS, searches=0 if judge else 2, tool=not judge))
    result = invoke(handler, FakeJob(tmp_path), judge=judge)  # tool_mode defaults to "server".
    assert seen[0]["model"] == OPUS
    assert seen[0]["output_config"]["effort"] == "high"
    assert not any(key in seen[0] for key in ("thinking", "system", "tool_choice"))
    assert seen[0]["messages"][0]["content"][0]["text"] == "Exact prompt"
    assert len(seen[0]["messages"][0]["content"]) == 1
    assert ("tools" in seen[0]) is not judge
    assert result["cost_usd"] == pytest.approx(.0111 if judge else .0311)  # Opus list rates plus two $0.01 searches.


@pytest.mark.parametrize("base", ["https://litellm.evolution.ml", "https://litellm.evolution.ml/",
                                  "https://litellm.evolution.ml/v1", "https://litellm.evolution.ml/v1/"])
def test_proxy_normalizes_base_uses_only_selected_key_and_skips_native_prices(tmp_path, monkeypatch, base):
    monkeypatch.setenv("LITELLM_API_KEY", "gateway-only-key")
    def handler(request):
        assert str(request.url) == "https://litellm.evolution.ml/v1/messages"
        assert request.headers["x-api-key"] == "gateway-only-key"
        assert "authorization" not in request.headers
        return stream_response(turn(model=OPUS))
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"api_base": base, "api_key_env": "LITELLM_API_KEY"})
    assert result["raw"]["transport"]["api_url"] == "https://litellm.evolution.ml/v1/messages"
    assert "gateway-only-key" not in json.dumps(job.state)
    # Without a matching price override, a gateway response is not priced at native rates.
    assert result["cost_usd"] is None
    assert result["raw"]["pricing"]["rates_by_model"][OPUS] is None
    assert result["raw"]["pricing"]["sources_by_model"][OPUS] == "unknown"


def test_missing_selected_key_never_falls_back_to_native_key(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    with pytest.raises(anthropic.ProviderError, match="LITELLM_API_KEY"):
        invoke(lambda request: pytest.fail("must not send using the native key"), FakeJob(tmp_path),
               {"api_base": "https://litellm.evolution.ml", "api_key_env": "LITELLM_API_KEY"})


@pytest.mark.parametrize("base", ["", "ftp://proxy.example", "https://user:secret@proxy.example",
                                  "https://proxy.example?key=secret", "https://proxy.example#secret"])
def test_invalid_or_secret_bearing_base_is_rejected_before_dispatch(tmp_path, base):
    job = FakeJob(tmp_path)
    with pytest.raises(ValueError, match="api_base"):
        invoke(lambda request: pytest.fail("invalid route must not dispatch"), job, {"api_base": base})
    assert not job.state.get("submission_unknown")


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504, 529])
def test_gateway_ambiguous_http_failure_is_never_reposted(tmp_path, status):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status, json={"error": "upstream outcome unknown"})
    job = FakeJob(tmp_path)
    settings = {"api_base": "https://proxy.example", "retry_attempts": 2,
                "retry_backoff_base_seconds": 0, "retry_backoff_max_seconds": 0}
    for _ in range(2):
        with pytest.raises(anthropic.ProviderError, match="unknown"):
            invoke(handler, job, settings)
    assert calls == ["https://proxy.example/v1/messages"]
    assert job.state["submission_unknown"] is True
    assert job.state["retry_events"][0]["retrying"] is False


def test_configured_pricing_is_frozen_in_receipt_and_replayed_without_credentials(tmp_path, monkeypatch):
    settings = {"api_base": "https://proxy.example", "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}}
    original = invoke(lambda request: stream_response(turn(model=OPUS)), FakeJob(tmp_path / "first"), settings)
    assert original["cost_usd"] == pytest.approx(.03221)
    assert original["raw"]["pricing"]["rates_by_model"][OPUS] == PROXY_RATES
    assert original["raw"]["pricing"]["sources_by_model"][OPUS] == "configured"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    changed = {"model_pricing": {OPUS: {k: v * 10 for k, v in PROXY_RATES.items()}}}
    job = FakeJob(tmp_path / "replay", {"raw": original["raw"]})
    replay = invoke(lambda request: pytest.fail("paid receipt must not dispatch"), job, changed)
    assert replay["cost_usd"] == pytest.approx(.03221)
    assert replay["raw"]["transport"] == original["raw"]["transport"]
    assert anthropic._account(replay["raw"]["turns"])[1] == pytest.approx(.03221)


def test_configured_prices_do_not_apply_to_an_unrecognized_response_alias(tmp_path):
    result = invoke(lambda request: stream_response(turn(model="bedrock/unpriced-opus-alias")), FakeJob(tmp_path),
                    {"model": OPUS, "model_pricing": {OPUS: PROXY_RATES}})
    assert result["cost_usd"] is None
    assert result["raw"]["pricing"]["rates_by_model"]["bedrock/unpriced-opus-alias"] is None


@pytest.mark.parametrize("rates", [{}, {**PROXY_RATES, "input": -1}, {**PROXY_RATES, "output": True},
                                    {**PROXY_RATES, "cached_input": float("nan")}])
def test_invalid_configured_prices_fail_before_paid_dispatch(tmp_path, rates):
    with pytest.raises(ValueError, match="model_pricing"):
        invoke(lambda request: pytest.fail("invalid prices must not dispatch"), FakeJob(tmp_path),
               {"model_pricing": {OPUS: rates}})


def test_configured_pricing_controls_continuation_and_abandoned_turn_accounting(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        return stream_response(turn(f"Round {len(calls)}", model=OPUS))
    settings = {"model": OPUS, "model_pricing": {OPUS: PROXY_RATES}, "budget_floor_usd": .07, "budget_usd": .1,
                "max_research_rounds": 4, "continuation_prompt": "{spent} {floor} {ceiling}"}
    result = invoke(handler, FakeJob(tmp_path / "rounds"), settings)
    # Two $0.03221 rounds stop near the floor; a third would overshoot the landing guard.
    assert len(calls) == 2
    assert result["cost_usd"] == pytest.approx(.06442)
    paused = dict(result["raw"]["turns"][0], stop_reason="pause_turn")
    job = FakeJob(tmp_path / "paused", {"raw": {"turns": [paused]}})
    recovered = invoke(lambda request: stream_response(turn(model=OPUS)), job, {"model": OPUS, "model_pricing": {OPUS: PROXY_RATES}})
    assert recovered["cost_usd"] == pytest.approx(.06442)


def test_ambiguous_later_gateway_round_preserves_answer_but_marks_total_unknown(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        return stream_response(turn("Paid earlier answer", model=OPUS)) if len(calls) == 1 else httpx.Response(502)
    settings = {"api_base": "https://proxy.example", "model": OPUS, "model_pricing": {OPUS: PROXY_RATES},
                "budget_floor_usd": 1, "max_research_rounds": 2,
                "continuation_prompt": "{spent} {floor} {ceiling}", "retry_attempts": 1}
    job = FakeJob(tmp_path)
    result = invoke(handler, job, settings)
    assert result["text"] == "Paid earlier answer"
    assert result["cost_usd"] is None
    assert job.state["submission_unknown"] is True
    assert len(calls) == 2


def client_turn(name="web_search", arguments=None, tool_id="tool-1", *, model=OPUS):
    events = turn(model=model, stop="tool_use", searches=0, tool=False, citation=False)
    return [events[0],
            {"type": "content_block_start", "index": 0, "content_block": {
                "type": "thinking", "thinking": "Find supporting evidence", "signature": "signed-block"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {
                "type": "tool_use", "id": tool_id, "name": name, "input": arguments or {"query": "evidence"}}},
            {"type": "content_block_stop", "index": 1}, *events[-2:]]


def bootstrap_evidence():
    return {"text": "Offline bootstrap source", "citations": [{"url": "https://example.org/bootstrap", "title": "Bootstrap"}]}


def install_client_tool(monkeypatch, execute, *, default_bootstrap=True):
    module = ModuleType("crest.providers.research_tools")
    async def wrapped(name, arguments, *, client=None):
        if default_bootstrap and name == "web_search" and arguments == {"query": "Exact prompt"}:
            return bootstrap_evidence()
        return await execute(name, arguments, client=client)
    module.execute_tool = wrapped
    monkeypatch.setitem(sys.modules, module.__name__, module)


def install_evidence_tool(monkeypatch, calls=None, *, text="Evidence"):
    """Every client tool call returns one public source; ``calls`` records the tool names."""
    async def execute(name, arguments, *, client=None):
        if calls is not None:
            calls.append(name)
        return {"text": text, "citations": [{"url": "https://example.org", "title": "Source"}]}
    install_client_tool(monkeypatch, execute)


def forbid_client_tools(monkeypatch, reason):
    """Any client tool call, including the free bootstrap search, fails the test."""
    async def execute(*args, **kwargs):
        pytest.fail(reason)
    install_client_tool(monkeypatch, execute, default_bootstrap=False)


def test_client_research_preserves_signed_blocks_collects_evidence_and_replays(tmp_path, monkeypatch):
    tool_calls, requests = [], []
    async def execute(name, arguments, *, client=None):
        tool_calls.append((name, arguments))
        return {"text": "Evidence from the source", "citations": [{"url": "https://example.org/evidence", "title": "Evidence"}]}
    install_client_tool(monkeypatch, execute)
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(client_turn() if len(requests) == 1 else answer("Grounded answer"))
    settings = {"tool_mode": "client", "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}}
    result = invoke(handler, FakeJob(tmp_path / "live"), settings)
    tools = requests[0]["tools"]
    assert [item["name"] for item in tools] == ["web_search", "web_fetch"]
    assert all("type" not in item and "input_schema" in item for item in tools)
    assert tools[0]["input_schema"]["required"] == ["query"]
    echoed = requests[1]["messages"]
    assert echoed[0]["content"][0]["text"] == "Exact prompt"
    assert "cache_control" not in echoed[0]["content"][-1]
    assert echoed[1]["content"][0] == {"type": "thinking", "thinking": "Find supporting evidence", "signature": "signed-block"}
    assert echoed[2]["content"][0]["type"] == "tool_result"
    assert echoed[2]["content"][0]["tool_use_id"] == "tool-1"
    assert echoed[2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert tool_calls == [("web_search", {"query": "evidence"})]
    assert result["citations"] == [*bootstrap_evidence()["citations"], {"url": "https://example.org/evidence", "title": "Evidence"}]
    assert result["usage"]["client_web_search_calls"] == 2
    assert result["usage"]["web_search_calls"] == 0
    assert result["cost_usd"] == pytest.approx(.02442)
    assert result["raw"]["tool_mode"] == "client"
    assert result["raw"]["pricing"]["rates_by_model"][OPUS]["web_search"] == 0
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    replay = invoke(lambda request: pytest.fail("completed client research must replay"),
                    FakeJob(tmp_path / "replay", {"raw": result["raw"]}), settings)
    assert replay["citations"] == result["citations"]
    assert replay["usage"]["client_web_search_calls"] == 2
    assert len(tool_calls) == 1


def test_client_mode_judge_stays_tool_free_and_needs_no_research_evidence(tmp_path, monkeypatch):
    forbid_client_tools(monkeypatch, "judges must not bootstrap even in client tool mode")
    def handler(request):
        payload = json.loads(request.content)
        assert not any(key in payload for key in ("tools", "system", "tool_choice"))
        assert payload["messages"][0]["content"][0]["text"] == "Exact prompt"
        assert len(payload["messages"][0]["content"]) == 1
        return stream_response(answer('{"reason":"A is stronger than B", "winner":"A"}'))
    assert invoke(handler, FakeJob(tmp_path), {"tool_mode": "client"}, judge=True)["text"]


def test_replayed_client_without_evidence_preserves_paid_receipt(tmp_path):
    original = invoke(lambda request: stream_response(answer()), FakeJob(tmp_path / "original"), {"tool_mode": "client"})
    original["raw"]["client_tools"] = []
    job = FakeJob(tmp_path / "replay", {"raw": original["raw"]})
    with pytest.raises(anthropic.ProviderError, match="evidence"):
        invoke(lambda request: pytest.fail("old completed turn must not resubmit"), job, {"tool_mode": "client"})
    assert job.state["provider_result"]["cost_usd"] == pytest.approx(.0111)


def test_client_tool_failure_is_explicit_and_not_evidence(tmp_path, monkeypatch):
    requests = []
    async def execute(name, arguments, *, client=None):
        raise RuntimeError("private-token-must-not-leak")
    install_client_tool(monkeypatch, execute)
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(client_turn() if len(requests) == 1 else answer())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"tool_mode": "client"})
    assert result["citations"] == bootstrap_evidence()["citations"]
    assert any("tools failed" in warning for warning in result["warnings"])
    assert requests[1]["messages"][-1]["content"][0]["is_error"] is True
    assert job.state["raw"]["client_tools"][-1]["status"] == "failed"
    assert "private-token-must-not-leak" not in json.dumps(job.state)


def test_client_search_limit_prevents_extra_execution(tmp_path, monkeypatch):
    tool_calls, requests = [], []
    async def execute(name, arguments, *, client=None):
        tool_calls.append(name)
        return {"text": "Source evidence", "citations": [{"url": "https://example.org/source", "title": "Source"}]}
    install_client_tool(monkeypatch, execute)
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(client_turn(tool_id=f"tool-{len(requests)}") if len(requests) < 3 else answer())
    result = invoke(handler, FakeJob(tmp_path), {"tool_mode": "client", "max_web_searches": 1})
    assert tool_calls == []  # Bootstrap consumed the only search slot.
    assert result["usage"]["client_web_search_calls"] == 1
    assert result["raw"]["client_tools"][0]["origin"] == "bootstrap"
    assert requests[2]["messages"][-1]["content"][0]["is_error"] is True
    assert result["raw"]["client_tools"][-1]["status"] == "limit_reached"


def client_turns_then_answer(requests, turns):
    """A handler that requests one client search per turn for ``turns`` turns, then answers."""
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(client_turn(tool_id=f"tool-{len(requests)}") if len(requests) <= turns else answer())
    return handler


def test_failed_client_searches_do_not_use_up_the_search_limit(tmp_path, monkeypatch):
    outcomes, executed = iter([False, False, True, True]), []
    async def execute(name, arguments, *, client=None):
        executed.append(next(outcomes))
        if not executed[-1]:
            raise RuntimeError("search backend down")
        return {"text": "Source evidence", "citations": [{"url": f"https://example.org/{len(executed)}", "title": "S"}]}
    install_client_tool(monkeypatch, execute)
    requests = []
    result = invoke(client_turns_then_answer(requests, 5), FakeJob(tmp_path), {"tool_mode": "client", "max_web_searches": 3})
    # Bootstrap plus two successful model searches reach the limit of three; the two failures do not count.
    assert executed == [False, False, True, True]
    assert [item["status"] for item in result["raw"]["client_tools"]] == [
        "completed", "failed", "failed", "completed", "completed", "limit_reached"]


def test_failed_client_searches_stop_at_twice_the_search_limit(tmp_path, monkeypatch):
    executed = []
    async def execute(name, arguments, *, client=None):
        executed.append(name)
        raise RuntimeError("search backend down")
    install_client_tool(monkeypatch, execute)
    requests = []
    result = invoke(client_turns_then_answer(requests, 5), FakeJob(tmp_path), {"tool_mode": "client", "max_web_searches": 2})
    assert executed == ["web_search"] * 3  # Bootstrap plus three failures make four attempts, twice the limit.
    assert [item["status"] for item in result["raw"]["client_tools"]] == [
        "completed", "failed", "failed", "failed", "limit_reached", "limit_reached"]


def test_client_tool_errors_ask_the_model_not_to_mention_them(tmp_path, monkeypatch):
    async def execute(name, arguments, *, client=None):
        raise RuntimeError("search backend down")
    install_client_tool(monkeypatch, execute)
    requests = []
    invoke(client_turns_then_answer(requests, 4), FakeJob(tmp_path), {"tool_mode": "client", "max_web_searches": 2})
    failed, limited = (requests[i]["messages"][-1]["content"][0] for i in (1, 4))
    assert failed["is_error"] and limited["is_error"]
    assert "research tool failed" in failed["content"] and "No more web_search calls" in limited["content"]
    for result in (failed, limited):
        assert "Do not mention tool limits, tool errors or the research process" in result["content"]


@pytest.mark.parametrize("searches, posts", [(1, 1), (2, 2)])
def test_client_follow_up_rounds_need_search_capacity(tmp_path, monkeypatch, searches, posts):
    install_evidence_tool(monkeypatch)
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(answer(f"Round {len(requests)}"))
    settings = {"tool_mode": "client", "max_web_searches": searches, "max_research_rounds": 2,
                "continuation_prompt": "Continue {spent} {ceiling}"}
    result = invoke(handler, FakeJob(tmp_path), settings)
    # The bootstrap uses one search; a follow-up round only runs while another search remains.
    assert len(requests) == posts and result["text"] == f"Round {posts}"
    assert any("search limit was used up" in warning for warning in result["warnings"]) == (posts == 1)


def test_client_follow_up_round_asks_for_the_answer_only(tmp_path, monkeypatch):
    install_evidence_tool(monkeypatch)
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(answer(f"Round {len(requests)}"))
    settings = {"tool_mode": "client", "max_research_rounds": 2, "continuation_prompt": "Continue {spent} {ceiling}"}
    invoke(handler, FakeJob(tmp_path), settings)
    text = requests[1]["messages"][-1]["content"][0]["text"]
    assert text.startswith("Continue 0.0") and text.endswith(anthropic.ANSWER_ONLY_NOTE)
    assert "Do not mention this round, earlier versions" in anthropic.ANSWER_ONLY_NOTE


def test_client_citations_are_the_sources_the_answer_cites_or_fetched(tmp_path, monkeypatch):
    async def execute(name, arguments, *, client=None):
        if name == "web_fetch":
            return {"text": "Page", "citations": [{"url": "https://example.org/read", "title": "Read"}]}
        return {"text": "Hits", "citations": [{"url": "https://example.org/cited", "title": "Cited"},
                                              {"url": "https://example.org/unused", "title": "Unused"}]}
    install_client_tool(monkeypatch, execute)
    requests = []
    def handler(request):
        requests.append(1)
        if len(requests) == 1:
            return stream_response(client_turn())
        if len(requests) == 2:
            return stream_response(client_turn("web_fetch", {"url": "https://example.org/read"}, "tool-2"))
        return stream_response(answer("Grounded in [Cited](https://example.org/cited)."))
    result = invoke(handler, FakeJob(tmp_path), {"tool_mode": "client"})
    # Uncited search hits (and the uncited bootstrap source) are not the answer's sources.
    assert result["citations"] == [{"url": "https://example.org/cited", "title": "Cited"},
                                   {"url": "https://example.org/read", "title": "Read"}]
    assert not any("cites no retrieved" in warning for warning in result["warnings"])


def test_client_answer_citing_nothing_lists_every_retrieved_source_with_a_warning(tmp_path, monkeypatch):
    install_evidence_tool(monkeypatch)
    requests = []
    def handler(request):
        requests.append(1)
        return stream_response(client_turn() if len(requests) == 1 else answer("No links here."))
    result = invoke(handler, FakeJob(tmp_path), {"tool_mode": "client"})
    assert result["citations"] == [*bootstrap_evidence()["citations"], {"url": "https://example.org", "title": "Source"}]
    assert any("cites no retrieved source" in warning for warning in result["warnings"])


def test_client_tool_turn_limit_preserves_billed_usage(tmp_path, monkeypatch):
    tool_calls = []
    install_evidence_tool(monkeypatch, tool_calls)
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="max_continuations"):
        invoke(lambda request: stream_response(client_turn()), job, {"tool_mode": "client", "max_continuations": 1})
    assert tool_calls == ["web_search"]
    assert job.state["provider_result"]["usage"]["turns"] == 2


class ToolCrash(BaseException):
    """Stands in for a process death while a client tool runs; nothing in the adapter catches it."""


def crash_during_client_tool(monkeypatch, tmp_path, handler, settings, state=None):
    async def execute(name, arguments, *, client=None):
        raise ToolCrash
    install_client_tool(monkeypatch, execute)
    job = FakeJob(tmp_path, dict(state or {}))
    with pytest.raises(ToolCrash):
        invoke(handler, job, settings)
    assert job.state["raw"]["turns"][-1]["stop_reason"] == "tool_use"
    return job


CLIENT_TURN_COST = .0111  # client_turn(): (1000*4 + 500*.4 + 200*5 + 300*20) / 1e6 at Opus rates


def test_crash_during_client_tools_restarts_once_and_keeps_the_abandoned_cost(tmp_path, monkeypatch):
    settings = {"tool_mode": "client"}
    job = crash_during_client_tool(monkeypatch, tmp_path, lambda request: stream_response(client_turn()), settings)
    install_client_tool(monkeypatch, lambda *args, **kwargs: pytest.fail("restart answers without tools"))
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(answer("Restarted answer"))
    result = invoke(handler, job, settings)
    assert len(requests) == 1 and requests[0]["messages"][0]["role"] == "user" and len(requests[0]["messages"]) == 1
    assert result["text"] == "Restarted answer"
    abandoned = job.state["interrupted_attempts"]
    assert len(abandoned) == 1 and abandoned[0]["cost_usd"] == pytest.approx(CLIENT_TURN_COST)
    assert result["cost_usd"] == pytest.approx(2 * CLIENT_TURN_COST)
    assert job.state["consecutive_interruptions"] == 0


def test_crash_during_client_tools_after_a_finished_round_keeps_that_answer(tmp_path, monkeypatch):
    settings = {"tool_mode": "client", "budget_floor_usd": 3.9, "max_research_rounds": 2,
                "continuation_prompt": "{spent} {floor} {ceiling}"}
    answers = iter([answer("Round 1 answer"), client_turn()])
    job = crash_during_client_tool(monkeypatch, tmp_path, lambda request: stream_response(next(answers)), settings)
    result = invoke(lambda request: pytest.fail("a finished paid round must not be paid for again"), job, settings)
    assert result["text"] == "Round 1 answer" and "interrupted_attempts" not in job.state


def test_repeated_crashes_during_client_tools_stop_at_the_retry_streak(tmp_path, monkeypatch):
    settings = {"tool_mode": "client", "retry_attempts": 2}
    posts = []
    def handler(request):
        posts.append(1)
        return stream_response(client_turn())
    job = crash_during_client_tool(monkeypatch, tmp_path, handler, settings)
    with pytest.raises(ToolCrash):  # The first restart is allowed and crashes in the same place.
        invoke(handler, job, settings)
    assert len(posts) == 2 and job.state["consecutive_interruptions"] == 1
    for _ in range(2):
        with pytest.raises(anthropic.ProviderError, match="interrupted 2 times"):
            invoke(handler, job, settings)
    assert len(posts) == 2 and len(job.state["interrupted_attempts"]) == 2 and job.state["raw"] is None


def test_client_budget_reservation_prevents_unaffordable_first_turn(tmp_path, monkeypatch):
    async def execute(name, arguments, *, client=None):
        pytest.fail("budget cannot cover the first model turn")
    install_client_tool(monkeypatch, execute)
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="remaining budget"):
        invoke(lambda request: pytest.fail("unaffordable model turn must not dispatch"), job,
               {"tool_mode": "client", "budget_usd": .001})
    assert job.state["provider_result"]["cost_usd"] == 0
    assert not job.state.get("submission_unknown")


def test_client_helper_error_flag_is_not_accepted_as_evidence(tmp_path, monkeypatch):
    requests = []
    async def execute(name, arguments, *, client=None):
        return {"text": "Search unavailable", "is_error": True,
                "citations": [{"url": "https://example.org/not-evidence", "title": "Not evidence"}]}
    install_client_tool(monkeypatch, execute)
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(client_turn() if len(requests) == 1 else answer())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"tool_mode": "client"})
    assert result["citations"] == bootstrap_evidence()["citations"]
    assert requests[1]["messages"][-1]["content"][0]["is_error"] is True
    assert job.state["raw"]["client_tools"][-1]["status"] == "failed"
    assert job.state["raw"]["client_tools"][-1]["error"] == "Search unavailable"


def test_fragmented_thinking_signature_is_preserved_for_client_continuation(tmp_path, monkeypatch):
    requests = []
    install_evidence_tool(monkeypatch)
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            events = client_turn()
            events[1]["content_block"]["signature"] = ""
            events[2:2] = [{"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": part}}
                           for part in ("signed-", "block")]
            return stream_response(events)
        return stream_response(answer())
    invoke(handler, FakeJob(tmp_path), {"tool_mode": "client"})
    assert requests[1]["messages"][1]["content"][0]["signature"] == "signed-block"


def test_client_followup_transport_failure_keeps_a_normalized_paid_receipt(tmp_path, monkeypatch):
    requests = []
    install_evidence_tool(monkeypatch)
    def handler(request):
        requests.append(1)
        if len(requests) == 1:
            return stream_response(client_turn())
        raise httpx.ReadTimeout("response unavailable")
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="unknown"):
        invoke(handler, job, {"tool_mode": "client"})
    assert job.state["provider_result"]["cost_usd"] is None
    assert job.state["provider_result"]["usage"]["turns"] == 1
    assert job.state["provider_result"]["usage"]["client_web_search_calls"] == 2


@pytest.mark.parametrize("name,arguments,enabled", [
    ("web_fetch", {"url": "https://example.org"}, True),
    ("web_fetch", {"url": "https://example.org"}, False),
    ("unknown_tool", {"query": "unused"}, True),
])
def test_client_fetch_and_disabled_tools_respect_configuration(tmp_path, monkeypatch, name, arguments, enabled):
    calls, requests = [], []
    async def execute(tool_name, tool_arguments, *, client=None):
        calls.append((tool_name, tool_arguments))
        return {"text": "Fetched evidence", "citations": [{"url": "https://example.org", "title": "Source"}]}
    install_client_tool(monkeypatch, execute)
    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(client_turn(name, arguments) if len(requests) == 1 else answer())
    result = invoke(handler, FakeJob(tmp_path), {"tool_mode": "client", "web_fetch": enabled})
    if name == "web_fetch" and enabled:
        assert calls == [(name, arguments)]
        assert result["usage"]["client_web_fetch_calls"] == 1
    else:
        assert result["citations"] == bootstrap_evidence()["citations"]
        assert calls == []
        assert requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_malformed_client_tool_stop_preserves_paid_receipt(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="tool_use blocks"):
        invoke(lambda request: stream_response(answer(stop="tool_use")), job, {"tool_mode": "client"})
    assert job.state["provider_result"]["cost_usd"] == pytest.approx(.0111)


@pytest.mark.parametrize("tool_mode", ["server", "client"])
def test_gateway_tool_rejection_never_switches_route_or_tool_mode(tmp_path, tool_mode):
    requests = []
    def handler(request):
        requests.append((str(request.url), json.loads(request.content)))
        return httpx.Response(400, json={"error": "tool unsupported"})
    with pytest.raises(anthropic.ProviderError, match="HTTP 400"):
        invoke(handler, FakeJob(tmp_path), {"api_base": "https://proxy.example", "tool_mode": tool_mode,
                                          "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}})
    assert len(requests) == 1
    assert requests[0][0] == "https://proxy.example/v1/messages"
    assert ("input_schema" in requests[0][1]["tools"][0]) is (tool_mode == "client")


@pytest.mark.parametrize("kind", ["disconnect", "empty", "truncated", "early_error", "late_error"])
@pytest.mark.parametrize("judge", [False, True])
def test_ambiguous_gateway_stream_never_retries_or_resubmits(tmp_path, kind, judge):
    calls = []
    events = answer()
    def handler(request):
        calls.append(1)
        if len(calls) > 1:
            return stream_response(events)
        if kind == "disconnect":
            return httpx.Response(200, stream=BrokenStream(sse(events[:2])))
        if kind == "empty":
            return httpx.Response(200, content=b"")
        if kind == "truncated":
            return stream_response(events[:2])
        error = {"type": "error", "error": {"type": "api_error", "message": "upstream failed"}}
        return stream_response(events[:1 if kind == "early_error" else 2] + [error])
    job = FakeJob(tmp_path)
    settings = {"api_base": "https://proxy.example", "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}, "retry_attempts": 3}
    for _ in range(2):
        with pytest.raises(anthropic.ProviderError):
            invoke(handler, job, settings, judge=judge)
    assert calls == [1]
    assert job.state["submission_unknown"] is True
    assert job.state["unresolved_submission"] is True
    assert len(job.state["interrupted_attempts"]) == 1
    assert job.state["interrupted_attempts"][0]["cost_usd"] is None


@pytest.mark.parametrize("base,cap", [("https://api.anthropic.com", "hard"),
                                      ("https://proxy.example", "hard"), ("https://proxy.example", "soft")])
def test_unknown_client_turn_cost_blocks_another_paid_turn(tmp_path, monkeypatch, base, cap):
    calls, tool_calls = [], []
    install_evidence_tool(monkeypatch, tool_calls)
    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            events = client_turn(tool_id=f"tool-{len(calls)}")
            if len(calls) == 2:
                events[-2].pop("usage")  # Paid, but its final output usage is unknown.
            return stream_response(events)
        return stream_response(answer())
    job = FakeJob(tmp_path)
    settings = {"api_base": base, "tool_mode": "client", "budget_cap": cap, "budget_usd": 4,
                "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}}
    with pytest.raises(anthropic.ProviderError, match="unknown.*cost|cost.*unknown"):
        invoke(handler, job, settings)
    assert calls == [1, 1]
    assert tool_calls == ["web_search"]
    assert job.state["provider_result"]["cost_usd"] is None
    assert job.state["provider_result"]["known_cost_usd"] == pytest.approx(.01221)
    assert job.state["provider_result"]["estimate_incomplete"] is True


def test_unknown_hard_client_history_cannot_restart_paid_research(tmp_path):
    job = FakeJob(tmp_path, {"interrupted_attempts": [{"cost_usd": None}], "consecutive_interruptions": 1})
    with pytest.raises(anthropic.ProviderError, match="unknown.*cost|cost.*unknown"):
        invoke(lambda request: pytest.fail("unknown exposure cannot fund another paid turn"), job,
               {"tool_mode": "client", "budget_cap": "hard", "retry_attempts": 4})
    assert job.state["provider_result"]["cost_usd"] is None


def test_crash_after_new_post_replays_prior_answer_with_unknown_total(tmp_path, monkeypatch):
    class Crash(BaseException):
        pass
    install_evidence_tool(monkeypatch)
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 3:
            raise Crash()
        return stream_response(client_turn() if len(calls) == 1 else answer("Paid answer"))
    settings = {"api_base": "https://proxy.example", "tool_mode": "client", "model": OPUS, "model_pricing": {OPUS: PROXY_RATES},
                "budget_floor_usd": .1, "max_research_rounds": 6, "continuation_prompt": "{spent} {floor} {ceiling}"}
    job = FakeJob(tmp_path)
    with pytest.raises(Crash):
        invoke(handler, job, settings)
    assert len(calls) == 3 and job.state["submission_unknown"] is True
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = invoke(lambda request: pytest.fail("must not dispatch on replay"), job, settings)
    assert result["text"] == "Paid answer"
    assert result["cost_usd"] is None
    assert result["estimate_incomplete"] is True
    assert result["known_cost_usd"] == pytest.approx(.02442)
    assert result["raw"]["unresolved_submission"] is True


def test_known_subtotal_overrun_is_visible_even_when_total_cost_is_unknown(tmp_path):
    original = invoke(lambda request: stream_response(answer()), FakeJob(tmp_path / "first"))
    raw = copy.deepcopy(original["raw"])
    missing = copy.deepcopy(raw["turns"][0])
    missing.pop("_usage_final")
    expensive = copy.deepcopy(raw["turns"][0])
    expensive["usage"]["output_tokens"] = 300000
    raw["turns"] = [missing, expensive]
    result = invoke(lambda request: pytest.fail("saved answer should replay"), FakeJob(tmp_path / "replay", {"raw": raw}),
                    {"budget_usd": 4, "budget_cap": "hard"})
    assert result["cost_usd"] is None
    assert result["known_cost_usd"] == pytest.approx(6.0051)
    assert result["budget_exceeded"] is True
    assert result["usage"]["budget_exceeded"] is True
    assert any("known" in warning.lower() and "exceed" in warning.lower() for warning in result["warnings"])


@pytest.mark.parametrize("prompt,query", [
    ("Header\n### QUERY\n\nWhich five-tone orthography?\n\n### YOUR TASK\nAnswer with sources", "Which five-tone orthography?"),
    ("A long fallback " * 200, ("A long fallback " * 200).strip()[:2000]),
], ids=["standard-query", "bounded-fallback"])
def test_bootstrap_precedes_first_paid_post_and_supplies_real_evidence(tmp_path, monkeypatch, prompt, query):
    order, requests = [], []
    job = FakeJob(tmp_path)
    async def execute(name, arguments, *, client=None):
        assert name == "web_search" and arguments == {"query": query}
        assert client is None
        order.append("free search")
        return {"text": "Source says: inspect the alphabet", "citations": [{"url": "https://example.org/alphabet", "title": "Alphabet"}]}
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    def handler(request):
        order.append("paid post")
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["messages"][0]["content"][0]["text"] == prompt
        evidence = payload["messages"][0]["content"][1]["text"]
        assert "untrusted" in evidence.lower() and "https://example.org/alphabet" in evidence
        assert "Source says: inspect the alphabet" in evidence
        assert all(message["role"] == "user" for message in payload["messages"])
        assert "tool_choice" not in payload and "thinking" not in payload and "system" not in payload
        assert payload["output_config"]["effort"] == "high" and payload["max_tokens"] == 64000
        assert job.state["client_tool_results"][0]["origin"] == "bootstrap"
        assert "tool_use_id" not in job.state["client_tool_results"][0]
        return stream_response(answer("Evidence-grounded answer", model=SONNET))
    result = invoke(handler, job, {"tool_mode": "client", "max_output_tokens": 64000, "answer_word_limit": None}, prompt=prompt)
    assert order == ["free search", "paid post"]
    assert result["citations"] == [{"url": "https://example.org/alphabet", "title": "Alphabet"}]
    assert result["usage"]["client_web_search_calls"] == 1
    assert result["cost_usd"] == pytest.approx(.00555)
    invoke(lambda request: pytest.fail("completed bootstrap answer must replay"), job, {"tool_mode": "client"}, prompt=prompt)
    assert order == ["free search", "paid post"]


@pytest.mark.parametrize("failure", ["empty", "no_sources", "error", "is_error", "exception", "invalid_url"])
def test_bootstrap_failure_has_zero_paid_posts_and_truthful_receipt(tmp_path, monkeypatch, failure):
    searches = []
    async def execute(name, arguments, *, client=None):
        searches.append(arguments)
        if failure == "exception":
            raise RuntimeError("secret-must-not-leak")
        result = bootstrap_evidence()
        if failure == "empty":
            result["text"] = ""
        elif failure == "no_sources":
            result["citations"] = []
        elif failure == "invalid_url":
            result["citations"][0]["url"] = "javascript:bad()"
        else:
            result[failure] = True
        return result
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    job = FakeJob(tmp_path)
    for _ in range(2):
        with pytest.raises(anthropic.ProviderError, match="bootstrap.*evidence"):
            invoke(lambda request: pytest.fail("no source evidence means zero model calls"), job, {"tool_mode": "client"})
    # Each run retries the free search; a resumed run searches again instead of replaying the failure.
    attempts = 2 * anthropic.BOOTSTRAP_ATTEMPTS
    assert len(searches) == attempts
    receipt = job.state["provider_result"]
    assert receipt["cost_usd"] == 0 and receipt["usage"]["client_web_search_calls"] == attempts
    assert [item["status"] for item in receipt["raw"]["client_tools"]] == ["failed"] * attempts
    assert not job.state.get("submission_unknown")
    assert "secret-must-not-leak" not in json.dumps(job.state)


def test_transient_bootstrap_failure_recovers_within_one_run(tmp_path, monkeypatch):
    searches, posts = [], []
    async def execute(name, arguments, *, client=None):
        searches.append(arguments)
        if len(searches) == 1:
            raise RuntimeError("search backend hiccup")
        return bootstrap_evidence()
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    def handler(request):
        posts.append(1)
        return stream_response(answer())
    job = FakeJob(tmp_path)
    result = invoke(handler, job, {"tool_mode": "client"})
    assert len(searches) == 2 and posts == [1]
    assert [item["status"] for item in result["raw"]["client_tools"]] == ["failed", "completed"]
    assert result["usage"]["client_web_search_calls"] == 2


def test_failed_bootstrap_is_searched_again_on_resume(tmp_path, monkeypatch):
    searches, posts = [], []
    outage = [True]
    async def execute(name, arguments, *, client=None):
        searches.append(arguments)
        if outage[0]:
            return {"text": "", "citations": []}
        return bootstrap_evidence()
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    def handler(request):
        posts.append(1)
        return stream_response(answer())
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="bootstrap.*evidence"):
        invoke(handler, job, {"tool_mode": "client"})
    assert posts == [] and len(searches) == anthropic.BOOTSTRAP_ATTEMPTS
    outage[0] = False
    result = invoke(handler, job, {"tool_mode": "client"})
    assert posts == [1] and len(searches) == anthropic.BOOTSTRAP_ATTEMPTS + 1
    statuses = [item["status"] for item in result["raw"]["client_tools"]]
    assert statuses == ["failed"] * anthropic.BOOTSTRAP_ATTEMPTS + ["completed"]


def test_bootstrap_retries_stop_at_search_limit(tmp_path, monkeypatch):
    searches = []
    async def execute(name, arguments, *, client=None):
        searches.append(arguments)
        raise RuntimeError("down")
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    job = FakeJob(tmp_path)
    for _ in range(2):
        with pytest.raises(anthropic.ProviderError, match="bootstrap.*evidence"):
            invoke(lambda request: pytest.fail("not grounded"), job, {"tool_mode": "client", "max_web_searches": 2})
    assert len(searches) == 2
    assert job.state["client_tool_results"][-1]["status"] == "limit_reached"


def test_bootstrap_respects_zero_search_limit(tmp_path, monkeypatch):
    forbid_client_tools(monkeypatch, "zero search limit prohibits even free bootstrap")
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="bootstrap.*evidence"):
        invoke(lambda request: pytest.fail("no bootstrap means no paid call"), job, {"tool_mode": "client", "max_web_searches": 0})
    assert job.state["provider_result"]["usage"]["client_web_search_calls"] == 0


# Hard-capped client research through the priced Opus gateway; tests copy and extend it.
HARD_GATEWAY_CLIENT = {"api_base": "https://proxy.example", "tool_mode": "client", "budget_cap": "hard", "budget_usd": 4,
                       "max_output_tokens": 64000, "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}}


def test_hard_client_reserves_input_cache_write_and_maximum_output_before_each_post(tmp_path, monkeypatch):
    requests = []
    job = FakeJob(tmp_path)
    install_evidence_tool(monkeypatch)
    def handler(request):
        requests.append(json.loads(request.content))
        reservation = job.state["request_budget"]
        assert reservation["output_usd"] == pytest.approx(1.408)
        assert reservation["input_rate_per_million"] == 5.5
        assert reservation["input_token_bound"] > len(request.content)
        assert reservation["reserved_usd"] <= reservation["remaining_usd"]
        assert reservation["known_spent_usd"] == pytest.approx(0 if len(requests) == 1 else .01221)
        return stream_response(client_turn() if len(requests) == 1 else answer())
    result = invoke(handler, job, dict(HARD_GATEWAY_CLIENT))
    assert len(requests) == 2 and result["cost_usd"] == pytest.approx(.02442)
    assert result["raw"]["turns"][0]["_request_budget"]["reserved_usd"] > 1.408


def test_hard_client_shrinks_output_to_include_prior_paid_attempts(tmp_path):
    job = FakeJob(tmp_path, {"interrupted_attempts": [{"cost_usd": 3.0}]})
    def handler(request):
        payload = json.loads(request.content)
        assert 1024 <= payload["max_tokens"] < 45000
        reserve = job.state["request_budget"]
        assert reserve["remaining_usd"] == 1 and reserve["reserved_usd"] <= 1
        return stream_response(answer())
    result = invoke(handler, job, dict(HARD_GATEWAY_CLIENT))
    assert result["cost_usd"] == pytest.approx(3.01221)
    assert not job.state.get("budget_stop")


def test_hard_client_shrinks_again_for_utf8_tool_result_growth(tmp_path, monkeypatch):
    calls, bounds = [], []
    install_evidence_tool(monkeypatch, text="界" * 16000)
    job = FakeJob(tmp_path, {"interrupted_attempts": [{"cost_usd": 2.4}]})
    def handler(request):
        calls.append(json.loads(request.content))
        bounds.append(dict(job.state["request_budget"]))
        assert bounds[-1]["reserved_usd"] <= bounds[-1]["remaining_usd"]
        return stream_response(client_turn() if len(calls) == 1 else answer())
    result = invoke(handler, job, dict(HARD_GATEWAY_CLIENT))
    assert len(calls) == 2 and calls[1]["max_tokens"] < calls[0]["max_tokens"]
    assert bounds[1]["input_token_bound"] > 48000
    assert result["cost_usd"] == pytest.approx(2.42442)


def test_budget_reservation_keeps_last_complete_answer_when_context_cannot_fit(tmp_path):
    calls = []
    job = FakeJob(tmp_path)
    def handler(request):
        calls.append(json.loads(request.content))
        assert len(calls) == 1, "large next-round context cannot fit remaining funds"
        return stream_response(answer("Paid answer"))
    result = invoke(handler, job, {**HARD_GATEWAY_CLIENT, "budget_usd": .2, "budget_floor_usd": .1, "max_research_rounds": 6,
                                  "continuation_prompt": "界" * 16000})
    assert result["text"] == "Paid answer" and result["cost_usd"] == pytest.approx(.01221)
    assert result["raw"]["budget_stop"]["input_usd"] > result["raw"]["budget_stop"]["remaining_usd"]
    assert any("reservation" in warning.lower() for warning in result["warnings"])


def test_hard_client_without_gateway_prices_does_not_dispatch(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="pricing.*unknown|unknown.*pricing"):
        invoke(lambda request: pytest.fail("unknown pricing prohibits paid call"), job,
               {"api_base": "https://proxy.example", "tool_mode": "client"})
    assert job.state["provider_result"]["cost_usd"] == 0


def test_bootstrap_checkpoint_reuses_free_search_after_predispatch_crash(tmp_path, monkeypatch):
    class Crash(BaseException):
        pass
    searches = []
    async def execute(name, arguments, *, client=None):
        searches.append(arguments)
        return bootstrap_evidence()
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    job = FakeJob(tmp_path)
    original_save = job.save
    def save(**changes):
        original_save(**changes)
        if "request_budget" in changes:
            raise Crash()
    monkeypatch.setattr(job, "save", save)
    with pytest.raises(Crash):
        invoke(lambda request: pytest.fail("checkpoint crashed before model call"), job, {"tool_mode": "client"})
    monkeypatch.setattr(job, "save", original_save)
    result = invoke(lambda request: stream_response(answer()), job, {"tool_mode": "client"})
    assert len(searches) == 1 and result["usage"]["client_web_search_calls"] == 1
    assert result["citations"] == bootstrap_evidence()["citations"]


def test_failed_thinking_only_receipt_is_not_reposted_after_widening_output(tmp_path):
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="max_tokens"):
        invoke(lambda request: stream_response(answer(stop="max_tokens")), job, {"tool_mode": "client", "max_output_tokens": 16384})
    saved_cost = job.state["provider_result"]["cost_usd"]
    with pytest.raises(anthropic.ProviderError, match="max_tokens"):
        invoke(lambda request: pytest.fail("changed output limit must not silently repurchase a failed cached turn"),
               job, {"tool_mode": "client", "max_output_tokens": 64000})
    assert job.state["provider_result"]["cost_usd"] == saved_cost


@pytest.mark.parametrize("output", ["omitted", None, -1, True])
def test_nonempty_terminal_usage_without_valid_output_blocks_second_paid_turn(tmp_path, output):
    calls = []
    def handler(request):
        calls.append(1)
        assert len(calls) == 1, "message_start output placeholder is not final billable usage"
        events = client_turn()
        events[-2]["usage"] = {"input_tokens": 1000}
        if output != "omitted":
            events[-2]["usage"]["output_tokens"] = output
        return stream_response(events)
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="cost.*unknown"):
        invoke(handler, job, {"api_base": "https://proxy.example", "tool_mode": "client", "budget_usd": 4,
                             "max_output_tokens": 64000, "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}})
    assert calls == [1]
    assert job.state["provider_result"]["cost_usd"] is None
    assert job.state["provider_result"]["estimate_incomplete"] is True
    assert job.state["provider_result"]["usage"]["output_tokens"] is None


def test_cancelled_free_bootstrap_can_recover_without_repeating_a_paid_turn(tmp_path, monkeypatch):
    searches, posts = [], []
    async def execute(name, arguments, *, client=None):
        searches.append(arguments)
        if len(searches) == 1:
            raise asyncio.CancelledError()
        return bootstrap_evidence()
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    def handler(request):
        posts.append(1)
        return stream_response(answer())
    job = FakeJob(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        invoke(handler, job, {"tool_mode": "client"})
    assert posts == [] and not job.state.get("submission_unknown")
    result = invoke(handler, job, {"tool_mode": "client"})
    assert len(searches) == 2 and posts == [1]
    records = result["raw"]["client_tools"]
    assert [item["status"] for item in records] == ["interrupted", "completed"]
    assert all(item["origin"] == "bootstrap" and "tool_use_id" not in item for item in records)
    assert result["usage"]["client_web_search_calls"] == 2
    assert result["cost_usd"] == pytest.approx(.0111)


def test_cancelled_bootstrap_recovery_still_honors_search_limit(tmp_path, monkeypatch):
    calls = []
    async def execute(name, arguments, *, client=None):
        calls.append(1)
        raise asyncio.CancelledError()
    install_client_tool(monkeypatch, execute, default_bootstrap=False)
    job = FakeJob(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        invoke(lambda request: pytest.fail("not grounded"), job, {"tool_mode": "client", "max_web_searches": 1})
    with pytest.raises(anthropic.ProviderError, match="bootstrap.*evidence"):
        invoke(lambda request: pytest.fail("not grounded"), job, {"tool_mode": "client", "max_web_searches": 1})
    assert calls == [1]
    assert job.state["provider_result"]["cost_usd"] == 0
    assert job.state["client_tool_results"][-1]["status"] == "limit_reached"


def test_paid_success_clears_submission_guard_only_with_durable_message(tmp_path, monkeypatch):
    class Crash(BaseException):
        pass
    job, calls = FakeJob(tmp_path), []
    original_save = job.save
    def save(**changes):
        original_save(**changes)
        if changes.get("submission_unknown") is False:
            raise Crash()
    monkeypatch.setattr(job, "save", save)
    def handler(request):
        calls.append(1)
        return stream_response(answer("Durable answer"))
    settings = {"api_base": "https://proxy.example", "tool_mode": "client", "model": OPUS, "model_pricing": {OPUS: PROXY_RATES}}
    with pytest.raises(Crash):
        invoke(handler, job, settings)
    monkeypatch.setattr(job, "save", original_save)
    result = invoke(lambda request: pytest.fail("success must be durable before permitting resubmission"), job, settings)
    assert calls == [1] and result["text"] == "Durable answer"
    assert result["cost_usd"] == pytest.approx(.01221)


@pytest.mark.parametrize("stage", ["headers", "error_body", "sse"])
def test_absolute_deadline_bounds_entire_loopback_http_exchange(tmp_path, stage):
    """Real sockets: trickled HTTP errors must not outlive the operation deadline."""
    job, posts = FakeJob(tmp_path), []
    async def run():
        tasks = []
        events = answer(model=SONNET)
        async def serve(reader, writer):
            tasks.append(asyncio.current_task())
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n") if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                posts.append(1)
                if stage == "headers":
                    await asyncio.sleep(.25)
                if stage == "error_body":
                    body = b'{"error":"rejected"}'
                    writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n")
                    for byte in body:
                        writer.write(bytes([byte]))
                        await writer.drain()
                        await asyncio.sleep(.02)
                else:
                    body = sse(events)
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n")
                    if stage == "sse":
                        head = sse(events[:1])
                        writer.write(head)
                        await writer.drain()
                        await asyncio.sleep(.25)
                        writer.write(body[len(head):])
                    else:
                        writer.write(body)
                    await writer.drain()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass
        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        settings = {"api_base": f"http://127.0.0.1:{port}", "timeout_seconds": .05, "retry_attempts": 3}
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                started = asyncio.get_running_loop().time()
                failure = None
                try:
                    await anthropic.generate("Offline loopback request", settings, job, client=client)
                except (TimeoutError, anthropic.ProviderError) as exc:
                    failure = exc
                elapsed = asyncio.get_running_loop().time() - started
            assert elapsed < .15, f"{stage} exceeded .05s deadline: {elapsed:.3f}s"
            assert failure is not None
        finally:
            # Cancel stalled handlers first: wait_closed() waits for open connections.
            server.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await server.wait_closed()
        return settings
    settings = asyncio.run(run())
    assert posts == [1]
    assert job.state["submission_unknown"] is True
    assert job.state["unresolved_submission"] is True
    assert job.state["provider_result"]["cost_usd"] is None
    with pytest.raises(anthropic.ProviderError, match="submission status unknown"):
        invoke(lambda request: pytest.fail("ambiguous deadline expiry must not repost"), job, settings)


def test_absolute_deadline_after_explicit_429_does_not_invent_unknown_billing(tmp_path):
    class SlowCooldown:
        async def wait_ready(self):
            pass
        async def observe_headers(self, headers):
            pass
        async def rate_limited(self, delay):
            await asyncio.sleep(.25)
    job = FakeJob(tmp_path)
    job.rate_controller = SlowCooldown()
    calls = []
    async def run():
        def handler(request):
            calls.append(1)
            return httpx.Response(429, json={"error": "rate limited"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            started = asyncio.get_running_loop().time()
            with pytest.raises((TimeoutError, anthropic.ProviderError)):
                await anthropic.generate("Offline request", {"api_base": "https://proxy.example", "timeout_seconds": .05}, job, client=client)
            elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < .15, f"rejection cooldown exceeded .05s deadline: {elapsed:.3f}s"
    asyncio.run(run())
    assert calls == [1] and job.state["submission_unknown"] is False
    assert not job.state.get("unresolved_submission")
    assert job.state["provider_result"]["cost_usd"] == 0


@pytest.mark.parametrize("gateway,prior", [(False, 0), (False, 3.5), (True, 0), (True, 3.5)])
def test_sonnet_xhigh_client_budget_signed_history_and_replay(tmp_path, monkeypatch, gateway, prior):
    requests, job = [], FakeJob(tmp_path / "first", {"interrupted_attempts": [{"cost_usd": prior}]} if prior else {})
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == SONNET and payload["output_config"]["effort"] == "xhigh"
        assert "thinking" not in payload and "tool_choice" not in payload
        bound = job.state["request_budget"]
        assert bound["input_rate_per_million"] == (2.75 if gateway else 2.5)
        assert bound["reserved_usd"] <= bound["remaining_usd"]
        if prior:
            assert 1024 <= payload["max_tokens"] < 50000
        else:
            assert payload["max_tokens"] == 64000
            assert bound["output_usd"] == pytest.approx(.704 if gateway else .64)
        if len(requests) == 2:
            assert payload["messages"][1]["content"][0] == {"type": "thinking", "thinking": "Find supporting evidence", "signature": "signed-block"}
        return stream_response(client_turn(model=SONNET) if len(requests) == 1 else answer("Sonnet answer", model=SONNET))
    settings = {"model": SONNET, "tool_mode": "client", "budget_cap": "hard", "budget_usd": 4, "effort": "xhigh"}
    if gateway:
        settings.update(api_base="https://proxy.example", model_pricing={SONNET: SONNET_PROXY_RATES})
    result = invoke(handler, job, settings)
    assert len(requests) == 2 and result["model"] == SONNET
    assert result["cost_usd"] == pytest.approx(prior + (.01221 if gateway else .0111))
    assert result["usage"]["client_web_search_calls"] == 2
    assert result["raw"]["pricing"]["rates_by_model"][SONNET]["web_search"] == 0
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    replay = invoke(lambda request: pytest.fail("completed Sonnet receipt must not repurchase"),
                    FakeJob(tmp_path / "replay", {"raw": result["raw"], "interrupted_attempts": job.state.get("interrupted_attempts", [])}),
                    {"model": OPUS, "effort": "high", "model_pricing": {SONNET: {name: rate * 10 for name, rate in SONNET_PROXY_RATES.items()}}})
    assert replay["model"] == SONNET and replay["text"] == "Sonnet answer"
    assert replay["cost_usd"] == result["cost_usd"]


@pytest.mark.parametrize("model,effort", [(OPUS, "high"), ("claude-fable-5-1", "high")])  # Sonnet/max: generate test.
def test_explicit_research_model_and_effort_are_preserved_after_sonnet_default(tmp_path, model, effort):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == model and payload["output_config"]["effort"] == effort
        return stream_response(turn(model=model))
    assert invoke(handler, FakeJob(tmp_path), {"model": model, "effort": effort})["model"] == model


def test_sonnet_gateway_response_alias_stops_unknown_exposure_without_second_post(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        assert len(calls) == 1
        return stream_response(client_turn(model="unpriced-sonnet-alias"))
    job = FakeJob(tmp_path)
    with pytest.raises(anthropic.ProviderError, match="cost.*unknown"):
        invoke(handler, job, {"model": SONNET, "api_base": "https://proxy.example", "tool_mode": "client",
                              "model_pricing": {SONNET: SONNET_PROXY_RATES}})
    assert calls == [1]
    assert job.state["provider_result"]["cost_usd"] is None
    assert job.state["provider_result"]["usage"]["client_web_search_calls"] == 1


def test_http_body_deadline_preserves_previous_sonnet_answer_with_unknown_later_cost(tmp_path):
    class SlowErrorBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{'
            await asyncio.sleep(.25)
            yield b'}'
    calls, job = [], FakeJob(tmp_path)
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return stream_response(answer("Earlier complete answer", model=SONNET))
        assert len(calls) == 2, "a timed-out later submission cannot be retried"
        return httpx.Response(400, stream=SlowErrorBody())
    settings = {"model": SONNET, "api_base": "https://proxy.example", "tool_mode": "client", "timeout_seconds": .05,
                "budget_floor_usd": .1, "max_research_rounds": 6, "continuation_prompt": "Continue {spent} {floor} {ceiling}",
                "model_pricing": {SONNET: SONNET_PROXY_RATES}}
    result = invoke(handler, job, settings)
    assert calls == [1, 1] and result["text"] == "Earlier complete answer"
    assert result["cost_usd"] is None and result["known_cost_usd"] == pytest.approx(.006105)
    assert result["estimate_incomplete"] is True and result["raw"]["unresolved_submission"] is True
    replay = invoke(lambda request: pytest.fail("unknown later submission must not repost"), job, settings)
    assert replay["text"] == result["text"] and replay["cost_usd"] is None
    assert replay["known_cost_usd"] == result["known_cost_usd"]


@pytest.mark.parametrize("judge", [False, True])
@pytest.mark.parametrize("status", [200, 400])
def test_empty_failure_receipt_keeps_research_and_judge_model_identity(tmp_path, judge, status):
    job = FakeJob(tmp_path)
    def handler(request):
        return httpx.Response(200, content=b"") if status == 200 else httpx.Response(400, json={"error": "invalid request"})
    with pytest.raises(anthropic.ProviderError):
        invoke(handler, job, {"api_base": "https://proxy.example"}, judge=judge)
    receipt = job.state["provider_result"]
    assert receipt["model"] == OPUS
    assert receipt["cost_usd"] == (None if status == 200 else 0)


def test_default_gateway_judge_keeps_opus_high_without_mutating_settings(tmp_path, monkeypatch):
    forbid_client_tools(monkeypatch, "judges must not run bootstrap or research tools")
    settings = {"api_base": "https://proxy.example", "model_pricing": {OPUS: PROXY_RATES}}
    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == OPUS
        assert payload["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": anthropic.JUDGE_SCHEMA}}
        assert not any(key in payload for key in ("thinking", "tools", "tool_choice"))
        return stream_response(answer('{"reason":"A compares both answers", "winner":"A"}'))
    result = invoke(handler, FakeJob(tmp_path), settings, judge=True)
    assert "model" not in settings and "effort" not in settings
    assert result["model"] == OPUS and result["cost_usd"] == pytest.approx(.01221)
    assert result["raw"]["tool_mode"] == "none"


@pytest.mark.parametrize("mode", ["server", "client"])
def test_paused_recovery_retains_known_subtotal_and_frozen_evidence_without_post(tmp_path, mode):
    from crest.costs import assess_cost
    rates = {"input": 2., "cached_input": .1, "cache_write_5m": 2.5, "output": 10., "web_search": 0.}
    settings = {"api_base": "https://gateway.invalid", "tool_mode": mode, "budget_cap": "hard", "budget_usd": 4,
                "model": SONNET, "model_pricing": {SONNET: rates}}
    job, calls = FakeJob(tmp_path), []
    def handler(request):
        calls.append(1)
        assert len(calls) <= 2, "unknown paused exposure must not cause a third POST"
        events = answer(stop="pause_turn", model=SONNET)
        if len(calls) == 2:
            events[-2].pop("usage")
        return stream_response(events)
    with pytest.raises(anthropic.ProviderError, match="cost.*unknown"):
        invoke(handler, job, settings)
    frozen = copy.deepcopy(job.state["raw"])
    assert job.state["provider_result"]["known_cost_usd"] == pytest.approx(.00555)
    changed = {**settings, "model_pricing": {SONNET: {key: value * 10 for key, value in rates.items()}}}
    for _ in range(2):
        with pytest.raises(anthropic.ProviderError, match="cost.*unknown"):
            invoke(lambda request: pytest.fail("paused replay must not POST"), job, changed)
        result = job.state["provider_result"]
        assert result["cost_usd"] is None and result["estimate_incomplete"] is True
        assert result["known_cost_usd"] == pytest.approx(.00555)
        assert result["usage"]["known_cost_usd"] == pytest.approx(.00555)
        assert assess_cost(result, agent="anthropic")["cumulative_known_estimate_usd"] == pytest.approx(.00555)
        assert job.state["raw"] is None
        assert len(job.state["interrupted_attempts"]) == 1
        abandoned = job.state["interrupted_attempts"][0]
        assert abandoned["cost_usd"] is None and abandoned["known_cost_usd"] == pytest.approx(.00555)
        assert abandoned["raw"] == frozen
        assert result["raw"]["interrupted_attempts"][0]["raw"] == frozen
    assert calls == [1, 1]
    # Returned provenance must not alias the durable checkpoint.
    result["raw"]["interrupted_attempts"][0]["raw"]["turns"].clear()
    assert job.state["interrupted_attempts"][0]["raw"] == frozen


@pytest.mark.parametrize("attempts,expected,total", [
    *[([{"cost_usd": complete, "known_cost_usd": partial}], expected, total) for complete, partial, expected, total in [
        (.4, .2, .4, .4), (0., .2, 0., 0.), (None, .2, .2, None),
        (None, 0., 0., None), (None, None, 0., None),
        (None, True, 0., None), (None, -1., 0., None), (None, float("nan"), 0., None),
    ]],
    # A partial subtotal is neither added twice nor lost alongside complete history.
    ([{"cost_usd": 1.25, "known_cost_usd": 1.25}, {"cost_usd": None, "known_cost_usd": .00555}, {"cost_usd": None}],
     1.25555, None),
])
def test_prior_attempt_uses_complete_or_partial_cost_once(attempts, expected, total):
    usage, cost = anthropic._account([], attempts)
    assert usage["known_cost_usd"] == pytest.approx(expected)
    assert usage["interrupted_attempt_cost_usd"] == pytest.approx(expected)
    assert cost == (pytest.approx(total) if total is not None else None)


def test_complete_paused_recovery_counts_frozen_total_once(tmp_path):
    original_job = FakeJob(tmp_path / "original")
    with pytest.raises(anthropic.ProviderError, match="max_continuations"):
        invoke(lambda request: stream_response(answer(stop="pause_turn", model=SONNET)), original_job, {"max_continuations": 0})
    original = copy.deepcopy(original_job.state["raw"])
    job = FakeJob(tmp_path / "recovered", {"raw": original, "interrupted_attempts": [{"cost_usd": .25, "known_cost_usd": .25}]})
    result = invoke(lambda request: stream_response(answer(model=SONNET)), job)
    assert result["cost_usd"] == pytest.approx(.2611)
    assert result["known_cost_usd"] == pytest.approx(.2611)
    assert result["usage"]["interrupted_attempt_cost_usd"] == pytest.approx(.25555)
    abandoned = job.state["interrupted_attempts"][-1]
    assert abandoned["cost_usd"] == pytest.approx(.00555)
    assert abandoned["known_cost_usd"] == pytest.approx(.00555)
    assert abandoned["raw"] == original
    assert result["raw"]["interrupted_attempts"][-1]["raw"] == original
