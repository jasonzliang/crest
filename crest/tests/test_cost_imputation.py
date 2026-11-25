"""Imputed costs for calls that never reported one; saved rows are read, never changed."""
import copy
import json
import math
from pathlib import Path

import pytest

from crest.cost_imputation import (impute_answer_costs, impute_judgment_costs,
                                   summarize_imputation)

RATES = {'input': 4.4, 'cached_input': .22, 'cache_write_5m': 5.5, 'output': 22.0, 'web_search': 0}


def ev(model, reserved, cost=None, failed=False):
    if failed:
        return {'model': model, 'reserved_usd': reserved, 'unknown_cost': True, 'status': 'failed',
                'status_code': 520, 'cost_usd': None}
    return {'model': model, 'reserved_usd': reserved, 'unknown_cost': False, 'status': 'completed',
            'cost_usd': cost}


def caesar(qid, events, in_flight=()):
    known = math.fsum(e['cost_usd'] for e in events if e.get('cost_usd') is not None)
    usage = {'known_cost_usd': known, 'cost_usd': None if any(e.get('unknown_cost') for e in events) else known,
             'unknown_cost': any(e.get('unknown_cost') for e in events) or bool(in_flight),
             'events': events, 'in_flight': list(in_flight)}
    return {'key': f'caesar-{qid}', 'question_id': qid, 'agent': 'caesar',
            'result': {'model': 'gpt-6.1-sol', 'cost_usd': usage['cost_usd'], 'usage': usage,
                       'raw': {'usage_audit': usage}}}


def turn(rnd, stop, *, inp=2, read=0, write=0, out=0):
    return {'model': 'claude-opus-5-5', 'stop_reason': stop, '_round': rnd,
            'usage': {'input_tokens': inp, 'cache_read_input_tokens': read,
                      'cache_creation_input_tokens': write, 'output_tokens': out},
            '_pricing': {'rates': RATES, 'source': 'configured'}}


def turn_cost(t):
    u = t['usage']
    return (u['input_tokens'] * 4.4 + u['cache_read_input_tokens'] * .22
            + u['cache_creation_input_tokens'] * 5.5 + u['output_tokens'] * 22) / 1e6


def anthropic(qid, turns, *, unresolved=True):
    known = math.fsum(turn_cost(t) for t in turns)
    raw = {'turns': turns, 'tool_mode': 'client',
           'pricing': {'rates_by_model': {'claude-opus-5-5': RATES}}}
    if unresolved:
        raw['unresolved_submission'] = True
    return {'key': f'anthropic-{qid}', 'question_id': qid, 'agent': 'anthropic',
            'result': {'model': 'claude-opus-5-5', 'cost_usd': None if unresolved else known,
                       'known_cost_usd': known, 'estimate_incomplete': unresolved,
                       'usage': {'known_cost_usd': known}, 'raw': raw}}


def by_key(records):
    return {r['key']: r for r in records}


# Caesar: failed calls in the usage ledger ------------------------------------------------

def test_failed_call_takes_the_cost_of_the_same_size_retry_and_reports_its_reservation():
    events = [ev('gpt-6.1-sol', .10, .010), ev('gpt-6.1-sol', .20, .020), ev('gpt-6.1-sol', .30, .030),
              ev('gpt-6.1-sol', .40, .040), ev('gpt-6.1-sol', .50, .050), ev('gpt-6.1-sol', .55, .055),
              ev('gpt-6.1-sol', .547, failed=True), ev('gpt-6.1-sol', .547, .111),
              ev('gpt-6-luna', .547, .9)]  # A different model never counts as comparable.
    row = caesar('q1', events)
    rec = by_key(impute_answer_costs([row]))['caesar-q1']
    assert rec['imputed_calls'] == 1
    assert rec['imputed_usd'] == pytest.approx(.111)
    assert rec['upper_bound_usd'] == pytest.approx(.547)
    assert rec['known_usd'] == pytest.approx(math.fsum(e['cost_usd'] or 0 for e in events))
    assert rec['estimate_usd'] == pytest.approx(rec['known_usd'] + .111)
    assert rec['estimate_incomplete'] is True and rec['residual_incomplete'] is False
    call = rec['calls'][0]
    assert call['index'] == 6 and call['model'] == 'gpt-6.1-sol'
    assert call['basis'] == 'same_reservation_in_answer' and call['comparable_count'] == 1


def test_without_an_equal_reservation_uses_the_k_nearest_reservations_in_the_answer():
    events = [ev('gpt-6.1-sol', r, r / 10) for r in (.10, .20, .30, .40, .50, .60, .70)]
    events.append(ev('gpt-6.1-sol', .42, failed=True))
    rec = impute_answer_costs([caesar('q1', events)])[0]
    # Nearest five to .42: .40, .50, .30, .60, .20 (ties broken toward the smaller reservation).
    assert rec['imputed_usd'] == pytest.approx((.040 + .050 + .030 + .060 + .020) / 5)
    assert rec['calls'][0]['basis'] == 'nearest_reservation_in_answer'
    assert rec['calls'][0]['comparable_count'] == 5


def test_too_few_comparables_in_the_answer_falls_back_to_the_system_and_model():
    sparse = caesar('q1', [ev('gpt-6.1-sol', .30, .03), ev('gpt-6.1-sol', .45, failed=True)])
    other = caesar('q2', [ev('gpt-6.1-sol', r, r / 5) for r in (.40, .44, .46, .50, .55, .90)]
                   + [ev('gpt-6-luna', .45, 5.0)])
    gpt_researcher = {'key': 'g', 'question_id': 'q2', 'agent': 'gpt_researcher',
                      'result': caesar('q3', [ev('gpt-6.1-sol', .45, 9.0)])['result']}
    rec = by_key(impute_answer_costs([sparse, other, gpt_researcher]))['caesar-q1']
    # Pool = known Sol calls from every Caesar answer: .30 (q1) and q2's six; five nearest to .45.
    assert rec['imputed_usd'] == pytest.approx((.088 + .092 + .080 + .100 + .110) / 5)
    assert rec['calls'][0]['basis'] == 'nearest_reservation_in_system'


def test_imputed_call_is_capped_at_its_reservation():
    events = [ev('gpt-6.1-sol', .01, .5)] * 5 + [ev('gpt-6.1-sol', .01, failed=True)]
    rec = impute_answer_costs([caesar('q1', events)])[0]
    assert rec['imputed_usd'] == pytest.approx(.01)
    assert rec['calls'][0]['capped_at_reservation'] is True


def test_in_flight_calls_are_imputed_like_failed_calls():
    events = [ev('gpt-6-luna', r, r / 10) for r in (.001, .002, .003, .004, .005)]
    row = caesar('q1', events, in_flight=[{'model': 'gpt-6-luna', 'reserved_usd': .003}])
    rec = impute_answer_costs([row])[0]
    assert rec['imputed_calls'] == 1 and rec['imputed_usd'] == pytest.approx(.0003)
    assert rec['calls'][0]['source'] == 'in_flight'


def test_complete_rows_and_assumed_price_rows_impute_nothing():
    done = caesar('q1', [ev('gpt-6.1-sol', .1, .01)])
    gemini = {'key': 'gem', 'question_id': 'q1', 'agent': 'gemini',
              'result': {'model': 'gemini-3.1-pro-preview', 'cost_usd': 2.0, 'usage': {},
                         'raw': {'agent': 'deep-research-pro'}},
              'settings': {'agent': 'deep-research-pro'}}
    recs = by_key(impute_answer_costs([done, gemini]))
    assert recs['caesar-q1']['imputed_calls'] == 0 and recs['caesar-q1']['imputed_usd'] == 0
    assert recs['caesar-q1']['estimate_incomplete'] is False
    assert recs['gem']['imputed_calls'] == 0 and recs['gem']['estimate_incomplete'] is True
    assert recs['gem']['residual_incomplete'] is True
    assert recs['gem']['residual_reason'] == 'conditional_list_price_scenario'


def test_rows_are_never_mutated():
    rows = [caesar('q1', [ev('gpt-6.1-sol', .2, .02)] * 5 + [ev('gpt-6.1-sol', .2, failed=True)]),
            anthropic('q2', [turn(1, 'tool_use', write=1000, out=100), turn(1, 'end_turn', read=1000, out=50)])]
    before = copy.deepcopy(rows)
    impute_answer_costs(rows)
    summarize_imputation(impute_answer_costs(rows))
    assert rows == before


# Anthropic: an unresolved submission after the last saved turn ------------------------------

def test_lost_continuation_turn_uses_known_continuation_turns_of_the_same_round():
    turns = [turn(1, 'tool_use', write=2000, out=8000), turn(1, 'tool_use', read=2000, write=500, out=100),
             turn(1, 'end_turn', read=2500, write=300, out=9000),
             turn(2, 'tool_use', read=2800, write=4000, out=900),      # round start
             turn(2, 'tool_use', read=6800, write=400, out=200),       # continuation
             turn(2, 'tool_use', read=7200, write=600, out=300)]       # continuation, then the lost POST
    row = anthropic('q1', turns)
    rec = impute_answer_costs([row])[0]
    assert rec['imputed_calls'] == 1
    assert rec['imputed_usd'] == pytest.approx((turn_cost(turns[4]) + turn_cost(turns[5])) / 2)
    assert rec['upper_bound_usd'] is None
    assert rec['calls'][0]['basis'] == 'same_kind_turns_in_round'
    assert rec['calls'][0]['kind'] == 'continuation' and rec['calls'][0]['round'] == 2
    assert rec['known_usd'] == pytest.approx(math.fsum(turn_cost(t) for t in turns))


def test_lost_round_start_falls_back_to_round_starts_in_the_answer():
    turns = [turn(1, 'tool_use', write=2000, out=800), turn(1, 'end_turn', read=2000, out=900),
             turn(2, 'tool_use', read=2900, write=3000, out=700), turn(2, 'end_turn', read=5900, out=600)]
    rec = impute_answer_costs([anthropic('q1', turns)])[0]
    assert rec['calls'][0]['kind'] == 'round_start' and rec['calls'][0]['round'] == 3
    assert rec['calls'][0]['basis'] == 'same_kind_turns_in_answer'
    assert rec['imputed_usd'] == pytest.approx((turn_cost(turns[0]) + turn_cost(turns[2])) / 2)


def test_completed_anthropic_answer_imputes_nothing():
    rec = impute_answer_costs([anthropic('q1', [turn(1, 'end_turn', write=10, out=10)], unresolved=False)])[0]
    assert rec['imputed_calls'] == 0 and rec['estimate_incomplete'] is False


# Judging: attempts resent after an unknown outcome -----------------------------------------

JUDGES = {'anthropic': {'model': 'claude-opus-5-5', 'max_output_tokens': 32768}}


def judgment(key, qid, attempts, judge='anthropic'):
    known = math.fsum(a['cost_usd'] for a in attempts if a['cost_usd'] is not None)
    complete = all(a['cost_usd'] is not None for a in attempts)
    final = attempts[-1]
    return {'key': key, 'question_id': qid, 'judge': judge, 'cost_scope': 'all_judgment_attempts',
            'cost_usd': known if complete else None, 'known_cost_usd': known,
            'unknown_cost_count': sum(a['cost_usd'] is None for a in attempts),
            'result': final['result'] if final['cost_usd'] is not None else {}, 'attempts': attempts}


def attempt(key, cost, *, write=20000, out=1200):
    if cost is None:
        return {'key': key, 'status': 'rejected', 'cost_usd': None, 'resent_after_unknown_outcome': True,
                'result': {'model': 'claude-opus-5-5', 'cost_usd': None, 'estimate_incomplete': True,
                           'usage': {'turns': 0, 'known_cost_usd': 0.0},
                           'raw': {'turns': [], 'unresolved_submission': True,
                                   'pricing': {'rates_by_model': {'claude-opus-5-5': RATES}}}}}
    t = turn(1, 'end_turn', inp=4, write=write, out=out)
    return {'key': key, 'status': 'completed', 'cost_usd': cost,
            'result': {'model': 'claude-opus-5-5', 'cost_usd': cost, 'usage': {'known_cost_usd': cost},
                       'raw': {'turns': [t], 'pricing': {'rates_by_model': {'claude-opus-5-5': RATES}}}}}


def test_unknown_judge_attempt_takes_the_cost_of_its_resend_and_a_max_output_bound():
    row = judgment('j1', 'q1', [attempt('a1', None), attempt('a2', .1426876, write=20964, out=1244)])
    other = judgment('j2', 'q1', [attempt('b1', .09)])
    before = copy.deepcopy([row, other])
    recs = by_key(impute_judgment_costs([row, other], judges=JUDGES))
    rec = recs['j1']
    assert rec['imputed_calls'] == 1 and rec['imputed_usd'] == pytest.approx(.1426876)
    assert rec['calls'][0]['basis'] == 'same_job_resend'
    # The resend's prompt at the dearest input-side rate, plus the judge's max_output_tokens.
    assert rec['upper_bound_usd'] == pytest.approx(((4 + 20964) * 5.5 + 32768 * 22) / 1e6)
    assert rec['known_usd'] == pytest.approx(.1426876)
    assert recs['j2']['imputed_calls'] == 0
    assert [row, other] == before


def test_judge_attempt_without_a_resend_uses_the_same_question_and_judge_median():
    lost = judgment('j1', 'q1', [attempt('a1', None)])
    same_q = [judgment(f'q{i}', 'q1', [attempt(f'x{i}', c)]) for i, c in enumerate((.10, .30, .20))]
    other_q = judgment('z', 'q2', [attempt('z1', 5.0)])
    other_judge = judgment('o', 'q1', [attempt('o1', 7.0)], judge='openai')
    rec = by_key(impute_judgment_costs([lost, *same_q, other_q, other_judge]))['j1']
    assert rec['imputed_usd'] == pytest.approx(.20)
    assert rec['calls'][0]['basis'] == 'same_question_and_judge_median'
    assert rec['upper_bound_usd'] is None  # No judge settings, so no output cap.


def test_judge_fallback_to_the_judge_median_across_questions():
    lost = judgment('j1', 'q1', [attempt('a1', None)])
    rows = [lost] + [judgment(f'k{i}', 'q9', [attempt(f'k{i}', c)]) for i, c in enumerate((.1, .2, .3, .4))]
    rec = by_key(impute_judgment_costs(rows))['j1']
    assert rec['imputed_usd'] == pytest.approx(.25)
    assert rec['calls'][0]['basis'] == 'same_judge_median'


# Summary ------------------------------------------------------------------------------------

def test_summary_reports_means_before_and_after_per_system():
    rows = [caesar('q1', [ev('gpt-6.1-sol', .2, .1)] * 5 + [ev('gpt-6.1-sol', .2, failed=True)]),
            caesar('q2', [ev('gpt-6.1-sol', .2, .3)])]
    summary = summarize_imputation(impute_answer_costs(rows))
    s = summary['caesar']
    assert s['records'] == 2 and s['incomplete_before'] == 1 and s['incomplete_after'] == 0
    assert s['imputed_records'] == 1 and s['imputed_calls'] == 1
    assert s['imputed_usd'] == pytest.approx(.1) and s['upper_bound_usd'] == pytest.approx(.2)
    assert s['known_mean_usd'] == pytest.approx((.5 + .3) / 2)
    assert s['estimate_mean_usd'] == pytest.approx((.6 + .3) / 2)
    assert s['mean_change_usd'] == pytest.approx(.05)
    assert s['upper_bound_mean_usd'] == pytest.approx((.7 + .3) / 2)


def test_summary_upper_bound_is_none_when_a_call_has_no_bound():
    turns = [turn(1, 'tool_use', write=100, out=100), turn(1, 'tool_use', read=100, write=50, out=50)]
    s = summarize_imputation(impute_answer_costs([anthropic('q1', turns)]))['anthropic']
    assert s['imputed_calls'] == 1 and s['upper_bound_usd'] is None


# Frozen 2026-11-24 study (read-only; skipped when the results are absent) ------------------

RESULTS = Path(__file__).resolve().parents[1] / 'results' / '2026-11-24'
GENERATE = (RESULTS / '04-13-43-CST-5-research-agents-q50-6324120b'
            / '01-generate-2026-11-24_04-13-44-CST' / 'answers.jsonl')


def _jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.skipif(not GENERATE.exists(), reason='frozen study results not present')
def test_frozen_study_imputes_twelve_caesar_answers_and_one_anthropic_answer():
    rows = _jsonl(GENERATE)
    recs = impute_answer_costs(rows)
    imputed = [r for r in recs if r['imputed_calls']]
    assert sorted({r['agent'] for r in imputed}) == ['anthropic', 'caesar']
    assert sum(r['agent'] == 'caesar' for r in imputed) == 12
    assert sum(r['agent'] == 'anthropic' for r in imputed) == 1
    assert all(r['residual_incomplete'] is False for r in imputed)
    assert {r['agent'] for r in recs if r['residual_incomplete']} == {'gemini'}
    summary = summarize_imputation(recs)
    assert summary['caesar']['imputed_calls'] == 15
    assert summary['caesar']['upper_bound_usd'] == pytest.approx(4.64, abs=.01)
    assert 0 < summary['caesar']['imputed_usd'] < summary['caesar']['upper_bound_usd']


@pytest.mark.skipif(not GENERATE.exists(), reason='frozen study results not present')
def test_frozen_study_judging_imputes_three_v1_and_one_v2_calls():
    counts = {}
    for run, expected in (('04-13-43-CST-5-research-agents-q50-6324120b', 3),
                          ('04-14-01-CST-5-research-agents-q50-d1ec03a9', 1)):
        stage = RESULTS / run / '02-judge-2026-11-24_14-49-13-CST'
        judges = json.loads((stage / 'judges.json').read_text())
        recs = impute_judgment_costs(_jsonl(stage / 'judgments.jsonl'), judges=judges)
        counts[run] = sum(r['imputed_calls'] for r in recs)
        assert counts[run] == expected
        assert all(c['basis'] == 'same_job_resend' for r in recs for c in r['calls'])
