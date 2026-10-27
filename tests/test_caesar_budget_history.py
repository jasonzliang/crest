"""Fresh restarts inherit spending, never old research state."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from crest import caesar_worker as worker
from crest.providers import caesar
from test_caesar import _source, _options


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
            assert config["LLMHandler"]["max_completion_tokens"] == 25000
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
    settings = {"budget_history_from": str(source), "budget_usd": 5., "handler_budget_usd": 5., "use_quick_explore": False}
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


def test_fresh_identity_hashes_all_prior_ledgers_but_not_saved_knowledge(tmp_path):
    source = _source(tmp_path / "old", .5, .2)
    settings = {"rome_path": str(tmp_path), "budget_history_from": str(source)}
    old = caesar.identity_metadata(settings)
    (source / "caesar-output" / "chroma" / "chroma.sqlite3").write_bytes(b"irrelevant old knowledge")
    assert old == caesar.identity_metadata(settings)
    record = json.loads((source / "caesar-result.json").read_text())
    record["usage"]["known_cost_usd"] = .6
    worker.atomic_json(source / "caesar-result.json", record)
    assert old != caesar.identity_metadata(settings)


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


def test_new_retrieval_fields_preserve_legacy_fallback(tmp_path):
    config = worker.build_config("Q", {"synthesis_top_k": 15, "synthesis_top_n": 10}, tmp_path / "new", "new")
    assert config["ArtifactSynthesizer"]["synthesis_top_k"] == 15
    assert config["ArtifactSynthesizer"]["synthesis_top_n"] == 10
    assert config["ChromaClientManager"]["top_k"] == 15
    assert config["ChromaClientManager"]["enable_reranking"] is False
    old = worker.build_config("Q", {"retrieval_chunks": 8}, tmp_path / "old", "old")
    assert old["ArtifactSynthesizer"]["synthesis_top_k"] == 8
    assert old["ArtifactSynthesizer"]["synthesis_top_n"] == 8


def test_two_dollar_residual_leaves_positive_qa_allowance(tmp_path):
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
    with worker.adaptive_synthesis_budget(agent, {"budget_usd": 2, "handler_budget_usd": 2}, audit) as report:
        assert agent.synthesizer._generate_qa_pairs()
    assert report["drafts"][0]["qa_allowance_usd"] > 0
    assert report["drafts"][0]["remaining_write_allowance_usd"] <= 1.4 + 1e-9


def test_unknown_summary_without_bounded_entries_cannot_fund_restart(tmp_path):
    source = _source(tmp_path / "unbounded", .5, .2)
    path = source / "caesar-result.json"
    value = json.loads(path.read_text())
    value["usage"].update(unknown_cost=True, cost_usd=None, events=[], in_flight=[])
    worker.atomic_json(path, value)
    with pytest.raises(ValueError, match="unknown|bound"):
        worker.prepare_budget_history("Q", {"budget_history_from": str(source), "budget_usd": 5})
