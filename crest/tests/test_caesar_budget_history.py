"""Budget history and synthesis recovery: restarts inherit every prior attempt's spending, never old research state."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from crest.providers import caesar_worker as worker
from crest.providers import caesar


def _options():
    return SimpleNamespace(json_data={"model": worker.SOL, "messages": [], "max_completion_tokens": 100})


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


def test_second_recovery_inherits_every_prior_attempt_and_rejects_the_previous_430_allowance(tmp_path):
    first = _source(tmp_path / "original", .45898205, .2114525)
    second = _source(tmp_path / "recovery-one", .05257166, .00454525, first)
    original = {str(p): p.read_bytes() for root in (first, second) for p in root.rglob("*") if p.is_file()}
    rejected = tmp_path / "rejected-output"
    config = worker.build_config("Q", {}, rejected, "new")
    with pytest.raises(ValueError):
        worker.prepare_synthesis_recovery("Q", {"recovery_from": str(second), "budget_usd": 4.3}, rejected, "new", config)
    destination = tmp_path / "recovery-two-output"
    config = worker.build_config("Q", {}, destination, "new")
    result = worker.prepare_synthesis_recovery("Q", {"recovery_from": str(second), "budget_usd": 4.25}, destination, "new", config)
    assert result["previous_known_cost_usd"] == pytest.approx(.51155371)
    assert result["previous_unknown_reserved_usd"] == pytest.approx(.21599775)
    assert result["budgeted_total_exposure_usd"] == pytest.approx(4.97755146)
    assert len(result["ancestry"]) == 2
    assert original == {str(p): p.read_bytes() for root in (first, second) for p in root.rglob("*") if p.is_file()}


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
    settings = {"recovery_from": str(source), "budget_usd": 3.}
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


def test_fresh_restart_keeps_global_budget_and_does_not_restore_knowledge(tmp_path, monkeypatch):
    source = _source(tmp_path / "old-job", .5, .2)
    original = {str(p): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    called = []
    class SDK:
        def request(self, *args, **kwargs):
            called.append("paid")
            return SimpleNamespace(usage={"prompt_tokens": 100, "completion_tokens": 20})
    class Agent:
        def __init__(self, name, repository, config):
            assert config["CaesarAgent"]["use_quick_explore"] is False
            assert config["CaesarAgent"]["max_iterations"] == 250
            assert config["CaesarAgent"].get("starting_url") is None
            assert config["LLMHandler"]["cost_limit"] == pytest.approx(4.3)
            assert config["LLMHandler"]["max_completion_tokens"] == 32768
            old_collection = "crest_" + hashlib.sha256(source.name.encode()).hexdigest()[:40]
            assert config["ChromaClientManager"]["collection_name"] != old_collection
            assert not (Path(repository) / "chroma").exists()
            assert not list((Path(repository) / "__rome__").glob("*.checkpoint.json"))
            self.current_iteration = 0
        def perceive(self): return "fresh page", []
        def explore(self):
            called.append("fresh exploration")
            SDK().request(object, _options())
            return {"artifact": "fresh answer", "num_drafts": 3, "metadata": {"synthesis_queries": 15}}
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit):
        assert audit.budget == pytest.approx(4.3)
        with audit.installed(SDK): yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    path = tmp_path / "fresh-job" / "result.json"
    settings = {"budget_history_from": str(source), "budget_usd": 5., "use_quick_explore": False}
    assert worker.run_worker({"prompt": "Q", "settings": settings, "job_key": "fresh", "worker_id": "fresh-worker", "output_dir": str(path.parent / "output")}, path) == 0
    result = json.loads(path.read_text())["result"]
    assert called == ["fresh exploration", "paid"]
    history = result["raw"]["budget_history"]
    assert history["original_budget_usd"] == 5
    assert history["previous_known_cost_usd"] == .5
    assert history["previous_unknown_reserved_usd"] == .2
    assert history["new_attempt_budget_usd"] == pytest.approx(4.3)
    assert result["cost_usd"] is None
    assert result["usage"]["known_cost_usd"] == pytest.approx(.5004)
    assert result["usage"]["budget_target_usd"] == 5
    assert result["raw"]["new_attempt_usage_audit"]["budget_target_usd"] == pytest.approx(4.3)
    assert original == {str(p): p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("status", ["failed", "completed"])
def test_history_accepts_terminal_attempts_and_accumulates_new_history_links(tmp_path, status):
    first = _source(tmp_path / "first", .3, .1)
    second = _source(tmp_path / "second", .2, .1, first)
    record = json.loads((second / "caesar-result.json").read_text())
    record["status"] = status
    record["raw"]["budget_history"] = record["raw"].pop("recovery")
    worker.atomic_json(second / "caesar-result.json", record)
    request = json.loads((second / "caesar-request.json").read_text())
    request["settings"]["budget_history_from"] = request["settings"].pop("recovery_from")
    worker.atomic_json(second / "caesar-request.json", request)
    value = worker.prepare_budget_history("Q", {"budget_history_from": str(second), "budget_usd": 5})
    assert value["previous_known_cost_usd"] == pytest.approx(.5)
    assert value["previous_unknown_reserved_usd"] == pytest.approx(.2)
    assert value["new_attempt_budget_usd"] == pytest.approx(4.3)
    assert len(value["ancestry"]) == 2


def test_insufficient_restart_allowance_fails_before_runtime_or_calls(tmp_path, monkeypatch):
    source = _source(tmp_path / "spent", 4.9, .2)
    entered = []
    def no_runtime(*args):
        entered.append(True)
        pytest.fail("no runtime before budget admission")
    monkeypatch.setattr(worker, "_runtime", no_runtime)
    path = tmp_path / "new-job" / "result.json"
    request = {"prompt": "Q", "settings": {"budget_history_from": str(source), "budget_usd": 5}, "job_key": "new", "output_dir": str(path.parent / "output")}
    assert worker.run_worker(request, path) == 1
    record = json.loads(path.read_text())
    assert record["status"] == "failed"
    assert record["usage"]["known_cost_usd"] == 0
    assert record["usage"]["successful_calls"] == 0
    assert entered == []


def test_fresh_and_synthesis_recovery_modes_are_mutually_exclusive(tmp_path, monkeypatch):
    source = _source(tmp_path / "old", .5, .2)
    monkeypatch.setattr(worker, "_runtime", lambda *args: pytest.fail("ambiguous recovery mode"))
    with pytest.raises(ValueError, match="exclusive"):
        worker.run_worker({"prompt": "Q", "settings": {"budget_history_from": str(source), "recovery_from": str(source)},
            "job_key": "new", "output_dir": str(tmp_path / "output")}, tmp_path / "result.json")


def test_fresh_identity_hashes_all_prior_ledgers_and_final_usage_but_not_saved_knowledge(tmp_path):
    source = _source(tmp_path / "old", .5, .2)
    settings = {"rome_path": str(tmp_path), "budget_history_from": str(source)}
    old = caesar.identity_metadata(settings)
    (source / "caesar-output" / "chroma" / "chroma.sqlite3").write_bytes(b"irrelevant old knowledge")
    assert old == caesar.identity_metadata(settings)
    record = json.loads((source / "caesar-result.json").read_text())
    record["usage"]["known_cost_usd"] = .6
    worker.atomic_json(source / "caesar-result.json", record)
    assert old != caesar.identity_metadata(settings)
    # The ancestral final usage file is a ledger too.
    final = {"known_cost_usd": .6, "unknown_cost": True, "budget_target_usd": 5.,
        "events": [{"status": "failed", "unknown_cost": True, "reserved_usd": .1}], "in_flight": []}
    path = source / "caesar-output" / "usage.json"
    worker.atomic_json(path, final)
    with_final = caesar.identity_metadata(settings)
    final["known_cost_usd"] = .7
    worker.atomic_json(path, final)
    assert with_final != caesar.identity_metadata(settings)


@pytest.mark.parametrize("bad_status,bad_known", [("running", .5), ("failed", float("nan"))])
def test_nonterminal_or_nonfinite_history_is_rejected(tmp_path, bad_status, bad_known):
    source = _source(tmp_path / "old", .5, .2)
    path = source / "caesar-result.json"
    value = json.loads(path.read_text())
    value["status"] = bad_status
    value["usage"]["known_cost_usd"] = bad_known
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        worker.prepare_budget_history("Q", {"budget_history_from": str(source), "budget_usd": 5})


def test_short_synthesis_calls_use_6000_with_reasoning_and_restore_25000():
    calls = []
    class Agent:
        def __init__(self): self.llm_handler = SimpleNamespace(max_completion_tokens=25000)
        def chat_completion(self, prompt, **kwargs):
            calls.append((prompt, kwargs.get("override_config"), self.llm_handler.max_completion_tokens))
            return "result"
    agent = Agent()
    class Synthesizer:
        def _llm_call(self, prompt, required_keys, *, label, reasoning="medium"):
            return agent.chat_completion(prompt, override_config={"reasoning_effort": reasoning})
    agent.synthesizer = Synthesizer()
    original_chat = agent.chat_completion
    with worker.synthesis_query_completion_limits(agent, {"query_max_completion_tokens": 6000}):
        for label in ("NEXT_QUERY", "REFINE", "SYNTHESIS", "MERGE"):
            agent.synthesizer._llm_call(label, [], label=label, reasoning="medium")
    assert calls[0][1] == {"reasoning_effort": "medium", "max_completion_tokens": 6000}
    assert calls[1][1] == {"reasoning_effort": "medium", "max_completion_tokens": 6000}
    assert [row[2] for row in calls] == [6000, 6000, 25000, 25000]
    assert agent.chat_completion == original_chat
    assert agent.llm_handler.max_completion_tokens == 25000


@pytest.mark.parametrize("effort,completion_limit,hold", [("medium", 10000, .515), ("xhigh", 32768, 1.88072)])
def test_two_dollar_residual_holds_writes_without_clamping_xhigh(tmp_path, effort, completion_limit, hold):
    audit = worker.UsageAudit(2, tmp_path / "usage.json")
    class Synthesizer:
        _current_draft = 1
        synthesis_drafts = 3
        synthesis_iterations = 15
        synthesis_merge_artifacts = True
        def _generate_qa_pairs(self):
            assert audit.request_limit > 0
            return [("Q", "A", [])]
    agent = SimpleNamespace(synthesizer=Synthesizer())
    settings = {"budget_usd": 2, "synthesis_reasoning_effort": effort, "max_completion_tokens": completion_limit}
    with worker.adaptive_synthesis_budget(agent, settings, audit) as report:
        assert agent.synthesizer._generate_qa_pairs()
    assert report["drafts"][0]["qa_allowance_usd"] > 0
    assert report["drafts"][0]["remaining_write_allowance_usd"] == pytest.approx(hold)
    assert report["drafts"][0]["qa_allowance_usd"] == pytest.approx((2 - hold) / 3)


def test_unknown_summary_without_bounded_entries_cannot_fund_restart(tmp_path):
    source = _source(tmp_path / "unbounded", .5, .2)
    path = source / "caesar-result.json"
    value = json.loads(path.read_text())
    value["usage"].update(unknown_cost=True, cost_usd=None, events=[], in_flight=[])
    worker.atomic_json(path, value)
    with pytest.raises(ValueError, match="unknown|bound"):
        worker.prepare_budget_history("Q", {"budget_history_from": str(source), "budget_usd": 5})


def test_final_usage_file_replaces_stale_terminal_snapshot(tmp_path):
    source = _source(tmp_path / "old", .5, .2)
    snapshot_path = source / "caesar-result.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["usage"].update(successful_calls=1, events=[], in_flight=[{"reserved_usd": .2}])
    worker.atomic_json(snapshot_path, snapshot)
    final = {"known_cost_usd": .65, "unknown_cost": False, "cost_usd": .65,
        "budget_target_usd": 5., "successful_calls": 2, "events": [{"status": "completed", "cost_usd": .65, "unknown_cost": False}], "in_flight": []}
    worker.atomic_json(source / "caesar-output" / "usage.json", final)
    value = worker.prepare_budget_history("Q", {"budget_history_from": str(source), "budget_usd": 5})
    assert value["previous_known_cost_usd"] == .65
    assert value["previous_unknown_reserved_usd"] == 0
    assert value["new_attempt_budget_usd"] == pytest.approx(4.35)
    assert value["previous_cost_unknown"] is False


@pytest.mark.parametrize("command,blocks", [
    (["-m", "crest.caesar_worker", "--result", "{result}"], True),
    (["-m", "crest.providers.caesar_worker", "--result", "{result}"], True),
    (["-m", "unrelated"], False),
], ids=["legacy-module-live", "provider-module-live", "recycled-pid"])
def test_only_a_live_owned_worker_pid_prevents_history_admission(tmp_path, monkeypatch, command, blocks):
    import psutil
    source = _source(tmp_path / "old", .5, .2)
    worker.atomic_json(source / "state.json", {"worker_pid": 43210})
    cmdline = ["python"] + [part.format(result=source / "caesar-result.json") for part in command]
    process = SimpleNamespace(status=lambda: psutil.STATUS_RUNNING, cmdline=lambda: cmdline)
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    if blocks:
        with pytest.raises(ValueError, match="running|alive"):
            worker.prepare_budget_history("Q", {"budget_history_from": str(source), "budget_usd": 5})
    else:
        value = worker.prepare_budget_history("Q", {"budget_history_from": str(source), "budget_usd": 5})
        assert value["new_attempt_budget_usd"] == pytest.approx(4.3)


@pytest.mark.parametrize("mode", ["recovery", "budget_history"])
@pytest.mark.parametrize("prior_unknown", [False, True])
@pytest.mark.parametrize("prior_known,new_target,total,over_target,attempt_over", [
    (4.8, 4., 5.3, True, False),
    (.2, .3, .7, False, True),
    (5.2, 6., 5.7, True, False),
])
def test_soft_history_result_recalculates_cumulative_warning_and_keeps_attempt_audit(
        tmp_path, monkeypatch, mode, prior_unknown, prior_known, new_target, total, over_target, attempt_over):
    source = _source(tmp_path / "source", prior_known, .2)
    if not prior_unknown:
        record = json.loads((source / "caesar-result.json").read_text())
        record["usage"].update(unknown_cost=False, events=[])
        worker.atomic_json(source / "caesar-result.json", record)
    original = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}

    class SDK:
        def request(self, *args, **kwargs):
            return SimpleNamespace(usage={"prompt_tokens": 200000, "completion_tokens": 10000})

    class Agent:
        def __init__(self, name, repository, config):
            assert config["LLMHandler"]["cost_limit"] == 0.
            assert config["CaesarAgent"]["max_iterations"] == (0 if mode == "recovery" else 250)
            self.current_iteration = 163
            self.visited_urls = {"https://example.test": 1}
            self.kb_manager = SimpleNamespace(size=lambda: 1)
            self.synthesizer = SimpleNamespace(synthesize_artifact=self.synthesize)
        def synthesize(self):
            SDK().request(object, _options())
            return {"artifact": "completed answer", "sources": {}, "num_drafts": 3,
                    "metadata": {"synthesis_queries": 15}}
        def explore(self):
            assert mode == "budget_history"
            return self.synthesize()
        def shutdown(self): pass

    @contextmanager
    def runtime(settings, audit):
        assert audit.budget == new_target and audit.enforce is False
        with audit.installed(SDK):
            yield Agent
    monkeypatch.setattr(worker, "_runtime", runtime)
    job = tmp_path / "new-job"
    settings = {mode + "_from": str(source), "budget_usd": new_target, "budget_cap": "soft"}
    request = {"prompt": "Q", "settings": settings, "job_key": "new",
               "output_dir": str(job / "caesar-output")}
    worker.atomic_json(job / "caesar-request.json", request)
    result_path = job / "caesar-result.json"
    assert worker.run_worker(request, result_path) == 0
    result = json.loads(result_path.read_text())["result"]
    usage, attempt = result["usage"], result["raw"]["new_attempt_usage_audit"]
    assert usage["known_cost_usd"] == pytest.approx(total)
    assert usage["budget_target_usd"] == 5.
    assert usage["budget_exceeded"] is over_target
    assert usage["new_attempt_budget_exceeded"] is attempt_over
    assert usage["new_attempt_cost_usd"] == pytest.approx(.5)
    assert usage["new_attempt_budget_target_usd"] == new_target
    assert attempt["known_cost_usd"] == pytest.approx(.5)
    assert attempt["budget_target_usd"] == new_target
    assert attempt["budget_exceeded"] is attempt_over
    assert attempt["successful_calls"] == 1 and attempt["unknown_cost"] is False
    assert usage[mode + "_previous_unknown_reserved_usd"] == (.2 if prior_unknown else 0.)
    if prior_unknown:
        assert result["cost_usd"] is None and usage["unknown_cost"] is True
        assert any("total cost is unknown" in warning for warning in result["warnings"])
    else:
        assert result["cost_usd"] == pytest.approx(total) and usage["unknown_cost"] is False
    warnings = [warning for warning in result["warnings"] if "exceeded" in warning and "budget" in warning]
    assert len(warnings) == int(over_target)
    if over_target:
        assert f"${total:.2f}" in warnings[0] and "$5.00" in warnings[0]
        assert "known estimated cost" in warnings[0].lower() and "soft cap" in warnings[0]
    history, target = worker.recovery_history(job, "Q")
    assert target == 5. and len(history) == 2
    assert sum(item["known_cost_usd"] for item in history) == pytest.approx(total)
    assert sum(item["unknown_reserved_usd"] for item in history) == (.2 if prior_unknown else 0.)
    assert original == {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}


@pytest.mark.parametrize("target", [3., 6.])
def test_soft_fresh_history_keeps_original_target_without_enforcing_spent_residual(tmp_path, target):
    source = _source(tmp_path / "spent", 5.2, .3)
    value = worker.prepare_budget_history("Q", {"budget_history_from": str(source),
        "budget_cap": "soft", "budget_usd": target, "synthesis_reserve_usd": 1.5})
    assert value["original_budget_usd"] == 5.
    assert value["new_attempt_budget_usd"] == target
    assert value["previous_known_cost_usd"] == 5.2
    assert value["previous_unknown_reserved_usd"] == .3
    assert value["budgeted_total_exposure_usd"] == pytest.approx(5.5 + target)
    assert value["effective_synthesis_reserve_usd"] == 1.5


@pytest.mark.parametrize("cap", ["hard", "auto"])
@pytest.mark.parametrize("target,original,residual", [(3., 3., 2.3), (7., 5., 4.3)])
def test_fresh_history_hard_and_auto_keep_effective_ceiling(tmp_path, cap, target, original, residual):
    source = _source(tmp_path / "source", .5, .2)
    settings = {"budget_history_from": str(source), "budget_cap": cap, "budget_usd": target}
    value = worker.prepare_budget_history("Q", settings)
    assert value["original_budget_usd"] == original
    assert value["new_attempt_budget_usd"] == pytest.approx(residual)
    spent = _source(tmp_path / "spent", 5.2, .3)
    with pytest.raises(ValueError, match="No budget remains"):
        worker.prepare_budget_history("Q", dict(settings, budget_history_from=str(spent)))


@pytest.mark.parametrize("cap", ["soft", "hard", "auto"])
@pytest.mark.parametrize("field", ["budget_usd", "synthesis_reserve_usd"])
@pytest.mark.parametrize("invalid", [0., -1., float("nan"), float("inf"), True, "4", None])
def test_fresh_history_rejects_invalid_targets_and_reserves(tmp_path, cap, field, invalid):
    source = _source(tmp_path / "source", .5, .2)
    settings = {"budget_history_from": str(source), "budget_cap": cap,
                "budget_usd": 5., "synthesis_reserve_usd": 3., field: invalid}
    with pytest.raises(ValueError, match="positive and finite"):
        worker.prepare_budget_history("Q", settings)
