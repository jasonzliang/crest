"""Hand-calculated checks for fixed-pool pairwise analysis."""

from copy import deepcopy
from itertools import combinations, product
import json

import pytest

from crest_ais.analysis import analyze
from crest_ais.protocol import make_plan


def plan_for(counts=None, sample_size=4):
    counts = counts or {"a": 1, "b": 1}
    papers = [
        {"id": f"{agent}{i}", "agent": agent, "title": f"Paper {agent}{i}",
         "pdf_path": f"data/{agent}{i}.pdf", "eligible_primary": True}
        for agent, count in counts.items() for i in range(count)
    ]
    plan = {"version": "crest-ais-overall-v2", "agents": {a: a.upper() for a in counts},
            "judges": {"j1": {}, "j2": {}}, "papers": papers,
            "catalog": deepcopy(papers), "selection": {"method": "uniform_without_replacement"},
            "seed": 2026, "pairs_per_matchup": sample_size, "strata": [], "jobs": []}
    for a, b in combinations(counts, 2):
        population = list(product([p for p in papers if p["agent"] == a],
                                  [p for p in papers if p["agent"] == b]))
        selected = population[:sample_size]
        plan["strata"].append({"agents": [a, b], "population_pairs": len(population),
                               "sampled_pairs": len(selected)})
        for pa, pb in selected:
            pair_id = f"{pa['id']}:{pb['id']}"
            for order in ([pa["id"], pb["id"]], [pb["id"], pa["id"]]):
                for judge in plan["judges"]:
                    plan["jobs"].append({
                        "key": f"{pair_id}:{order[0]}:{judge}", "pair_id": pair_id,
                        "agents": [a, b], "papers": [pa["id"], pb["id"]],
                        "order": order, "judge": judge, "settings": {}, "prompt": "Compare"})
    return plan


def results_for(plan, winners=None):
    """winners(job) returns a canonical agent id for the one overall verdict."""
    records = []
    for job in plan["jobs"]:
        agent = winners(job) if winners else job["agents"][0]
        paper = job["papers"][job["agents"].index(agent)]
        verdict = {"reason": f"Overall creativity evidence for {paper}",
                   "winner": "A" if job["order"][0] == paper else "B"}
        records.append({"key": job["key"], "verdict": verdict,
                        "cost_usd": 0.1, "usage": {}, "model": "fixture", "warnings": []})
    return records


def ranking(report, agent):
    return next(row for row in report["rankings"] if row["agent"] == agent)


def test_reversed_labels_and_four_overall_judgment_averages():
    plan = plan_for()
    keys = [j["key"] for j in plan["jobs"]]

    def winner(job):
        index = keys.index(job["key"])
        return "a" if index < 3 else "b"

    report = analyze(plan, results_for(plan, winner))
    a = ranking(report, "a")
    assert not a.get("metrics")
    assert a["overall_pct"] == 75.0
    assert ranking(report, "b")["overall_pct"] == 25.0
    assert a["rank"] == 1
    assert report["coverage"]["expected_decisions"] == 4
    assert report["coverage"]["used_decisions"] == 4
    assert report["comparisons"][0]["decision_count"] == 4
    assert a["intervals"] == {"overall": {"low": 75.0, "high": 75.0}}
    assert not report["comparisons"][0].get("metrics_pct_a")
    assert report["status"] == "complete"


def test_unequal_matchup_sizes_receive_equal_opponent_weight_and_ties():
    plan = plan_for({"a": 2, "b": 2, "c": 1})

    def winner(job):
        return {("a", "b"): "a", ("a", "c"): "c", ("b", "c"): "b"}[tuple(job["agents"])]

    report = analyze(plan, results_for(plan, winner))
    # A wins four A/B pairs, loses two A/C pairs: macro=50%, pooled=66.7%.
    assert [row["overall_pct"] for row in report["rankings"]] == [50.0, 50.0, 50.0]
    assert [row["rank"] for row in report["rankings"]] == [1, 1, 1]
    assert ranking(report, "a")["decision_count"] == 24
    assert report["coverage"]["complete_pairs"] == 8
    assert report["diagnostics"]["position_a_pct"] == 50.0
    assert report["diagnostics"]["swapped_inconsistency_pct"] == 0.0
    assert report["diagnostics"]["judge_disagreement_pct"] == 0.0


def test_five_scientists_weight_four_opponents_equally_with_six_pair_census():
    # A two-paper pool versus a three-paper pool is a six-pair census; every
    # other matchup samples ten pairs. B's 3–1 pair wins must remain fractional.
    plan = plan_for({"a": 2, "b": 3, "c": 5, "d": 5, "e": 5}, sample_size=10)
    block_keys = {}
    for job in plan["jobs"]:
        block_keys.setdefault(job["pair_id"], []).append(job["key"])

    def winner(job):
        a, b = job["agents"]
        if (a, b) == ("a", "b"):
            return "b" if block_keys[job["pair_id"]].index(job["key"]) < 3 else "a"
        return b if a == "b" else a

    results = results_for(plan, winner)
    report = analyze(plan, results)
    by_agent = {row["agent"]: row for row in report["rankings"]}
    # B has 75% against A and 0% against C/D/E: macro=18.75%; pooling votes
    # would incorrectly give 18/144=12.5% because the winning stratum is smaller.
    assert by_agent["b"]["overall_pct"] == 18.75
    assert by_agent["a"]["overall_pct"] == 81.25
    assert [row["agent"] for row in report["rankings"]] == ["a", "c", "d", "e", "b"]
    assert [row["rank"] for row in report["rankings"]] == [1, 2, 3, 4, 5]
    assert all(row["expected_opponents"] == row["opponents_with_data"] == 4 for row in report["rankings"])
    assert by_agent["b"]["decision_count"] == 144
    assert by_agent["c"]["decision_count"] == 160
    census = next(c for c in report["comparisons"] if c["agents"] == ["a", "b"])
    assert census["complete_pairs"] == census["population_pairs"] == 6
    assert census["overall_pct_a"] == 25.0
    assert census["sampling"]["overall"]["interval"] == {"low": 25.0, "high": 25.0}
    assert report["uncertainty"]["family_size"] == 10
    assert report["coverage"]["complete_pairs"] == 96
    assert report["coverage"]["used_decisions"] == 384
    assert report["diagnostics"]["per_judge"]["j1"]["b"]["overall_pct"] == 25.0
    assert report["diagnostics"]["per_judge"]["j2"]["b"]["overall_pct"] == 12.5
    assert report["diagnostics"]["per_order"]["canonical"]["b"]["overall_pct"] == 25.0
    assert report["diagnostics"]["per_order"]["reversed"]["b"]["overall_pct"] == 12.5


def test_existing_four_scientist_votes_do_not_imply_five_scientist_scores():
    parent = plan_for({"a": 2, "c": 5, "d": 5, "e": 5}, sample_size=10)
    expanded = plan_for({"a": 2, "b": 3, "c": 5, "d": 5, "e": 5}, sample_size=10)
    old_results = results_for(parent)
    report = analyze(expanded, old_results)
    assert report["status"] == "partial"
    assert report["coverage"]["completed_jobs"] == 240
    assert report["coverage"]["expected_jobs"] == 384
    assert report["coverage"]["complete_pairs"] == 60
    assert all(row["rank"] is None and row["overall_pct"] is None for row in report["rankings"])
    assert all(row["expected_opponents"] == 4 for row in report["rankings"])


def test_posthoc_cohort_addition_marks_new_scores_as_a_different_opponent_average():
    plan = plan_for({"a": 2, "b": 3, "c": 5, "d": 5, "e": 5}, sample_size=10)
    plan["extension"] = {
        "stage": "post_initial_results", "kind": "cohort_addition", "added_agents": ["b"],
        "previous_agent_count": 4, "current_agent_count": 5,
        "original_pairs": 60, "additional_pairs": 36, "target_pairs_per_matchup": 10,
        "parent_extension": {"stage": "post_initial_results", "original_pairs": 36,
                             "target_pairs_per_matchup": 10},
    }
    report = analyze(plan, results_for(plan))
    assert report["cohort_comparability"] == {
        "previous_agent_count": 4, "current_agent_count": 5,
        "previous_opponents": 3, "current_opponents": 4, "directly_comparable": False}
    assert report["uncertainty"]["confidence"] is None
    assert report["uncertainty"]["inference_scope"] == "exploratory_fixed_size_reference"
    assert report["uncertainty"]["family_size"] == 10
    assert report["uncertainty"]["sequential_valid"] is False
    assert all(not r["design_sampling"]["overall"]["variance_valid_for_design"] for r in report["rankings"])
    assert report["extension"] == plan["extension"]


def test_four_scientist_design_counts_144_overall_decisions_and_six_bands():
    plan = plan_for({"a": 2, "b": 3, "c": 3, "d": 3}, sample_size=6)
    report = analyze(plan, results_for(plan))
    assert report["coverage"]["expected_pairs"] == 36
    assert report["coverage"]["complete_pairs"] == 36
    assert report["coverage"]["expected_jobs"] == 144
    assert report["coverage"]["expected_decisions"] == 144
    assert report["coverage"]["used_decisions"] == 144
    assert report["uncertainty"]["family_size"] == 6
    assert all(comparison["decision_count"] == 24 for comparison in report["comparisons"])
    assert ranking(report, "a")["decision_count"] == 72
    assert ranking(report, "a")["overall_pct"] == 100.0
    assert ranking(report, "b")["overall_pct"] == pytest.approx(200 / 3)
    assert report["diagnostics"]["denominators"] == {
        "position_a": 144, "swapped_inconsistency": 72, "judge_disagreement": 72}
    assert all(set(row["intervals"]) == {"overall"} and not row.get("metrics") for row in report["rankings"])


def test_posthoc_extension_preserves_old_results_and_marks_bands_exploratory():
    original = plan_for({"a": 4, "b": 4, "c": 4, "d": 4}, sample_size=6)
    extended = plan_for({"a": 4, "b": 4, "c": 4, "d": 4}, sample_size=10)
    extended["extension"] = {"stage": "post_initial_results", "original_pairs": 36,
                             "additional_pairs": 24, "target_pairs_per_matchup": 10,
                             "parent_fingerprint": "original-frozen-plan"}
    original_results = results_for(original)
    original_report = analyze(original, original_results)
    partial = analyze(extended, original_results)
    assert len({j["key"] for j in extended["jobs"]} - {j["key"] for j in original["jobs"]}) == 96
    assert partial["coverage"]["expected_jobs"] == 240
    assert partial["coverage"]["completed_jobs"] == 144
    assert partial["coverage"]["expected_pairs"] == 60
    assert partial["coverage"]["complete_pairs"] == 36
    assert partial["coverage"]["used_decisions"] == 144
    assert all(row["rank"] is None for row in partial["rankings"])
    assert {row["agent"]: row["overall_pct"] for row in partial["rankings"]} == {
        row["agent"]: row["overall_pct"] for row in original_report["rankings"]}
    complete = analyze(extended, results_for(extended))
    assert complete["status"] == "complete"
    assert complete["coverage"]["complete_pairs"] == 60
    assert complete["coverage"]["used_decisions"] == 240
    assert all(c["complete_pairs"] == 10 for c in complete["comparisons"])
    assert [row["rank"] for row in complete["rankings"]] == [1, 2, 3, 4]
    assert complete["uncertainty"]["family_size"] == 6
    assert complete["uncertainty"]["confidence"] is None
    assert complete["uncertainty"]["nominal_fixed_size_level"] == 0.95
    assert complete["uncertainty"]["inference_scope"] == "exploratory_fixed_size_reference"
    assert complete["uncertainty"]["sequential_valid"] is False
    assert complete["extension"] == extended["extension"]
    assert all(not c["sampling"]["overall"]["variance_valid_for_design"] for c in complete["comparisons"])
    assert all(row["intervals"]["overall"] is not None for row in complete["rankings"])
    fixed_target = deepcopy(extended)
    del fixed_target["extension"]
    fixed_report = analyze(fixed_target, results_for(fixed_target))
    assert [(r["overall_pct"], r["intervals"]) for r in complete["rankings"]] == [
        (r["overall_pct"], r["intervals"]) for r in fixed_report["rankings"]]
    assert fixed_report["uncertainty"]["confidence"] == 0.95


def test_incomplete_pair_never_contributes_votes_and_blocks_primary_ranks():
    plan = plan_for({"a": 2, "b": 1}, sample_size=2)
    results = results_for(plan, lambda job: "a" if job["papers"][0] == "a0" else "b")
    report = analyze(plan, results[:-1])
    assert report["status"] == "partial"
    assert report["coverage"]["completed_jobs"] == 7
    assert report["coverage"]["usable_jobs"] == 4
    assert report["coverage"]["complete_pairs"] == 1
    assert report["coverage"]["used_decisions"] == 4
    assert ranking(report, "a")["overall_pct"] == 100.0
    assert all(row["rank"] is None for row in report["rankings"])
    assert all(interval is None for row in report["rankings"] for interval in row["intervals"].values())
    assert len(report["judgments"]) == 7


def test_missing_opponent_stratum_does_not_change_macro_estimand():
    plan = plan_for({"a": 1, "b": 1, "c": 1})
    report = analyze(plan, results_for(plan)[:4])
    assert ranking(report, "a")["overall_pct"] is None
    assert not ranking(report, "a").get("metrics")
    assert all(row["rank"] is None for row in report["rankings"])
    assert report["comparisons"][0]["overall_pct_a"] == 100.0
    assert report["comparisons"][1]["overall_pct_a"] is None


def test_no_results_preserves_nulls_and_counts_catalog_exclusions():
    plan = plan_for()
    plan["catalog"].append({"id": "a-excluded", "agent": "a", "pdf_path": "excluded.pdf",
                             "eligible_primary": False})
    report = analyze(plan, [])
    assert report["status"] == "not_judged"
    assert report["coverage"]["expected_jobs"] == 4
    assert report["coverage"]["expected_decisions"] == 4
    assert report["coverage"]["downloaded_papers"] == 3
    assert report["coverage"]["eligible_papers"] == 2
    assert report["coverage"]["selected_papers"] == 2
    assert report["coverage"]["per_agent"]["a"] == {"downloaded": 2, "eligible": 1, "selected": 1}
    assert all(row["rank"] is None and row["overall_pct"] is None for row in report["rankings"])
    assert report["diagnostics"]["position_a_pct"] is None
    assert report["diagnostics"]["swapped_inconsistency_pct"] is None
    assert report["costs"] == {"known_usd": 0, "unknown_jobs": 0, "completed_jobs": 0}
    json.dumps(report, allow_nan=False)


def test_empty_eligible_pool_has_no_invented_jobs_or_scores():
    report = analyze(plan_for({"a": 0, "b": 1}), [])
    assert report["status"] == "not_judged"
    assert report["coverage"]["expected_jobs"] == 0
    assert report["comparisons"][0]["population_pairs"] == 0
    assert all(row["overall_pct"] is None and row["rank"] is None for row in report["rankings"])
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "missing_key", "empty_key", "non_string_key",
                                      "bad_winner", "empty_reason", "extra_verdict_field", "nested_legacy_verdict",
                                      "nan_cost", "negative_cost"])
def test_rejects_invalid_results_instead_of_silently_changing_the_estimate(mutation):
    plan = plan_for()
    results = results_for(plan)
    if mutation == "duplicate":
        results.append(deepcopy(results[0]))
    elif mutation == "unknown":
        results[0]["key"] = "not-in-plan"
    elif mutation == "missing_key":
        del results[0]["key"]
    elif mutation == "empty_key":
        results[0]["key"] = ""
    elif mutation == "non_string_key":
        results[0]["key"] = ["invalid"]
    elif mutation == "bad_winner":
        results[0]["verdict"]["winner"] = "tie"
    elif mutation == "empty_reason":
        results[0]["verdict"]["reason"] = " "
    elif mutation == "extra_verdict_field":
        results[0]["verdict"]["overall"] = "A"
    elif mutation == "nested_legacy_verdict":
        results[0]["verdict"] = {c: {"reason": "Old criterion vote", "winner": "A"}
                                  for c in ("new", "useful", "surprising")}
    elif mutation == "nan_cost":
        results[0]["cost_usd"] = float("nan")
    elif mutation == "negative_cost":
        results[0]["cost_usd"] = -1
    with pytest.raises(ValueError):
        analyze(plan, results)


def test_position_order_and_judge_diagnostics_use_matched_observations():
    plan = plan_for()
    results = results_for(plan)
    # Always choosing label A yields a 50% aggregate paper tie, but 100% order disagreement.
    for result in results:
        result["verdict"]["winner"] = "A"
    report = analyze(plan, results)
    assert ranking(report, "a")["overall_pct"] == 50.0
    assert report["diagnostics"]["position_a_pct"] == 100.0
    assert report["diagnostics"]["swapped_inconsistency_pct"] == 100.0
    assert report["diagnostics"]["judge_disagreement_pct"] == 0.0
    assert report["diagnostics"]["denominators"] == {
        "position_a": 4, "swapped_inconsistency": 2, "judge_disagreement": 2}
    assert report["diagnostics"]["ties"]["pair_blocks"]["overall"] == 1
    partial = analyze(plan, results[:1])
    assert partial["diagnostics"]["denominators"] == {
        "position_a": 1, "swapped_inconsistency": 0, "judge_disagreement": 0}
    assert partial["diagnostics"]["judge_disagreement_pct"] is None


def test_unknown_cost_is_not_replaced_with_zero_and_inputs_are_unchanged():
    plan = plan_for()
    results = results_for(plan)
    results[0]["cost_usd"] = None
    before = deepcopy((plan, results))
    report = analyze(plan, results)
    assert report["costs"]["known_usd"] == pytest.approx(0.3)
    assert report["costs"]["unknown_jobs"] == 1
    assert report["costs"]["completed_jobs"] == 4
    assert (plan, results) == before
    assert report["judgments"][0]["pair_id"] == plan["jobs"][0]["pair_id"]


def test_sampling_bands_do_not_claim_certainty_from_unanimous_small_sample():
    plan = plan_for({"a": 4, "b": 4}, sample_size=2)
    report = analyze(plan, results_for(plan))
    interval = ranking(report, "a")["intervals"]["overall"]
    assert interval["low"] < 100.0
    assert interval["high"] == 100.0
    assert report["comparisons"][0]["population_pairs"] == 16
    assert report["comparisons"][0]["sampling"]["overall"]["sample_variance"] == 0.0
    assert report["uncertainty"]["confidence"] == 0.95
    assert report["uncertainty"]["family_size"] == 1


def test_design_variance_uses_pair_means_and_finite_population_correction():
    plan = plan_for({"a": 2, "b": 2}, sample_size=2)
    report = analyze(plan, results_for(plan, lambda job: "a" if job["papers"][1] == "b0" else "b"))
    # Sample values [1,0]: s²=.5, n=2, N=4, estimated Var(mean)=.125.
    sampling = report["comparisons"][0]["sampling"]["overall"]
    assert sampling["sample_variance"] == 0.5
    assert sampling["variance_fpc"] == 0.5
    assert sampling["mean_variance"] == 0.125
    assert sampling["standard_error_pct"] == pytest.approx(35.35533905932738)
    assert ranking(report, "a")["design_sampling"]["overall"]["mean_variance"] == 0.125

    three_agent_plan = plan_for({"a": 2, "b": 2, "c": 1}, sample_size=2)
    macro = analyze(three_agent_plan, results_for(
        three_agent_plan, lambda job: job["agents"][0]
        if job["papers"][1].endswith("0") else job["agents"][1]))
    # A/B variance=.125, A/C is a census. Two equal opponent weights give .125/4.
    assert ranking(macro, "a")["design_sampling"]["overall"]["mean_variance"] == 0.03125


def test_overall_variance_uses_pair_blocks_instead_of_individual_votes():
    plan = plan_for({"a": 2, "b": 2}, sample_size=2)
    block_keys = {}
    for job in plan["jobs"]:
        block_keys.setdefault(job["pair_id"], []).append(job["key"])

    def winner(job):
        first_pair = job["papers"][1] == "b0"
        index = block_keys[job["pair_id"]].index(job["key"])
        return "a" if index < (3 if first_pair else 1) else "b"

    report = analyze(plan, results_for(plan, winner))
    # Pair means are .75 and .25: s²=.125, Var(mean)=(1/2)*.125/2.
    assert report["comparisons"][0]["sampling"]["overall"]["mean_variance"] == 0.03125


@pytest.mark.parametrize("mutation", ["reverse_orders", "prompt_content", "paper_metadata"])
def test_generated_plan_fingerprint_rejects_tampered_order_or_content(tmp_path, mutation):
    fixture = plan_for({"a": 1, "b": 1, "c": 1, "d": 1})
    for index, paper in enumerate(fixture["catalog"]):
        paper["blind_text_path"] = f"{paper['id']}.txt"
        paper["sha256"] = f"{index:064x}"
        (tmp_path / paper["blind_text_path"]).write_text(f"[Page 1] Unique manuscript by {paper['agent']}.", encoding="utf-8")
    plan = make_plan(fixture["catalog"], fixture["agents"], fixture["judges"],
                     tmp_path, "Compare New, Useful, and Surprising.", pairs_per_matchup=1)
    results = results_for(plan)
    baseline = analyze(plan, results)
    assert baseline["status"] == "complete"
    assert ranking(baseline, "a")["overall_pct"] == 100.0
    tampered = deepcopy(plan)
    if mutation == "reverse_orders":
        # This preserves each valid four-cell schedule but reinterprets every
        # cached A/B label, reversing scores unless the frozen input is checked.
        for job in tampered["jobs"]:
            job["order"].reverse()
    elif mutation == "prompt_content":
        tampered["jobs"][0]["prompt"] += "\nChanged manuscript evidence."
    else:
        tampered["catalog"][0]["title"] = "Changed source identity"
    with pytest.raises(ValueError, match="fingerprint"):
        analyze(tampered, results)


def test_per_judge_order_and_paper_diagnostics_preserve_actual_denominators():
    plan = plan_for({"a": 2, "b": 1}, sample_size=2)
    report = analyze(plan, results_for(plan, lambda job: "a" if job["judge"] == "j1" else "b"))
    diagnostics = report["diagnostics"]
    assert diagnostics["per_judge"]["j1"]["a"]["overall_pct"] == 100.0
    assert diagnostics["per_judge"]["j2"]["a"]["overall_pct"] == 0.0
    assert diagnostics["per_order"]["canonical"]["a"]["overall_pct"] == 50.0
    assert diagnostics["per_order"]["reversed"]["a"]["overall_pct"] == 50.0
    assert diagnostics["per_judge"]["j1"]["a"]["decision_count"] == 4
    appearances = diagnostics["paper_appearances"]
    assert appearances["b0"] == {"agent": "b", "sampled_pairs": 2, "complete_pairs": 2}
    assert appearances["a0"] == {"agent": "a", "sampled_pairs": 1, "complete_pairs": 1}
    assert diagnostics["per_paper"]["a0"]["overall_pct"] == 50.0
    assert diagnostics["per_paper"]["a0"]["complete_pairs_by_opponent"] == {"b": 1}
    assert diagnostics["pool_sizes"]["a"] == {"eligible": 2, "distinct_sampled": 2, "distinct_complete": 2}


@pytest.mark.parametrize("mutation", ["duplicate_key", "duplicate_cell", "missing_order", "wrong_order",
                                      "wrong_population", "missing_stratum", "undersampled_stratum"])
def test_malformed_plan_cannot_make_an_incomplete_schedule_look_complete(mutation):
    plan = plan_for({"a": 1, "b": 1, "c": 1})
    if mutation == "duplicate_key":
        plan["jobs"][1]["key"] = plan["jobs"][0]["key"]
    elif mutation == "duplicate_cell":
        plan["jobs"][1]["judge"] = plan["jobs"][0]["judge"]
    elif mutation == "missing_order":
        plan["jobs"].pop()
    elif mutation == "wrong_order":
        plan["jobs"][0]["order"] = ["a0", "c0"]
    elif mutation == "wrong_population":
        plan["strata"][0]["population_pairs"] = 100
    elif mutation == "missing_stratum":
        plan["strata"].pop()
    elif mutation == "undersampled_stratum":
        plan["strata"][0]["sampled_pairs"] = 0
        plan["jobs"] = plan["jobs"][4:]
    with pytest.raises(ValueError):
        analyze(plan, [])
