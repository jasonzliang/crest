"""Behavioral checks for balanced, question-clustered pairwise analysis."""
import copy
from concurrent.futures import ProcessPoolExecutor
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from itertools import combinations

from crest.analysis import analyze, write_report

AGENTS = ["a", "b", "c"]
JUDGES = ["openai", "gemini"]


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


def core_cost_fields(cost):
    return {key: cost[key] for key in ("known_usd", "unknown_count", "records")}


def failure_cost_fields(cost):
    return core_cost_fields(cost) | {key: cost[key] for key in (
        "partial_observed_estimate_usd", "observed_count", "budget_exceeded_count")}


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


class AnalysisTests(unittest.TestCase):
    def test_swapped_labels_map_back_to_agent_and_rank_three_entrants(self):
        result = report(experiment())
        self.assertEqual([(r["agent"], r["rank"], r["preference_rate"]) for r in result["ranking"]],
                         [("a", 1, 1.0), ("b", 2, 0.5), ("c", 3, 0.0)])
        self.assertEqual(result["pairwise"]["overall"]["a"]["b"], 1.0)
        self.assertEqual(result["pairwise"]["overall"]["b"]["a"], 0.0)
        self.assertIsNone(result["pairwise"]["overall"]["a"]["a"])
        self.assertEqual(result["diagnostics"]["position_a_preference"]["rate"], 0.5)
        self.assertEqual(result["diagnostics"]["swapped_inconsistency"]["rate"], 0.0)

    def test_balanced_overall_win_rates_weight_questions_and_opponents_equally(self):
        orders = ("abc", "bca")
        data = experiment(2, choose=lambda q, pair, judge, order: min(pair, key=orders[q].index))
        result = report(data)
        self.assertEqual([(r["agent"], r["wins"], r["choices"], r["preference_rate"])
                          for r in result["ranking"]],
                         [("b", 12, 16, 0.75), ("a", 8, 16, 0.5), ("c", 4, 16, 0.25)])
        self.assertEqual(result["pairwise"]["overall"]["a"]["b"], 0.5)
        self.assertEqual(result["pairwise"]["overall"]["b"]["c"], 1.0)
        self.assertNotIn("per_criterion", result)
        self.assertNotIn("per_criterion", result["pairwise"])

    def test_position_bias_retains_exact_aggregate_ties_and_flags_swapped_inconsistency(self):
        result = report(experiment(choose=lambda q, pair, judge, order: order[0]))
        self.assertEqual([r["rank"] for r in result["ranking"]], [1, 1, 1])
        self.assertEqual([r["preference_rate"] for r in result["ranking"]], [0.5, 0.5, 0.5])
        self.assertEqual(result["diagnostics"]["position_a_preference"]["rate"], 1.0)
        self.assertEqual(result["diagnostics"]["swapped_inconsistency"],
                         {"disagreements": 6, "comparisons": 6, "rate": 1.0})

    def test_pairwise_cycles_remain_visible_even_when_aggregate_ranks_tie(self):
        preferred = {("a", "b"): "a", ("a", "c"): "c", ("b", "c"): "b"}
        result = report(experiment(choose=lambda q, pair, judge, order: preferred[pair]))
        self.assertEqual([r["rank"] for r in result["ranking"]], [1, 1, 1])
        self.assertEqual(result["diagnostics"]["cycles"], [["a", "b", "c", "a"]])

    def test_per_judge_rankings_and_disagreement_compare_mapped_winners(self):
        result = report(experiment(choose=lambda q, pair, judge, order:
                                   pair[0] if judge == "openai" else pair[1]))
        self.assertEqual(result["per_judge"]["openai"][0]["agent"], "a")
        self.assertEqual(result["per_judge"]["gemini"][0]["agent"], "c")
        self.assertEqual(result["diagnostics"]["judge_disagreement"],
                         {"disagreements": 6, "comparisons": 6, "rate": 1.0})
        self.assertEqual(result["diagnostics"]["swapped_inconsistency"]["rate"], 0.0)

    def test_opposing_position_preferences_remain_visible_per_judge(self):
        data = experiment(2, choose=lambda q, pair, judge, order:
                          order[0] if judge == "openai" else order[1])
        data[2].pop()  # Every diagnostic must exclude this incomplete question.
        diagnostics = report(data)["diagnostics"]
        self.assertEqual(diagnostics["position_a_preference"]["rate"], 0.5)
        views = diagnostics["by_judge"]
        self.assertEqual(views["openai"]["position_a_preference"],
                         {"wins": 6, "choices": 6, "rate": 1.0})
        self.assertEqual(views["gemini"]["position_a_preference"],
                         {"wins": 0, "choices": 6, "rate": 0.0})
        for judge in JUDGES:
            self.assertEqual(views[judge]["swapped_inconsistency"],
                             {"disagreements": 3, "comparisons": 3, "rate": 1.0})
            self.assertEqual(views[judge]["judge_disagreement"],
                             {"disagreements": 6, "comparisons": 6, "rate": 1.0})
        self.assertEqual(diagnostics["judge_disagreement"],
                         {"disagreements": 6, "comparisons": 6, "rate": 1.0})

    def test_paired_contrast_uses_same_question_draws_and_reports_ordering_ties(self):
        data = experiment(2, choose=lambda q, pair, judge, order: pair[q % 2])
        result = report(data, bootstrap_samples=4, seed=19)
        # Seed 19 draws the question blocks [0,0], [0,1], [1,1], [0,1].
        # For a minus b, their shared-draw index differences are .5, 0, -.5, 0.
        contrast = result["paired_contrasts"][0]
        self.assertEqual(contrast["pair"], ["a", "b"])
        self.assertEqual(contrast["difference"], 0.0)
        self.assertAlmostEqual(contrast["ci95"][0], -0.4625)
        self.assertAlmostEqual(contrast["ci95"][1], 0.4625)
        self.assertEqual(contrast["ordering_stability"],
                         {"first_higher": 0.25, "equal": 0.5, "second_higher": 0.25})
        self.assertEqual(contrast["bootstrap_samples"], 4)
        self.assertEqual(result, report(data, bootstrap_samples=4, seed=19))

    def test_contrasts_compare_overall_indices_on_common_blocks_not_head_to_head_votes(self):
        data = experiment(2, choose=lambda q, pair, judge, order: pair[q % 2])
        data[2].pop()
        result = report(data)
        self.assertEqual(result["pairwise"]["overall"]["a"]["b"], 1.0)
        contrast = result["paired_contrasts"][0]
        self.assertEqual(contrast["difference"], 0.5)
        self.assertEqual(contrast["ci95"], [0.5, 0.5])
        self.assertEqual(contrast["ordering_stability"],
                         {"first_higher": 1.0, "equal": 0.0, "second_higher": 0.0})

    def test_exact_index_ties_have_zero_contrasts_and_equal_bootstrap_ordering(self):
        result = report(experiment(choose=lambda q, pair, judge, order: order[0]))
        for contrast in result["paired_contrasts"]:
            self.assertEqual(contrast["difference"], 0.0)
            self.assertEqual(contrast["ci95"], [0.0, 0.0])
            self.assertEqual(contrast["ordering_stability"],
                             {"first_higher": 0.0, "equal": 1.0, "second_higher": 0.0})
        self.assertEqual([row["rank"] for row in result["ranking"]], [1, 1, 1])

    def test_empty_blocks_or_disabled_bootstrap_do_not_fabricate_contrast_stability(self):
        for data, samples, difference in ((([], [], []), 200, None), (experiment(), 0, 0.5)):
            with self.subTest(samples=samples, difference=difference):
                result = report(data, bootstrap_samples=samples)
                contrast = result["paired_contrasts"][0]
                self.assertEqual(contrast["difference"], difference)
                self.assertIsNone(contrast["ci95"])
                self.assertEqual(contrast["bootstrap_samples"], 0)
                self.assertEqual(contrast["ordering_stability"],
                                 {"first_higher": None, "equal": None, "second_higher": None})
        empty = report(([], [], []))["diagnostics"]["by_judge"]["openai"]
        self.assertEqual(empty["position_a_preference"], {"wins": 0, "choices": 0, "rate": None})
        self.assertEqual(empty["swapped_inconsistency"],
                         {"disagreements": 0, "comparisons": 0, "rate": None})

    def test_missing_judge_excludes_whole_question_from_all_summaries(self):
        questions, answers, judgments = experiment(2)
        judgments.pop()
        result = report((questions, answers, judgments))
        self.assertEqual(result["coverage"]["complete_question_ids"], ["q0"])
        self.assertEqual(result["coverage"]["complete_questions"], 1)
        self.assertEqual(result["coverage"]["expected_judgments_per_question"], 12)
        excluded = result["coverage"]["excluded_questions"][0]
        self.assertEqual(excluded["question_id"], "q1")
        self.assertEqual(len(excluded["missing_judgments"]), 1)
        self.assertEqual(result["ranking"][0]["choices"], 8)

    def test_missing_or_empty_answer_excludes_otherwise_complete_question(self):
        for change in ("missing", "empty"):
            with self.subTest(change=change):
                data = experiment()
                if change == "missing":
                    data[1].pop()
                else:
                    data[1][-1]["result"]["text"] = "  "
                result = report(data)
                self.assertEqual(result["coverage"]["complete_questions"], 0)
                self.assertEqual(result["coverage"]["excluded_questions"][0]["missing_answers"], ["c"])
                self.assertTrue(all(r["preference_rate"] is None for r in result["ranking"]))

    def test_wrong_order_noncanonical_pairs_or_invalid_binary_verdict_cannot_fill_missing_cells(self):
        mutations = [lambda j: j.update(order=["a", "a"]),
                     lambda j: j.update(pair=["b", "a"]),
                     lambda j: j["verdict"].update(winner="tie"),
                     lambda j: j["verdict"].update(reason=""),
                     lambda j: j["verdict"].update(overall="A"),
                     lambda j: j.update(verdict={"new": {"reason": "N", "winner": "A"},
                                                 "useful": {"reason": "U", "winner": "A"},
                                                 "surprising": {"reason": "S", "winner": "A"}})]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = experiment()
                mutate(data[2][0])
                result = report(data)
                self.assertEqual(result["coverage"]["complete_questions"], 0)
                self.assertEqual(result["coverage"]["invalid_judgments"], 1)

    def test_duplicate_answer_or_judgment_excludes_ambiguous_question(self):
        for index, reason in ((1, "duplicate_answers"), (2, "duplicate_judgments")):
            with self.subTest(index=index):
                data = experiment()
                data[index].append(copy.deepcopy(data[index][0]))
                result = report(data)
                self.assertEqual(result["coverage"]["complete_questions"], 0)
                self.assertIn(reason, result["coverage"]["excluded_questions"][0]["reasons"])

    def test_bootstrap_resamples_whole_questions_and_is_seed_deterministic(self):
        data = experiment(2, choose=lambda q, pair, judge, order: pair[q % 2])
        first = report(data, seed=19)
        self.assertEqual(first, report(data, seed=19))
        rows = by_agent(first["ranking"])
        self.assertEqual(rows["a"]["ci95"], [0.0, 1.0])
        self.assertEqual(rows["b"]["ci95"], [0.5, 0.5])
        self.assertEqual(rows["c"]["ci95"], [0.0, 1.0])
        self.assertEqual(first["bootstrap"]["unit"], "question")

    def test_process_workers_produce_exact_serial_results_with_shared_question_draws(self):
        data = experiment(30, choose=lambda q, pair, judge, order:
                          pair[(q + (judge == "gemini" and q % 3 == 0)) % 2])
        data[2].pop()
        failures = [{"stage": "judge", "key": "failed-job", "cost_usd": 0.42}]
        serial = report(data, workers=1, failures=failures, seed=19, bootstrap_samples=10000)
        with patch("crest.analysis.ProcessPoolExecutor", wraps=ProcessPoolExecutor) as executor:
            parallel = report(data, workers=2, failures=failures, seed=19, bootstrap_samples=10000)
        executor.assert_called_once_with(max_workers=2)
        self.assertEqual(parallel, serial)
        self.assertIsNotNone(parallel["ranking"][0]["ci95"])

    def test_auto_workers_use_cpu_bound_and_preserve_results(self):
        data = experiment(25)
        serial = report(data, bootstrap_samples=10000)
        with patch("crest.analysis.os.cpu_count", return_value=2), patch(
                "crest.analysis.ProcessPoolExecutor", wraps=ProcessPoolExecutor) as executor:
            parallel = report(data, workers=0, bootstrap_samples=10000)
        executor.assert_called_once_with(max_workers=2)
        self.assertEqual(parallel, serial)

    def test_small_or_empty_bootstraps_avoid_process_startup(self):
        with patch("crest.analysis.ProcessPoolExecutor", side_effect=AssertionError("Unexpected process pool")):
            for questions, samples in ((0, 1000), (1, 1000), (2, 99), (2, 1000), (50, 99), (50, 1000)):
                with self.subTest(questions=questions, samples=samples):
                    result = analyze(*experiment(questions), agents=AGENTS, judges=JUDGES,
                                     workers=2, bootstrap_samples=samples)
                    self.assertEqual(result["coverage"]["complete_questions"], questions)

    def test_invalid_worker_counts_are_rejected(self):
        for workers in (-1, True, 1.5):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                report(experiment(), workers=workers)

    def test_zero_data_has_no_ranks_or_fabricated_intervals(self):
        result = report(([], [], []))
        self.assertEqual(result["coverage"]["complete_questions"], 0)
        self.assertTrue(all(r["rank"] is None and r["ci95"] is None for r in result["ranking"]))
        self.assertIsNone(result["diagnostics"]["position_a_preference"]["rate"])
        self.assertEqual(result["costs"]["total"]["known_usd"], 0.0)
        self.assertEqual(result["costs"]["total"]["unknown_count"], 0)

    def test_costs_include_excluded_records_and_unknowns_without_claiming_this_run_spend(self):
        data = experiment()
        data[1][0]["result"]["cost_usd"] = None
        data[2][-1].pop("verdict")
        result = report(data)
        self.assertEqual(result["coverage"]["complete_questions"], 0)
        self.assertAlmostEqual(result["costs"]["total"]["known_usd"], 3.2)
        self.assertEqual(result["costs"]["total"]["unknown_count"], 1)
        self.assertIsNone(result["costs"]["this_run_usd"])

    def test_malformed_paid_judge_responses_count_costs_without_filling_cells(self):
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
        self.assertEqual(result["coverage"]["complete_questions"], 0)
        self.assertEqual(result["coverage"]["valid_judgments"], 6)
        self.assertEqual(len(result["coverage"]["excluded_questions"][0]["missing_judgments"]), 6)
        self.assertEqual(failure_cost_fields(result["costs"]["failures"]), {"known_usd": 2.52, "unknown_count": 0, "records": 6,
                         "partial_observed_estimate_usd": 0.0, "observed_count": 0, "budget_exceeded_count": 0})
        self.assertAlmostEqual(result["costs"]["judging"]["known_usd"], 0.06)
        self.assertAlmostEqual(result["costs"]["total"]["known_usd"], 2.58)
        self.assertEqual(result["costs"]["total"]["records"], 15)
        self.assertIsNone(result["costs"]["this_run_usd"])
        self.assertEqual(failures, snapshot)
        with tempfile.TemporaryDirectory() as directory:
            write_report(result, Path(directory))
            markdown = (Path(directory) / "report.md").read_text()
            self.assertIn("failed judgments: $2.520000", markdown)
            self.assertIn("judging: $0.060000", markdown)

    def test_failure_costs_deduplicate_job_keys_within_each_stage_and_keep_unknowns(self):
        failures = [
            {"stage": "generate", "key": "same-key", "cost_usd": 0.25},
            {"stage": "judge", "key": "same-key", "cost_usd": 0.5},
            {"stage": "judge", "key": "unknown-cost", "cost_usd": None},
            {"stage": "judge", "key": "another-key", "cost_usd": 0.5},
        ]
        failures.append(copy.deepcopy(failures[1]))
        result = report(([], [], []), failures=failures)
        self.assertEqual(failure_cost_fields(result["costs"]["failures"]), {"known_usd": 1.25, "unknown_count": 1, "records": 4,
                         "partial_observed_estimate_usd": 0.0, "observed_count": 0, "budget_exceeded_count": 0})
        self.assertEqual(failure_cost_fields(result["costs"]["failure_by_stage"]["generate"]),
                         {"known_usd": 0.25, "unknown_count": 0, "records": 1,
                          "partial_observed_estimate_usd": 0.0, "observed_count": 0, "budget_exceeded_count": 0})
        self.assertEqual(failure_cost_fields(result["costs"]["failure_by_stage"]["judge"]),
                         {"known_usd": 1.0, "unknown_count": 1, "records": 3,
                          "partial_observed_estimate_usd": 0.0, "observed_count": 0, "budget_exceeded_count": 0})
        self.assertEqual(core_cost_fields(result["costs"]["total"]), {"known_usd": 1.25, "unknown_count": 1, "records": 4})

    def test_budget_cancellation_keeps_observed_estimate_separate_from_unknown_final_cost(self):
        failure = {"stage": "generate", "key": "cancelled-job", "provider": "gemini",
                   "cost_usd": None, "observed_cost_usd": 5.25,
                   "usage": {"input_tokens": 1000}, "budget_exceeded": True}
        result = report(([], [], []), failures=[failure, copy.deepcopy(failure)])
        cost = result["costs"]["failures"]
        self.assertEqual(cost["known_usd"], 0.0)
        self.assertEqual(cost["unknown_count"], 1)
        self.assertEqual(cost["records"], 1)
        self.assertEqual(cost["partial_observed_estimate_usd"], 5.25)
        self.assertEqual(cost["observed_count"], 1)
        self.assertEqual(cost["budget_exceeded_count"], 1)
        self.assertEqual(result["costs"]["failure_by_stage"]["generate"], cost)
        self.assertEqual(result["costs"]["total"]["known_usd"], 0.0)
        self.assertEqual(result["costs"]["total"]["unknown_count"], 1)
        with tempfile.TemporaryDirectory() as directory:
            write_report(result, Path(directory))
            markdown = (Path(directory) / "report.md").read_text()
            self.assertIn("Partial observed failure estimate: $5.250000", markdown)
            self.assertIn("Final billed costs remain unknown", markdown)
            self.assertIn("excluded from known totals", markdown)

    def test_known_final_failure_cost_does_not_also_count_observed_estimate(self):
        failure = {"stage": "judge", "key": "finalized-job", "cost_usd": 6.0,
                   "observed_cost_usd": 5.25, "budget_exceeded": True}
        result = report(([], [], []), failures=[failure])
        cost = result["costs"]["failures"]
        self.assertEqual(cost["known_usd"], 6.0)
        self.assertEqual(cost["partial_observed_estimate_usd"], 0.0)
        self.assertEqual(cost["observed_count"], 0)
        self.assertEqual(cost["budget_exceeded_count"], 1)
        self.assertEqual(result["costs"]["total"]["known_usd"], 6.0)
        self.assertEqual(result["costs"]["total"]["unknown_count"], 0)

    def test_partial_caesar_known_components_remain_in_cost_totals(self):
        data = experiment()
        data[1][0]["result"].update(cost_usd=None, usage={"known_cost_usd": 3.05, "unknown_cost": True},
            raw={"usage_audit": {"known_cost_usd": 3.05, "cumulative_known_cost_usd": 3.05,
                                 "unknown_cost": True},
                 "new_attempt_usage_audit": {"known_cost_usd": 1.4, "unknown_cost": False},
                 "budget_history": {"previous_known_cost_usd": 1.65,
                                    "previous_unknown_reserved_usd": .48, "previous_cost_unknown": True}})
        result = report(data)
        self.assertAlmostEqual(result["costs"]["generation"]["known_usd"], 5.05)
        self.assertAlmostEqual(result["costs"]["generation"]["partial_known_estimate_usd"], 3.05)
        self.assertAlmostEqual(result["costs"]["total"]["known_usd"], 6.25)
        self.assertEqual(result["costs"]["generation"]["unknown_count"], 1)
        self.assertEqual(result["costs"]["generation"]["unresolved_reserved_exposure_usd"], .48)

    def test_superseded_paid_judgments_contribute_cost_once_and_never_votes(self):
        data = experiment()
        old = copy.deepcopy(data[2][0])
        old.update(key="superseded-paid", cost_usd=.42)
        old["verdict"]["winner"] = "B"
        data[2].append(old)
        prior = {"key": old["key"], "stage": "judge", "judge": old["judge"],
                 "cost_usd": .42, "valid_for_ranking": False}
        result = report(data, prior_judgments=[prior, copy.deepcopy(prior)])
        self.assertEqual(result["coverage"]["complete_questions"], 1)
        self.assertEqual(result["coverage"]["superseded_judgments_excluded"], 1)
        self.assertEqual(result["ranking"][0]["preference_rate"], 1.0)
        self.assertEqual(result["costs"]["prior_judgments"]["known_usd"], .42)
        self.assertAlmostEqual(result["costs"]["total"]["known_usd"], 4.62)

    def test_inputs_are_not_mutated(self):
        data = experiment(2)
        snapshot = copy.deepcopy(data)
        report(data)
        self.assertEqual(data, snapshot)

    def test_report_writer_emits_json_csv_and_readable_coverage_costs(self):
        result = report(experiment())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reports"
            write_report(result, output)
            self.assertEqual(json.loads((output / "ranking.json").read_text()), result)
            with (output / "ranking.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["agent"], "a")
            self.assertEqual(float(rows[0]["preference_rate"]), 1.0)
            markdown = (output / "report.md").read_text()
            self.assertIn("1 / 1", markdown)
            self.assertIn("unknown", markdown.lower())
            self.assertIn("descriptive", markdown.lower())
            self.assertIn("question", markdown.lower())
            self.assertIn("Paired overall-index contrasts", markdown)
            self.assertIn("Judge diagnostics", markdown)
            self.assertNotIn("Criterion:", markdown)
            self.assertIn("swapped-presentation inconsistency", markdown)
            self.assertIn("frozen answers", markdown)
            self.assertIn("not a Bayesian probability", markdown)


if __name__ == "__main__":
    unittest.main()
