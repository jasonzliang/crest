"""Behavioral checks for balanced, question-clustered pairwise analysis."""
import copy
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import csv
from itertools import combinations
import json
from unittest.mock import patch

import pytest

from crest.analysis import analyze, write_report

AGENTS = ["a", "b", "c"]
JUDGES = ["openai", "gemini"]
EMPTY = ([], [], [])


def experiment(count=1, choose=None):
    questions, answers, judgments = [], [], []
    choose = choose or (lambda q, pair, judge, order: pair[0])
    for number in range(count):
        question_id = f"q{number}"
        questions.append({"id": question_id, "text": f"Question {number}?"})
        for agent in AGENTS:
            answers.append({"question_id": question_id, "agent": agent,
                            "key": f"answer-{question_id}-{agent}",
                            "result": {"text": f"Answer from {agent}", "cost_usd": 1.0}})
        for pair in combinations(AGENTS, 2):
            for judge in JUDGES:
                for order in (pair, pair[::-1]):
                    winner = choose(number, pair, judge, order)
                    verdict = {"winner": "A" if winner == order[0] else "B",
                               "reason": "Comparative creativity evidence."}
                    judgments.append({"question_id": question_id, "pair": list(pair),
                                      "order": list(order), "judge": judge,
                                      "key": f"judge-{question_id}-{pair}-{judge}-{order}",
                                      "verdict": verdict, "cost_usd": 0.1})
    return questions, answers, judgments


def report(data, **kwargs):
    return analyze(*data, agents=AGENTS, judges=JUDGES,
                   bootstrap_samples=kwargs.pop("bootstrap_samples", 200), **kwargs)


def by_agent(rows):
    return {row["agent"]: row for row in rows}


def failure_cost_fields(cost):
    return {key: cost[key] for key in ("known_usd", "unknown_count", "records",
                                       "partial_observed_estimate_usd", "observed_count",
                                       "budget_exceeded_count")}


def no_observed(known, unknown, records):
    return {"known_usd": known, "unknown_count": unknown, "records": records,
            "partial_observed_estimate_usd": 0.0, "observed_count": 0, "budget_exceeded_count": 0}


def by_question_parity(q, pair, judge, order):
    return pair[q % 2]


def test_revised_protocol_excludes_noncomparative_reason_but_preserves_legacy_reproduction():
    data = experiment(2)
    data[2][0]['verdict']['reason'] = 'Wait, no markdown!'
    assert report(data)['coverage']['complete_questions'] == 2
    for row in data[2]:
        row['protocol_version'] = 'nus-overall-pairwise-v3'
        if row is not data[2][0]:
            row['verdict']['reason'] = (
                "A develops an original load-sharing mechanism with a supported payoff, "
                "whereas B repeats the expected bridge design without resolving its stated weakness.")
    result = report(data)
    assert result['coverage']['complete_questions'] == 1
    assert result['coverage']['invalid_judgments'] == 1


def test_swapped_labels_map_back_to_agent_and_rank_three_entrants():
    result = report(experiment())
    assert [(r["agent"], r["rank"], r["preference_rate"]) for r in result["ranking"]] == [
        ("a", 1, 1.0), ("b", 2, 0.5), ("c", 3, 0.0)]
    overall = result["pairwise"]["overall"]
    assert (overall["a"]["b"], overall["b"]["a"], overall["a"]["a"]) == (1.0, 0.0, None)
    assert result["diagnostics"]["position_a_preference"]["rate"] == 0.5
    assert result["diagnostics"]["swapped_inconsistency"]["rate"] == 0.0


def test_balanced_overall_win_rates_weight_questions_and_opponents_equally():
    orders = ("abc", "bca")
    result = report(experiment(2, choose=lambda q, pair, judge, order: min(pair, key=orders[q].index)))
    assert [(r["agent"], r["wins"], r["choices"], r["preference_rate"]) for r in result["ranking"]] == [
        ("b", 12, 16, 0.75), ("a", 8, 16, 0.5), ("c", 4, 16, 0.25)]
    assert result["pairwise"]["overall"]["a"]["b"] == 0.5
    assert result["pairwise"]["overall"]["b"]["c"] == 1.0
    assert "per_criterion" not in result
    assert "per_criterion" not in result["pairwise"]


def test_position_bias_retains_exact_aggregate_ties_and_flags_swapped_inconsistency():
    result = report(experiment(choose=lambda q, pair, judge, order: order[0]))
    assert [r["rank"] for r in result["ranking"]] == [1, 1, 1]
    assert [r["preference_rate"] for r in result["ranking"]] == [0.5, 0.5, 0.5]
    assert result["diagnostics"]["position_a_preference"]["rate"] == 1.0
    assert result["diagnostics"]["swapped_inconsistency"] == {
        "disagreements": 6, "comparisons": 6, "rate": 1.0}
    # Exact index ties also have zero contrasts and always-equal bootstrap orderings.
    for contrast in result["paired_contrasts"]:
        assert contrast["difference"] == 0.0
        assert contrast["ci95"] == [0.0, 0.0]
        assert contrast["ordering_stability"] == {"first_higher": 0.0, "equal": 1.0, "second_higher": 0.0}


def test_pairwise_cycles_remain_visible_even_when_aggregate_ranks_tie():
    preferred = {("a", "b"): "a", ("a", "c"): "c", ("b", "c"): "b"}
    result = report(experiment(choose=lambda q, pair, judge, order: preferred[pair]))
    assert [r["rank"] for r in result["ranking"]] == [1, 1, 1]
    assert result["diagnostics"]["cycles"] == [["a", "b", "c", "a"]]


def test_per_judge_rankings_and_disagreement_compare_mapped_winners():
    result = report(experiment(choose=lambda q, pair, judge, order:
                               pair[0] if judge == "openai" else pair[1]))
    assert result["per_judge"]["openai"][0]["agent"] == "a"
    assert result["per_judge"]["gemini"][0]["agent"] == "c"
    assert result["diagnostics"]["judge_disagreement"] == {
        "disagreements": 6, "comparisons": 6, "rate": 1.0}
    assert result["diagnostics"]["swapped_inconsistency"]["rate"] == 0.0


def test_opposing_position_preferences_remain_visible_per_judge():
    data = experiment(2, choose=lambda q, pair, judge, order:
                      order[0] if judge == "openai" else order[1])
    data[2].pop()  # Every diagnostic must exclude this incomplete question.
    diagnostics = report(data)["diagnostics"]
    assert diagnostics["position_a_preference"]["rate"] == 0.5
    views = diagnostics["by_judge"]
    assert views["openai"]["position_a_preference"] == {"wins": 6, "choices": 6, "rate": 1.0}
    assert views["gemini"]["position_a_preference"] == {"wins": 0, "choices": 6, "rate": 0.0}
    for judge in JUDGES:
        assert views[judge]["swapped_inconsistency"] == {"disagreements": 3, "comparisons": 3, "rate": 1.0}
        assert views[judge]["judge_disagreement"] == {"disagreements": 6, "comparisons": 6, "rate": 1.0}
    assert diagnostics["judge_disagreement"] == {"disagreements": 6, "comparisons": 6, "rate": 1.0}


def test_paired_contrast_uses_same_question_draws_and_reports_ordering_ties():
    data = experiment(2, choose=by_question_parity)
    result = report(data, bootstrap_samples=4, seed=19)
    # Seed 19 draws the question blocks [0,0], [0,1], [1,1], [0,1].
    # For a minus b, their shared-draw index differences are .5, 0, -.5, 0.
    contrast = result["paired_contrasts"][0]
    assert contrast["pair"] == ["a", "b"]
    assert contrast["difference"] == 0.0
    assert contrast["ci95"] == pytest.approx([-0.4625, 0.4625])
    assert contrast["ordering_stability"] == {"first_higher": 0.25, "equal": 0.5, "second_higher": 0.25}
    assert contrast["bootstrap_samples"] == 4
    assert result == report(data, bootstrap_samples=4, seed=19)


def test_contrasts_compare_overall_indices_on_common_blocks_not_head_to_head_votes():
    data = experiment(2, choose=by_question_parity)
    data[2].pop()
    result = report(data)
    assert result["pairwise"]["overall"]["a"]["b"] == 1.0
    contrast = result["paired_contrasts"][0]
    assert contrast["difference"] == 0.5
    assert contrast["ci95"] == [0.5, 0.5]
    assert contrast["ordering_stability"] == {"first_higher": 1.0, "equal": 0.0, "second_higher": 0.0}


UNAVAILABLE_STABILITY = {"first_higher": None, "equal": None, "second_higher": None}


def test_zero_data_has_no_ranks_intervals_or_contrast_stability():
    result = report(EMPTY)
    assert result["coverage"]["complete_questions"] == 0
    assert all(r["rank"] is None and r["ci95"] is None for r in result["ranking"])
    assert result["diagnostics"]["position_a_preference"]["rate"] is None
    assert result["costs"]["total"]["known_usd"] == 0.0
    assert result["costs"]["total"]["unknown_count"] == 0
    contrast = result["paired_contrasts"][0]
    assert (contrast["difference"], contrast["ci95"], contrast["bootstrap_samples"]) == (None, None, 0)
    assert contrast["ordering_stability"] == UNAVAILABLE_STABILITY
    empty = result["diagnostics"]["by_judge"]["openai"]
    assert empty["position_a_preference"] == {"wins": 0, "choices": 0, "rate": None}
    assert empty["swapped_inconsistency"] == {"disagreements": 0, "comparisons": 0, "rate": None}


def test_disabled_bootstrap_keeps_difference_without_fabricating_stability():
    contrast = report(experiment(), bootstrap_samples=0)["paired_contrasts"][0]
    assert (contrast["difference"], contrast["ci95"], contrast["bootstrap_samples"]) == (0.5, None, 0)
    assert contrast["ordering_stability"] == UNAVAILABLE_STABILITY


def test_missing_judge_excludes_whole_question_from_all_summaries():
    questions, answers, judgments = experiment(2)
    judgments.pop()
    result = report((questions, answers, judgments))
    coverage = result["coverage"]
    assert coverage["complete_question_ids"] == ["q0"]
    assert coverage["complete_questions"] == 1
    assert coverage["expected_judgments_per_question"] == 12
    excluded = coverage["excluded_questions"][0]
    assert excluded["question_id"] == "q1"
    assert len(excluded["missing_judgments"]) == 1
    assert result["ranking"][0]["choices"] == 8


@pytest.mark.parametrize("change", ["missing", "empty"])
def test_missing_or_empty_answer_excludes_otherwise_complete_question(change):
    data = experiment()
    if change == "missing":
        data[1].pop()
    else:
        data[1][-1]["result"]["text"] = "  "
    result = report(data)
    assert result["coverage"]["complete_questions"] == 0
    assert result["coverage"]["excluded_questions"][0]["missing_answers"] == ["c"]
    assert all(r["preference_rate"] is None for r in result["ranking"])


@pytest.mark.parametrize("mutate", [
    lambda j: j.update(order=["a", "a"]),
    lambda j: j.update(pair=["b", "a"]),
    lambda j: j["verdict"].update(winner="tie"),
    lambda j: j["verdict"].update(reason=""),
    lambda j: j["verdict"].update(overall="A"),
    lambda j: j.update(verdict={"new": {"reason": "N", "winner": "A"},
                                "useful": {"reason": "U", "winner": "A"},
                                "surprising": {"reason": "S", "winner": "A"}}),
], ids=["repeated-order", "noncanonical-pair", "tie", "empty-reason", "extra-field", "criterion-verdict"])
def test_wrong_order_noncanonical_pairs_or_invalid_binary_verdict_cannot_fill_missing_cells(mutate):
    data = experiment()
    mutate(data[2][0])
    result = report(data)
    assert result["coverage"]["complete_questions"] == 0
    assert result["coverage"]["invalid_judgments"] == 1


@pytest.mark.parametrize("index,reason", [(1, "duplicate_answers"), (2, "duplicate_judgments")])
def test_duplicate_answer_or_judgment_excludes_ambiguous_question(index, reason):
    data = experiment()
    data[index].append(copy.deepcopy(data[index][0]))
    result = report(data)
    assert result["coverage"]["complete_questions"] == 0
    assert reason in result["coverage"]["excluded_questions"][0]["reasons"]


def test_bootstrap_resamples_whole_questions_is_seed_deterministic_and_leaves_inputs_unmutated():
    data = experiment(2, choose=by_question_parity)
    snapshot = copy.deepcopy(data)
    first = report(data, seed=19)
    assert data == snapshot
    assert first == report(data, seed=19)
    rows = by_agent(first["ranking"])
    assert rows["a"]["ci95"] == [0.0, 1.0]
    assert rows["b"]["ci95"] == [0.5, 0.5]
    assert rows["c"]["ci95"] == [0.0, 1.0]
    assert first["bootstrap"]["unit"] == "question"


def test_process_workers_reproduce_serial_results_with_shared_question_draws():
    # 20 complete questions x 10,000 draws is the smallest load that starts a pool.
    data = experiment(21, choose=lambda q, pair, judge, order:
                      pair[(q + (judge == "gemini" and q % 3 == 0)) % 2])
    data[2].pop()
    failures = [{"stage": "judge", "key": "failed-job", "cost_usd": 0.42}]
    options = {"failures": failures, "seed": 19, "bootstrap_samples": 10000}
    serial = report(data, workers=1, **options)
    assert serial["coverage"]["complete_questions"] == 20
    assert serial["ranking"][0]["ci95"] is not None
    # Real worker processes must pickle each view and return the serial result.
    with patch("crest.analysis.ProcessPoolExecutor", wraps=ProcessPoolExecutor) as executor:
        assert report(data, workers=2, **options) == serial
    executor.assert_called_once_with(max_workers=2)
    # Zero selects the CPU count; an in-process pool suffices to check the sizing.
    with patch("crest.analysis.os.cpu_count", return_value=2), patch(
            "crest.analysis.ProcessPoolExecutor", wraps=ThreadPoolExecutor) as executor:
        assert report(data, workers=0, **options) == serial
    executor.assert_called_once_with(max_workers=2)


@pytest.mark.parametrize("questions,samples", [(0, 1000), (1, 1000), (2, 99), (2, 1000), (50, 99), (50, 1000)])
def test_small_or_empty_bootstraps_avoid_process_startup(questions, samples):
    with patch("crest.analysis.ProcessPoolExecutor", side_effect=AssertionError("Unexpected process pool")):
        result = analyze(*experiment(questions), agents=AGENTS, judges=JUDGES,
                         workers=2, bootstrap_samples=samples)
    assert result["coverage"]["complete_questions"] == questions


@pytest.mark.parametrize("workers", [-1, True, 1.5])
def test_invalid_worker_counts_are_rejected(workers):
    with pytest.raises(ValueError):
        report(experiment(), workers=workers)


def test_costs_include_excluded_records_and_unknowns_without_claiming_this_run_spend():
    data = experiment()
    data[1][0]["result"]["cost_usd"] = None
    data[2][-1].pop("verdict")
    result = report(data)
    assert result["coverage"]["complete_questions"] == 0
    assert result["costs"]["total"]["known_usd"] == pytest.approx(3.2)
    assert result["costs"]["total"]["unknown_count"] == 1
    assert result["costs"]["this_run_usd"] is None


def test_malformed_paid_judge_responses_count_costs_without_filling_cells(tmp_path):
    questions, answers, judgments = experiment()
    for answer in answers:
        answer["result"]["cost_usd"] = 0.0
    failures = [{"stage": "judge", "key": j["key"], "question_id": j["question_id"],
                 "provider": j["judge"], "error": "Malformed binary verdict", "cost_usd": 0.42,
                 "usage": {"output_tokens": 100}, "cache_record": "failed-record.json"}
                for j in judgments[6:]]
    for judgment in judgments[:6]:
        judgment["cost_usd"] = 0.01
    snapshot = copy.deepcopy(failures)
    result = report((questions, answers, judgments[:6]), failures=failures)
    assert result["coverage"]["complete_questions"] == 0
    assert result["coverage"]["valid_judgments"] == 6
    assert len(result["coverage"]["excluded_questions"][0]["missing_judgments"]) == 6
    assert failure_cost_fields(result["costs"]["failures"]) == no_observed(2.52, 0, 6)
    assert result["costs"]["judging"]["known_usd"] == pytest.approx(0.06)
    assert result["costs"]["total"]["known_usd"] == pytest.approx(2.58)
    assert result["costs"]["total"]["records"] == 15
    assert result["costs"]["this_run_usd"] is None
    assert failures == snapshot
    write_report(result, tmp_path)
    markdown = (tmp_path / "report.md").read_text()
    assert "failed judgments: $2.520000" in markdown
    assert "judging: $0.060000" in markdown


def test_failure_costs_deduplicate_job_keys_within_each_stage_and_keep_unknowns():
    failures = [
        {"stage": "generate", "key": "same-key", "cost_usd": 0.25},
        {"stage": "judge", "key": "same-key", "cost_usd": 0.5},
        {"stage": "judge", "key": "unknown-cost", "cost_usd": None},
        {"stage": "judge", "key": "another-key", "cost_usd": 0.5},
    ]
    failures.append(copy.deepcopy(failures[1]))
    costs = report(EMPTY, failures=failures)["costs"]
    assert failure_cost_fields(costs["failures"]) == no_observed(1.25, 1, 4)
    assert failure_cost_fields(costs["failure_by_stage"]["generate"]) == no_observed(0.25, 0, 1)
    assert failure_cost_fields(costs["failure_by_stage"]["judge"]) == no_observed(1.0, 1, 3)
    assert {key: costs["total"][key] for key in ("known_usd", "unknown_count", "records")} == {
        "known_usd": 1.25, "unknown_count": 1, "records": 4}


def test_budget_cancellation_keeps_observed_estimate_separate_from_unknown_final_cost(tmp_path):
    failure = {"stage": "generate", "key": "cancelled-job", "provider": "gemini",
               "cost_usd": None, "observed_cost_usd": 5.25,
               "usage": {"input_tokens": 1000}, "budget_exceeded": True}
    result = report(EMPTY, failures=[failure, copy.deepcopy(failure)])
    cost = result["costs"]["failures"]
    assert failure_cost_fields(cost) == {"known_usd": 0.0, "unknown_count": 1, "records": 1,
                                         "partial_observed_estimate_usd": 5.25, "observed_count": 1,
                                         "budget_exceeded_count": 1}
    assert result["costs"]["failure_by_stage"]["generate"] == cost
    assert result["costs"]["total"]["known_usd"] == 0.0
    assert result["costs"]["total"]["unknown_count"] == 1
    write_report(result, tmp_path)
    markdown = (tmp_path / "report.md").read_text()
    assert "Partial observed failure estimate: $5.250000" in markdown
    assert "Final billed costs remain unknown" in markdown
    assert "excluded from known totals" in markdown


def test_known_final_failure_cost_does_not_also_count_observed_estimate():
    failure = {"stage": "judge", "key": "finalized-job", "cost_usd": 6.0,
               "observed_cost_usd": 5.25, "budget_exceeded": True}
    result = report(EMPTY, failures=[failure])
    assert failure_cost_fields(result["costs"]["failures"]) == {
        "known_usd": 6.0, "unknown_count": 0, "records": 1,
        "partial_observed_estimate_usd": 0.0, "observed_count": 0, "budget_exceeded_count": 1}
    assert result["costs"]["total"]["known_usd"] == 6.0
    assert result["costs"]["total"]["unknown_count"] == 0


def test_partial_caesar_known_components_remain_in_cost_totals():
    data = experiment()
    data[1][0]["result"].update(cost_usd=None, usage={"known_cost_usd": 3.05, "unknown_cost": True},
        raw={"usage_audit": {"known_cost_usd": 3.05, "cumulative_known_cost_usd": 3.05,
                             "unknown_cost": True},
             "new_attempt_usage_audit": {"known_cost_usd": 1.4, "unknown_cost": False},
             "budget_history": {"previous_known_cost_usd": 1.65,
                                "previous_unknown_reserved_usd": .48, "previous_cost_unknown": True}})
    costs = report(data)["costs"]
    assert costs["generation"]["known_usd"] == pytest.approx(5.05)
    assert costs["generation"]["partial_known_estimate_usd"] == pytest.approx(3.05)
    assert costs["total"]["known_usd"] == pytest.approx(6.25)
    assert costs["generation"]["unknown_count"] == 1
    assert costs["generation"]["unresolved_reserved_exposure_usd"] == .48


def test_superseded_paid_judgments_contribute_cost_once_and_never_votes():
    data = experiment()
    old = copy.deepcopy(data[2][0])
    old.update(key="superseded-paid", cost_usd=.42)
    old["verdict"]["winner"] = "B"
    data[2].append(old)
    prior = {"key": old["key"], "stage": "judge", "judge": old["judge"],
             "cost_usd": .42, "valid_for_ranking": False}
    result = report(data, prior_judgments=[prior, copy.deepcopy(prior)])
    assert result["coverage"]["complete_questions"] == 1
    assert result["coverage"]["superseded_judgments_excluded"] == 1
    assert result["ranking"][0]["preference_rate"] == 1.0
    assert result["costs"]["prior_judgments"]["known_usd"] == .42
    assert result["costs"]["total"]["known_usd"] == pytest.approx(4.62)


def test_report_writer_emits_json_csv_and_readable_coverage_costs(tmp_path):
    result = report(experiment())
    output = tmp_path / "reports"
    write_report(result, output)
    assert json.loads((output / "ranking.json").read_text()) == result
    with (output / "ranking.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["agent"] == "a"
    assert float(rows[0]["preference_rate"]) == 1.0
    markdown = (output / "report.md").read_text()
    for text in ("1 / 1", "Paired overall-index contrasts", "Judge diagnostics",
                 "swapped-presentation inconsistency", "frozen answers", "not a Bayesian probability"):
        assert text in markdown
    for word in ("unknown", "descriptive", "question"):
        assert word in markdown.lower()
    assert "Criterion:" not in markdown
