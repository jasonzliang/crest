"""Offline HTML publication of a complete, frozen CREST research comparison.

Usage: python -m crest.report RUN --output docs/deep-research-creativity.html
Only complete 50-question, three-system comparisons can be written. Rendering
never submits jobs, changes analysis, or reads mutable generation caches.
Category headings use saved metadata or the bundled query dataset.

Optional enrichment uses the existing crest-final-audit-v1 artifact produced by
crest-final-audit.py. It must be complete, ready, and match the frozen answer
identities. No alternative audit or accounting protocol is introduced here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from html import escape
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import statistics
import tempfile

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML

from .analysis import analyze
from .artifacts import configuration_record
from .costs import cost_for_row, summarize_costs
from .judging import parse_verdict, validate_verdict
from crest_ais.navigation import CSS as SITE_CSS, site_header

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ('caesar', 'gemini', 'openai')
JUDGES = ('gemini', 'openai')
LABELS = {'caesar': 'Caesar', 'openai': 'OpenAI (Sol + web search)', 'gemini': 'Google Deep Research'}
JUDGE_LABELS = {'gpt-6-astra': 'GPT-6 Astra', 'gemini-4-argon': 'Gemini 4 Argon'}
SOURCE_URLS = {'caesar': 'https://github.com/jasonzliang/caesar-agent',
               'openai': 'https://developers.openai.com/api/docs/guides/tools-web-search',
               'gemini': 'https://ai.google.dev/gemini-api/docs/deep-research'}
COLORS = {'caesar': '#0b5967', 'gemini': '#b4652b', 'openai': '#5e628c'}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _text(value):
    return escape(str(value), quote=True)


def _evidence_text(value):
    # Preserve source whitespace without leaving trailing blanks in generated HTML.
    return _text(value).replace(' \n', '&#32;\n').replace('\t\n', '&#9;\n')


class _AnswerMarkdownRenderer(RendererHTML):
    def image(self, tokens, idx, _options, _env):
        # Keep reading the offline report free of automatic image requests.
        token = tokens[idx]
        label, source = _text(token.content or 'Image'), token.attrGet('src') or ''
        link_depth = sum(t.nesting for t in tokens[:idx] if t.type in {'link_open', 'link_close'})
        if not link_depth and source.lower().startswith(('http://', 'https://')):
            return f'<a href="{_text(source)}">{label}</a>'
        return label

    def table_open(self, _tokens, _idx, _options, _env):
        return '<div class="table-scroll" role="region" aria-label="Answer table" tabindex="0"><table>'

    def table_close(self, _tokens, _idx, _options, _env):
        return '</table></div>\n'


def _markdown_answer(text):
    parser = MarkdownIt('js-default', renderer_cls=_AnswerMarkdownRenderer)
    env = {}
    tokens = parser.parse(text, env)
    for token in tokens:
        if token.type in {'heading_open', 'heading_close'}:
            token.tag = f'h{min(6, int(token.tag[1:]) + 3)}'
        elif token.type == 'th_open':
            token.attrSet('scope', 'col')
    return parser.renderer.render(tokens, parser.options, env)


def _judge_label(data, judge):
    model = data['judges'][judge].get('model', judge)
    return JUDGE_LABELS.get(model, model)


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
        protocol = row.get('protocol_version')
        if protocol not in (None, 'nus-overall-pairwise-v2', 'nus-overall-pairwise-v3'):
            raise ValueError('Unsupported judging protocol')
        strict_reason = protocol == 'nus-overall-pairwise-v3'
        verdict = validate_verdict(row.get('verdict'), require_reason_quality=strict_reason)
        text = (row.get('result') or {}).get('text')
        if text is not None and parse_verdict(text, require_reason_quality=strict_reason) != verdict:
            raise ValueError('Stored verdict differs from the provider result')
        ordered = [answer_map[row['question_id'], a] for a in order]
        if 'answer_keys' in row and row['answer_keys'] != [a['key'] for a in ordered]:
            raise ValueError('Judgment references different saved answers')
        if 'answer_hashes' in row and row['answer_hashes'] != [
                hashlib.sha256(a['result']['text'].encode()).hexdigest() for a in ordered]:
            raise ValueError('Judgment answer content hashes do not match')
        if strict_reason:
            from .presentation import PRESENTATION_VERSION, present_answer
            if row.get('presentation_version') != PRESENTATION_VERSION or row.get('presented_answer_hashes') != [
                    hashlib.sha256(present_answer(a['result']['text']).encode()).hexdigest() for a in ordered]:
                raise ValueError('Judgment presentation hashes do not match the saved answers')
    if any(j.get('protocol_version') == 'nus-overall-pairwise-v3' for j in judgments) and not all(
            j.get('protocol_version') == 'nus-overall-pairwise-v3' for j in judgments):
        raise ValueError('Do not mix judgments from different rubric protocols')
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
    known_total = costs['cumulative_known_estimate_usd'] if known_available else None
    return {'answers': len(rows), 'cost_assessment': costs,
            'known_cost_usd': known_total,
            'mean_known_cost_usd': known_total / len(rows) if known_total is not None and rows else None,
            'current_attempt_known_cost_usd': costs['current_attempt_known_estimate_usd'] if current_available else None,
            'unknown_cost_answers': costs['unknown_count'],
            'unknown_current_cost_answers': costs['current_attempt_unknown_count'],
            'historical_unknown_reserved_usd': costs['historical_unresolved_reserved_exposure_usd'],
            'current_unknown_reserved_usd': costs['current_unresolved_reserved_exposure_usd'],
            'audited_known_cost_usd': math.fsum(known) if len(known) == len(rows) else None,
            'duration_count': len(durations), 'duration_sum_seconds': math.fsum(durations) if durations else None,
            'mean_duration_seconds': statistics.mean(durations) if durations else None,
            'median_duration_seconds': statistics.median(durations) if durations else None,
            'min_duration_seconds': min(durations) if durations else None,
            'max_duration_seconds': max(durations) if durations else None,
            'unknown_duration_answers': len(rows) - len(durations),
            'lifetime_duration_count': len(lifetime),
            'mean_lifetime_duration_seconds': statistics.mean(lifetime) if lifetime else None,
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
    data['prior_judgments_path'] = prior_path.relative_to(run).as_posix()
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
        'paid_judging': summarize_costs([*data['judgments'], *prior]),
        'prior_judging': summarize_costs(prior)}
    return data


def _pct(value):
    return f'{value * 100:.1f}%' if _number(value) else 'Unavailable'


def _money(value, places=4):
    return f'${value:,.{places}f}' if _number(value) else 'Unknown'


def _duration(value):
    if not _number(value):
        return 'Unknown'
    return f'{value / 60:,.1f} min' if value >= 60 else f'{value:,.1f} s'


def _interval(value):
    return '–'.join(_pct(v) for v in value) if isinstance(value, list) and len(value) == 2 else 'Unavailable'


def _table(headers, rows, label, extra='', *, row_headers=False):
    return (f'<div class="table-scroll" role="region" aria-label="{_text(label)}" tabindex="0">'
            f'<table {extra}><thead><tr>' + ''.join(f'<th scope="col">{_text(h)}</th>' for h in headers)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(
                f'<th scope="row">{c}</th>' if row_headers and index == 0 else f'<td>{c}</td>'
                for index, c in enumerate(row)) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def _system_order(data):
    return [row['agent'] for row in data['ranking']['ranking']]


def _ranking(data):
    report = data['ranking']
    parts = ['<section id="overall"><h2>Observed creativity ranking</h2>',
             '<p>Ranked by how often each system’s answer was preferred. Each system appears in 400 of the 600 judgments '
             '(50 questions × 2 opponents × 2 judges × 2 answer orders). '
             'Win rate is wins ÷ 400. Lines show 95% intervals from resampling the questions.</p>']
    for row in report['ranking']:
        agent, value = row['agent'], row['preference_rate']
        low, high = row['ci95']
        description = f'{LABELS[agent]}: {_pct(value)}, 95% question-bootstrap interval {_interval(row["ci95"])}'
        parts.append(f'<div class="ranking-row" data-agent="{agent}" data-rank="{row["rank"]}">'
                     f'<div class="rank-label"><span class="rank">{row["rank"]}</span>'
                     f'<strong><a href="{SOURCE_URLS[agent]}">{_text(LABELS[agent])}</a></strong></div>'
                     f'<svg viewBox="0 0 400 40" role="img" aria-label="{_text(description)}"><title>{_text(description)}</title>'
                     '<rect x="4" y="17" width="392" height="13" fill="#edf2f3"/>'
                     '<path d="M200 5V37" stroke="#91a4ad" stroke-dasharray="3 3"/>'
                     f'<rect x="4" y="17" width="{value * 392:.3f}" height="13" fill="{COLORS[agent]}"/>'
                     f'<path d="M{4 + low * 392:.3f} 11H{4 + high * 392:.3f}M{4 + low * 392:.3f} 6V16M{4 + high * 392:.3f} 6V16" stroke="#172c3e" stroke-width="2"/>'
                     f'<circle cx="{4 + value * 392:.3f}" cy="23.5" r="4" fill="#172c3e" stroke="white"/></svg>'
                     f'<div class="score"><strong>{_pct(value)}</strong><small>{row["wins"]} / 400 wins<br>{_interval(row["ci95"])}</small></div></div>')
    parts.append('<p class="small">Scale: 0% to 100%; dashed midpoint = 50%.</p>')
    parts.append('<details><summary>Paired differences and bootstrap statistics</summary>')
    rows = []
    for c in report['paired_contrasts']:
        a, b = c['pair']
        interval = '–'.join(f'{v * 100:+.1f}' for v in c['ci95'])
        stability = c['ordering_stability']
        rows.append([_text(f'{LABELS[a]} − {LABELS[b]}'), f'{100 * c["difference"]:+.1f} pp',
                     _text(interval + ' pp'), _pct(stability['first_higher']), _pct(stability['equal'])])
    parts.append(_table(['Overall-index contrast', 'Difference', 'Paired 95% interval', 'First higher in bootstrap', 'Equal in bootstrap'], rows, 'Paired question-bootstrap contrasts'))
    parts.append('<p class="small">Contrasts compare overall indices, not only the direct matchup. Bootstrap ordering '
                 'fractions are not Bayesian probabilities of true superiority.</p></details></section>')
    return ''.join(parts)


def _head_to_head(data):
    report = data['ranking']
    agents = _system_order(data)
    rows = []
    for a in agents:
        cells = [f'<strong>{_text(LABELS[a])}</strong>']
        for b in agents:
            value = report['pairwise']['overall'][a][b]
            cells.append('<span class="diagonal" role="img" aria-label="Same system; no comparison">—</span>' if a == b
                         else f'<span class="heat-cell" style="--shade:{.06 + value * .28:.3f}">{_pct(value)}</span>')
        rows.append(cells)
    parts = ['<section id="matchups"><h2>Head-to-head results</h2>'
             '<p>How often the row system was preferred to the column system (200 comparisons per matchup).</p>',
             _table(['Row / column', *[LABELS[a] for a in agents]], rows,
                    'Overall head-to-head preferences', 'class="matrix"', row_headers=True)]
    cycles = report['diagnostics']['cycles']
    if cycles:
        parts.append('<p class="small">Preference cycle: '
                     + '; '.join(' → '.join(LABELS[a] for a in cycle) for cycle in cycles) + '.</p>')
    parts.append('</section>')
    return ''.join(parts)


def _judges(data):
    report = data['ranking']
    agents = _system_order(data)
    parts = ['<section id="judges"><h2>How the judges compare</h2>'
             '<p>Both judges evaluated every pair in both orders, without tools.</p>']
    rows = []
    for judge in JUDGES:
        settings = data['judges'][judge]
        by_agent = {r['agent']: r for r in report['per_judge'][judge]}
        diag = report['diagnostics']['by_judge'][judge]
        effort = settings.get('reasoning_effort') or settings.get('thinking_level')
        label = _judge_label(data, judge) + (f' · {effort}' if effort else '')
        rows.append([_text(label), *[_pct(by_agent[a]['preference_rate']) for a in agents],
                     _pct(diag['position_a_preference']['rate']), _pct(diag['swapped_inconsistency']['rate'])])
    parts.append(_table(['Judge', *[LABELS[a] + ' win rate' for a in agents], 'Chose A', 'Changed winner after swap'], rows, 'Per-judge overall preferences and order diagnostics'))
    diag = report['diagnostics']
    parts.append(f'<p>Judges disagree on {_pct(diag["judge_disagreement"]["rate"])} of matched presentations '
                 f'({diag["judge_disagreement"]["disagreements"]} / {diag["judge_disagreement"]["comparisons"]}). '
                 '“Chose A” shows how often the first answer won. “Changed winner after swap” shows how often '
                 'a judge preferred a different system when the answer order was reversed. '
                 'This can reflect order effects or variation between calls.</p>')
    parts.append('<details><summary>Frozen judge configurations</summary><pre>'
                 + _text(json.dumps(data['judges'], ensure_ascii=False, indent=2)) + '</pre></details>')
    parts.extend([_models(data), '</section>'])
    return ''.join(parts)


def _resources(data):
    generation, judging = data['resources']['generation'], data['resources']['judging']
    agents = _system_order(data)
    parts = ['<section id="resources"><h2>Cost and elapsed time</h2>'
             '<p>Per-question means across 50 questions. Dollar figures are published-rate estimates, not invoices.</p>']
    averages = []
    for agent in agents:
        r = generation[agent]
        averages.append([_text(LABELS[agent]), _money(r['mean_known_cost_usd']),
                         _duration(r['mean_duration_seconds']), _duration(r['mean_lifetime_duration_seconds'])])
    parts.append(_table(['System', 'Average estimated cost', 'Average generation time',
                         'Average active time, all attempts'], averages, 'Per-question cost and elapsed-time means'))
    parts.append('<p class="small">Google’s estimate uses assumed model rates because its internal billing breakdown is unavailable. '
                 'Unreported charges are excluded. '
                 'Generation time covers the final successful job; active time includes earlier attempts.</p>')
    google = generation['gemini']
    if google['estimated_above_target']:
        parts.append(f'<p class="small">{google["estimated_above_target"]} Google answer estimates exceed the $5 target. '
                     'The target is not a provider spending cap; actual bills have not been verified.</p>')
    parts.append('<details class="resource-details"><summary>Cost totals and timing</summary>')
    parts.append('<p>Generation totals include recorded recovery attempts.</p>'
                 '<p>Google’s pricing scenario uses high-context Gemini 3.1 Pro rates, counts tool tokens as additional input, '
                 'and charges searches at full price. The service does not report the model and pricing tier for each internal step.</p>'
                 '<p class="small">Cost means divide the recorded totals by all 50 questions. Time means use only answers '
                 'with recorded durations; missing times are excluded.</p>')
    rows = []
    for agent in agents:
        r = generation[agent]
        rows.append([_text(LABELS[agent]), _money(r['known_cost_usd'])])
    parts.append(_table(['System', 'Total generation estimate'], rows, 'Generation cost totals'))
    parts.append('<p class="small">Judging is additional: '
                 + '; '.join(_text(_judge_label(data, j)) + ' ' + _money(judging[j]['known_cost_usd']) for j in JUDGES) + '.</p>')
    scored = math.fsum(judging[j]['known_cost_usd'] or 0 for j in JUDGES)
    parts.append(f'<p><strong>Total for 600 judgments: {_money(scored)}.</strong> Includes retries.</p>')
    parts.append('<p class="small">Pricing references: '
                 '<a href="https://developers.openai.com/api/docs/models/gpt-6.1-sol">OpenAI Sol</a>, '
                 '<a href="https://developers.openai.com/api/docs/models/gpt-6-luna">OpenAI Luna</a>, and '
                 '<a href="https://ai.google.dev/gemini-api/docs/pricing">Gemini API pricing</a>. '
                 'Each answer’s record retains the assessment date and pricing assumptions.</p>')
    rows = []
    for agent in agents:
        r = generation[agent]
        rows.append([_text(LABELS[agent]), _duration(r['median_duration_seconds']),
                     _duration(r['min_duration_seconds']) + '–' + _duration(r['max_duration_seconds']),
                     str(r['duration_count']) + ' / 50', _duration(r['median_lifetime_duration_seconds']),
                     str(r['lifetime_duration_count']) + ' / 50'])
    parts.append(_table(['System', 'Median successful-attempt elapsed', 'Min–max successful-attempt elapsed', 'Timed answers',
                         'Audited median cumulative active execution', 'Active-time audit coverage'], rows, 'Saved answer elapsed times'))
    parts.append('<p class="small">Elapsed time includes provider queueing, polling and retries. '
                 'Active time adds earlier attempts and excludes gaps between them. Cache hits retain original durations.</p>')
    if data['audit_path']:
        differs = any(_number(generation[a]['audited_known_cost_usd'])
                      and (not _number(generation[a]['known_cost_usd']) or not math.isclose(
                          generation[a]['audited_known_cost_usd'], generation[a]['known_cost_usd'])) for a in agents)
        if differs:
            parts.append(_table(['System', 'Audited cumulative attempt estimate'], [
                [_text(LABELS[a]), _money(generation[a]['audited_known_cost_usd'])] for a in agents],
                'Audited lifetime generation estimates'))
    parts.append('</details></section>')
    return ''.join(parts)


def _models(data):
    research = data['manifest'].get('config', {}).get('research', {})
    rows = []
    for agent in _system_order(data):
        settings = research.get(agent, {})
        models = sorted({str(a['result'].get('model', 'Unavailable')) for a in data['answers'] if a['agent'] == agent})
        if agent == 'gemini':
            detail = f'Managed agent: {settings.get("agent", "not recorded")}. Configured billing model: {settings.get("billing_model", "not recorded")}; not an override of the provider-controlled backbone. Per-loop backend models are not reported for this run.'
        elif agent == 'openai':
            detail = f'Sol + hosted web search through Responses API; reasoning effort: {settings.get("reasoning_effort", "not recorded")}. This run evaluates that configured workflow.'
        else:
            detail = f'Exploration: {settings.get("exploration_model", "not recorded")}; knowledge base: {settings.get("kb_model", "not recorded")}. Per-answer configuration records retain helper settings and recovery provenance.'
        rows.append([_text(LABELS[agent]), _text(', '.join(models)), _text(detail)])
    return ('<details id="systems"><summary>Models and research workflows</summary>'
            + _table(['System', 'Recorded result model / billing reference', 'Workflow'], rows, 'Frozen research systems')
            + '<p class="small">Google introduced its April 2026 Deep Research agents as built with Gemini 3.1 Pro '
            '(<a href="https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/">Google announcement</a>). '
            'That product description does not identify this run’s per-loop backend models.</p>'
            '<p class="small">OpenAI’s o3-deep-research and o4-mini-deep-research API models shut down July 23, 2026 '
            '(<a href="https://developers.openai.com/api/docs/deprecations">deprecation notice</a>; '
            '<a href="https://developers.openai.com/api/docs/guides/deep-research">deep research guide</a>). '
            'The OpenAI results here come from the Sol workflow recorded above.</p>'
            + '</details>')


def _questions(data):
    agents = _system_order(data)
    answers = {(a['question_id'], a['agent']): a for a in data['answers']}
    judgments = defaultdict(list)
    for j in data['judgments']:
        judgments[j['question_id']].append(j)
    parts = ['<section id="questions"><h2>All questions, answers and judgments</h2>',
             '<p>Every question includes all three complete answers and its 12 saved overall judgments. '
             'The question winner has the most pairwise wins; ties are shown. '
             'Expand an answer or reason to read it.</p>']
    catalog = _jsonl(ROOT / 'crest/data/queries_n50.jsonl')
    categories = {row['query']: row['category'] for row in catalog}
    groups = {row['category']: [] for row in catalog}
    for index, question in enumerate(data['questions'], 1):
        category = question.get('category')
        if not isinstance(category, str) or not category.strip():
            category = categories.get(question['text'], 'Other questions')
        groups.setdefault(category, []).append((index, question))
    for group_number, (category, questions) in enumerate(groups.items(), 1):
        if not questions:
            continue
        parts.append(f'<section class="question-category" data-category="{_text(category)}" '
                     f'aria-labelledby="category-{group_number}">'
                     f'<h3 id="category-{group_number}">{_text(category)} '
                     f'<small>{len(questions)} questions</small></h3>')
        for index, question in questions:
            qid = question['id']
            votes = Counter(row['order'][0 if row['verdict']['winner'] == 'A' else 1]
                            for row in judgments[qid])
            most_wins = max(votes.values())
            winners = [agent for agent in agents if votes[agent] == most_wins]
            outcome = ('Winner: ' if len(winners) == 1 else 'Tie: ') + ' / '.join(LABELS[a] for a in winners)
            parts.append(f'<details class="question" id="question-{index}"><summary>'
                         f'<span class="question-number">{index:02d}</span><span class="question-title">{_text(question["text"])}</span>'
                         f'<span class="question-outcome" data-winners="{" ".join(winners)}" data-wins="{most_wins}" '
                         f'title="{most_wins} wins in 8 comparisons per system">{_text(outcome)}</span>'
                         '</summary><div class="question-content">')
            parts.append('<h4 class="evidence-heading">Answers</h4>')
            for agent in agents:
                row = answers[qid, agent]
                cost = cost_for_row(row)
                audited = data['audit_records'].get((qid, agent))
                record = {'cost_details': cost, 'usage': row['result'].get('usage'), 'timing': row.get('timing')}
                usage = record['usage']
                event_note = ''
                if isinstance(usage, dict) and isinstance(usage.get('events'), list):
                    count = len(usage['events'])
                    record['usage'] = {key: value for key, value in usage.items() if key != 'events'}
                    source = data['generation_dir'].name + '/answers.jsonl'
                    record['omitted_usage_events'] = {'count': count, 'source': source,
                                                    'field': 'result.usage.events', 'answer_key': row['key']}
                    event_note = (f'<p class="small">Usage events omitted from this HTML: {count}. '
                                  f'Canonical source: <code>{_text(source)}</code>, field <code>result.usage.events</code>; '
                                  f'answer key <code>{_text(row["key"])}</code>.</p>')
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
                parts.append(f'<details class="answer" id="answer-{index}-{agent}"><summary>{_text(LABELS[agent])}</summary>'
                             f'<div class="answer-text" data-answer-sha256="{hashlib.sha256(row["result"]["text"].encode()).hexdigest()}" '
                             f'role="region" tabindex="0" aria-label="{_text(LABELS[agent])} answer, question {index}">'
                             f'{_markdown_answer(row["result"]["text"])}</div>'
                             '<details class="answer-metadata"><summary>Answer metadata and source records</summary>'
                             f'<p class="small">Saved cumulative estimate {_money(cost["cumulative_known_estimate_usd"])} · saved job elapsed '
                             f'{_duration((row.get("timing") or {}).get("duration_seconds"))}{audit_note}</p>'
                             '<details class="configuration"><summary>Research configuration</summary>'
                             f'<pre tabindex="0" aria-label="Frozen configuration">{_text(json.dumps(configuration, ensure_ascii=False, indent=2))}</pre></details>'
                             f'<details class="cost-record"><summary>Cost, usage and timing record</summary>'
                             f'{event_note}'
                             f'<pre tabindex="0" aria-label="Cost, usage and timing record">{_text(json.dumps(record, ensure_ascii=False, indent=2))}</pre></details>'
                             f'<p class="small">{artifact_note}Answer key: <code>{_text(row["key"])}</code></p></details></details>')
            parts.append('<details class="judgments"><summary>Read all 12 overall judgments</summary>')
            for pair in combinations(agents, 2):
                parts.append('<section class="judgment-group">'
                             f'<h4>{_text(LABELS[pair[0]])} vs {_text(LABELS[pair[1]])}</h4>')
                matched = [j for j in judgments[qid] if frozenset(j['pair']) == frozenset(pair)]
                for j in sorted(matched, key=lambda r: (r['judge'], r['order'])):
                    order = j['order']
                    winner = order[0 if j['verdict']['winner'] == 'A' else 1]
                    parts.append(f'<details class="judgment"><summary>{_text(_judge_label(data, j["judge"]))} '
                                 f'· preferred {_text(LABELS[winner])}</summary>'
                                 f'<p class="presentation">A: {_text(LABELS[order[0]])} · B: {_text(LABELS[order[1]])}</p>'
                                 f'<p class="reason">{_evidence_text(j["verdict"]["reason"])}</p>'
                                 '<details class="judgment-metadata"><summary>Judgment source record</summary>'
                                 f'<p class="small">Judgment key: <code>{_text(j["key"])}</code></p></details></details>')
                parts.append('</section>')
            parts.append('</details></div></details>')
        parts.append('</section>')
    parts.append('</section>')
    return ''.join(parts)


def _method(data):
    bootstrap = data['ranking']['bootstrap']
    openai_tracking = sum(a['agent'] == 'openai' and 'utm_source=openai' in a['result']['text']
                          for a in data['answers'])
    google_grounding = sum(a['agent'] == 'gemini' and 'vertexaisearch.cloud.google.com' in a['result']['text']
                           for a in data['answers'])
    provenance = ''
    revised = bool(data.get('judgments')) and all(
        j.get('protocol_version') == 'nus-overall-pairwise-v3'
        and j.get('presentation_version') == 'citation-neutral-v1' for j in data['judgments'])
    if revised:
        provenance = ('<p>URL destinations were hidden uniformly in judge presentations; meaningful citation labels and '
                      'answer content were retained. Original answers are preserved below. Wording can still reveal '
                      'which system wrote an answer.</p>'
                      '<p>Originality can come from combining familiar ideas. Usefulness is judged within the question’s '
                      'premises; unfamiliarity alone is not evidence of novelty. If a judge cannot support a substantive '
                      'preference, it must say so and choose A. Doing this in both orders gives each system one win.</p>'
                      '<p>Incomplete or noncomparative explanations trigger retries. These checks do not verify the judges’ claims.</p>')
    elif openai_tracking or google_grounding:
        provenance = ('<p>Provider labels were withheld, but this run was not fully blinded. '
                      f'Links reveal provenance in {openai_tracking} / 50 {LABELS["openai"]} answers '
                      f'and {google_grounding} / 50 {LABELS["gemini"]} answers. '
                      'These cues do not establish that provider bias caused the ranking.</p>')
    return ('<section id="method"><h2>How the comparison works</h2>'
            '<p>Each question produces 12 decisions: three answer pairs, evaluated by two judges in both orders.</p>'
            '<dl class="method-summary">'
            '<dt>Choose a winner</dt><dd>Each judge chooses A or B using <strong>New</strong> (original contribution), '
            '<strong>Useful</strong> (fit and support), and <strong>Surprising</strong> (departure from the expected approach). '
            'These guide one overall decision, with no separate scores.</dd>'
            '<dt>Count the votes</dt><dd>Every decision counts equally. Each system appears in 400 decisions; '
            'wins ÷ 400 gives its win rate.</dd>'
            '<dt>Read the error bars</dt><dd>We resample the 50 questions 1,000 times, keeping each question’s 12 decisions '
            'together. The middle 95% of the resulting win rates forms the interval.</dd></dl>'
            '<p class="small">The ranking describes these saved answers and judge preferences. The intervals show sensitivity '
            'to the question mix; they do not cover new answers or different judges. Factual accuracy has not been verified, '
            'and answer length or style may influence preferences.</p>'
            '<details><summary>Rubric, presentation and references</summary>' + provenance +
            f'<p>The bootstrap uses seed {_text(bootstrap["seed"])}. All systems use the same sampled questions when '
            'calculating ranking differences.</p>'
            '<ul><li><a href="https://doi.org/10.1080/10400419.2012.650092">Runco and Jaeger, 2012</a>: '
            'originality and effectiveness as core creativity criteria.</li>'
            '<li><a href="https://jmlr.org/papers/v18/16-206.html">Shah and Wainwright, 2018</a>: '
            'ranking by pairwise win counts (Borda counting).</li>'
            '<li><a href="https://aclanthology.org/P18-1128/">Dror et al., 2018</a>: '
            'resampling methods and their assumptions in evaluation.</li>'
            '<li><a href="https://arxiv.org/abs/2306.05685">Zheng et al., 2023</a>: '
            'position and verbosity biases in LLM judging.</li></ul>'
            '<p class="small">These sources inform the design; they do not validate this rubric or its judgments against human experts.</p>'
            '</details></section>')


CSS = """
#judges>details{margin:.3rem 0}
.question-category{margin-top:2rem}.question-category>h3{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem .8rem}
.method-summary{display:grid;grid-template-columns:10rem minmax(0,1fr);gap:1rem 1.5rem}.method-summary dt{font-weight:650;color:#0b5967}.method-summary dd{margin:0}
.small,small{color:#526574}.small{font-size:.9rem}
.run-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin:1.8rem 0}.run-stats strong{display:block;color:#0b5967;font-size:1.9rem}.run-stats span{font-size:.85rem;color:#526574}
.ranking-row{display:grid;grid-template-columns:minmax(160px,1.1fr) minmax(150px,2fr) 130px;gap:1rem;align-items:center;margin:1.1rem 0}.rank-label{display:flex;align-items:center;gap:.7rem}.rank{color:#526574;font-size:1.3rem}.ranking-row svg{width:100%;height:48px}.score{text-align:right;font-variant-numeric:tabular-nums}.score strong{display:block;font-size:1.4rem}.score small{display:block;font-size:.8rem;line-height:1.5}
.table-scroll{max-width:100%;overflow:auto}.table-scroll table{min-width:630px}.table-scroll .matrix{table-layout:fixed;min-width:700px}.matrix th,.matrix td{vertical-align:middle;padding:.9rem}.matrix th:first-child{width:29%}.matrix thead th,.matrix td{text-align:center}.matrix tbody th{font-weight:650;line-height:1.5}.heat-cell,.diagonal{display:flex;align-items:center;justify-content:center;min-height:3rem;padding:.6rem;font-variant-numeric:tabular-nums}.heat-cell{background:rgba(11,89,103,var(--shade))}.diagonal{background:#f0f3f5;color:#71818c}
.question{padding:0;border:1px solid #d7e1e6;border-radius:6px;margin:1rem 0}.question>summary{display:grid;grid-template-columns:2rem minmax(0,1fr) auto 1rem;gap:.8rem;align-items:start;padding:1.2rem;font-size:1rem;list-style:none}.question>summary::-webkit-details-marker{display:none}.question>summary::after{grid-column:-2;grid-row:1;content:"+";font-size:1.2rem;line-height:1.2;text-align:center}.question[open]>summary::after{content:"−"}.question-number{color:#526574;font-weight:400;font-variant-numeric:tabular-nums}.question-title{min-width:0}.question-outcome{max-width:16rem;font-size:.78rem;line-height:1.6;font-weight:500;text-align:right}.question-content{padding:0 1.2rem 1rem}.question .evidence-heading{margin:1rem 0 .5rem}.question .answer{border-top:1px solid #d7e1e6;margin:0;padding:.15rem 0}.question .answer>summary{font-size:1rem;padding:1rem 0}.reason{white-space:pre-wrap;overflow-wrap:anywhere}.answer-text{white-space:normal;overflow-wrap:anywhere;max-height:40rem;overflow:auto;background:#f5f8f9;padding:1.2rem;font-size:.95rem;line-height:1.8}.answer-text>:first-child{margin-top:0}.answer-text>:last-child{margin-bottom:0}.answer-text h4{font-size:1.2rem}.answer-text h5{font-size:1.05rem}.answer-text h6{font-size:1rem}.answer-text pre{white-space:pre;overflow:auto}.answer-text .table-scroll table{min-width:480px}.answer-text .table-scroll th,.answer-text .table-scroll td{padding:.6rem .75rem;border-bottom:1px solid var(--line)}.answer-metadata{margin:1rem 0}.cost-record pre{max-height:32rem;white-space:pre-wrap;overflow-wrap:anywhere}.question .judgments{border-top:1px solid #d7e1e6;margin:1rem 0 0;padding-top:.5rem}.judgment-group{margin:1.5rem 0;padding-top:1rem;border-top:1px solid #d7e1e6}.judgment-group:first-of-type{margin-top:.5rem;padding-top:0;border-top:0}.judgment-group>h4{font-size:1rem;margin:.5rem 0}.question .judgment{margin:.3rem 0;padding:.2rem 0}.judgment .presentation{font-size:.85rem;color:#526574;margin:.2rem 0 1rem}.judgment .reason{margin:.7rem 0 1.5rem}summary{overflow-wrap:anywhere}code{overflow-wrap:anywhere}
@media(max-width:650px){.question-outcome{grid-column:2;grid-row:2;max-width:none;text-align:left}.method-summary{grid-template-columns:1fr;gap:.25rem}.method-summary dd{margin-bottom:1rem}.ranking-row{grid-template-columns:minmax(0,1fr) 125px;gap:.4rem 1rem}.ranking-row svg{grid-column:1/-1;grid-row:2}.score{grid-column:2;grid-row:1}.rank-label{font-size:.9rem}.run-stats{gap:.7rem}.run-stats strong{font-size:1.4rem}.answer-text{max-height:32rem;padding:1rem}.question>summary{grid-template-columns:1.6rem minmax(0,1fr) 1rem;gap:.5rem;padding:1rem .9rem}.question-content{padding:0 .9rem .9rem}}
@media print{.skip-link,main>nav{display:none}.ranking-row{break-inside:avoid}.answer-text{max-height:none;overflow:visible}details>summary{break-after:avoid}}
"""


def _render(data, destination):
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">',
             '<title>Deep research comparison · CREST</title>', f'<style>{SITE_CSS}\n{CSS}</style></head><body>',
             '<a class="skip-link" href="#main-content">Skip to report</a>', site_header(ROOT, destination),
             '<main id="main-content" tabindex="-1"><h1>Deep research comparison</h1>',
             '<nav aria-label="Report contents"><a href="#overall">Ranking</a><a href="#matchups">Head-to-head</a>'
             '<a href="#resources">Cost and time</a><a href="#method">Method</a>'
             '<a href="#judges">Judges</a><a href="#questions">Answers</a></nav>',
             '<div class="run-stats"><div><strong>50</strong><span>questions</span></div>'
             '<div><strong>150</strong><span>answers</span></div><div><strong>600</strong><span>pairwise judgments</span></div></div>',
             _ranking(data), _head_to_head(data), _resources(data), _method(data), _judges(data),
             _questions(data),
             '</main></body></html>\n']
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
