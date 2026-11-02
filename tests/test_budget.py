"""The master budget calculator keeps every research agent under its budget."""
import json

import pytest

from crest.budget import AGENTS, main, plan, rounds_cost


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
