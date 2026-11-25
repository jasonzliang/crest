"""Offline checks: connection errors and timeouts on exploration, KB and embedding calls are retried, bounded and billed."""
import asyncio
from contextlib import contextmanager
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from crest.providers import caesar_worker as worker


def _reply(model=worker.SOL):
    if model.startswith("text-embedding-"):
        return httpx.Response(200, json={"object": "list", "model": model,
            "data": [{"object": "embedding", "index": 0, "embedding": [.1, .2]}],
            "usage": {"prompt_tokens": 50, "total_tokens": 50}})
    return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "answer"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})


def _real_sdk(audit, transport, asynchronous=False, embedding=False):
    """The installed audit boundary with the real OpenAI SDK; only the HTTP transport is fake."""
    from openai import OpenAI, AsyncOpenAI
    from openai._base_client import SyncAPIClient, AsyncAPIClient
    def create(client):
        if embedding:
            return client.embeddings.create(model="text-embedding-3-small", input=["source"])
        return client.chat.completions.create(model=worker.LUNA, messages=[{"role": "user", "content": "Q"}],
                                              max_completion_tokens=100)
    with audit.installed(SyncAPIClient, AsyncAPIClient):
        if asynchronous:
            async def call():
                async with AsyncOpenAI(api_key="offline-fixture", max_retries=0,
                        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                    return await create(client)
            return asyncio.run(call())
        with OpenAI(api_key="offline-fixture", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            return create(client)


def _flaky(sent, failures, error=httpx.ConnectError, model=worker.LUNA):
    """Raise ``error`` from the transport for the first ``failures`` sends, then reply."""
    def transport(request):
        sent.append(1)
        if len(sent) <= failures:
            raise error("Connection error.", request=request)
        return _reply(model)
    return transport


@pytest.fixture
def waits(monkeypatch):
    recorded = []
    monkeypatch.setattr(worker.time, "sleep", recorded.append)
    async def sleep(delay): recorded.append(delay)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: 0)
    return recorded


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("cause,sdk_error", [(httpx.ConnectError, "APIConnectionError"),
                                             (httpx.ReadTimeout, "APITimeoutError"),
                                             (httpx.ConnectTimeout, "APITimeoutError"),
                                             (httpx.RemoteProtocolError, "APIConnectionError")],
                         ids=["connect-error", "read-timeout", "connect-timeout", "server-disconnected"])
def test_one_transport_error_then_success_continues_and_holds_the_unknown_reservation(tmp_path, waits, asynchronous, cause, sdk_error):
    sent = []
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    response = _real_sdk(audit, _flaky(sent, 1, cause), asynchronous)
    assert response.choices[0].message.content == "answer"
    assert len(sent) == 2
    assert waits == [1]
    usage = json.loads(audit.path.read_text())
    assert usage["successful_calls"] == 1 and usage["failed_calls"] == 1
    failed = usage["events"][0]
    assert failed["status"] == "failed" and failed["status_code"] is None
    assert failed["error_type"] == sdk_error
    assert failed["transport_error_type"] == cause.__name__
    assert failed["transient_retry"] is True
    # The first attempt may have been billed: unknown cost, reservation held, never reset.
    assert failed["unknown_cost"] is True and failed["cost_usd"] is None and failed["reserved_usd"] > 0
    assert usage["unknown_cost"] is True and usage["cost_usd"] is None
    assert usage["known_cost_usd"] == pytest.approx(usage["events"][1]["cost_usd"])
    assert audit.transient_retries_used == 1


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_embedding_connection_error_is_retried(tmp_path, waits, asynchronous):
    sent = []
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    _real_sdk(audit, _flaky(sent, 1, model="text-embedding-3-small"), asynchronous, embedding=True)
    events = audit.snapshot()["events"]
    assert [event["status"] for event in events] == ["failed", "completed"]
    assert events[0]["model"] == "text-embedding-3-small"
    assert events[0]["unknown_cost"] is True and events[0]["reserved_usd"] > 0


def test_dead_network_stops_after_the_per_request_cap_with_todays_error(tmp_path, waits):
    sent = []
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with pytest.raises(worker.SDKRequestFailed) as raised:
        _real_sdk(audit, _flaky(sent, 99))
    assert str(raised.value) == "APIConnectionError: billing outcome unknown; stopped after 4 attempt(s)"
    assert len(sent) == 4
    assert waits == [1, 2, 4]
    usage = audit.snapshot()
    assert usage["failed_calls"] == 4 and not usage["in_flight"]
    assert all(event["unknown_cost"] and event["cost_usd"] is None and event["reserved_usd"] > 0 for event in usage["events"])
    assert [event["transient_retry"] for event in usage["events"]] == [True, True, True, False]


def test_total_transient_retries_are_capped_across_requests(tmp_path, waits):
    sent = []
    audit = worker.UsageAudit(5, tmp_path / "usage.json", transient_retry_limit=2)
    _real_sdk(audit, _flaky(sent, 2))  # Uses both retries, then succeeds.
    later = []
    with pytest.raises(worker.SDKRequestFailed, match=r"^APIConnectionError: billing outcome unknown; stopped after 1 attempt\(s\)$"):
        _real_sdk(audit, _flaky(later, 1))
    assert len(sent) == 3 and len(later) == 1
    assert audit.transient_retries_used == 2
    last = audit.snapshot()["events"][-1]
    assert last["transient_retry"] is False and last["unknown_cost"] is True and last["reserved_usd"] > 0


def test_retry_limit_setting_reaches_the_worker_audit(tmp_path, monkeypatch):
    seen = {}
    @contextmanager
    def runtime(settings, audit):
        seen["limit"] = audit.transient_retry_limit
        raise RuntimeError("stop before Rome")
        yield
    monkeypatch.setattr(worker, "_runtime", runtime)
    for settings, expected in (({}, worker.DEFAULT_TRANSIENT_RETRY_LIMIT), ({"transient_retry_limit": 3}, 3)):
        worker.run_worker({"prompt": "Q", "settings": settings, "output_dir": str(tmp_path / "out"), "job_key": "abc"},
                          tmp_path / "result.json")
        assert seen["limit"] == expected


class _NotNetwork(Exception):
    pass


@pytest.mark.parametrize("transport_error", [_NotNetwork, httpx.LocalProtocolError, httpx.UnsupportedProtocol],
                         ids=["sdk-wrapped-bug", "local-protocol", "unsupported-protocol"])
def test_non_network_failures_wrapped_as_connection_errors_stay_terminal(tmp_path, waits, transport_error):
    sent = []
    def transport(request):
        sent.append(1)
        raise transport_error("not a network failure")
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with pytest.raises(worker.SDKRequestFailed, match=r"stopped after 1 attempt\(s\)$"):
        _real_sdk(audit, transport)
    assert len(sent) == 1 and waits == []
    assert audit.transient_retries_used == 0
    assert audit.snapshot()["events"][0]["unknown_cost"] is True


@pytest.mark.parametrize("error", [TimeoutError("socket timeout"), ConnectionResetError("reset"), ValueError("bad")],
                         ids=["builtin-timeout", "builtin-reset", "value-error"])
def test_errors_outside_the_sdk_transport_family_stay_terminal(tmp_path, waits, error):
    sent = []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            raise error
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed, match=r"stopped after 1 attempt\(s\)$"):
        SDK().request(object, SimpleNamespace(json_data={"model": worker.LUNA, "messages": [], "max_completion_tokens": 10}))
    assert len(sent) == 1 and waits == []


def test_http_400_stays_terminal(tmp_path, waits):
    sent = []
    def transport(request):
        sent.append(1)
        return httpx.Response(400, json={"error": {"message": "bad request", "type": "invalid_request_error"}})
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with pytest.raises(worker.SDKRequestFailed, match=r"^BadRequestError: billing outcome unknown; stopped after 1 attempt\(s\)$"):
        _real_sdk(audit, transport)
    assert len(sent) == 1 and waits == []


def _sdk_error(error=openai.APIConnectionError, cause=httpx.ConnectError):
    request = httpx.Request("POST", "https://api.openai.test/v1/chat/completions")
    value = error(request=request)
    value.__cause__ = cause("Connection error.", request=request)
    return value


def _call(model=worker.LUNA, tokens=10):
    return SimpleNamespace(json_data={"model": model, "messages": [], "max_completion_tokens": tokens})


@pytest.mark.parametrize("label,retried", [("SYNTHESIS", False), ("MERGE", False), ("CLARIFY", False),
                                           ("POST-PROCESS", False), ("NEXT_QUERY", True), ("REFINE", True)])
def test_synthesis_write_calls_keep_todays_terminal_behavior(tmp_path, waits, label, retried):
    sent = []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            if len(sent) == 1:
                raise _sdk_error()
            return SimpleNamespace(usage={"prompt_tokens": 10, "completion_tokens": 2})
    def llm_call(prompt, required_keys, retries=3, reasoning=None, label="LLM"):
        SDK().request(object, _call(worker.SOL))
        return {"artifact": "text"}
    synthesizer = SimpleNamespace(_llm_call=llm_call)
    agent = SimpleNamespace(synthesizer=synthesizer)
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), worker.synthesis_writes_keep_transport_errors_terminal(agent, audit):
        if retried:
            assert synthesizer._llm_call("p", ["artifact"], label=label) == {"artifact": "text"}
        else:
            with pytest.raises(worker.SDKRequestFailed, match=r"^APIConnectionError: billing outcome unknown; stopped after 1 attempt\(s\)$"):
                synthesizer._llm_call("p", ["artifact"], label=label)
        # Outside a write call, a KB/exploration call is retryable again.
        sent.clear()
        SDK().request(object, _call())
    assert synthesizer._llm_call is llm_call
    assert len(sent) == 2
    assert audit.snapshot()["events"][0]["unknown_cost"] is True


def _run(tmp_path, monkeypatch, fail_once):
    """run_worker with a fake Caesar whose exploration, KB and embedding calls cross the audit boundary.

    Each tag in ``fail_once`` makes that call's first attempt raise a transport error.
    """
    sent, pending = [], set(fail_once)
    errors = {"explore": (), "embed": (), "kb": (openai.APITimeoutError, httpx.ReadTimeout), "synthesis": ()}
    class SDK:
        def request(self, cast_to, options, **kwargs):
            sent.append(options.json_data["model"])
            tag = options.json_data.get("tag")
            if tag in pending:
                pending.discard(tag)
                raise _sdk_error(*errors[tag])
            return SimpleNamespace(usage={"prompt_tokens": 10, "completion_tokens": 0 if "embedding" in options.json_data["model"] else 2})
    def pay(model, tag):
        data = {"model": model, "input": ["x"]} if model.startswith("text-embedding-") else {
            "model": model, "messages": [], "max_completion_tokens": 10}
        SDK().request(object, SimpleNamespace(json_data={**data, "tag": tag}))
    class Agent:
        def __init__(self, **kwargs):
            self.current_iteration = 0
            self.visited_urls = []
            self.synthesizer = SimpleNamespace(_llm_call=self.llm_call, synthesize_artifact=self.synthesize,
                                               synthesis_drafts=3, synthesis_iterations=15, synthesis_merge_artifacts=True)
        def perceive(self):
            return "content", []
        def explore(self):
            self.current_iteration = 1
            self.perceive()
            pay(worker.LUNA, "explore")
            pay("text-embedding-3-small", "embed")
            pay(worker.LUNA, "kb")
            return self.synthesize()
        def llm_call(self, prompt, required_keys, retries=3, reasoning=None, label="LLM"):
            pay(worker.SOL, "synthesis")
            return {"artifact": "text"}
        def synthesize(self):
            self.synthesizer._llm_call("draft", ["artifact"], label="SYNTHESIS")
            return {"abstract": "A.", "artifact": "Finding [1].", "sources": {"https://example.test": 1},
                    "num_drafts": 3, "metadata": {"synthesis_queries": 15}}
        def shutdown(self):
            pass
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK):
            yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    path = tmp_path / "result.json"
    code = worker.run_worker({"prompt": "Q", "settings": {"budget_usd": 5.}, "output_dir": str(tmp_path / "output"),
                              "job_key": "abc"}, path)
    return code, json.loads(path.read_text()), sent


def test_answer_survives_exploration_kb_and_embedding_transport_errors(tmp_path, monkeypatch):
    code, saved, sent = _run(tmp_path, monkeypatch, {"explore", "embed", "kb"})
    assert code == 0 and saved["status"] == "completed"
    usage = saved["result"]["usage"]
    failed = [event for event in usage["events"] if event["status"] == "failed"]
    assert [(event["model"], event["error_type"], event["transport_error_type"]) for event in failed] == [
        (worker.LUNA, "APIConnectionError", "ConnectError"),
        ("text-embedding-3-small", "APIConnectionError", "ConnectError"),
        (worker.LUNA, "APITimeoutError", "ReadTimeout")]
    assert all(event["unknown_cost"] and event["cost_usd"] is None and event["reserved_usd"] > 0 for event in failed)
    assert usage["successful_calls"] == 4
    assert usage["unknown_cost"] is True and saved["result"]["cost_usd"] is None
    assert any("total cost is unknown" in warning for warning in saved["result"]["warnings"])
    assert len(sent) == 7


def test_final_synthesis_transport_error_still_ends_the_answer(tmp_path, monkeypatch):
    code, saved, sent = _run(tmp_path, monkeypatch, {"synthesis"})
    assert code == 1 and saved["status"] == "failed"
    assert saved["error"] == "SDKRequestFailed: APIConnectionError: billing outcome unknown; stopped after 1 attempt(s)"
    last = saved["usage"]["events"][-1]
    assert last["model"] == worker.SOL and last["unknown_cost"] is True and last["reserved_usd"] > 0
    assert sent.count(worker.SOL) == 1
