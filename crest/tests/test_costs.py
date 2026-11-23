"""Receipt-based cost metadata never turns reservations or scenarios into invoices."""
import copy
from pathlib import Path

import pytest

from crest.costs import assess_cost, cost_for_row, summarize_costs

PRIOR_KEY = "a" * 64
CURRENT_KEY = "b" * 64


def test_astra_judge_metadata_identifies_usage_pricing_without_changing_saved_cost():
    result = {'model': 'gpt-6-astra', 'cost_usd': .123, 'usage': {}}
    details = assess_cost(result, agent='openai')
    assert details['cost_basis'] == 'usage_priced_estimate'
    assert details['cumulative_known_estimate_usd'] == .123
    assert details['pricing']['rates']['gpt-6-astra'] == {
        'input': 10, 'cached_input': 1, 'cache_write_30m': 12.5, 'output': 50}
    assert 'https://developers.openai.com/api/docs/models/gpt-6-astra' in details['pricing']['source_urls']


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


def test_judge_retry_with_no_known_attempt_charge_is_unpriced_like_a_single_receipt():
    # The outer result reports a price, but every retained attempt's charge is unknown.
    row = {'judge': 'openai', 'key': CURRENT_KEY, 'cost_usd': None, 'cost_scope': 'all_judgment_attempts',
           'result': {'model': 'gpt-6-astra', 'cost_usd': .3},
           'attempts': [{'key': PRIOR_KEY, 'cost_usd': None, 'result': {'model': 'gpt-6-astra'}},
                        {'key': CURRENT_KEY, 'cost_usd': None, 'result': {'model': 'gpt-6-astra'}}]}
    cost = cost_for_row(row)
    assert cost['cumulative_known_estimate_usd'] is None and cost['estimate_incomplete'] is True
    assert cost['cost_basis'] == assess_cost({'model': 'gpt-6-astra', 'cost_usd': None}, agent='openai')['cost_basis'] == 'unpriced'
    summary = summarize_costs([row])
    assert summary['basis_counts'] == {'unpriced': 1} and summary['usage_priced_estimate_usd'] == 0


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


ANTHROPIC_MODEL = 'claude-opus-5-5'
GATEWAY_URL = 'https://gateway.example/v1/messages'
NATIVE_URL = 'https://api.anthropic.com/v1/messages'
GATEWAY_RATES = {'input': 4.4, 'cached_input': .22, 'cache_write_5m': 5.5,
                 'output': 22., 'web_search': 0.}


def anthropic_receipt(*, cost=.044, known=.044, tool_mode='client'):
    """A frozen tariff receipt; its saved dollars must never be recomputed from usage."""
    rates = dict(GATEWAY_RATES, web_search=0. if tool_mode == 'client' else .01)
    return {'model': ANTHROPIC_MODEL, 'cost_usd': cost, 'known_cost_usd': known,
            'estimate_incomplete': cost is None,
            'text': '{"reason":"A proposes an original mechanism with useful evidence, whereas B repeats familiar advice.","winner":"A"}',
            'usage': {'known_cost_usd': known, 'input_tokens': 1000, 'output_tokens': 300},
            'raw': {'turns': [{'model': ANTHROPIC_MODEL, '_api_url': GATEWAY_URL,
                               '_tool_mode': tool_mode,
                               '_pricing': {'rates': rates.copy(), 'source': 'configured'}}],
                    'transport': {'api_url': GATEWAY_URL}, 'tool_mode': tool_mode,
                    'pricing': {'rates_by_model': {ANTHROPIC_MODEL: rates.copy()},
                                'sources_by_model': {ANTHROPIC_MODEL: 'configured'}}}}


@pytest.mark.parametrize('location', ['result', 'usage', 'both'])
@pytest.mark.parametrize('known', [0., 1.25])
def test_anthropic_partial_subtotal_survives_assessment_and_duplicate_summary(location, known):
    result = anthropic_receipt(cost=None, known=known)
    result['raw']['unresolved_submission'] = True
    if location == 'result':
        result['usage'].pop('known_cost_usd')
    elif location == 'usage':
        result.pop('known_cost_usd')
    before = copy.deepcopy(result)
    details = assess_cost(result, agent='anthropic')
    assert details['current_attempt_known_estimate_usd'] == known
    assert details['cumulative_known_estimate_usd'] == known
    assert details['recorded_provider_estimate_usd'] is None
    assert details['estimate_incomplete'] is details['current_attempt_estimate_incomplete'] is True
    assert details['actual_billed_usd'] is None
    row = {'agent': 'anthropic', 'key': CURRENT_KEY, 'result': result, 'cost_details': details}
    summary = summarize_costs([row, copy.deepcopy(row)])
    assert summary['records'] == 1
    assert summary['cumulative_known_estimate_usd'] == known
    assert summary['partial_known_estimate_usd'] == known
    assert summary['unknown_count'] == 1
    assert result == before


@pytest.mark.parametrize('flag', ['result', 'usage', 'raw'])
def test_anthropic_explicit_uncertainty_does_not_become_a_complete_bill(flag):
    result = anthropic_receipt()
    if flag == 'result':
        result['estimate_incomplete'] = True
    elif flag == 'usage':
        result['usage']['unknown_cost'] = True
    else:
        result['raw']['unresolved_submission'] = True
    details = assess_cost(result, agent='anthropic')
    assert details['estimate_incomplete'] is True
    assert details['current_attempt_estimate_incomplete'] is True
    assert details['recorded_provider_estimate_usd'] == .044
    assert details['cumulative_known_estimate_usd'] == .044
    assert details['actual_billed_usd'] is None


@pytest.mark.parametrize('metadata', ['turns', 'aggregate', 'both'])
def test_anthropic_frozen_tariffs_transport_and_tools_win_over_current_settings(metadata):
    result = anthropic_receipt()
    if metadata == 'turns':
        for field in ('pricing', 'transport', 'tool_mode'):
            result['raw'].pop(field)
    elif metadata == 'aggregate':
        result['raw'].pop('turns')
    else:
        # Per-turn evidence takes precedence over a stale aggregate, too.
        result['raw']['pricing']['rates_by_model'][ANTHROPIC_MODEL]['output'] = 999.
        result['raw']['transport']['api_url'] = NATIVE_URL
        result['raw']['tool_mode'] = 'server'
    settings = {'api_base': 'https://api.anthropic.com', 'tool_mode': 'server',
                'model_pricing': {ANTHROPIC_MODEL: {key: value * 10 for key, value in GATEWAY_RATES.items()}}}
    before = copy.deepcopy((result, settings))
    details = assess_cost(result, agent='anthropic', settings=settings)
    assert details['pricing']['rates'][ANTHROPIC_MODEL] == GATEWAY_RATES
    assert details['pricing']['api_url'] == GATEWAY_URL
    assert details['pricing']['tool_mode'] == 'client'
    assert details['pricing']['tool_rates']['web_search_per_request_usd'] == 0
    assert details['cost_basis'] == 'gateway_usage_priced_estimate'
    assert details['recorded_provider_estimate_usd'] == .044
    assert details['cumulative_known_estimate_usd'] == .044
    assert (result, settings) == before


def test_anthropic_judge_executor_row_keeps_receipt_tariff_without_settings(tmp_path):
    from types import SimpleNamespace
    from crest.judge_execution import _row
    result = anthropic_receipt(tool_mode='none')
    parent = SimpleNamespace(key=CURRENT_KEY, path=tmp_path / 'state.json',
                             state={'status': 'completed', 'result': result})
    task = {'key': CURRENT_KEY, 'question_id': 'q1', 'pair': ['a', 'b'], 'order': ['a', 'b'],
            'judge': 'anthropic', 'answer_keys': ['a-key', 'b-key'], 'answer_hashes': ['a-hash', 'b-hash']}
    row, cached = _row(task, parent, True)
    before = copy.deepcopy(row)
    assert cached and 'settings' not in row
    details = cost_for_row(row)
    assert details['cost_basis'] == 'gateway_usage_priced_estimate'
    assert details['pricing']['rates'][ANTHROPIC_MODEL]['output'] == 22.
    assert details['pricing']['tool_mode'] == 'none'
    assert details['pricing']['tool_rates']['web_search_per_request_usd'] == 0
    assert details['recorded_provider_estimate_usd'] == .044
    assert row == before


@pytest.mark.parametrize('raw', [
    {'turns': [{'model': ANTHROPIC_MODEL, '_api_url': NATIVE_URL, '_tool_mode': 'server'}]},
    {'transport': {'api_url': NATIVE_URL}, 'tool_mode': 'server'},
], ids=['turns', 'aggregate'])
def test_anthropic_proven_native_legacy_route_overrides_todays_gateway_config(raw):
    result = {'model': ANTHROPIC_MODEL, 'cost_usd': .123, 'usage': {}, 'raw': raw}
    details = assess_cost(result, agent='anthropic', settings={
        'api_base': 'https://gateway.example', 'tool_mode': 'client',
        'model_pricing': {ANTHROPIC_MODEL: GATEWAY_RATES}})
    assert details['cost_basis'] == 'usage_priced_estimate'
    assert details['pricing']['rates'][ANTHROPIC_MODEL]['output'] == 20
    assert details['pricing']['tool_rates']['web_search_per_request_usd'] == .01
    assert details['recorded_provider_estimate_usd'] == .123


@pytest.mark.parametrize('metadata', ['missing', 'gateway', 'explicit_unknown'])
def test_anthropic_unknown_recorded_tariff_never_gets_guessed_native_or_current_prices(metadata):
    result = {'model': ANTHROPIC_MODEL, 'cost_usd': .123, 'raw': {}}
    settings = {}
    if metadata == 'gateway':
        result['raw']['transport'] = {'api_url': GATEWAY_URL}
        settings = {'api_base': 'https://api.anthropic.com'}
    elif metadata == 'explicit_unknown':
        result['raw'] = {'turns': [{'model': ANTHROPIC_MODEL, '_api_url': NATIVE_URL,
                                    '_pricing': {'rates': None, 'source': 'unknown'}}]}
        settings = {'model_pricing': {ANTHROPIC_MODEL: GATEWAY_RATES}}
    details = assess_cost(result, agent='anthropic', settings=settings)
    assert not details['pricing']['rates'].get(ANTHROPIC_MODEL)
    assert details['cost_basis'] == 'recorded_provider_estimate'
    assert details['recorded_provider_estimate_usd'] == .123
    assert details['cumulative_known_estimate_usd'] == .123


def test_anthropic_all_recorded_model_tariffs_are_retained_without_repricing():
    result = anthropic_receipt()
    result['raw']['turns'].insert(0, {'model': 'gateway/recorded-alias', '_api_url': GATEWAY_URL,
                                    '_tool_mode': 'client',
                                    '_pricing': {'rates': dict(GATEWAY_RATES, output=33.), 'source': 'configured'}})
    details = assess_cost(result, agent='anthropic')
    assert details['pricing']['rates']['gateway/recorded-alias']['output'] == 33.
    assert details['pricing']['rates'][ANTHROPIC_MODEL]['output'] == 22.
    assert details['cumulative_known_estimate_usd'] == .044


def test_gateway_usage_classification_mixed_with_native_gpt_and_scenarios_counts_once():
    gateway = {'agent': 'anthropic', 'key': CURRENT_KEY, 'result': anthropic_receipt(cost=1.25, known=1.25)}
    gateway['cost_details'] = assess_cost(gateway['result'], agent='anthropic', settings={
        'api_base': 'https://gateway.example', 'model_pricing': {ANTHROPIC_MODEL: GATEWAY_RATES}})
    # Synthetic copy of the supplied partial-GPT accounting shape; no pilot artifacts are read.
    gpt = {'agent': 'gpt_researcher', 'result': {'cost_usd': None, 'raw': {
        'accounting': {'known_cost_usd': 2.6069605, 'reserved_usd': .32, 'unknown_cost': True}}}}
    rows = [gateway, copy.deepcopy(gateway), gpt,
            {'agent': 'openai', 'result': {'model': 'gpt-6.1-sol', 'cost_usd': 1.2}},
            {'agent': 'gemini', 'result': google_result()},
            {'agent': 'other', 'result': {'model': 'unpriced-vendor', 'cost_usd': .4}}]
    before = copy.deepcopy(rows)
    summary = summarize_costs(rows)
    assert summary['usage_priced_estimate_usd'] == pytest.approx(5.0569605)
    assert summary['recorded_provider_estimate_usd'] == .4
    assert summary['conditional_scenario_estimate_usd'] == .854
    assert summary['cumulative_known_estimate_usd'] == pytest.approx(6.3109605)
    assert summary['partial_known_estimate_usd'] == 2.6069605
    assert summary['unknown_count'] == 2
    assert summary['unresolved_reserved_exposure_usd'] == .32
    assert summary['basis_counts']['gateway_usage_priced_estimate'] == 1
    assert rows == before


def test_anthropic_partial_judge_attempt_is_retained_and_shared_ancestry_counted_once():
    prior = anthropic_receipt(cost=None, known=1.25)
    success = anthropic_receipt(tool_mode='none')
    row = {'judge': 'anthropic', 'key': CURRENT_KEY, 'cost_usd': None,
           'cost_scope': 'all_judgment_attempts', 'result': success,
           'attempts': [{'key': PRIOR_KEY, 'cost_usd': None, 'result': prior},
                        {'key': CURRENT_KEY, 'cost_usd': .044, 'result': success}]}
    before = copy.deepcopy(row)
    details = cost_for_row(row)
    assert details['cumulative_known_estimate_usd'] == pytest.approx(1.294)
    assert details['prior_attempt_known_estimate_usd'] == 1.25
    assert details['current_attempt_known_estimate_usd'] == .044
    assert details['estimate_incomplete'] is True
    assert details['current_attempt_estimate_incomplete'] is False
    second = copy.deepcopy(row)
    second['key'] = second['attempts'][-1]['key'] = 'c' * 64
    summary = summarize_costs([row, row, second])
    assert summary['cumulative_known_estimate_usd'] == pytest.approx(1.338)
    assert summary['unknown_count'] == 2
    assert row == before


def test_anthropic_stale_attached_assessment_is_rederived_from_receipt_without_mutation():
    row = {'agent': 'anthropic', 'result': anthropic_receipt(cost=None, known=1.25),
           'cost_details': {'version': 'crest-cost-assessment-v2', 'cumulative_known_estimate_usd': None}}
    before = copy.deepcopy(row)
    details = cost_for_row(row)
    assert details['cumulative_known_estimate_usd'] == 1.25
    assert details['pricing']['rates'][ANTHROPIC_MODEL]['output'] == 22.
    assert row == before


def test_anthropic_failed_pipeline_receipt_reaches_report_with_known_partial_cost(tmp_path, write_master_config):
    import asyncio
    import json
    from crest.config import load_config
    from crest.pipeline import Pipeline
    from crest.report import _summarize
    receipt = anthropic_receipt(cost=None, known=1.25)
    receipt['raw']['unresolved_submission'] = True
    class FailedProvider:
        ADAPTER_VERSION = 'offline-cost-regression'
        async def generate(self, prompt, settings, job):
            job.save(provider_result=receipt)
            raise RuntimeError('Synthetic unresolved submission')
    config = load_config(write_master_config(cache_dir=str(tmp_path / 'cache'), output_dir=str(tmp_path / 'results')))
    config['research'] = {'anthropic': config['research']['anthropic']}
    pipeline = Pipeline(config, limit=1, providers={'anthropic': FailedProvider()})
    run = asyncio.run(pipeline.generate())
    assert run['failed'] == 1 and run['completed'] == 0
    path = Path(run['directory']) / 'errors.jsonl'
    original = path.read_bytes()
    row = json.loads(original)
    details = row['cost_details']
    assert details['cumulative_known_estimate_usd'] == 1.25
    assert details['estimate_incomplete'] is True
    assert row['cost_usd'] is None
    summary = _summarize([row], {})
    assert summary['known_cost_usd'] == 1.25
    assert summary['unknown_cost_answers'] == 1
    assert summary['cost_assessment']['usage_priced_estimate_usd'] == 1.25
    assert path.read_bytes() == original


@pytest.mark.parametrize('outer_result', [None, {}])
def test_anthropic_failed_judge_row_uses_nested_attempt_receipt_without_settings(outer_result):
    receipt = anthropic_receipt(cost=None, known=1.25, tool_mode='none')
    row = {'stage': 'judge', 'provider': 'anthropic', 'key': CURRENT_KEY,
           'cost_usd': None, 'known_cost_usd': 0, 'unknown_cost_count': 1,
           'cost_scope': 'all_judgment_attempts',
           'attempts': [{'key': CURRENT_KEY, 'cost_usd': None, 'result': receipt}]}
    if outer_result is not None:
        row['result'] = outer_result
    before = copy.deepcopy(row)
    details = cost_for_row(row)
    assert details['cost_basis'] == 'gateway_usage_priced_estimate'
    assert details['pricing']['rates'][ANTHROPIC_MODEL]['output'] == 22.
    assert details['cumulative_known_estimate_usd'] == 1.25
    assert details['current_attempt_estimate_incomplete'] is details['estimate_incomplete'] is True
    assert summarize_costs([row])['usage_priced_estimate_usd'] == 1.25
    assert row == before


def test_anthropic_recorded_turn_model_wins_when_outer_model_is_absent():
    result = anthropic_receipt()
    result.pop('model')
    details = assess_cost(result, agent='anthropic', settings={'model': 'claude-sonnet-5-5'})
    assert details['actual_internal_model'] == ANTHROPIC_MODEL
    assert details['pricing']['model'] == ANTHROPIC_MODEL
    assert details['pricing']['rates'][ANTHROPIC_MODEL]['output'] == 22.
    assert details['recorded_provider_estimate_usd'] == .044
