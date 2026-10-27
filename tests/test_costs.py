"""Receipt-based cost metadata never turns reservations or scenarios into invoices."""
import copy
from pathlib import Path

import pytest

from crest.costs import assess_cost, cost_for_row, summarize_costs

PRIOR_KEY = "a" * 64
CURRENT_KEY = "b" * 64


def test_judge_retry_receipts_count_rejected_attempts_without_repricing_success_usage():
    success = {'model': 'gpt-6-astra', 'cost_usd': .3, 'usage': {'output_tokens': 100}}
    row = {'judge': 'openai', 'key': CURRENT_KEY, 'result': success, 'cost_usd': .5,
           'cost_scope': 'all_judgment_attempts', 'attempts': [
               {'key': PRIOR_KEY, 'status': 'rejected', 'cost_usd': .2,
                'result': {'model': 'gpt-6-astra', 'cost_usd': .2}},
               {'key': CURRENT_KEY, 'status': 'completed', 'cost_usd': .3, 'result': success}]}
    before = copy.deepcopy(row)
    cost = cost_for_row(row)
    assert cost['current_attempt_known_estimate_usd'] == .3
    assert cost['prior_attempt_known_estimate_usd'] == .2
    assert cost['cumulative_known_estimate_usd'] == .5
    assert summarize_costs([row, row])['cumulative_known_estimate_usd'] == .5
    assert row == before


def test_judge_retry_unknown_charge_retains_known_subtotal_and_uncertainty():
    row = {'judge': 'gemini', 'cost_scope': 'all_judgment_attempts', 'cost_usd': None,
           'result': {'model': 'gemini-4-argon', 'cost_usd': .3},
           'attempts': [{'key': PRIOR_KEY, 'cost_usd': None},
                        {'key': CURRENT_KEY, 'status': 'completed', 'cost_usd': .3}]}
    cost = cost_for_row(row)
    assert cost['cumulative_known_estimate_usd'] == .3
    assert cost['estimate_incomplete'] is True


def caesar_result():
    current = {"known_cost_usd": 1.4, "unknown_cost": False,
               "events": [{"status": "completed", "cost_usd": 1.4}], "in_flight": []}
    history = {"previous_known_cost_usd": 1.65, "previous_unknown_reserved_usd": .48,
               "previous_cost_unknown": True, "source_job": "/jobs/" + PRIOR_KEY,
               "ancestry": [{"source_job": "/jobs/" + PRIOR_KEY, "known_cost_usd": 1.65,
                             "unknown_reserved_usd": .48, "cost_unknown": True}]}
    cumulative = {**current, "known_cost_usd": 3.05, "cumulative_known_cost_usd": 3.05,
                  "new_attempt_cost_usd": 1.4, "unknown_cost": True}
    return {"text": "Unchanged final answer", "model": "gpt-6.1-sol", "cost_usd": None,
            "usage": cumulative, "raw": {"usage_audit": cumulative,
                "new_attempt_usage_audit": current, "budget_history": history}}


def test_caesar_keeps_partial_cumulative_known_cost_without_adding_history_twice():
    result = caesar_result()
    before = copy.deepcopy(result)
    cost = assess_cost(result, agent="caesar")
    assert cost["current_attempt_known_estimate_usd"] == 1.4
    assert cost["prior_attempt_known_estimate_usd"] == 1.65
    assert cost["cumulative_known_estimate_usd"] == 3.05
    assert cost["historical_unresolved_reserved_exposure_usd"] == .48
    assert cost["current_unresolved_reserved_exposure_usd"] == 0
    assert cost["unresolved_reserved_exposure_usd"] == .48
    assert cost["estimate_incomplete"] is True
    assert cost["actual_billed_usd"] is None
    assert cost["invoice_status"] == "unverified"
    assert result == before
    assert assess_cost(result, agent="caesar") == cost


def test_failed_caesar_current_audit_and_prior_reservations_are_not_measured_spend():
    result = {"cost_usd": None, "usage": {"known_cost_usd": .4, "unknown_cost": True,
        "events": [{"status": "failed", "cost_usd": None, "unknown_cost": True, "reserved_usd": .2},
                   {"status": "failed", "cost_usd": 0, "unknown_cost": False, "reserved_usd": 0}],
        "in_flight": []}, "raw": {"budget_history": {"previous_known_cost_usd": 1,
        "previous_unknown_reserved_usd": .3, "previous_cost_unknown": True}}}
    cost = assess_cost(result, agent="caesar")
    assert cost["current_attempt_known_estimate_usd"] == .4
    assert cost["cumulative_known_estimate_usd"] == 1.4
    assert cost["unresolved_reserved_exposure_usd"] == .5
    assert cost["estimate_incomplete"] is True


def google_result():
    return {"text": "Unchanged Google answer", "model": "gemini-3.1-pro-preview", "cost_usd": .854,
        "usage": {"input_tokens": 100000, "cached_input_tokens": 10000, "output_tokens": 20000,
                  "reasoning_tokens": 5000, "tool_use_tokens": 3000, "total_tokens": 128000,
                  "grounding_tool_count": [{"type": "google_search", "count": 2}]},
        "raw": {"agent": "deep-research-preview-04-2026"}}


def test_google_eight_conditional_scenarios_are_not_verified_costs_or_bounds():
    result = google_result()
    cost = assess_cost(result, agent="gemini", settings={"agent": "deep-research-preview-04-2026"})
    assert cost["cost_basis"] == "conditional_list_price_scenario"
    assert cost["actual_internal_model"] is None
    assert cost["pricing"]["reference_model"] == "gemini-3.1-pro-preview"
    assert cost["cumulative_known_estimate_usd"] == .854
    assert cost["actual_billed_usd"] is None
    assert cost["invoice_status"] == "unverified"
    assert cost["estimate_incomplete"] is True
    scenarios = cost["conditional_scenarios"]
    assert len(scenarios) == 8
    assert scenarios["high_tool_input_included_full_price_search"]["estimate_usd"] == pytest.approx(.854)
    assert scenarios["low_tool_input_included_full_price_search"]["estimate_usd"] == pytest.approx(.516)
    assert scenarios["low_tool_input_excluded_search_allowance"]["estimate_usd"] == pytest.approx(.482)
    assert all(row["classification"] == "conditional_scenario" for row in scenarios.values())
    assert all("bound" not in row for row in scenarios.values())


def test_missing_google_usage_does_not_fabricate_a_zero_cost_scenario():
    result = google_result()
    result["usage"].pop("tool_use_tokens")
    cost = assess_cost(result, agent="gemini")
    assert cost["conditional_scenarios"] == {}
    assert cost["estimate_incomplete"] is True
    assert cost["cumulative_known_estimate_usd"] == .854


def test_summary_derives_legacy_records_and_keeps_partial_known_components():
    rows = [{"agent": "caesar", "key": CURRENT_KEY, "result": caesar_result()},
            {"agent": "openai", "key": "native", "result": {"model": "gpt-6.1-sol", "cost_usd": 1.2}}]
    snapshot = copy.deepcopy(rows)
    summary = summarize_costs(rows)
    assert summary["cumulative_known_estimate_usd"] == pytest.approx(4.25)
    assert summary["current_attempt_known_estimate_usd"] == pytest.approx(2.6)
    assert summary["prior_attempt_known_estimate_usd"] == 1.65
    assert summary["unknown_count"] == 1
    assert summary["unresolved_reserved_exposure_usd"] == .48
    assert summary["actual_billed_usd"] is None
    assert rows == snapshot
    assert cost_for_row(rows[0])["cumulative_known_estimate_usd"] == 3.05


def test_history_covered_failure_and_duplicate_rows_are_not_charged_twice():
    answer = {"agent": "caesar", "key": CURRENT_KEY, "result": caesar_result()}
    prior = {"stage": "generate", "provider": "caesar", "key": PRIOR_KEY,
             "cache_record": "/jobs/" + PRIOR_KEY + "/state.json", "cost_usd": None,
             "usage": {"known_cost_usd": 1.65, "unknown_cost": True}}
    summary = summarize_costs([answer, prior, copy.deepcopy(prior)])
    assert summary["records"] == 2
    assert summary["history_covered_records"] == 1
    assert summary["cumulative_known_estimate_usd"] == 3.05
    assert summary["unresolved_reserved_exposure_usd"] == .48
    assert summary["unknown_count"] == 1


def test_conditional_google_scenario_is_separate_from_usage_priced_estimates():
    rows = [{"agent": "gemini", "result": google_result()},
            {"agent": "openai", "result": {"model": "gpt-6.1-sol", "cost_usd": 1.2}}]
    summary = summarize_costs(rows)
    assert summary["usage_priced_estimate_usd"] == 1.2
    assert summary["conditional_scenario_estimate_usd"] == .854
    assert summary["cumulative_known_estimate_usd"] == pytest.approx(2.054)
    assert summary["basis_counts"]["conditional_list_price_scenario"] == 1


def test_annotation_leaves_all_200_native_judgment_keys_and_answer_bytes_unchanged():
    from crest.cache import digest
    from crest.judging import make_judgment_jobs
    questions = [{"id": f"q-{i}", "text": f"Question {i}"} for i in range(50)]
    answers = [{"question_id": q["id"], "agent": agent, "key": digest([q["id"], agent]),
                "result": {"text": f"Full answer {agent} / {q['id']}", "cost_usd": .2}}
               for q in questions for agent in ("openai", "gemini")]
    snapshot = copy.deepcopy(answers)
    judges = {"openai": {"model": "gpt-6-astra"}, "gemini": {"model": "gemini-4-argon"}}
    before = make_judgment_jobs(questions, answers, judges, "One overall creativity preference")
    for row in answers:
        row["cost_details"] = assess_cost(row["result"], agent=row["agent"])
    after = make_judgment_jobs(questions, answers, judges, "One overall creativity preference")
    assert len(before) == len(after) == 200
    assert [row["key"] for row in after] == [row["key"] for row in before]
    assert [{k: v for k, v in row.items() if k != "cost_details"} for row in answers] == snapshot


def test_shared_prior_attempt_is_deduplicated_across_descendant_ledgers():
    first, second = caesar_result(), caesar_result()
    second['usage'].update(known_cost_usd=2.15, cumulative_known_cost_usd=2.15, new_attempt_cost_usd=.5)
    second['raw']['new_attempt_usage_audit']['known_cost_usd'] = .5
    summary = summarize_costs([{'agent': 'caesar', 'key': CURRENT_KEY, 'result': first},
                               {'agent': 'caesar', 'key': 'c' * 64, 'result': second}])
    assert summary['cumulative_known_estimate_usd'] == pytest.approx(3.55)
    assert summary['partial_known_estimate_usd'] == pytest.approx(3.55)
    assert summary['current_attempt_known_estimate_usd'] == pytest.approx(1.9)
    assert summary['prior_attempt_known_estimate_usd'] == 1.65
    assert summary['unresolved_reserved_exposure_usd'] == .48


def test_legacy_cumulative_usage_markers_do_not_add_prior_cost_twice():
    result = {'cost_usd': None, 'usage': {'known_cost_usd': 3.05, 'unknown_cost': True,
              'budget_history_previous_known_cost_usd': 1.65,
              'budget_history_previous_unknown_reserved_usd': .48}}
    cost = assess_cost(result, agent='caesar')
    assert cost['cumulative_known_estimate_usd'] == 3.05
    assert cost['current_attempt_known_estimate_usd'] == pytest.approx(1.4)


def test_google_recorded_scenario_mismatch_is_exposed_without_overwriting_receipt():
    result = google_result()
    result['cost_usd'] = .5
    cost = assess_cost(result, agent='gemini')
    assert cost['recorded_scenario_matches'] is False
    assert cost['conditional_scenarios']['high_tool_input_included_full_price_search']['estimate_usd'] == pytest.approx(.854)
    assert cost['recorded_provider_estimate_usd'] == .5
    assert result['cost_usd'] == .5


def test_ordinary_legacy_gemini_31_judge_is_not_managed_research():
    result = {'model': 'gemini-3.1-pro-preview', 'cost_usd': .2,
              'raw': {'model': 'gemini-3.1-pro-preview'},
              'usage': {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 20,
                        'reasoning_tokens': 10, 'tool_use_tokens': 0, 'grounding_tool_count': []}}
    direct = assess_cost(result, agent='gemini')
    legacy = cost_for_row({'judge': 'gemini', 'result': result})
    assert direct['cost_basis'] != 'conditional_list_price_scenario'
    assert direct['conditional_scenarios'] == {}
    assert direct['estimate_incomplete'] is False
    assert legacy == direct
