"""Shared overall-vote semantics; the pipelines retain different sampling units.

Only balanced, fully observed point estimates are compared. CREST resamples
shared complete questions, while AIS samples paper pairs and withholds ranks
until its whole plan is complete; their uncertainty ranges need not agree.
"""

from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from crest import judging as crest_judging
from crest.analysis import analyze as analyze_crest
from crest_ais import protocol as ais_protocol
from crest_ais.analysis import analyze as analyze_ais
from crest_ais.tests.test_analysis import plan_for, results_for


AGENTS = ("atlas", "birch", "cedar", "delta")
ROOT = Path(__file__).resolve().parents[2]


def test_configured_rubric_and_overall_verdict_protocol_match_current_crest():
    crest_config = yaml.safe_load((ROOT / "crest.yaml").read_text())
    ais_config = json.loads((ROOT / "crest_ais/config.json").read_text())
    crest_rubric = (ROOT / crest_config["rubric"]).read_text()
    ais_rubric = (ROOT / "crest_ais" / ais_config["rubric"]).read_text()
    assert ais_rubric == crest_rubric
    assert ais_protocol.SCHEMA == crest_judging.SCHEMA
    assert set(ais_protocol.SCHEMA["properties"]) == {"reason", "winner"}
    assert ais_protocol.JUDGING_VERSION == crest_judging.PROTOCOL_VERSION
    # AIS adds its manuscript preface when making a plan. The shared overall
    # response instructions and encoding must still behave identically.
    arguments = ("Compare these proposals.", "First proposal", "Second proposal", crest_rubric)
    assert ais_protocol.build_prompt(*arguments) == crest_judging.build_prompt(*arguments)


@pytest.mark.parametrize("winner", ["A", "B"])
def test_both_protocols_accept_one_overall_winner(winner):
    verdict = {"reason": "The overall choice reflects the relevant N/U/S tradeoffs.", "winner": winner}
    assert ais_protocol.validate_verdict(verdict) == crest_judging.validate_verdict(verdict) == verdict
    assert ais_protocol.parse_verdict(json.dumps(verdict)) == crest_judging.parse_verdict(json.dumps(verdict))


@pytest.mark.parametrize("verdict", [
    {"reason": "An overall comparison.", "winner": "tie"},
    {"reason": " ", "winner": "A"},
    {"reason": "An overall comparison.", "winner": "A", "score": 4},
    {criterion: {"reason": "A separate criterion vote.", "winner": "A"}
     for criterion in ("new", "useful", "surprising")},
])
def test_both_protocols_reject_ties_ratings_and_separate_criterion_votes(verdict):
    for validate in (ais_protocol.validate_verdict, crest_judging.validate_verdict):
        with pytest.raises(ValueError):
            validate(verdict)


def _balanced_equivalent_data(block_count):
    plan = plan_for(dict.fromkeys(AGENTS, 2), sample_size=block_count)
    # Number of four overall votes favoring the canonical first agent. The
    # first question has real 3–1 splits; two questions produce shared ranks.
    quotas = (
        {("atlas", "birch"): 3, ("atlas", "cedar"): 4, ("atlas", "delta"): 2,
         ("birch", "cedar"): 2, ("birch", "delta"): 4, ("cedar", "delta"): 1},
        {("atlas", "birch"): 1, ("atlas", "cedar"): 4, ("atlas", "delta"): 4,
         ("birch", "cedar"): 4, ("birch", "delta"): 4, ("cedar", "delta"): 3},
    )
    blocks = defaultdict(dict)
    for job in plan["jobs"]:
        blocks[tuple(job["agents"])].setdefault(job["pair_id"], []).append(job)
    winners, question_for = {}, {}
    for pair, pairs in blocks.items():
        for number, jobs in enumerate(pairs.values()):
            for cell, job in enumerate(jobs):
                winners[job["key"]] = pair[0 if cell < quotas[number][pair] else 1]
                question_for[job["key"]] = f"question-{number}"
    results = results_for(plan, lambda job: winners[job["key"]])
    questions = [{"id": f"question-{n}", "text": f"Shared synthetic task {n}."}
                 for n in range(block_count)]
    answers = [{"question_id": q["id"], "agent": agent,
                "result": {"text": f"Unique proposal from {agent} for {q['id']}.", "cost_usd": 0.0}}
               for q in questions for agent in AGENTS]
    paper_agents = {paper["id"]: paper["agent"] for paper in plan["papers"]}
    judgments = [{"key": job["key"], "question_id": question_for[job["key"]],
                  "pair": job["agents"][:], "order": [paper_agents[p] for p in job["order"]],
                  "judge": job["judge"], "verdict": deepcopy(result["verdict"]), "cost_usd": 0.0}
                 for job, result in zip(plan["jobs"], results)]
    return plan, results, questions, answers, judgments


@pytest.mark.parametrize("block_count,expected_rates,expected_ranks", [
    (1, {"atlas": 3 / 4, "birch": 7 / 12, "cedar": 1 / 4, "delta": 5 / 12},
     {"atlas": 1, "birch": 2, "cedar": 4, "delta": 3}),
    (2, {"atlas": 3 / 4, "birch": 3 / 4, "cedar": 1 / 4, "delta": 1 / 4},
     {"atlas": 1, "birch": 1, "cedar": 3, "delta": 3}),
])
def test_balanced_votes_match_rates_fractional_pair_contributions_ranks_and_matrix(
        block_count, expected_rates, expected_ranks):
    plan, results, questions, answers, judgments = _balanced_equivalent_data(block_count)
    ais = analyze_ais(plan, results)
    crest = analyze_crest(questions, answers, judgments, agents=list(AGENTS),
                          judges=list(plan["judges"]), bootstrap_samples=0)
    ais_rows = {r["agent"]: r for r in ais["rankings"]}
    crest_rows = {r["agent"]: r for r in crest["ranking"]}
    for agent in AGENTS:
        assert ais_rows[agent]["overall_pct"] == pytest.approx(expected_rates[agent] * 100)
        assert crest_rows[agent]["preference_rate"] == pytest.approx(expected_rates[agent])
        assert ais_rows[agent]["overall_pct"] == pytest.approx(crest_rows[agent]["preference_rate"] * 100)
        assert ais_rows[agent]["rank"] == crest_rows[agent]["rank"] == expected_ranks[agent]
        assert ais_rows[agent]["decision_count"] == crest_rows[agent]["choices"] == 12 * block_count
    for matchup in ais["comparisons"]:
        first, second = matchup["agents"]
        assert matchup["overall_pct_a"] == pytest.approx(100 * crest["pairwise"]["overall"][first][second])
        assert 100 - matchup["overall_pct_a"] == pytest.approx(100 * crest["pairwise"]["overall"][second][first])
    atlas_birch = next(r for r in ais["comparisons"] if r["agents"] == ["atlas", "birch"])
    assert atlas_birch["overall_pct_a"] == (75.0 if block_count == 1 else 50.0)
    assert ais["coverage"]["used_decisions"] == 24 * block_count
    assert crest["coverage"]["complete_questions"] == block_count
    for ais_key, crest_key in (("position_a_pct", "position_a_preference"),
                               ("swapped_inconsistency_pct", "swapped_inconsistency"),
                               ("judge_disagreement_pct", "judge_disagreement")):
        assert ais["diagnostics"][ais_key] == pytest.approx(100 * crest["diagnostics"][crest_key]["rate"])
