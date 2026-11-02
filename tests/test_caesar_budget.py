"""The single Caesar budget derives its depth settings and stays under the ceiling."""
import pytest

from crest.caesar_budget import (DERIVED, DRAFT_WRITE_USD, PRICES, SETUP_SECONDS, SOL, TIME_MARGIN, exploration,
                                 plan, qa_rounds_cost, qa_rounds_seconds, write_bound, write_hold)
from crest.config import load_config


@pytest.mark.parametrize("budget", [1.5, 3.0, 4.0, 6.0])
def test_plan_fits_the_margin_and_grows_with_the_budget(budget):
    result = plan(budget)
    assert result["estimate"]["total_usd"] <= budget * .85 + 1e-9
    assert set(result["settings"]) == set(DERIVED)
    assert result["settings"]["synthesis_reserve_usd"] >= result["estimate"]["synthesis_usd"]
    larger = plan(budget + 1)["settings"]
    assert larger["max_iterations"] > result["settings"]["max_iterations"]
    assert larger["timeout_seconds"] >= result["settings"]["timeout_seconds"]


@pytest.mark.parametrize("budget", [0, 0.5])
def test_plan_rejects_budgets_below_the_fixed_costs(budget):
    with pytest.raises(ValueError):
        plan(budget)


def test_exploration_and_qa_models_reproduce_the_october_run():
    usd, seconds = exploration(112)  # October averaged 112 iterations, $0.414 and 40.3 minutes per answer
    assert usd == pytest.approx(.414, rel=.05) and seconds / 60 == pytest.approx(40.3, rel=.05)
    assert 3 * qa_rounds_cost(15) == pytest.approx(.79, rel=.10)  # 3 drafts x 15 rounds cost $0.79
    assert 3 * qa_rounds_seconds(15) / 60 == pytest.approx(19.1, rel=.05)


def test_one_timeout_covers_setup_exploration_and_synthesis_with_the_margin():
    result = plan(3.5)
    settings, estimate = result["settings"], result["estimate"]
    _, exploration_seconds = exploration(settings["max_iterations"])
    total = SETUP_SECONDS + exploration_seconds + estimate["synthesis_minutes"] * 60
    assert estimate["exploration_minutes"] == pytest.approx(exploration_seconds / 60, abs=.1)
    assert total * TIME_MARGIN <= settings["timeout_seconds"] < total * TIME_MARGIN + 300
    assert settings["timeout_seconds"] % 300 == 0


@pytest.mark.parametrize("budget", [1.5, 3.0, 3.5, 4.0])
def test_planned_rounds_fit_the_first_draft_allowance_after_the_write_hold(budget):
    estimate = plan(budget)["estimate"]
    assert estimate["qa_usd_per_draft"] <= estimate["first_draft_allowance_usd"] + 1e-9
    assert estimate["qa_usd_per_draft"] == pytest.approx(qa_rounds_cost(plan(budget)["settings"]["synthesis_iterations"]), abs=1e-4)


def test_write_bound_follows_the_completion_limit_and_prices():
    assert write_bound({"max_completion_tokens": 10000}) == pytest.approx(.175)
    assert write_bound({"max_completion_tokens": 25000}) == pytest.approx(.325)
    cheap = {"max_completion_tokens": 5, "model_pricing": {SOL: {"input": 0, "output": 10000}}}
    assert write_bound(cheap) == pytest.approx(.05)
    assert write_bound({}) == pytest.approx((30_000 * PRICES[SOL]["cache_write"] + 10000 * PRICES[SOL]["output"]) / 1e6)


def test_write_hold_shrinks_as_drafts_finish_and_drops_the_merge():
    settings = {"max_completion_tokens": 10000}
    holds = [write_hold(settings, remaining) for remaining in (3, 2, 1)]
    assert holds == sorted(holds, reverse=True) and holds[-1] > write_bound(settings)
    assert write_hold(settings, 1, merge=False) == pytest.approx(write_bound(settings))  # the last write is the bound itself
    assert write_hold(settings, 1, merge=True) == pytest.approx(write_bound(settings) + 2 * DRAFT_WRITE_USD)


def test_master_config_derives_null_caesar_settings_and_keeps_explicit_ones(write_master_config):
    caesar = load_config()["research"]["caesar"]
    assert (caesar["max_iterations"], caesar["synthesis_drafts"], caesar["synthesis_iterations"]) == (300, 3, 20)
    assert {key: caesar[key] for key in DERIVED} == plan(caesar["budget_usd"], settings=caesar)["settings"]
    custom = load_config(write_master_config(**{"research.caesar.budget_usd": 3.0,
                                                "research.caesar.synthesis_drafts": 2}))["research"]["caesar"]
    assert custom["synthesis_drafts"] == 2 and custom["max_iterations"] == 300  # explicit depth is kept
    assert custom["synthesis_reserve_usd"] == plan(3.0, settings=custom)["settings"]["synthesis_reserve_usd"]
    derived = load_config(write_master_config(**{"research.caesar.budget_cap": "auto",
                                                 "research.caesar.budget_usd": 2.0}))["research"]["caesar"]
    assert derived["max_iterations"] == plan(2.0, settings={"max_completion_tokens": 10000})["settings"]["max_iterations"] < 300


def test_explicit_depth_above_the_budget_is_rejected_at_load_under_a_hard_cap(write_master_config):
    with pytest.raises(ValueError, match="above budget_usd"):
        load_config(write_master_config(**{"research.caesar.budget_cap": "hard", "research.caesar.budget_usd": 2.0}))


def test_explicit_depth_is_kept_and_costed():
    chosen = {"max_completion_tokens": 10000, "max_iterations": 300, "synthesis_drafts": 3, "synthesis_iterations": 20}
    result = plan(3.5, settings=chosen)
    assert {k: result["settings"][k] for k in ("max_iterations", "synthesis_drafts", "synthesis_iterations")} == {"max_iterations": 300, "synthesis_drafts": 3, "synthesis_iterations": 20}
    estimate = result["estimate"]
    assert estimate["chosen"] == {"max_iterations": 300, "synthesis_drafts": 3, "synthesis_iterations": 20}
    assert estimate["total_usd"] == pytest.approx(.05 + exploration(300)[0] + 3 * .05 + 2 * .01 + .03 + 3 * qa_rounds_cost(20), abs=1e-4)
    assert estimate["total_usd"] < 3.5 and result["settings"]["synthesis_reserve_usd"] == pytest.approx(estimate["synthesis_usd"] * 1.1, abs=.01)
    assert estimate["warnings"] == [] or all("target" in w or "allowance" in w for w in estimate["warnings"])
    too_deep = plan(2.0, settings={**chosen, "max_iterations": 600})["estimate"]
    assert too_deep["total_usd"] > 2.0 and any("above budget_usd" in warning for warning in too_deep["warnings"])
