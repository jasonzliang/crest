"""The single Caesar budget derives its depth settings and stays under the ceiling."""
import json

import pytest

from crest.providers.caesar_budget import (DERIVED, DRAFT_WRITE_USD, PRICES, SETUP_SECONDS, SOL, TIME_MARGIN, exploration,
                                 main, plan, qa_rounds_cost, qa_rounds_seconds, write_bound, write_hold)
from crest.config import load_config


@pytest.mark.parametrize("budget", [1.5, 3.0, 3.5, 4.0, 6.0])
def test_plan_fits_the_margin_grows_with_the_budget_and_times_every_phase(budget):
    result = plan(budget)
    settings, estimate = result["settings"], result["estimate"]
    assert estimate["total_usd"] <= budget * .85 + 1e-9
    assert set(settings) == set(DERIVED)
    assert settings["synthesis_reserve_usd"] >= estimate["synthesis_usd"]
    larger = plan(budget + 1)["settings"]
    assert larger["max_iterations"] > settings["max_iterations"]
    assert larger["timeout_seconds"] >= settings["timeout_seconds"]
    # Planned rounds fit the first-draft allowance left after the write hold.
    assert estimate["qa_usd_per_draft"] <= estimate["first_draft_allowance_usd"] + 1e-9
    assert estimate["qa_usd_per_draft"] == pytest.approx(qa_rounds_cost(settings["synthesis_iterations"]), abs=1e-4)
    # One timeout covers setup, exploration and synthesis with the margin.
    _, exploration_seconds = exploration(settings["max_iterations"])
    total = SETUP_SECONDS + exploration_seconds + estimate["synthesis_minutes"] * 60
    assert estimate["exploration_minutes"] == pytest.approx(exploration_seconds / 60, abs=.1)
    assert total * TIME_MARGIN <= settings["timeout_seconds"] < total * TIME_MARGIN + 300
    assert settings["timeout_seconds"] % 300 == 0


@pytest.mark.parametrize("budget", [0, 0.5])
def test_plan_rejects_budgets_below_the_fixed_costs(budget):
    with pytest.raises(ValueError):
        plan(budget)


def test_exploration_and_qa_models_reproduce_the_october_run():
    usd, seconds = exploration(112)  # October averaged 112 iterations, $0.414 and 40.3 minutes per answer
    assert usd == pytest.approx(.414, rel=.05) and seconds / 60 == pytest.approx(40.3, rel=.05)
    assert 3 * qa_rounds_cost(15) == pytest.approx(.79, rel=.10)  # 3 drafts x 15 rounds cost $0.79
    assert 3 * qa_rounds_seconds(15) / 60 == pytest.approx(19.1, rel=.05)


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


@pytest.mark.parametrize("remaining,merge,expected", [
    (3, True, 1.88072), (2, True, 1.34304), (1, True, .80536),
    (3, False, 1.47804), (2, False, .94036), (1, False, .40268),
])
def test_xhigh_write_hold_reserves_every_remaining_write_and_refinement(remaining, merge, expected):
    settings = {"synthesis_reasoning_effort": "xhigh", "max_completion_tokens": 32768,
                "query_max_completion_tokens": 6000}
    assert write_bound(settings) == pytest.approx(.40268)
    assert write_hold(settings, remaining, merge) == pytest.approx(expected)


@pytest.mark.parametrize("writer_limit,query_limit,expected_hold", [
    (32768, None, 1.88072), (32768, 3000, 1.82072), (32768, 65536, 2.41608),
    (1000, 6000, .51),
])
def test_xhigh_refinement_hold_uses_query_cap_limited_by_writer(writer_limit, query_limit, expected_hold):
    settings = {"synthesis_reasoning_effort": "xhigh", "max_completion_tokens": writer_limit}
    if query_limit is not None:
        settings["query_max_completion_tokens"] = query_limit
    before = dict(settings)
    assert write_hold(settings, 3) == pytest.approx(expected_hold)
    assert settings == before


def test_xhigh_write_hold_uses_configured_model_prices_for_all_calls():
    settings = {"synthesis_reasoning_effort": "xhigh", "max_completion_tokens": 32768,
                "query_max_completion_tokens": 6000, "model": "custom-writer",
                "model_pricing": {"custom-writer": {"input": 4, "cache_write": 5, "output": 20}}}
    assert write_hold(settings, 3) == pytest.approx(4 * .80536 + 2 * .27)


@pytest.mark.parametrize("effort", [None, "medium", "high"])
def test_non_xhigh_write_hold_keeps_legacy_allowances_at_larger_output_limit(effort):
    settings = {"max_completion_tokens": 32768, "reasoning_effort": "xhigh"}
    if effort is not None:
        settings["synthesis_reasoning_effort"] = effort
    assert [write_hold(settings, n) for n in (3, 2, 1)] == pytest.approx([.74268, .62268, .50268])
    assert write_hold(settings, 1, merge=False) == pytest.approx(.40268)
    assert write_hold(None, 3) == pytest.approx(.515)


def test_xhigh_plan_labels_historical_estimates_and_input_heuristic_without_recalibrating():
    chosen = {"max_completion_tokens": 32768, "query_max_completion_tokens": 6000,
              "max_iterations": 300, "synthesis_drafts": 3, "synthesis_iterations": 20}
    legacy = plan(4, settings=chosen)
    medium = plan(4, settings={**chosen, "synthesis_reasoning_effort": "medium"})
    assert medium == legacy
    xhigh = plan(4, settings={**chosen, "synthesis_reasoning_effort": "xhigh"})
    assert xhigh["settings"] == legacy["settings"]
    for key in ("total_usd", "synthesis_usd", "total_minutes", "synthesis_minutes", "measured_runs"):
        assert xhigh["estimate"][key] == legacy["estimate"][key]
    estimate = xhigh["estimate"]
    assert estimate["total_usd"] == pytest.approx(3.034)  # Historical baseline, not an xhigh forecast.
    assert estimate["write_hold_usd"] == pytest.approx(1.8807)
    assert estimate["first_draft_allowance_usd"] == pytest.approx(.2293)
    assert any("allowance" in warning for warning in estimate["warnings"])
    assert any(all(term in warning for term in ("xhigh", "uncalibrated", "medium", "600-word"))
               for warning in estimate["warnings"])
    assert any(all(term in warning for term in ("30,000", "heuristic", "not enforced"))
               for warning in estimate["warnings"])
    assert not any("uncalibrated" in warning for warning in legacy["estimate"]["warnings"])


def test_master_config_keeps_chosen_depth_and_derives_explicitly_null_settings(write_master_config):
    caesar = load_config()["research"]["caesar"]
    assert (caesar["max_iterations"], caesar["synthesis_drafts"], caesar["synthesis_iterations"]) == (300, 3, 20)
    # Nulls opt into historical derivation; master reserve/timeout may instead be explicit.
    custom = load_config(write_master_config(**{
        "research.caesar.budget_usd": 3.0, "research.caesar.synthesis_drafts": 2,
        "research.caesar.synthesis_reserve_usd": None, "research.caesar.timeout_seconds": None,
        "research.caesar.synthesis_reasoning_effort": "medium",
        "research.caesar.max_completion_tokens": 10000,
    }))["research"]["caesar"]
    assert custom["synthesis_drafts"] == 2 and custom["max_iterations"] == 300
    assert {key: custom[key] for key in DERIVED} == plan(3.0, settings=custom)["settings"]


def test_master_config_preserves_explicit_xhigh_reserve_timeout_and_output_limits(write_master_config):
    overrides = {"synthesis_reasoning_effort": "xhigh", "max_completion_tokens": 32768,
                 "query_max_completion_tokens": 6000, "call_timeout_seconds": 1200,
                 "timeout_seconds": 21600, "synthesis_reserve_usd": 2.6}
    custom = load_config(write_master_config(**{
        **{"research.caesar." + key: value for key, value in overrides.items()},
        "research.caesar.budget_cap": "hard", "research.caesar.budget_usd": 4.0,
    }))["research"]["caesar"]
    assert {key: custom[key] for key in overrides} == overrides
    historical = plan(4.0, settings=custom)["settings"]
    assert custom["synthesis_reserve_usd"] != historical["synthesis_reserve_usd"]
    assert custom["timeout_seconds"] != historical["timeout_seconds"]


@pytest.mark.parametrize("effort,budget,writer_limit", [("medium", 2.0, 10000), ("xhigh", 4.0, 32768)])
def test_auto_budget_still_derives_depth_reserve_and_timeout(write_master_config, effort, budget, writer_limit):
    derived = load_config(write_master_config(**{
        "research.caesar.budget_cap": "auto", "research.caesar.budget_usd": budget,
        "research.caesar.synthesis_reasoning_effort": effort,
        "research.caesar.max_completion_tokens": writer_limit,
        "research.caesar.synthesis_reserve_usd": 2.6, "research.caesar.timeout_seconds": 21600,
    }))["research"]["caesar"]
    probe = {**derived, **{key: None for key in DERIVED}}
    assert {key: derived[key] for key in DERIVED} == plan(budget, settings=probe)["settings"]
    if effort == "medium":
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


def test_cli_prints_the_plan_for_the_given_budget_and_depth(capsys):
    assert main(["3.5", "--max-iterations", "300"]) == 0
    expected = plan(3.5, settings={"max_completion_tokens": 10000, "max_iterations": 300})
    assert json.loads(capsys.readouterr().out) == expected
