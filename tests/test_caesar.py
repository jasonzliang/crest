"""Offline regressions for budgeted transient retries and recovery ancestry."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from crest import caesar_worker as worker
from crest.providers import caesar


def _options():
    return SimpleNamespace(json_data={"model": worker.SOL, "messages": [], "max_completion_tokens": 100})


class Transient(Exception):
    status_code = 520
    response = SimpleNamespace(headers={})
    body = {"retryable": True, "retry_after": 60}


def test_http520_body_backoff_retains_ambiguous_reservation_before_success(tmp_path, monkeypatch):
    from openai import OpenAI
    from openai._base_client import SyncAPIClient
    sent, waits = [], []
    def transport(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(520, json={"title": "Unknown origin error", "status": 520, "retryable": True, "retry_after": 60})
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0, "model": worker.SOL,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "answer"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
    monkeypatch.setattr(worker.time, "sleep", waits.append)
    monkeypatch.setattr(worker.random, "uniform", lambda *args: 0)
    audit = worker.UsageAudit(.003, tmp_path / "usage.json")
    with audit.installed(SyncAPIClient), OpenAI(api_key="offline", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        assert client.chat.completions.create(model=worker.SOL, messages=[], max_completion_tokens=100).choices[0].message.content == "answer"
    value = audit.snapshot()
    assert len(sent) == 2
    assert waits == [60]
    assert value["successful_calls"] == 1
    assert value["failed_calls"] == 1
    assert value["unknown_cost"] is True
    assert value["cost_usd"] is None
    assert value["events"][0]["reserved_usd"] > 0
    assert value["known_cost_usd"] + value["events"][0]["reserved_usd"] <= .003


def test_transient_retry_is_blocked_when_second_reservation_cannot_fit(tmp_path, monkeypatch):
    sent = []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            raise Transient()
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    audit = worker.UsageAudit(.002, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.BudgetExceeded):
        SDK().request(object, _options())
    assert len(sent) == 1
    assert audit.snapshot()["events"][0]["reserved_usd"] > 0
    assert audit.snapshot()["unknown_cost"] is True


def test_explicit_nonretryable_520_is_not_repeated(tmp_path, monkeypatch):
    sent = []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            error = Transient()
            error.body = {"retryable": False, "retry_after": 60}
            raise error
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("must not sleep"))
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, _options())
    assert len(sent) == 1


def test_async_520_retry_keeps_both_attempts_and_body_delay(tmp_path, monkeypatch):
    sent, waits = [], []
    class Sync:
        def request(self, *args, **kwargs): pytest.fail("sync request")
    class Async:
        async def request(self, *args, **kwargs):
            sent.append(1)
            if len(sent) == 1: raise Transient()
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20})
    async def sleep(delay): waits.append(delay)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    audit = worker.UsageAudit(.003, tmp_path / "usage.json")
    with audit.installed(Sync, Async):
        asyncio.run(Async().request(object, _options()))
    assert len(sent) == 2
    assert waits == [60]
    assert audit.snapshot()["unknown_cost"] is True


def test_retry_after_wait_never_extends_worker_wall_deadline(tmp_path):
    sent = []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            raise Transient()
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    with worker._deadline(.02), audit.installed(SDK), pytest.raises(worker.WorkerDeadlineExceeded):
        SDK().request(object, _options())
    assert len(sent) == 1


def _source(path, known, reserved, previous=None):
    output = path / "caesar-output"
    (output / "__rome__").mkdir(parents=True)
    (output / "chroma").mkdir()
    (output / "chroma" / "chroma.sqlite3").write_bytes(b"saved database")
    worker.atomic_json(output / "__rome__" / "agent_saved.checkpoint.json", {
        "iteration": 163, "visited_urls": {"https://example.test": 1}, "cost": {"accumulated_cost": 99},
        "config": {"starting_query": "Q", "starting_url": "https://example.test"}})
    settings = {"budget_usd": 5. if previous is None else 4.3}
    if previous is not None: settings["recovery_from"] = str(previous)
    worker.atomic_json(path / "caesar-request.json", {"prompt": "Q", "worker_id": path.name, "job_key": path.name, "settings": settings})
    worker.atomic_json(path / "caesar-result.json", {"status": "failed", "usage": {
        "known_cost_usd": known, "budget_target_usd": settings["budget_usd"], "unknown_cost": True,
        "events": [{"status": "failed", "unknown_cost": True, "reserved_usd": reserved}], "in_flight": []},
        "raw": {"recovery": {"source_job": str(previous)} if previous is not None else None}})
    return path


def test_second_recovery_inherits_every_prior_attempt_not_only_embedded_summary(tmp_path):
    first = _source(tmp_path / "original", .45898205, .2114525)
    second = _source(tmp_path / "recovery-one", .05257166, .00454525, first)
    original = {str(p): p.read_bytes() for root in (first, second) for p in root.rglob("*") if p.is_file()}
    destination = tmp_path / "recovery-two-output"
    config = worker.build_config("Q", {}, destination, "new")
    result = worker.prepare_synthesis_recovery("Q", {"recovery_from": str(second), "budget_usd": 4.25}, destination, "new", config)
    assert result["previous_known_cost_usd"] == pytest.approx(.51155371)
    assert result["previous_unknown_reserved_usd"] == pytest.approx(.21599775)
    assert result["budgeted_total_exposure_usd"] == pytest.approx(4.97755146)
    assert len(result["ancestry"]) == 2
    assert original == {str(p): p.read_bytes() for root in (first, second) for p in root.rglob("*") if p.is_file()}


def test_second_recovery_rejects_previous_430_allowance(tmp_path):
    first = _source(tmp_path / "original", .45898205, .2114525)
    second = _source(tmp_path / "recovery-one", .05257166, .00454525, first)
    config = worker.build_config("Q", {}, tmp_path / "destination", "new")
    with pytest.raises(ValueError):
        worker.prepare_synthesis_recovery("Q", {"recovery_from": str(second), "budget_usd": 4.3}, tmp_path / "destination", "new", config)


def test_source_version_and_commit_are_identity_metadata(tmp_path, monkeypatch):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname="caesar-agent"\nversion="0.4.31"\n')
    monkeypatch.setattr(caesar.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="1a297af410063ef44e270bf727a7d4ee0ccc72d9\n"))
    first = caesar.identity_metadata({"rome_path": str(tmp_path)})
    assert first["rome_source_version"] == "0.4.31"
    assert first["rome_git_commit"] == "1a297af410063ef44e270bf727a7d4ee0ccc72d9"
    project.write_text('[project]\nname="caesar-agent"\nversion="0.4.32"\n')
    assert first != caesar.identity_metadata({"rome_path": str(tmp_path)})


def test_four_520_attempts_hold_four_reservations_and_never_enter_outer_retry(tmp_path, monkeypatch):
    sent, waits = [], []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            raise Transient()
    monkeypatch.setattr(worker.time, "sleep", waits.append)
    audit = worker.UsageAudit(.01, tmp_path / "usage.json")
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, _options())
    assert len(sent) == 4
    assert waits == [60, 60, 60]
    value = audit.snapshot()
    assert value["failed_calls"] == 4
    assert len(value["events"]) == 4
    assert sum(event["reserved_usd"] for event in value["events"]) <= .01
    assert all(event["unknown_cost"] for event in value["events"])


def test_520_with_unknown_model_price_cannot_retry_without_a_reservation(tmp_path, monkeypatch):
    sent = []
    class SDK:
        def request(self, *args, **kwargs):
            sent.append(1)
            raise Transient()
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("unbounded retry"))
    audit = worker.UsageAudit(5, tmp_path / "usage.json")
    options = _options()
    options.json_data["model"] = "unpriced-helper"
    with audit.installed(SDK), pytest.raises(worker.SDKRequestFailed):
        SDK().request(object, options)
    assert len(sent) == 1


def test_recovery_ancestry_cycle_is_rejected_before_copying(tmp_path):
    first = _source(tmp_path / "original", .45898205, .2114525)
    second = _source(tmp_path / "recovery-one", .05257166, .00454525, first)
    request = json.loads((first / "caesar-request.json").read_text())
    request["settings"]["recovery_from"] = str(second)
    worker.atomic_json(first / "caesar-request.json", request)
    config = worker.build_config("Q", {}, tmp_path / "destination", "new")
    with pytest.raises(ValueError, match="cycle"):
        worker.prepare_synthesis_recovery("Q", {"recovery_from": str(second), "budget_usd": 4.25}, tmp_path / "destination", "new", config)
    assert not (tmp_path / "destination" / "chroma").exists()


def test_deep_ancestor_ledger_changes_recovery_cache_identity(tmp_path):
    first = _source(tmp_path / "original", .45898205, .2114525)
    second = _source(tmp_path / "recovery-one", .05257166, .00454525, first)
    settings = {"rome_path": str(tmp_path), "recovery_from": str(second)}
    old = caesar.identity_metadata(settings)
    record = json.loads((first / "caesar-result.json").read_text())
    record["usage"]["known_cost_usd"] = .6
    worker.atomic_json(first / "caesar-result.json", record)
    assert old != caesar.identity_metadata(settings)


@pytest.mark.parametrize("prior_unknown", [False, True])
def test_recovery_result_reports_cumulative_cost_and_keeps_new_attempt_audit(tmp_path, monkeypatch, prior_unknown):
    from contextlib import contextmanager
    source = _source(tmp_path / "original", 1.2, .2)
    record = json.loads((source / "caesar-result.json").read_text())
    if not prior_unknown:
        record["usage"].update(unknown_cost=False, events=[])
        worker.atomic_json(source / "caesar-result.json", record)
    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20})
    class Agent:
        def __init__(self, **kwargs):
            self.current_iteration = 163
            self.visited_urls = {"https://example.test": 1}
            self.kb_manager = SimpleNamespace(size=lambda: 1)
            self.synthesizer = SimpleNamespace(synthesize_artifact=self.synthesize)
        def synthesize(self):
            SDK().request(object, _options())
            return {"artifact": "completed answer", "sources": {}, "num_drafts": 3, "metadata": {"synthesis_queries": 15}}
        def explore(self): pytest.fail("recovery must not explore")
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit):
        with audit.installed(SDK): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "new-job" / "result.json"
    settings = {"recovery_from": str(source), "budget_usd": 3., "handler_budget_usd": 3.}
    assert worker.run_worker({"prompt": "Q", "settings": settings, "output_dir": str(path.parent / "output"), "job_key": "new"}, path) == 0
    result = json.loads(path.read_text())["result"]
    assert result["usage"]["known_cost_usd"] == pytest.approx(1.2004)
    assert result["usage"]["cumulative_known_cost_usd"] == pytest.approx(1.2004)
    assert result["raw"]["new_attempt_usage_audit"]["known_cost_usd"] == pytest.approx(.0004)
    assert result["usage"]["new_attempt_cost_usd"] == pytest.approx(.0004)
    if prior_unknown:
        assert result["cost_usd"] is None
    else:
        assert result["cost_usd"] == pytest.approx(1.2004)


def test_history_prefers_per_attempt_audit_over_cumulative_success_summary(tmp_path):
    first = _source(tmp_path / "original", .45898205, .2114525)
    second = _source(tmp_path / "recovery-one", .05257166, .00454525, first)
    value = json.loads((second / "caesar-result.json").read_text())
    attempt = value.pop("usage")
    previous = value.pop("raw")["recovery"]
    value.update(status="completed", result={"usage": dict(attempt, known_cost_usd=.51155371),
        "raw": {"recovery": previous, "new_attempt_usage_audit": attempt}})
    worker.atomic_json(second / "caesar-result.json", value)
    history, budget = worker.recovery_history(second, "Q")
    assert budget == 5
    assert sum(row["known_cost_usd"] for row in history) == pytest.approx(.51155371)
    assert sum(row["unknown_reserved_usd"] for row in history) == pytest.approx(.21599775)
