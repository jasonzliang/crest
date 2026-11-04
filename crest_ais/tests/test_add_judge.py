"""Adding a judge to a frozen comparison reuses exact prompts and paid votes."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from crest_ais.pipeline import create_judge_extension, run_judging
from crest_ais.protocol import add_judge_plan, validate_plan_fingerprint
from crest_ais.tests.test_pipeline import JUDGES, _plan, _verdict

FABLE = {"model": "claude-fable-5-1", "effort": "high", "max_output_tokens": 32768,
         "concurrency": 2, "initial_concurrency": 2, "timeout_seconds": 900, "poll_interval_seconds": 5}


def _complete_parent(tmp_path, calls=None):
    parent = _plan(tmp_path, (2, 2, 2, 2), pairs_per_matchup=1)
    source = tmp_path / "source"

    async def judge(prompt, settings, job):
        if calls is not None:
            calls.append(("parent", job.key))
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    asyncio.run(run_judging(parent, source, providers={name: SimpleNamespace(judge=judge) for name in JUDGES},
                            progress=False))
    return parent, source


def test_added_judge_reads_byte_identical_prompts_and_keeps_parent_jobs(tmp_path):
    parent = _plan(tmp_path, (2, 2, 2, 2), pairs_per_matchup=1)
    plan = add_judge_plan(parent, {"anthropic": FABLE}, tmp_path, parent_run_dir="source")
    validate_plan_fingerprint(plan)
    assert plan["jobs"][:len(parent["jobs"])] == parent["jobs"]
    added = plan["jobs"][len(parent["jobs"]):]
    assert len(added) == len(parent["jobs"]) // 2
    assert {job["judge"] for job in added} == {"anthropic"}
    assert all(job["settings"] == FABLE for job in added)
    prompts = {(job["pair_id"], tuple(job["order"])): job["prompt"] for job in parent["jobs"]}
    assert len(prompts) == len(added)
    for job in added:
        assert job["prompt"] == prompts[job["pair_id"], tuple(job["order"])]
    assert len({job["key"] for job in plan["jobs"]}) == len(plan["jobs"])
    assert list(plan["judges"]) == ["anthropic", "gemini", "openai"]
    assert plan["selection"]["judges_per_pair"] == 3
    extension = plan["extension"]
    assert extension["kind"] == "judge_addition" and extension["added_judges"] == ["anthropic"]
    assert extension["imported_jobs"] == len(parent["jobs"]) and extension["additional_jobs"] == len(added)
    assert extension["original_pairs"] == len({job["pair_id"] for job in parent["jobs"]})
    for key in ("agents", "papers", "catalog", "strata", "rubric", "rubric_sha256", "version", "seed"):
        assert plan[key] == parent[key]
    again = add_judge_plan(parent, {"anthropic": FABLE}, tmp_path, parent_run_dir="source")
    assert again["jobs"] == plan["jobs"] and again["fingerprint"] == plan["fingerprint"]


@pytest.mark.parametrize("judges,match", [({}, "nonempty"), ({"openai": FABLE}, "disjoint"),
                                          ({"anthropic": {"effort": "high"}}, "model")])
def test_add_judge_rejects_empty_existing_or_modelless_judges(tmp_path, judges, match):
    parent = _plan(tmp_path, (2, 2, 2, 2), pairs_per_matchup=1)
    with pytest.raises(ValueError, match=match):
        add_judge_plan(parent, judges, tmp_path)


def test_add_judge_rejects_changed_frozen_text(tmp_path):
    parent = _plan(tmp_path, (2, 2, 2, 2), pairs_per_matchup=1)
    (tmp_path / "a-0.txt").write_text("[Page 1]\nAbstract\nEdited after freezing.")
    with pytest.raises(ValueError):
        add_judge_plan(parent, {"anthropic": FABLE}, tmp_path)


def test_judge_extension_imports_paid_votes_and_calls_only_the_new_judge(tmp_path):
    parent, source = _complete_parent(tmp_path)
    destination = tmp_path / "three-judges"
    plan = create_judge_extension(source, destination, tmp_path, new_judges={"anthropic": FABLE})
    imported = json.loads((destination / "imported_results.json").read_text())
    assert len(imported) == len(parent["jobs"])
    assert json.loads((destination / "results.json").read_text()) == imported
    calls = []

    async def fable(prompt, settings, job):
        calls.append(job.key)
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "claude-fable-5-1"}

    async def refuse(prompt, settings, job):
        raise AssertionError("Existing judges must not be called again")
    providers = {"anthropic": SimpleNamespace(judge=fable), **{name: SimpleNamespace(judge=refuse) for name in JUDGES}}
    results = asyncio.run(run_judging(plan, destination, providers=providers, progress=False, workers_per_judge=16))
    added = {job["key"] for job in plan["jobs"] if job["judge"] == "anthropic"}
    assert set(calls) == added and len(calls) == len(added)
    assert len(results) == len(plan["jobs"])
    summary = json.loads((destination / "judging.json").read_text())
    assert summary["imported_jobs"] == len(parent["jobs"]) and summary["newly_completed_jobs"] == len(added)
    assert summary["new_known_usd"] == pytest.approx(.02 * len(added))
    assert create_judge_extension(source, destination, tmp_path, new_judges={"anthropic": FABLE}) == plan
    assert asyncio.run(run_judging(plan, destination, providers=providers, progress=False)) == results
    assert len(calls) == len(added)


def test_uncached_anthropic_jobs_require_the_anthropic_key(tmp_path, monkeypatch):
    parent, source = _complete_parent(tmp_path)
    plan = create_judge_extension(source, tmp_path / "keyless", tmp_path, new_judges={"anthropic": FABLE})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        asyncio.run(run_judging(plan, tmp_path / "keyless", progress=False))


def _turn(input_tokens, output_tokens, final=True):
    return {"model": "claude-fable-5-1", "stop_reason": "end_turn", "_usage_final": final,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}


def test_anthropic_accounting_keeps_billed_turns_and_interrupted_attempts():
    from crest_ais.pipeline import _account
    state = {"raw": {"turns": [_turn(20_000, 1_000)]},
             "interrupted_attempts": [{"cost_usd": .05}]}
    account = _account(state, "anthropic", {"model": "claude-fable-5-1"})
    assert account["cost_usd"] == pytest.approx(20_000 * 10 / 1e6 + 1_000 * 50 / 1e6 + .05)
    failed = {"provider_result": {"raw": {"turns": [_turn(10_000, 500)]}}}
    assert _account(failed, "anthropic", {})["cost_usd"] == pytest.approx(.1 + .025)
    unknown = {"interrupted_attempts": [{"cost_usd": None}]}
    assert _account(unknown, "anthropic", {})["cost_usd"] is None


def test_cli_add_judge_uses_master_settings_normalized_like_existing_judges(tmp_path, monkeypatch):
    from crest_ais import cli
    parent = _plan(tmp_path, (2, 2, 2, 2), pairs_per_matchup=1)
    master = tmp_path / "crest.yaml"
    master.write_text("judges:\n  anthropic:\n    model: claude-fable-5-1\n    effort: high\n"
                      "    max_output_tokens: 32768\n    refusal_fallback: false\n"
                      "    initial_concurrency: 8\n    concurrency: 16\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"data_root": ".", "output_dir": "results", "inherit_judges": "crest.yaml"}))
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "plan.json").write_text(json.dumps(parent))
    seen = []

    def create(source, run, root, **kwargs):
        seen.append(kwargs)
        return {**parent, "jobs": parent["jobs"] * 2, "extension": {"original_pairs": 6, "imported_jobs": len(parent["jobs"])}}
    monkeypatch.setattr(cli, "create_judge_extension", create)
    monkeypatch.setattr(cli, "load_config", lambda *a, **kw: pytest.fail("Frozen settings must come from the parent and master config"))
    assert cli.main(["add-judge", "--config", str(config), "--source-run", str(tmp_path / "source"),
                     "--run-dir", str(tmp_path / "new"), "--judge", "anthropic"]) == 0
    settings = seen[0]["new_judges"]["anthropic"]
    from crest_ais.providers.anthropic import ADAPTER_VERSION
    assert settings == {"model": "claude-fable-5-1", "effort": "high", "max_output_tokens": 32768,
                        "refusal_fallback": False, "initial_concurrency": 2, "concurrency": 2,
                        "timeout_seconds": 900, "poll_interval_seconds": 5, "_adapter_version": ADAPTER_VERSION}
    assert cli.main(["add-judge", "--config", str(config), "--source-run", str(tmp_path / "source"),
                     "--run-dir", str(tmp_path / "other"), "--judge", "openai"]) == 1


def _complete_legacy_parent(tmp_path):
    """Write a finished v2 run the way the original two-judge run left it on disk."""
    from crest.cache import Cache, write_json
    from crest_ais.pipeline import _completed
    from crest_ais.tests.test_protocol_v3 import GOOD_REASON, legacy_plan
    parent = legacy_plan(tmp_path)
    source = tmp_path / "legacy-source"
    cache = Cache(source / ".cache" / "judgments")
    rows = []
    for task in parent["jobs"]:
        state = {"status": "completed", "verdict": GOOD_REASON,
                 "result": {"text": json.dumps(GOOD_REASON), "cost_usd": .01, "usage": {}, "model": "fixture", "warnings": []}}
        write_json(cache.job(task["key"]).path, state)
        rows.append(_completed(task, state))
    write_json(source / "plan.json", parent)
    write_json(source / "results.json", rows)
    return parent, source


def test_legacy_v2_run_accepts_an_added_judge_with_its_exact_prompts(tmp_path):
    parent, source = _complete_legacy_parent(tmp_path)
    assert parent["version"] == "crest-ais-overall-v2"

    async def refuse(prompt, settings, job):
        raise AssertionError("A plain legacy plan must not dispatch")
    with pytest.raises(ValueError, match="protocol version"):
        asyncio.run(run_judging(parent, tmp_path / "replay", providers={name: SimpleNamespace(judge=refuse) for name in parent["judges"]},
                                progress=False))
    plan = create_judge_extension(source, tmp_path / "legacy-three", tmp_path, new_judges={"anthropic": FABLE})
    assert plan["version"] == "crest-ais-overall-v2"
    prompts = {(job["pair_id"], tuple(job["order"])): job["prompt"] for job in parent["jobs"]}
    seen = []

    async def fable(prompt, settings, job):
        seen.append(prompt)
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "claude-fable-5-1"}
    providers = {"anthropic": SimpleNamespace(judge=fable), **{name: SimpleNamespace(judge=refuse) for name in parent["judges"]}}
    results = asyncio.run(run_judging(plan, tmp_path / "legacy-three", providers=providers, progress=False, workers_per_judge=16))
    assert len(results) == len(plan["jobs"]) == len(parent["jobs"]) * 3 // 2
    assert sorted(seen) == sorted(prompts.values())


def test_refused_pairs_keep_the_other_judges_votes_and_never_fill_in_a_vote(tmp_path):
    from crest_ais.cli import _report
    parent, source = _complete_parent(tmp_path)
    destination = tmp_path / "refusals"
    plan = create_judge_extension(source, destination, tmp_path, new_judges={"anthropic": FABLE})
    refused_pair = plan["jobs"][0]["pair_id"]

    async def fable(prompt, settings, job):
        task = next(item for item in plan["jobs"] if item["key"] == job.key)
        if task["pair_id"] == refused_pair:
            raise RuntimeError('Anthropic stop_reason refusal; stop_details={"type": "refusal", "category": "bio"}')
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "claude-fable-5-1"}
    asyncio.run(run_judging(plan, destination, providers={"anthropic": SimpleNamespace(judge=fable)}, progress=False))
    report = _report(plan, destination, tmp_path, destination / "report.html")
    assert report["status"] == "complete" and set(report["judges"]) == {"anthropic", *JUDGES}
    coverage = report["coverage"]
    assert coverage["declined_jobs"] == 2 and coverage["completed_jobs"] == len(plan["jobs"]) - 2
    assert coverage["complete_pairs"] == coverage["expected_pairs"]
    assert coverage["used_decisions"] == len(plan["jobs"]) - 2
    assert {row["pair_id"] for row in report["declined"]} == {refused_pair}
    assert all(row["reason"]["category"] == "bio" for row in report["declined"])
    assert all(row["rank"] is not None for row in report["rankings"])
    refused = [row for row in report["judgments"] if row["pair_id"] == refused_pair]
    assert len(refused) == 4 and {row["judge"] for row in refused} == set(JUDGES)
    # Refusals are not a failure caveat; the run summary states them once.
    assert not any("failed" in line or "refus" in line or "declin" in line for line in report["limitations"])
    html = (destination / "report.html").read_text()
    assert html.count("data-declined=") == 1 and "Claude Fable 5.1 refused this pair" in html
    assert html.count("refused, on safety grounds") == 1
    progress = html.split('<section id="progress"', 1)[1].split("</section>", 1)[0]
    assert "Claude Fable 5.1 refused, on safety grounds, to judge 1 paper pair." in progress
    assert "That pair is scored on the other two judges’ 4 votes" in progress
    assert "added after" not in html and "We added a judge" not in html and "Partial:" not in html
    judges = html.split('<section id="judges"', 1)[1].split("</section>", 1)[0]
    assert "Claude Fable 5.1" in judges and "claude-fable-5-1" not in judges


def test_a_complete_judge_addition_reports_all_judges_in_the_ranking(tmp_path):
    from crest_ais.cli import _report
    parent, source = _complete_parent(tmp_path)
    destination = tmp_path / "complete-three"
    plan = create_judge_extension(source, destination, tmp_path, new_judges={"anthropic": FABLE})

    async def fable(prompt, settings, job):
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "claude-fable-5-1"}
    asyncio.run(run_judging(plan, destination, providers={"anthropic": SimpleNamespace(judge=fable)}, progress=False))
    report = _report(plan, destination, tmp_path, destination / "report.html")
    assert report["status"] == "complete" and "added_judges" not in report
    assert set(report["judges"]) == {"anthropic", *JUDGES}
