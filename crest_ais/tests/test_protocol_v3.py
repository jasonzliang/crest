"""Prospective contract checks and compatibility with an actual v2 plan."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from crest.cache import Cache
from crest_ais.analysis import analyze
from crest_ais.pipeline import run_judging
from crest_ais.protocol import extend_plan, make_plan


LEGACY_PLAN = Path(__file__).parent / "fixtures" / "overall_v2_plan.json"
REJECTED_REASON = {"reason": "Wait, no markdown!", "winner": "A"}
GOOD_REASON = {
    "reason": "A develops a new coupled mechanism on page 1 with evidence on page 2, whereas B uses a familiar mechanism on page 1 with narrower evidence on page 2. A therefore offers stronger overall creative quality despite B's simpler implementation.",
    "winner": "A",
}


def legacy_plan(tmp_path):
    plan = json.loads(LEGACY_PLAN.read_text())
    for agent in ("a", "b"):
        (tmp_path / f"{agent}.txt").write_text(
            f"[Page 1]\nThe complete manuscript {agent} explains a mechanism.\n[Page 2]\nExperimental evidence {agent}.")
    return plan


def new_plan(tmp_path):
    frozen = legacy_plan(tmp_path)
    return make_plan(frozen["catalog"], frozen["agents"], frozen["judges"],
                     tmp_path, "Compare overall creativity using New, Useful, and Surprising.",
                     pairs_per_matchup=1)


def result_rows(plan, verdict):
    return [{"key": job["key"], "verdict": deepcopy(verdict), "cost_usd": 0.01,
             "usage": {}, "model": "fixture", "warnings": []} for job in plan["jobs"]]


def test_new_plan_versions_change_keys_without_changing_paper_draw(tmp_path):
    old = legacy_plan(tmp_path)
    plan = new_plan(tmp_path)
    assert plan["version"] == "crest-ais-overall-v3"
    assert plan["judging_protocol"] == "nus-overall-pairwise-v3"
    assert plan["sampling_version"] == "crest-ais-v1"
    assert plan["presentation_version"] == "citation-neutral-v1"
    assert [(job["pair_id"], job["papers"], job["order"])
            for job in plan["jobs"]] == [(job["pair_id"], job["papers"], job["order"])
                                       for job in old["jobs"]]
    assert {job["key"] for job in old["jobs"]}.isdisjoint(job["key"] for job in plan["jobs"])


def test_new_prompts_neutralize_urls_and_record_raw_and_presented_hashes(tmp_path):
    old = legacy_plan(tmp_path)
    raw = "[Page 1]\nA mechanism [source](https://example.org/paper?utm_source=openai)."
    (tmp_path / "a.txt").write_text(raw)
    plan = make_plan(old["catalog"], old["agents"], old["judges"], tmp_path, "Compare creativity.")
    job = plan["jobs"][0]
    data = json.loads(job["prompt"].split("UNTRUSTED INPUT DATA (JSON):\n", 1)[1])
    assert "utm_source" not in data["A"]
    assert "example.org" not in data["A"]
    assert "A mechanism" in data["A"]
    assert job["answer_hashes"][0] == hashlib.sha256(raw.encode()).hexdigest()
    assert job["presented_answer_hashes"][0] == hashlib.sha256(data["A"].encode()).hexdigest()
    assert job["presentation_version"] == "citation-neutral-v1"
    assert job["judging_protocol"] == "nus-overall-pairwise-v3"
    assert (tmp_path / "a.txt").read_text() == raw


def test_raw_url_changes_preserve_presentation_but_invalidate_job_identity(tmp_path):
    old = legacy_plan(tmp_path)
    plans = []
    for provider in ("openai", "google"):
        (tmp_path / "a.txt").write_text(
            f"[Page 1]\nA mechanism [source](https://example.org/paper?utm_source={provider}).")
        plans.append(make_plan(old["catalog"], old["agents"], old["judges"], tmp_path, "Compare creativity."))
    assert [job["prompt"] for job in plans[0]["jobs"]] == [job["prompt"] for job in plans[1]["jobs"]]
    assert {job["key"] for job in plans[0]["jobs"]}.isdisjoint(job["key"] for job in plans[1]["jobs"])


def test_identical_presentations_cannot_create_paid_comparisons(tmp_path):
    old = legacy_plan(tmp_path)
    for agent, provider in (("a", "openai"), ("b", "google")):
        (tmp_path / f"{agent}.txt").write_text(
            f"[Page 1]\nA mechanism [source](https://example.org/paper?utm_source={provider}).")
    with pytest.raises(ValueError, match="Identical|identical"):
        make_plan(old["catalog"], old["agents"], old["judges"], tmp_path, "Compare creativity.")


def test_frozen_v2_plan_can_be_validated_and_analyzed_with_old_reason_rules(tmp_path):
    old = legacy_plan(tmp_path)
    verified = extend_plan(old, tmp_path, pairs_per_matchup=1)
    assert verified["jobs"] == old["jobs"]
    assert verified["version"] == "crest-ais-overall-v2"
    assert analyze(old, result_rows(old, REJECTED_REASON))["status"] == "complete"


def test_new_analysis_rejects_reason_that_legacy_analysis_preserves(tmp_path):
    plan = new_plan(tmp_path)
    with pytest.raises(ValueError, match="reason"):
        analyze(plan, result_rows(plan, REJECTED_REASON))
    assert analyze(plan, result_rows(plan, GOOD_REASON))["status"] == "complete"


@pytest.mark.parametrize("cached", [False, True])
def test_new_live_or_cached_rejected_reason_becomes_terminal_invalid(tmp_path, cached):
    plan = new_plan(tmp_path)
    run_dir = tmp_path / "run"
    cache = Cache(run_dir / ".cache" / "judgments")
    if cached:
        cache.job(plan["jobs"][0]["key"]).save(
            status="completed", verdict=REJECTED_REASON,
            result={"text": json.dumps(REJECTED_REASON), "cost_usd": 0.02,
                    "usage": {}, "model": "fixture"})

    async def judge(prompt, settings, job):
        return {"text": json.dumps(REJECTED_REASON), "cost_usd": 0.02,
                "usage": {}, "model": "fixture"}

    providers = {name: SimpleNamespace(judge=judge) for name in plan["judges"]}
    assert asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False)) == []
    assert all(cache.job(job["key"]).state["status"] == "invalid_verdict" for job in plan["jobs"])
    failures = json.loads((run_dir / "failures.json").read_text())
    assert len(failures) == 4
    assert json.loads((run_dir / "judging.json").read_text())["known_usd"] == pytest.approx(0.08)
