"""Research budgets: the calculator, continuation rounds, auto caps and overspend warnings."""
import asyncio
import json

import pytest

from crest.budget import AGENTS, main, plan, rounds_cost
from crest.config import load_config
from crest.pipeline import Pipeline
from crest.providers import budget_is_hard, needs_more_research
from crest.providers.caesar_budget import DERIVED


def test_hosted_plans_reproduce_the_hand_set_floor_and_round_caps():
    assert plan("openai", 4.0)["settings"] == {"budget_floor_usd": 3.0, "max_research_rounds": 6}
    assert plan("anthropic", 4.0)["settings"] == {"budget_floor_usd": 3.0, "max_research_rounds": 14}
    assert rounds_cost("openai", 5) == pytest.approx(3.75) and rounds_cost("anthropic", 13) == pytest.approx(3.12)
    assert plan("openai", 4.0)["estimate"]["expected_usd"] == pytest.approx(3.12, abs=.01)    # pilot: $3.13
    assert plan("anthropic", 4.0)["estimate"]["expected_usd"] == pytest.approx(2.94, abs=.01)  # pilot: $3.09


def test_caesar_and_gemini_plans():
    caesar = plan("caesar", 3.5, {"max_completion_tokens": 10000})
    assert caesar["settings"]["max_iterations"] == 309 and caesar["estimate"]["total_usd"] <= 3.5 * .85 + 1e-9
    gemini = plan("gemini", 4.0)
    assert gemini["settings"] == {} and gemini["estimate"]["expected_usd"] == 1.81


@pytest.mark.parametrize("agent, budget", [("mystery", 4.0), ("openai", 0), ("openai", float("nan"))])
def test_unknown_agents_and_bad_budgets_are_rejected(agent, budget):
    with pytest.raises(ValueError):
        plan(agent, budget)


def test_cli_prints_every_agent(capsys):
    assert main(["4.0"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == set(AGENTS) and printed["anthropic"]["settings"]["max_research_rounds"] == 14
    assert main(["3.5", "--agent", "caesar"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"caesar"}


def test_another_round_must_land_near_the_floor_and_under_the_ceiling():
    settings = {"budget_usd": 4.0, "budget_floor_usd": 3.0, "max_research_rounds": 6}
    assert needs_more_research(settings, 2, 0.98, 0.68)          # 1.66 projected: still short of the floor
    assert not needs_more_research(settings, 3, 2.78, 1.80)      # 4.58 projected: past the ceiling
    assert not needs_more_research(settings, 3, 2.40, 1.40)      # 3.80 projected overshoots 3.0 by more than the 0.60 shortfall
    assert needs_more_research(settings, 3, 2.80, 0.25)          # 3.05 projected: overshoot 0.05 within the 0.20 shortfall
    assert not needs_more_research(settings, 1, 3.2, 0.1)        # floor reached
    assert not needs_more_research(settings, 6, 1.0, 0.1)        # round cap
    assert not needs_more_research(settings, 1, None, 0.1)       # unknown cost never continues


def test_soft_cap_rounds_aim_at_the_floor_but_ignore_the_ceiling():
    soft = {"budget_cap": "soft", "budget_usd": 3.0, "budget_floor_usd": 3.0, "max_research_rounds": 6}
    assert needs_more_research(soft, 3, 2.80, 0.25)           # 3.05 projected: over the ceiling, inside the aim's shortfall
    assert not needs_more_research({**soft, "budget_cap": "hard"}, 3, 2.80, 0.25)  # the hard cap stops at the ceiling
    assert not needs_more_research(soft, 3, 2.50, 1.20)       # 3.70 projected overshoots the aim by more than the 0.50 shortfall
    assert not needs_more_research(soft, 3, 3.05, 0.5)        # the floor is reached
    assert not needs_more_research(soft, 6, 1.0, 0.5)         # rounds exhausted
    assert not needs_more_research({**soft, "budget_floor_usd": None}, 1, 1.0, 0.5)  # no aim: one round
    assert budget_is_hard({"budget_cap": "auto"}) and budget_is_hard({}) and not budget_is_hard(soft)


def test_auto_cap_overrides_configured_depth_and_reports_every_override(write_master_config, capsys):
    config = load_config(write_master_config(**{"research.caesar.budget_cap": "auto", "research.caesar.budget_usd": 3.5,
                                                "research.openai.budget_cap": "auto", "research.openai.budget_usd": 3.5}))
    caesar, hosted = config["research"]["caesar"], config["research"]["openai"]
    # Auto derives depth, but must retain the active model/effort/output profile.
    probe = {key: value for key, value in caesar.items() if key not in DERIVED}
    derived = plan("caesar", 3.5, probe)["settings"]
    assert {k: caesar[k] for k in derived} == derived and derived["max_iterations"] != 300  # 300/3/20 overridden
    assert (hosted["budget_floor_usd"], hosted["max_research_rounds"]) == (2.62, 6)
    changed = {(o["agent"], o["setting"]): (o["from"], o["to"]) for o in config["budget_overrides"]}
    assert changed[("caesar", "max_iterations")] == (300, derived["max_iterations"])
    assert changed[("caesar", "synthesis_iterations")] == (20, derived["synthesis_iterations"])
    assert ("caesar", "synthesis_drafts") not in changed  # unchanged values are not reported
    assert changed[("openai", "budget_floor_usd")] == (3.0, 2.62)
    err = capsys.readouterr().err
    assert f"budget_cap auto: research.caesar.max_iterations 300 -> {derived['max_iterations']} (derived from budget_usd 3.5 by crest/budget.py)" in err
    assert "research.openai.budget_floor_usd 3.0 -> 2.62" in err
    assert load_config()["budget_overrides"] == []  # Fixed-depth hard/soft caps override nothing


@pytest.mark.parametrize("cost, other_exceeded, anthropic_exceeded", [
    (3.75, False, False), (4.0, False, False), (4.25, True, False),
    (4.5, True, False), (4.75, True, True),
])
def test_research_budget_warnings_respect_each_agents_ceiling(
        tmp_path, write_master_config, cost, other_exceeded, anthropic_exceeded):
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"query": "Design a new game."}) + "\n")
    config = load_config(write_master_config(**{
        "questions": str(questions), "cache_dir": str(tmp_path / "cache"),
        "output_dir": str(tmp_path / "results"),
    }))

    class Provider:
        ADAPTER_VERSION = "offline-budget-check"

        async def generate(self, prompt, settings, job):
            return {"text": "A complete answer.", "model": "offline", "cost_usd": cost,
                    "citations": [], "usage": {}, "raw": {}, "warnings": []}

    summary = asyncio.run(Pipeline(config, providers={name: Provider() for name in config["research"]}).generate())
    assert summary["completed"] == len(config["research"])
    answer_path = next((tmp_path / "results").rglob("answers.jsonl"))
    rows = [json.loads(line) for line in answer_path.read_text().splitlines()]
    assert {row["agent"] for row in rows} == set(config["research"])
    for row in rows:
        result = row["result"]
        exceeded = anthropic_exceeded if row["agent"] == "anthropic" else other_exceeded
        assert result.get("budget_exceeded", False) is exceeded, row["agent"]
        warnings = [warning for warning in result["warnings"] if "budget" in warning]
        assert bool(warnings) is exceeded
        if exceeded:
            assert ("$4.50" if row["agent"] == "anthropic" else "$4.00") in warnings[0]
            assert ("soft cap" in warnings[0]) == (config["research"][row["agent"]]["budget_cap"] == "soft")
