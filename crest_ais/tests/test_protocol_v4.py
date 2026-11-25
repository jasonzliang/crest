"""New manuscript plans use crest-ais-overall-v4; frozen v3 plans keep their bytes and keys."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

from crest import judging as shared_judging
from crest_ais import protocol
from crest_ais.analysis import analyze
from crest_ais.pipeline import run_judging
from crest_ais.protocol import extend_plan, make_plan, plan_fingerprint, requires_reason_quality

V3_PAPER_QUESTION = ("Which scientific manuscript has stronger overall creative quality, considering New, "
                     "Useful, and Surprising jointly? Assess each relative to its own field and research task.")
GOOD = {"reason": "A develops a new coupled mechanism on page 1 with evidence on page 2, whereas B uses a "
                  "familiar mechanism on page 1 with narrower evidence on page 2. A therefore makes the "
                  "stronger overall creative contribution despite B's simpler implementation.",
        "winner": "A"}


def papers(tmp_path):
    catalog = []
    for agent in ("a", "b"):
        for index in range(2):
            identity = f"{agent}{index}"
            (tmp_path / f"{identity}.txt").write_text(f"[Page 1] Mechanism {identity}.\n[Page 2] Evidence {identity}.")
            catalog.append({"id": identity, "agent": agent, "eligible_primary": True,
                            "blind_text_path": f"{identity}.txt", "sha256": f"pdf-{identity}"})
    return catalog


def v4_plan(tmp_path, rubric="Compare New, Useful, and Surprising."):
    return make_plan(papers(tmp_path), {"a": "A", "b": "B"}, {"j1": {"model": "m1"}, "j2": {"model": "m2"}},
                     tmp_path, rubric, pairs_per_matchup=1)


def as_frozen_v3(plan, tmp_path):
    """Rebuild the plan exactly as the frozen crest-ais-overall-v3 make_plan produced it."""
    frozen = deepcopy(plan)
    frozen.pop("fingerprint")
    frozen.update(version="crest-ais-overall-v3", judging_protocol="nus-overall-pairwise-v3")
    records = {paper["id"]: paper for paper in frozen["catalog"]}
    texts = {identity: (tmp_path / paper["blind_text_path"]).read_text() for identity, paper in records.items()}
    pairs = list(dict.fromkeys(tuple(job["papers"]) for job in plan["jobs"]))
    frozen["jobs"] = [job for pair in pairs for job in protocol._frozen_pair_jobs(
        [records[identity] for identity in pair], texts, frozen["judges"], frozen["rubric"], V3_PAPER_QUESTION,
        protocol_version="crest-ais-overall-v3")]
    frozen["fingerprint"] = plan_fingerprint(frozen)
    return frozen


def test_new_plans_use_v4_and_say_creative_contribution(tmp_path):
    assert protocol.PROTOCOL_VERSION == "crest-ais-overall-v4"
    assert protocol.JUDGING_VERSION == shared_judging.PROTOCOL_VERSION == "nus-overall-pairwise-v4"
    assert protocol.V3_PROTOCOL_VERSION == "crest-ais-overall-v3"
    assert protocol.V3_PAPER_QUESTION == V3_PAPER_QUESTION
    assert "creative contribution" in protocol.PAPER_QUESTION
    assert "creative quality" not in protocol.PAPER_QUESTION
    plan = v4_plan(tmp_path)
    assert plan["version"] == "crest-ais-overall-v4"
    assert plan["judging_protocol"] == "nus-overall-pairwise-v4"
    assert requires_reason_quality(plan)
    for job in plan["jobs"]:
        assert job["judging_protocol"] == "nus-overall-pairwise-v4"
        assert "creative quality" not in job["prompt"]
        assert "creative contribution" in job["prompt"]
        data = json.loads(job["prompt"].split("UNTRUSTED INPUT DATA (JSON):\n", 1)[1])
        assert data["question"] == protocol.PAPER_QUESTION


def test_frozen_v3_plans_rebuild_byte_identically_and_stay_judgeable(tmp_path):
    plan = v4_plan(tmp_path)
    frozen = as_frozen_v3(plan, tmp_path)
    assert {job["key"] for job in frozen["jobs"]}.isdisjoint(job["key"] for job in plan["jobs"])
    for job in frozen["jobs"]:
        assert "of creative quality, guided jointly" in job["prompt"]
        assert "addressing each guidance aspect" in job["prompt"]
    verified = extend_plan(frozen, tmp_path, pairs_per_matchup=1)
    assert verified["jobs"] == frozen["jobs"] and verified["version"] == "crest-ais-overall-v3"
    assert requires_reason_quality(frozen)
    calls = []

    async def judge(prompt, settings, job):
        calls.append(prompt)
        return {"text": json.dumps(GOOD), "cost_usd": 0.0, "usage": {}, "model": "fixture"}

    providers = {name: SimpleNamespace(judge=judge) for name in frozen["judges"]}
    results = asyncio.run(run_judging(frozen, tmp_path / "run", providers=providers, progress=False))
    assert len(results) == len(frozen["jobs"]) == len(calls)
    assert sorted(calls) == sorted(job["prompt"] for job in frozen["jobs"])
    assert analyze(frozen, results)["status"] == "complete"


def test_aut_paper_wording_is_unchanged_in_v4_plans(tmp_path):
    aut = v4_plan(tmp_path, "RUBRIC ID: aut-inspired-pairwise-v1\nCompare fluency, flexibility, and originality.")
    assert aut["version"] == "crest-ais-overall-v4"
    assert aut["judging_protocol"] == "aut-inspired-overall-pairwise-v1"
    data = json.loads(aut["jobs"][0]["prompt"].split("UNTRUSTED INPUT DATA (JSON):\n", 1)[1])
    assert data["question"] == protocol.AUT_PAPER_QUESTION
    assert "creative quality under the AUT-inspired" in protocol.AUT_PAPER_QUESTION
