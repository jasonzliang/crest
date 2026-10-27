"""Offline HTML publication of a complete, frozen CREST research comparison.

Usage: python -m crest.report RUN --output docs/deep-research-creativity.html
Only complete 50-question, three-system comparisons can be written. Rendering
never submits jobs, changes analysis, or reads mutable generation caches.

Optional enrichment uses the existing crest-final-audit-v1 artifact produced by
crest-final-audit.py. It must be complete, ready, and match the frozen answer
identities. No alternative audit or accounting protocol is introduced here.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from html import escape
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import statistics
import tempfile

from .analysis import analyze
from .artifacts import configuration_record
from .costs import cost_for_row, summarize_costs
from .judging import parse_verdict, validate_verdict
from crest_ais.navigation import CSS as SITE_CSS, site_header

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ('caesar', 'gemini', 'openai')
JUDGES = ('gemini', 'openai')
LABELS = {'caesar': 'Caesar', 'openai': 'OpenAI · Sol + hosted web search',
          'gemini': 'Google · managed Deep Research'}
SHORT = {'caesar': 'Caesar', 'openai': 'OpenAI', 'gemini': 'Google'}
COLORS = {'caesar': '#0b5967', 'gemini': '#b4652b', 'openai': '#5e628c'}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _text(value):
    return escape(str(value), quote=True)


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _jsonl(path):
    return [_json_line(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def _json_line(line):
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError('A canonical record must be a JSON object')
    return value


def _stage(run, name):
    if not isinstance(name, str) or not name or Path(name).name != name or name in {'.', '..'}:
        raise ValueError('Invalid stage directory in run manifest')
    path = (run / name).resolve()
    if not path.is_relative_to(run) or not path.is_dir():
        raise ValueError('Stage directory must exist inside the selected run')
    return path


def _latest_analysis(run, manifest):
    stages = [s for s in manifest.get('stages', []) if s.get('name') == 'analysis'
              and s.get('status') == 'completed']
    if not stages:
        raise ValueError('Final publication requires a completed analysis stage')
    return _stage(run, stages[-1].get('directory'))


def _validate(data):
    questions, answers, judgments, ranking = (data[k] for k in ('questions', 'answers', 'judgments', 'ranking'))
    if (len(questions) != 50 or len({q['id'] for q in questions}) != 50
            or len({q.get('text') for q in questions}) != 50
            or any(not isinstance(q.get('text'), str) or not q['text'].strip() for q in questions)):
        raise ValueError('Final publication requires 50 unique questions')
    if data['manifest'].get('questions') != questions or set(data['manifest'].get('agents', [])) != set(AGENTS):
        raise ValueError('Questions and three agents must match the frozen run manifest')
    ids = {q['id'] for q in questions}
    expected_answers = {(q, a) for q in ids for a in AGENTS}
    answer_ids = [(a.get('question_id'), a.get('agent')) for a in answers]
    if len(answers) != 150 or set(answer_ids) != expected_answers:
        raise ValueError('Final publication requires 150 unique complete answers')
    if any(not isinstance(a.get('key'), str) or not a['key'] for a in answers) or len({a['key'] for a in answers}) != 150:
        raise ValueError('Every answer must have a unique canonical key')
    if any(not isinstance(a.get('result'), dict) or not isinstance(a['result'].get('text'), str)
           or not a['result']['text'].strip() or a.get('status', 'completed') != 'completed' for a in answers):
        raise ValueError('Every answer must be nonempty and complete')
    for qid in ids:
        texts = [a['result']['text'] for a in answers if a['question_id'] == qid]
        if len(set(texts)) != 3:
            raise ValueError('Identical answers cannot form a complete scored question')
    if set(data['judges']) != set(JUDGES):
        raise ValueError('Both configured judges are required')
    cells = {(q, pair, order, judge) for q in ids for pair in combinations(AGENTS, 2)
             for order in (pair, pair[::-1]) for judge in JUDGES}
    seen, keys = set(), set()
    answer_map = {(a['question_id'], a['agent']): a for a in answers}
    for row in judgments:
        pair, order = tuple(row.get('pair', [])), tuple(row.get('order', []))
        cell = (row.get('question_id'), pair, order, row.get('judge'))
        if cell not in cells or cell in seen or row.get('status', 'completed') != 'completed':
            raise ValueError('Missing, duplicate or invalid judgment cell')
        seen.add(cell)
        if not isinstance(row.get('key'), str) or not row['key'] or row['key'] in keys:
            raise ValueError('Judgments require unique canonical keys')
        keys.add(row['key'])
        verdict = validate_verdict(row.get('verdict'))
        text = (row.get('result') or {}).get('text')
        if text is not None and parse_verdict(text) != verdict:
            raise ValueError('Stored verdict differs from the provider result')
        ordered = [answer_map[row['question_id'], a] for a in order]
        if 'answer_keys' in row and row['answer_keys'] != [a['key'] for a in ordered]:
            raise ValueError('Judgment references different saved answers')
        if 'answer_hashes' in row and row['answer_hashes'] != [
                hashlib.sha256(a['result']['text'].encode()).hexdigest() for a in ordered]:
            raise ValueError('Judgment answer content hashes do not match')
    if len(judgments) != 600 or seen != cells:
        raise ValueError('Final publication requires 600 valid overall judgments')
    bootstrap = ranking.get('bootstrap', {})
    if bootstrap.get('unit') != 'question' or bootstrap.get('samples') != 1000 or type(bootstrap.get('seed')) is not int:
        raise ValueError('Final publication requires the saved 1000-resample question bootstrap')
    computed = analyze(questions, answers, judgments, agents=list(AGENTS), judges=list(JUDGES),
                       bootstrap_samples=1000, seed=bootstrap['seed'])
    # Display the saved analysis, checking its arithmetic and uncertainty rather
    # than silently replacing stale values or borrowing the AIS sampling method.
    for key in ('agents', 'judges', 'coverage', 'ranking', 'paired_contrasts', 'per_judge',
                'pairwise', 'diagnostics', 'bootstrap'):
        if ranking.get(key) != computed[key]:
            raise ValueError(f'Saved ranking does not match frozen evidence: {key}')


def _audit_records(run, path, answers):
    if path is None:
        candidates = sorted(run.glob('04-audit*/audit.json'), key=lambda p: (p.stat().st_mtime_ns, p.name))
        path = candidates[-1] if candidates else None
    if path is None:
        return {}, None, None
    path = Path(path).expanduser().resolve()
    doc = _json(path)
    generation, judging = doc.get('generation', {}), doc.get('judging', {})
    if (doc.get('audit_version') != 'crest-final-audit-v1' or doc.get('status') != 'complete'
            or doc.get('ready') is not True or doc.get('errors') != [] or doc.get('pending') != []
            or Path(doc.get('run_dir', '')).name != run.name
            or generation.get('completed_answers') != 150 or generation.get('snapshot_answer_rows') != 150
            or judging.get('valid_calls') != 600 or judging.get('complete_questions') != 50
            or doc.get('ranking', {}).get('matches_independent_calculation') is not True
            or not isinstance(generation.get('answer_details'), list)):
        raise ValueError('Final audit must be complete, ready, and match the selected run')
    expected = {(a['question_id'], a['agent']): a['key'] for a in answers}
    records = {}
    for row in generation['answer_details']:
        identity = (row.get('question_id'), row.get('agent'))
        if (identity not in expected or row.get('key') != expected[identity] or identity in records
                or row.get('status') != 'completed'):
            raise ValueError('Final audit answer identities do not match frozen evidence')
        for name in ('known_usd', 'exposure_upper_usd', 'active_attempt_seconds', 'active_time_limit_seconds'):
            if name in row and row[name] is not None and not _number(row[name]):
                raise ValueError('Final audit has an invalid cost or duration')
        records[identity] = row
    if set(records) != set(expected):
        raise ValueError('Final audit must identify all 150 saved answers')
    return records, path, doc


def _summarize(rows, audit_records):
    # One shared accounting implementation handles partial estimates and ancestry
    # deduplication. The lifetime audit is displayed separately, never substituted
    # into saved cost_details or added to them.
    costs = summarize_costs(rows)
    details = [cost_for_row(row) for row in rows]
    known_available = any(_number(c.get('cumulative_known_estimate_usd')) for c in details)
    current_available = any(_number(c.get('current_attempt_known_estimate_usd')) for c in details)
    durations = [(r.get('timing') or {}).get('duration_seconds') for r in rows]
    durations = [v for v in durations if _number(v)]
    audited = [audit_records.get((r.get('question_id'), r.get('agent')), {}) for r in rows]
    lifetime = [r.get('active_attempt_seconds') for r in audited if r.get('timing_complete') is True]
    lifetime = [v for v in lifetime if _number(v)]
    known = [r.get('known_usd') for r in audited if _number(r.get('known_usd'))]
    return {'answers': len(rows), 'cost_assessment': costs,
            'known_cost_usd': costs['cumulative_known_estimate_usd'] if known_available else None,
            'current_attempt_known_cost_usd': costs['current_attempt_known_estimate_usd'] if current_available else None,
            'unknown_cost_answers': costs['unknown_count'],
            'unknown_current_cost_answers': costs['current_attempt_unknown_count'],
            'historical_unknown_reserved_usd': costs['historical_unresolved_reserved_exposure_usd'],
            'current_unknown_reserved_usd': costs['current_unresolved_reserved_exposure_usd'],
            'audited_known_cost_usd': math.fsum(known) if len(known) == len(rows) else None,
            'duration_count': len(durations), 'duration_sum_seconds': math.fsum(durations) if durations else None,
            'median_duration_seconds': statistics.median(durations) if durations else None,
            'min_duration_seconds': min(durations) if durations else None,
            'max_duration_seconds': max(durations) if durations else None,
            'unknown_duration_answers': len(rows) - len(durations),
            'lifetime_duration_count': len(lifetime),
            'median_lifetime_duration_seconds': statistics.median(lifetime) if lifetime else None,
            'estimated_above_target': sum(_number((r.get('result') or {}).get('cost_usd'))
                                          and r['result']['cost_usd'] > 5 for r in rows)}


def _answer_artifact(generation, row):
    relative = row.get('answer_file', f'answers/{row["question_id"]}/{row["agent"]}.md')
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or '..' in Path(relative).parts or Path(relative).suffix != '.md'):
        raise ValueError('Invalid answer artifact path')
    path = (generation / relative).resolve()
    if not path.is_relative_to(generation):
        raise ValueError('Answer artifact path must remain inside its generation stage')
    return path if path.is_file() else None


def load_run(run_dir, *, audit=None):
    """Load frozen snapshots and refuse any incomplete or inconsistent final run."""
    run = Path(run_dir).expanduser().resolve()
    manifest = _json(run / 'run.json')
    if manifest.get('schema') != 'crest-run-v1':
        raise ValueError('Unsupported frozen run manifest schema')
    analysis_dir = _latest_analysis(run, manifest)
    stage = _json(analysis_dir / 'manifest.json')
    judging_dir = _stage(run, stage.get('judgment_directory'))
    judging_stage = _json(judging_dir / 'manifest.json')
    generation_dir = _stage(run, judging_stage.get('generation_directory'))
    data = {'run_dir': run, 'manifest': manifest, 'analysis_dir': analysis_dir, 'judging_dir': judging_dir,
            'generation_dir': generation_dir, 'ranking': _json(analysis_dir / 'ranking.json'),
            'questions': _json(judging_dir / 'questions.json'), 'answers': _json(judging_dir / 'answers.json'),
            'judgments': _jsonl(judging_dir / 'judgments.jsonl'), 'judges': _json(judging_dir / 'judges.json')}
    _validate(data)
    registry_path = judging_dir / 'configurations.json'
    if not registry_path.is_file():
        registry_path = generation_dir / 'configurations.json'
    configurations = _json(registry_path) if registry_path.is_file() else {}
    if not isinstance(configurations, dict):
        raise ValueError('Configuration registry must map configuration IDs to frozen settings')
    for row in data['answers']:
        identity = row.get('configuration_id')
        if identity is not None:
            record = configurations.get(identity)
            if (not isinstance(record, dict) or record.get('configuration_id') != identity
                    or record.get('configuration_sha256') != row.get('configuration_sha256')
                    or record.get('agent') != row['agent']):
                raise ValueError('Answer configuration does not match its frozen registry')
            recomputed = configuration_record(record, prompt_template=record.get('prompt_template'))
            if (recomputed['configuration_id'] != identity
                    or recomputed['configuration_sha256'] != row['configuration_sha256']):
                raise ValueError('Frozen configuration settings do not match their full hash')
    data['configurations'] = configurations
    data['answer_artifacts'] = {a['key']: _answer_artifact(generation_dir, a) for a in data['answers']}
    prior_path = judging_dir / 'prior_judgment_costs.jsonl'
    if not prior_path.is_file():
        prior_path = run / 'prior_judgment_costs.jsonl'
    prior = _jsonl(prior_path) if prior_path.is_file() else []
    scored_keys, prior_keys = {j['key'] for j in data['judgments']}, {}
    for row in prior:
        key = row.get('key')
        if (not isinstance(key, str) or not key or key in scored_keys
                or row.get('valid_for_ranking') is not False or row.get('stage') != 'judge'):
            raise ValueError('Invalid prior or superseded paid judgment ledger')
        if key in prior_keys and row != prior_keys[key]:
            raise ValueError('Conflicting prior paid judgment records')
        prior_keys[key] = row
    data['prior_judgments'] = prior
    audit_records, audit_path, audit_doc = _audit_records(run, audit, data['answers'])
    data.update(audit_records=audit_records, audit_path=audit_path, audit_doc=audit_doc)
    if audit_doc is not None:
        hashes = audit_doc.get('input_sha256', {})
        sources = [run / 'run.json', analysis_dir / 'ranking.json', judging_dir / 'questions.json',
                   judging_dir / 'answers.json', judging_dir / 'judgments.jsonl', judging_dir / 'judges.json']
        sources += [p for p in (registry_path, prior_path) if p.is_file()]
        for source in sources:
            suffix = (run.name, *source.relative_to(run).parts)
            expected = {value for key, value in hashes.items()
                        if tuple(Path(key).parts[-len(suffix):]) == suffix}
            if expected != {hashlib.sha256(source.read_bytes()).hexdigest()}:
                raise ValueError('Final audit input hashes do not match the selected snapshot')
    data['resources'] = {
        'generation': {agent: _summarize([a for a in data['answers'] if a['agent'] == agent], audit_records) for agent in AGENTS},
        'judging': {judge: _summarize([j for j in data['judgments'] if j['judge'] == judge], {}) for judge in JUDGES},
        'prior_judging': summarize_costs(prior)}
    return data


def _pct(value):
    return f'{value * 100:.1f}%' if _number(value) else 'Unavailable'


def _money(value):
    return f'${value:,.4f}' if _number(value) else 'Unknown'


def _duration(value):
    if not _number(value):
        return 'Unknown'
    return f'{value / 60:,.1f} min' if value >= 60 else f'{value:,.1f} s'


def _interval(value):
    return '–'.join(_pct(v) for v in value) if isinstance(value, list) and len(value) == 2 else 'Unavailable'


def _table(headers, rows, label, extra=''):
    return (f'<div class="table-scroll" role="region" aria-label="{_text(label)}" tabindex="0">'
            f'<table {extra}><thead><tr>' + ''.join(f'<th scope="col">{_text(h)}</th>' for h in headers)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def _ranking(data):
    report = data['ranking']
    parts = ['<section id="overall"><h2>Observed creativity ranking</h2>',
             '<p>Overall wins divided by 400 comparisons per system. Exact ties share a rank. '
             'Bars show observed preferences; whiskers show the saved 95% question-bootstrap intervals.</p>']
    for row in report['ranking']:
        agent, value = row['agent'], row['preference_rate']
        low, high = row['ci95']
        description = f'{LABELS[agent]}: {_pct(value)}, 95% question-bootstrap interval {_interval(row["ci95"])}'
        parts.append(f'<div class="ranking-row" data-agent="{agent}" data-rank="{row["rank"]}">'
                     f'<div class="rank-label"><span class="rank">{row["rank"]}</span><strong>{_text(LABELS[agent])}</strong></div>'
                     f'<svg viewBox="0 0 400 40" role="img" aria-label="{_text(description)}"><title>{_text(description)}</title>'
                     '<rect x="4" y="17" width="392" height="13" fill="#edf2f3"/>'
                     '<path d="M200 5V37" stroke="#91a4ad" stroke-dasharray="3 3"/>'
                     f'<rect x="4" y="17" width="{value * 392:.3f}" height="13" fill="{COLORS[agent]}"/>'
                     f'<path d="M{4 + low * 392:.3f} 11H{4 + high * 392:.3f}M{4 + low * 392:.3f} 6V16M{4 + high * 392:.3f} 6V16" stroke="#172c3e" stroke-width="2"/>'
                     f'<circle cx="{4 + value * 392:.3f}" cy="23.5" r="4" fill="#172c3e" stroke="white"/></svg>'
                     f'<div class="score"><strong>{_pct(value)}</strong><small>{row["wins"]} / 400 wins<br>{_interval(row["ci95"])}</small></div></div>')
    parts.append('<p class="small">Scale: 0% to 100%; dashed midpoint = 50%. Confidence intervals are descriptive '
                 'sensitivity to the curated question mix, conditional on saved answers and these judges.</p>')
    rows = []
    for c in report['paired_contrasts']:
        a, b = c['pair']
        interval = '–'.join(f'{v * 100:+.1f}' for v in c['ci95'])
        stability = c['ordering_stability']
        rows.append([_text(f'{SHORT[a]} − {SHORT[b]}'), f'{100 * c["difference"]:+.1f} pp',
                     _text(interval + ' pp'), _pct(stability['first_higher']), _pct(stability['equal'])])
    parts.append(_table(['Overall-index contrast', 'Difference', 'Paired 95% interval', 'First higher in bootstrap', 'Equal in bootstrap'], rows, 'Paired question-bootstrap contrasts'))
    parts.append('<p class="small">Contrasts compare overall indices, not only the direct matchup. Bootstrap ordering '
                 'fractions are not Bayesian probabilities of true superiority.</p></section>')
    return ''.join(parts)


def _head_to_head(data):
    report = data['ranking']
    rows = []
    for a in AGENTS:
        cells = [f'<strong>{_text(SHORT[a])}</strong>']
        for b in AGENTS:
            value = report['pairwise']['overall'][a][b]
            cells.append('—' if a == b else f'<span class="heat-cell" style="--shade:{.06 + value * .28:.3f}">{_pct(value)}</span>')
        rows.append(cells)
    parts = ['<section id="matchups"><h2>Head to head</h2><p>Row system’s share of the 200 overall votes against each column system.</p>',
             _table(['Row / opponent', *[SHORT[a] for a in AGENTS]], rows, 'Overall head-to-head preferences', 'class="matrix"')]
    cycles = report['diagnostics']['cycles']
    parts.append('<p class="small">' + ('Observed preference cycles: ' + '; '.join(' → '.join(SHORT[a] for a in cycle) for cycle in cycles)
                                      if cycles else 'No strict three-system preference cycle appears in the observed matrix.') + '</p></section>')
    return ''.join(parts)


def _judges(data):
    report = data['ranking']
    parts = ['<section id="judges"><h2>Judges and presentation diagnostics</h2><p>Both judges see every pair in both orders, without tools. '
             'Different provider families do not establish independent errors or eliminate style preferences.</p>']
    rows = []
    for judge in JUDGES:
        settings = data['judges'][judge]
        by_agent = {r['agent']: r for r in report['per_judge'][judge]}
        diag = report['diagnostics']['by_judge'][judge]
        effort = settings.get('reasoning_effort') or settings.get('thinking_level')
        label = settings.get('model', judge) + (f' · {effort}' if effort else '')
        rows.append([_text(label), *[_pct(by_agent[a]['preference_rate']) for a in AGENTS],
                     _pct(diag['position_a_preference']['rate']), _pct(diag['swapped_inconsistency']['rate'])])
    parts.append(_table(['Judge', *[SHORT[a] + ' win rate' for a in AGENTS], 'A-position preference', 'Swapped inconsistency'], rows, 'Per-judge overall preferences and order diagnostics'))
    diag = report['diagnostics']
    parts.append(f'<p>Judges disagree on {_pct(diag["judge_disagreement"]["rate"])} of matched presentations '
                 f'({diag["judge_disagreement"]["disagreements"]} / {diag["judge_disagreement"]["comparisons"]}). '
                 'Swapped inconsistency means a judge changes its preferred system when presentation is reversed; '
                 'it mixes position effects with call variability. Agreement is not verified accuracy.</p>')
    parts.append('</section>')
    return ''.join(parts)


def _resources(data):
    generation, judging = data['resources']['generation'], data['resources']['judging']
    parts = ['<section id="resources"><h2>Cost and elapsed time</h2><p>Dollar figures are published-rate estimates, '
             'not invoices. Saved cumulative answer estimates include embedded recovery history, even when additional charges are unknown. '
             'The current-attempt column is separate and is not added again. Unknown reservations are exposure, not measured spend.</p>']
    rows = []
    for agent in AGENTS:
        r = generation[agent]
        rows.append([_text(SHORT[agent]), _money(r['known_cost_usd']), _money(r['current_attempt_known_cost_usd']),
                     str(r['unknown_cost_answers']) + ' / 50', _money(r['historical_unknown_reserved_usd']),
                     _money(r['current_unknown_reserved_usd'])])
    parts.append(_table(['System', 'Saved cumulative estimate', 'Current-attempt estimate', 'Incomplete estimates',
                         'Historical unknown reservations', 'Current unknown reservations'], rows, 'Generation cost ledgers'))
    parts.append('<p class="small">Known ledger subtotals omit unknown additional charges. Failed jobs not linked to the saved '
                 'answer’s recovery history can add charges. Analysis uses the same shared cost assessments, including partial known '
                 'components and explicitly conditional Google pricing scenarios. '
                 'Judging is additional: ' + '; '.join(_text(j) + ' ' + _money(judging[j]['known_cost_usd']) for j in JUDGES) + '.</p>')
    prior = data['resources']['prior_judging']
    if prior['records']:
        parts.append(f'<p><strong>600 scored judgments + {prior["records"]} prior or superseded paid calls.</strong> '
                     f'The latter add {_money(prior["cumulative_known_estimate_usd"])} in recorded estimates '
                     f'({prior["unknown_count"]} incomplete estimates) and no ranking votes. '
                     'This separate subtotal is not included in the 600 scored-call estimates above. '
                     'It is already included when an audit-wide judging total covers these same prior keys.</p>')
        parts.append('<details><summary>Prior or superseded paid judgment ledger</summary><pre>'
                     + _text(json.dumps(data['prior_judgments'], ensure_ascii=False, indent=2)) + '</pre></details>')
    parts.append('<p class="small">Estimate classifications: ' + '; '.join(
        _text(SHORT[a]) + ' — usage-priced ' + _money(generation[a]['cost_assessment']['usage_priced_estimate_usd'])
        + ', conditional scenarios ' + _money(generation[a]['cost_assessment']['conditional_scenario_estimate_usd'])
        + ', other recorded estimates ' + _money(generation[a]['cost_assessment']['recorded_provider_estimate_usd'])
        for a in AGENTS) + '. The complete assumptions, pricing sources, usage and conditional scenarios are retained with each answer below.</p>')
    google = generation['gemini']
    parts.append(f'<p>Google research has {google["estimated_above_target"]} saved estimates above $5. '
                 'These are conditional list-price estimates under a conservative pricing envelope; actual billed USD and per-loop backend models are unknown. The flags do not establish invoice overruns. '
                 '$5 per answer is a target rather than a hard native-provider dollar cap.</p>')
    parts.append('<p class="small">Pricing references: '
                 '<a href="https://developers.openai.com/api/docs/models/gpt-6.1-sol">OpenAI Sol</a>, '
                 '<a href="https://developers.openai.com/api/docs/models/gpt-6-luna">OpenAI Luna</a>, and '
                 '<a href="https://ai.google.dev/gemini-api/docs/pricing">Gemini API pricing</a>. '
                 'Each answer’s record retains the assessment date and pricing assumptions.</p>')
    rows = []
    for agent in AGENTS:
        r = generation[agent]
        rows.append([_text(SHORT[agent]), _duration(r['median_duration_seconds']),
                     _duration(r['min_duration_seconds']) + '–' + _duration(r['max_duration_seconds']),
                     str(r['duration_count']) + ' / 50', _duration(r['median_lifetime_duration_seconds']),
                     str(r['lifetime_duration_count']) + ' / 50'])
    parts.append(_table(['System', 'Median successful-attempt elapsed', 'Min–max successful-attempt elapsed', 'Timed answers',
                         'Audited median cumulative active execution', 'Active-time audit coverage'], rows, 'Saved answer elapsed times'))
    parts.append('<p class="small">Canonical client elapsed includes provider queueing, polling, retries and interruptions, '
                 'excluding local scheduling before execution. Cache hits retain the original duration. These final-job durations '
                 'are not cumulative across earlier restarted jobs. Unknown timing remains unavailable.</p>')
    if data['audit_path']:
        doc = data['audit_doc']
        ledger, judging_audit = doc.get('ledger', {}), doc.get('judging', {})
        parts.append(f'<p class="small">Final audit: {_text(data["audit_path"].name)}; '
                     f'{len(data["audit_records"])} / 150 answer identities and frozen-input hashes matched. '
                     'Cumulative active execution sums deduplicated attempt intervals and excludes gaps between recovery attempts.</p>')
        parts.append(_table(['System', 'Audited cumulative attempt estimate'], [
            [_text(SHORT[a]), _money(generation[a]['audited_known_cost_usd'])] for a in AGENTS],
            'Audited lifetime generation estimates'))
        parts.append('<p>Audit-wide deduplicated generation attempt estimate: '
                     + _money(ledger.get('known_generation_attempt_usd'))
                     + '; failed-attempt known estimates already included: ' + _money(ledger.get('failed_known_usd'))
                     + '. Model-based reserved exposure for unresolved charges: ' + _money(ledger.get('unknown_reserved_usd'))
                     + '. This exposure is not a guaranteed invoice bound and is not added to known spend.</p>')
        parts.append('<p class="small">Audit judging estimates: successful verdicts '
                     + _money(judging_audit.get('known_estimated_usd')) + '; failed jobs '
                     + _money(judging_audit.get('failed_known_usd')) + '. Unknown failed-job bills: '
                     + _text(judging_audit.get('failed_unknown_cost_count', 'not recorded'))
                     + '; partial observations on unpriced failures: '
                     + _money(judging_audit.get('failed_partial_observed_usd')) + ' (not a final bill).</p>')
        warnings = doc.get('warnings') or []
        if warnings:
            parts.append('<details><summary>Final audit notes</summary><ul>'
                         + ''.join('<li>' + _text(warning) + '</li>' for warning in warnings) + '</ul></details>')
    else:
        parts.append('<p class="small">No final lifetime audit was supplied. Lifetime budget compliance is not established; '
                     'successful-attempt times alone cannot validate a cumulative two-hour limit.</p>')
    parts.append('</section>')
    return ''.join(parts)


def _models(data):
    research = data['manifest'].get('config', {}).get('research', {})
    rows = []
    for agent in AGENTS:
        settings = research.get(agent, {})
        models = sorted({str(a['result'].get('model', 'Unavailable')) for a in data['answers'] if a['agent'] == agent})
        if agent == 'gemini':
            detail = f'Managed agent: {settings.get("agent", "not recorded")}. Configured billing model: {settings.get("billing_model", "not recorded")}; not an override of the provider-controlled backbone.'
        elif agent == 'openai':
            detail = 'Sol + hosted web search through Responses API; not the complete hosted ChatGPT deep-research harness.'
        else:
            detail = f'Exploration: {settings.get("exploration_model", "not recorded")}; knowledge base: {settings.get("kb_model", "not recorded")}. Per-question frozen task settings and receipts retain helper differences.'
        rows.append([_text(LABELS[agent]), _text(', '.join(models)), _text(detail)])
    return '<section id="systems"><h2>Systems in this experiment</h2>' + _table(['System', 'Recorded result model / billing reference', 'Workflow'], rows, 'Frozen research systems') + '</section>'


def _questions(data):
    answers = {(a['question_id'], a['agent']): a for a in data['answers']}
    judgments = defaultdict(list)
    for j in data['judgments']:
        judgments[j['question_id']].append(j)
    parts = ['<section id="questions"><h2>All questions, answers and judgments</h2>',
             '<p>Every question includes all three complete answers and its 12 saved overall judgments. '
             'Expand an answer or reason to inspect the source content; no API or network request is needed.</p>']
    for index, question in enumerate(data['questions'], 1):
        qid = question['id']
        title = question['text'][:150] + ('…' if len(question['text']) > 150 else '')
        parts.append(f'<details class="question" id="question-{index}"><summary>{index:02d}. {_text(title)}</summary>'
                     f'<p class="full-question">{_text(question["text"])}</p><nav class="answer-links" aria-label="Answers for question {index}">')
        for agent in AGENTS:
            parts.append(f'<a href="#answer-{index}-{agent}">{_text(SHORT[agent])} answer</a>')
        parts.append('</nav>')
        for agent in AGENTS:
            row = answers[qid, agent]
            cost = cost_for_row(row)
            audited = data['audit_records'].get((qid, agent))
            record = {'cost_details': cost, 'usage': row['result'].get('usage'), 'timing': row.get('timing')}
            audit_note = ''
            if audited:
                record['final_audit'] = audited
                active = audited.get('active_attempt_seconds') if audited.get('timing_complete') is True else None
                audit_note = (' · audited cumulative attempt estimate ' + _money(audited.get('known_usd'))
                              + ' · audited cumulative active execution ' + _duration(active))
            artifact = data['answer_artifacts'][row['key']]
            artifact_note = ''
            if artifact:
                relative = artifact.relative_to(data['generation_dir'])
                artifact_note = f'Local Markdown: <code>{_text(relative)}</code><br>'
            identity = row.get('configuration_id')
            configuration = data['configurations'].get(identity) if identity else None
            if configuration is None:
                configuration = {'source': 'legacy run manifest; per-answer configuration was not recorded',
                                 'settings': data['manifest'].get('config', {}).get('research', {}).get(agent)}
            parts.append(f'<details class="answer" id="answer-{index}-{agent}"><summary>{_text(LABELS[agent])} · complete answer</summary>'
                         f'<p class="small">Saved cumulative estimate {_money(cost["cumulative_known_estimate_usd"])} · saved job elapsed '
                         f'{_duration((row.get("timing") or {}).get("duration_seconds"))}{audit_note}</p>'
                         f'<div class="answer-text" role="region" tabindex="0" aria-label="{_text(SHORT[agent])} answer, question {index}">{_text(row["result"]["text"])}</div>'
                         f'<details class="configuration"><summary>Configuration: {_text(identity or "legacy run settings")}</summary>'
                         f'<pre tabindex="0" aria-label="Frozen configuration">{_text(json.dumps(configuration, ensure_ascii=False, indent=2))}</pre></details>'
                         f'<details class="cost-record"><summary>Cost, usage and timing record</summary>'
                         f'<pre tabindex="0" aria-label="Cost, usage and timing record">{_text(json.dumps(record, ensure_ascii=False, indent=2))}</pre></details>'
                         f'<p class="small">{artifact_note}Answer key: <code>{_text(row["key"])}</code></p></details>')
        parts.append('<details class="judgments"><summary>Read all 12 overall judgments</summary>')
        for j in sorted(judgments[qid], key=lambda r: (r['pair'], r['judge'], r['order'])):
            order = j['order']
            winner = order[0 if j['verdict']['winner'] == 'A' else 1]
            parts.append(f'<details class="judgment"><summary>{_text(j["judge"])} · A: {_text(SHORT[order[0]])}, '
                         f'B: {_text(SHORT[order[1]])} · preferred {_text(SHORT[winner])}</summary>'
                         f'<p class="reason">{_text(j["verdict"]["reason"])}</p>'
                         f'<p class="small">Judgment key: <code>{_text(j["key"])}</code></p></details>')
        parts.append('</details></details>')
    parts.append('</section>')
    return ''.join(parts)


def _method(data):
    bootstrap = data['ranking']['bootstrap']
    return ('<section id="method"><h2>How to read this comparison</h2>'
            '<p>All three systems answer the same 50 questions. Each of three pairs receives two judges in both answer orders: '
            '12 overall A/B choices per question, 600 judgments total. New, Useful and Surprising guide one qualitative comparison; '
            'there are no separate criterion winners or numeric criterion weights. Opponents, judges, orders and questions receive '
            'equal weight. The win fraction is a normalized Borda-style count; '
            '<a href="https://jmlr.org/papers/v18/16-206.html">Shah and Wainwright</a> provide background on pairwise ranking.</p>'
            f'<p>Uncertainty is the saved 1,000-resample whole-question bootstrap (seed {_text(bootstrap["seed"])}). '
            'Each draw retains all dependent comparisons for the sampled questions; paired contrasts share those draws. '
            'These are descriptive percentile intervals, not the finite-pool concentration bounds used for AI scientist papers. '
            '<a href="https://aclanthology.org/P18-1128/">Dror et al., 2018</a> discuss paired resampling in evaluation.</p>'
            '<p>Intervals condition on the saved answers, judges, rubric and observed calls. They describe sensitivity to this '
            'curated question mix, not variability from generating new answers or choosing new judges. '
            '<a href="https://arxiv.org/abs/2306.05685">Zheng et al., 2023</a> document position and style biases in LLM judging. '
            'Balanced presentation and diagnostics do not prove that those biases disappear.</p>'
            '<p><a href="https://doi.org/10.1080/10400419.2012.650092">Runco and Jaeger, 2012</a> identify originality and effectiveness '
            'as central to creativity. This does not validate this rubric as a general creativity instrument. Recall-based source '
            'placeability is not verified historical novelty, and judge agreement is not independent factual validation.</p></section>')


CSS = """
.skip-link{position:fixed;left:1rem;top:-100px;z-index:20;background:#172c3e;color:white;padding:.7rem 1rem}.skip-link:focus{top:1rem}
main>section{margin:3rem 0}main>nav{display:flex;flex-wrap:wrap;gap:.5rem 1.2rem;margin:1.5rem 0;padding:1rem 0}
.metadata,.small,small{color:#526574}.small{font-size:.9rem}.metadata{font-size:.8rem}.subtitle{max-width:76ch}
.run-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin:1.8rem 0}.run-stats strong{display:block;color:#0b5967;font-size:1.9rem}.run-stats span{font-size:.85rem;color:#526574}
.ranking-row{display:grid;grid-template-columns:minmax(160px,1.1fr) minmax(150px,2fr) 130px;gap:1rem;align-items:center;margin:1.1rem 0}.rank-label{display:flex;align-items:center;gap:.7rem}.rank{color:#526574;font-size:1.3rem}.ranking-row svg{width:100%;height:48px}.score{text-align:right;font-variant-numeric:tabular-nums}.score strong{display:block;font-size:1.4rem}.score small{display:block;font-size:.8rem;line-height:1.5}
.table-scroll{max-width:100%;overflow:auto}.table-scroll table{min-width:630px}.table-scroll .matrix{min-width:480px}.matrix td:not(:first-child){text-align:center}.heat-cell{display:block;padding:.5rem;background:rgba(11,89,103,var(--shade));font-variant-numeric:tabular-nums}
.question{padding:1rem 0;border-top:1px solid #d7e1e6}.question>summary{font-size:1rem}.question .full-question,.reason,.answer-text{white-space:pre-wrap;overflow-wrap:anywhere}.answer-links{display:flex;flex-wrap:wrap;gap:.6rem 1.2rem;margin:1rem 0}.answer-text{max-height:40rem;overflow:auto;background:#f5f8f9;padding:1rem;font-size:.95rem;line-height:1.75}.cost-record pre{max-height:32rem;white-space:pre-wrap;overflow-wrap:anywhere}.question .judgment{padding:.7rem 0}.judgment .reason{margin:.7rem 0 1.5rem}summary{overflow-wrap:anywhere}code{overflow-wrap:anywhere}footer{padding:1rem 0;margin-top:3rem}
@media(max-width:650px){.ranking-row{grid-template-columns:minmax(0,1fr) 125px;gap:.4rem 1rem}.ranking-row svg{grid-column:1/-1;grid-row:2}.score{grid-column:2;grid-row:1}.rank-label{font-size:.9rem}.run-stats{gap:.7rem}.run-stats strong{font-size:1.4rem}.answer-text{max-height:32rem}.table-scroll .matrix{min-width:440px}}
@media print{.skip-link,main>nav{display:none}.ranking-row{break-inside:avoid}.answer-text{max-height:none;overflow:visible}details>summary{break-after:avoid}}
"""

SCRIPT = """
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#answer-"]');
  if (!link) return;
  const target = document.getElementById(link.getAttribute('href').slice(1));
  if (!target) return;
  for (let node = target; node; node = node.parentElement) {
    if (node.tagName === 'DETAILS') node.open = true;
  }
});
"""


def _render(data, destination):
    run = data['run_dir']
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">',
             '<title>Deep research creativity · CREST</title>', f'<style>{SITE_CSS}\n{CSS}</style></head><body>',
             '<a class="skip-link" href="#main-content">Skip to report</a>', site_header(ROOT, destination),
             '<main id="main-content" tabindex="-1"><header><p class="metadata">Completed 50-question research comparison</p>',
             '<h1>Deep research creativity</h1><p class="subtitle">Three research systems answer the same questions. '
             'Two AI judges compare overall creative quality, guided jointly by New, Useful and Surprising.</p></header>',
             '<nav aria-label="Report contents"><a href="#overall">Overall ranking</a><a href="#matchups">Head to head</a>'
             '<a href="#judges">Judges</a><a href="#resources">Cost and time</a><a href="#systems">Systems</a>'
             '<a href="#questions">All questions and evidence</a><a href="#method">Method</a></nav>',
             '<div class="run-stats"><div><strong>50</strong><span>common complete questions</span></div>'
             '<div><strong>150</strong><span>saved answers</span></div><div><strong>600</strong><span>overall binary judgments</span></div></div>',
             _ranking(data), _head_to_head(data), _judges(data), _resources(data), _models(data), _questions(data), _method(data),
             f'<footer>CREST · Run {_text(run.name)}<br>Frozen analysis: {_text(data["analysis_dir"].name)} · '
             f'Judgment snapshot: {_text(data["judging_dir"].name)} · Generation: {_text(data["generation_dir"].name)}<br>'
             'Offline report; observed preferences are not an absolute creativity measurement.</footer>',
             f'</main><script>{SCRIPT}</script></body></html>\n']
    return ''.join(parts)


def write_report(run_dir, destination, *, audit=None):
    """Write a validated final report atomically; errors leave old outputs intact."""
    data = load_run(run_dir, audit=audit)
    destination = Path(destination).expanduser().resolve()
    html = _render(data, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.name, dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(html)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='Render only a complete, frozen 150-answer / 600-judgment CREST report; no API calls.')
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, help='Optional final lifetime audit; otherwise use latest 04-audit*/audit.json')
    args = parser.parse_args(argv)
    try:
        result = write_report(args.run, args.output, audit=args.audit)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'crest.report: {exc}\n')
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
