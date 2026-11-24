"""Offline HTML publication of a complete, frozen CREST research comparison.

Usage: python -m crest.report RUN --output docs/deep-research-comparison-v3.html
Only 50-question comparisons of every agent in the frozen run manifest, judged by
every configured judge, can be written. A question may be left unranked only when
each of its missing judgments matches a recorded failure in the judge stage;
the page then names it. Rendering never submits jobs, changes analysis, or reads
mutable generation caches.

Add --rubric-run RUN (repeatable) to show the same answers judged under other
packaged NUS rubrics in a separate section.
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
import re
import statistics
import tempfile

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML

from .analysis import analyze
from .artifacts import configuration_record
from .costs import cost_for_row, summarize_costs
from .judging import parse_verdict, validate_verdict
from .rubrics import AUT_KIND, AUT_PROTOCOL, NUS_KIND, NUS_PROTOCOL, protocol_rubric_kind
from crest_ais.navigation import CSS as SITE_CSS, site_favicon, site_header
from crest_ais.site import page_path, page_title, page_updated, require_canonical_output, prepare_index_date, write_index_date

ROOT = Path(__file__).resolve().parents[1]
# Agents and judges come from each frozen run; these tables only decorate known identifiers.
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')
LABELS = {'caesar': 'Caesar', 'openai': 'OpenAI (Sol + web search)', 'gemini': 'Google Deep Research',
          'anthropic': 'Anthropic (Claude + web search)', 'gpt_researcher': 'GPT Researcher'}
JUDGE_LABELS = {'gpt-6.1-sol': 'GPT-6.1 Sol', 'claude-opus-5-5': 'Claude Opus 5.5', 'gpt-6-astra': 'GPT-6 Astra', 'gemini-4-argon': 'Gemini 4 Argon', 'claude-fable-5-1': 'Claude Fable 5.1',
                'claude-sonnet-5-5': 'Claude Sonnet 5.5'}
SOURCE_URLS = {'gpt_researcher': 'https://github.com/assafelovic/gpt-researcher', 'caesar': 'https://github.com/jasonzliang/caesar-agent',
               'openai': 'https://developers.openai.com/api/docs/guides/tools-web-search',
               'gemini': 'https://ai.google.dev/gemini-api/docs/deep-research',
               'anthropic': 'https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool'}
COLORS = {'gpt_researcher': '#8a4d69', 'caesar': '#0b5967', 'gemini': '#b4652b', 'openai': '#5e628c', 'anthropic': '#3d7a4a'}
DEFAULT_COLOR = '#526574'
PRICING_LINKS = {'openai': ('<a href="https://developers.openai.com/api/docs/models/gpt-6.1-sol">OpenAI Sol</a>',
                            '<a href="https://developers.openai.com/api/docs/models/gpt-6-luna">OpenAI Luna</a>'),
                 'gemini': ('<a href="https://ai.google.dev/gemini-api/docs/pricing">Gemini API pricing</a>',),
                 'anthropic': ('<a href="https://platform.claude.com/docs/en/about-claude/pricing">Claude pricing</a>',)}
PRICING_PROVIDER = {'caesar': 'openai', 'gpt_researcher': 'openai'}  # Caesar's SDK calls bill at OpenAI rates.


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


def _link_known_source_urls(state, silent):
    """Consume a recorded URL before its spaces or punctuation become Markdown."""
    if silent or state.linkLevel or state.src[state.pos] != ':':
        return False
    # Like the native inline linkifier, recognize the scheme at its colon.
    # Match raw source, not already-parsed tokens; never change link-label lookahead.
    match = re.search(r'(?:^|[^a-z0-9.+-])(https?)$', state.pending, re.IGNORECASE)
    if not match:
        return False
    scheme = match.group(1)
    start = state.pos - len(scheme)
    url = next((u for u in state.env['source_urls']
                if state.src.startswith(u, start, state.posMax)), None)
    if url is None:
        return False
    state.pending = state.pending[:-len(scheme)]
    opening = state.push('link_open', 'a', 1)
    opening.attrSet('href', state.md.normalizeLink(url))
    state.push('text', '', 0).content = url
    state.push('link_close', 'a', -1)
    state.pos = start + len(url)
    return True


def _markdown_answer(text, source_urls=()):
    parser = MarkdownIt('js-default', {'breaks': True, 'linkify': True}, renderer_cls=_AnswerMarkdownRenderer)
    parser.inline.ruler.before('linkify', 'known_source_urls', _link_known_source_urls)
    env = {'source_urls': sorted({u for u in source_urls if isinstance(u, str) and ' ' in u
                                and not any(c in u for c in '\r\n\t')
                                and u.lower().startswith(('https://', 'http://'))
                                and parser.validateLink(u)}, key=len, reverse=True)}
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


def _label(agent):
    return LABELS.get(agent, agent)


def _word(count):
    words = ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')
    return words[count] if 0 <= count < len(words) else f'{count:,}'


def _plural(count, noun, plural=None):
    return f'{_word(count)} {noun if count == 1 else plural or noun + "s"}'


def _join(items):
    items = list(items)
    return ' and '.join(items) if len(items) < 3 else ', '.join(items[:-1]) + ', and ' + items[-1]


def _agents(data):
    agents = data['manifest'].get('agents')
    if (not isinstance(agents, list) or len(agents) < 2 or len(set(agents)) != len(agents)
            or any(not isinstance(a, str) or not IDENTIFIER.fullmatch(a) for a in agents)):
        raise ValueError('The frozen run manifest must list at least two unique research agent identifiers')
    return list(agents)


def _judge_names(data):
    judges = data['judges']
    if (not isinstance(judges, dict) or not judges or any(
            not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or not isinstance(settings, dict)
            for name, settings in judges.items())):
        raise ValueError('judges.json must map at least one judge identifier to its frozen settings')
    return list(judges)


def _expected(agents, judge_names, ranked=50):
    """Evidence counts for 50 questions; ranking counts cover the ranked questions only."""
    systems, judges, pairs = len(agents), len(judge_names), math.comb(len(agents), 2)
    return {'systems': systems, 'judges': judges, 'pairs': pairs, 'answers': 50 * systems,
            'questions': 50, 'ranked': ranked, 'judgments': 50 * pairs * 2 * judges,
            'per_system': ranked * (systems - 1) * 2 * judges,
            'per_matchup': ranked * 2 * judges, 'per_question': pairs * 2 * judges,
            'per_question_system': (systems - 1) * 2 * judges}


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
    failures = data.get('judge_failures', [])
    family = ranking.get('rubric_kind', NUS_KIND)
    if family not in (NUS_KIND, AUT_KIND):
        raise ValueError('Unsupported ranking rubric kind')
    if (len(questions) != 50 or len({q['id'] for q in questions}) != 50
            or len({q.get('text') for q in questions}) != 50
            or any(not isinstance(q.get('text'), str) or not q['text'].strip() for q in questions)):
        raise ValueError('Final publication requires 50 unique questions')
    agents, judges = _agents(data), _judge_names(data)
    counts = _expected(agents, judges)
    if data['manifest'].get('questions') != questions:
        raise ValueError('Questions must match the frozen run manifest')
    ids = {q['id'] for q in questions}
    expected_answers = {(q, a) for q in ids for a in agents}
    answer_ids = [(a.get('question_id'), a.get('agent')) for a in answers]
    if len(answers) != counts['answers'] or set(answer_ids) != expected_answers:
        raise ValueError(f'Final publication requires {counts["answers"]} unique complete answers, '
                         'one per research agent in the frozen run manifest')
    if (any(not isinstance(a.get('key'), str) or not a['key'] for a in answers)
            or len({a['key'] for a in answers}) != counts['answers']):
        raise ValueError('Every answer must have a unique canonical key')
    if any(not isinstance(a.get('result'), dict) or not isinstance(a['result'].get('text'), str)
           or not a['result']['text'].strip() or a.get('status', 'completed') != 'completed' for a in answers):
        raise ValueError('Every answer must be nonempty and complete')
    for qid in ids:
        texts = [a['result']['text'] for a in answers if a['question_id'] == qid]
        if len(set(texts)) != len(agents):
            raise ValueError('Identical answers cannot form a complete scored question')
    # Judging stores each pair sorted; analysis only scores cells in that canonical form.
    cells = {(q, pair, order, judge) for q in ids for pair in combinations(sorted(agents), 2)
             for order in (pair, pair[::-1]) for judge in judges}
    seen, keys = set(), set()
    answer_map = {(a['question_id'], a['agent']): a for a in answers}
    for row in judgments:
        pair, order = tuple(row.get('pair', [])), tuple(row.get('order', []))
        cell = (row.get('question_id'), pair, order, row.get('judge'))
        if cell not in cells or cell in seen or row.get('status', 'completed') != 'completed':
            raise ValueError('Missing, duplicate or invalid judgment cell')
        seen.add(cell)
        _stand_in(data, row)
        if not isinstance(row.get('key'), str) or not row['key'] or row['key'] in keys:
            raise ValueError('Judgments require unique canonical keys')
        keys.add(row['key'])
        protocol = row.get('protocol_version')
        row_family = protocol_rubric_kind(protocol)
        if row_family != family or row.get('rubric_kind', row_family) != family:
            raise ValueError('Ranking and judgment rubric kinds must match the frozen protocol')
        strict_reason = protocol in (NUS_PROTOCOL, AUT_PROTOCOL)
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
            from .presentation import ANSWER_PRESENTATION_VERSION, PRESENTATION_VERSION, present_research_answer
            version = row.get('presentation_version')
            if version not in (PRESENTATION_VERSION, ANSWER_PRESENTATION_VERSION) or row.get('presented_answer_hashes') != [
                    hashlib.sha256(present_research_answer(a['result']['text'], version).encode()).hexdigest()
                    for a in ordered]:
                raise ValueError('Judgment presentation hashes do not match the saved answers')
    protocols = {j.get('protocol_version') for j in judgments}
    if protocols.intersection((NUS_PROTOCOL, AUT_PROTOCOL)) and len(protocols) != 1:
        raise ValueError('Do not mix judgments from different rubric protocols')
    failed = {f['cell'] for f in failures}
    if failed & seen or seen | failed != cells or len(judgments) + len(failed) != counts['judgments']:
        raise ValueError(f'Final publication requires {counts["judgments"]} valid overall judgments, '
                         'or a recorded failure for each missing one')
    bootstrap = ranking.get('bootstrap', {})
    if bootstrap.get('unit') != 'question' or bootstrap.get('samples') != 1000 or type(bootstrap.get('seed')) is not int:
        raise ValueError('Final publication requires the saved 1000-resample question bootstrap')
    computed = analyze(questions, answers, judgments, agents=agents, judges=judges,
                       bootstrap_samples=1000, seed=bootstrap['seed'])
    unranked = {cell[0] for cell in failed}
    if (computed['coverage']['complete_questions'] != 50 - len(unranked)
            or {q['question_id'] for q in computed['coverage']['excluded_questions']} != unranked
            or computed['coverage']['valid_judgments'] != len(judgments)):
        raise ValueError('Analysis must score every question that has all its judgments, from every saved judgment')
    # Display the saved analysis, checking its arithmetic and uncertainty rather
    # than silently replacing stale values or borrowing the AIS sampling method.
    for key in ('agents', 'judges', 'coverage', 'ranking', 'paired_contrasts', 'per_judge',
                'pairwise', 'diagnostics', 'bootstrap'):
        if ranking.get(key) != computed[key]:
            raise ValueError(f'Saved ranking does not match frozen evidence: {key}')
    return agents, judges


def _audit_records(run, path, answers, counts):
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
            or generation.get('completed_answers') != counts['answers']
            or generation.get('snapshot_answer_rows') != counts['answers']
            or judging.get('valid_calls') != counts['saved'] or judging.get('complete_questions') != counts['ranked']
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
        raise ValueError(f'Final audit must identify all {counts["answers"]} saved answers')
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
            # Google's assumed-price scenario is flagged incomplete by design; only missing calls make a lower bound.
            'missing_cost_answers': sum(bool(c.get('estimate_incomplete'))
                                        and c.get('cost_basis') != 'conditional_list_price_scenario' for c in details),
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
            'estimated_above_target': sum(bool((r.get('result') or {}).get('budget_exceeded')) for r in rows)}


def _answer_artifact(generation, row):
    relative = row.get('answer_file', f'answers/{row["question_id"]}/{row["agent"]}.md')
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or '..' in Path(relative).parts or Path(relative).suffix != '.md'):
        raise ValueError('Invalid answer artifact path')
    path = (generation / relative).resolve()
    if not path.is_relative_to(generation):
        raise ValueError('Answer artifact path must remain inside its generation stage')
    return path if path.is_file() else None


REFUSAL = re.compile(r'stop_reason refusal.*?"category": "([^"]+)"')


def _refused(attempt):
    return attempt.get('status') == 'rejected' and 'stop_reason refusal' in str(attempt.get('error') or '')


def _stand_in(data, row):
    """The model that judged in place of the judge's saved model, or None.

    A stand-in is accepted only after the saved model refused every earlier try;
    any other change of model is an error."""
    configured, model = data['judges'][row['judge']].get('model'), (row.get('result') or {}).get('model')
    attempts = [a for a in row.get('attempts') or [] if isinstance(a, dict)]
    if not any(a.get('substitute_model') for a in attempts) and (model is None or configured is None or model == configured):
        return None
    first = next((i for i, a in enumerate(attempts) if a.get('substitute_model')), len(attempts))
    earlier, later = attempts[:first], attempts[first:]
    if (not isinstance(model, str) or model == configured or not earlier or not later
            or not all(_refused(a) for a in earlier) or any(a.get('substitute_model') != model for a in later)
            or later[-1].get('status') != 'completed'):
        raise ValueError('A judgment came from a model other than its judge’s saved model, '
                         'without that model refusing every earlier try')
    return model


def _stand_ins(data):
    """Judgments made by a stand-in model after the judge's saved model refused them."""
    found = []
    for row in data['judgments']:
        model = _stand_in(data, row)
        if model:
            refused = [a for a in row['attempts'] if isinstance(a, dict) and not a.get('substitute_model')]
            labels = [m.group(1) for a in refused for m in [REFUSAL.search(str(a.get('error') or ''))] if m]
            found.append({'key': row['key'], 'question_id': row['question_id'], 'pair': list(row['pair']),
                          'order': list(row['order']), 'judge': row['judge'], 'model': model,
                          'refusals': len(refused), 'labeled': len(labels), 'categories': sorted(set(labels))})
    return found


def _resent_tries(data):
    """Earlier tries of saved judgments whose outcome, and so whose cost, is unknown."""
    tries = []
    for row in data['judgments']:
        attempts = [a for a in row.get('attempts') or [] if isinstance(a, dict)]
        for index, attempt in enumerate(attempts[:-1]):
            if attempt.get('submission_unknown') and not _number(attempt.get('cost_usd')):
                tries.append({'index': index, 'after': len(attempts) - index - 1,
                              'error': str(attempt.get('error') or '')})
    return tries


def _failure_kind(row):
    attempts = [a for a in row.get('attempts') or [] if isinstance(a, dict)]
    errors = [str(a.get('error') or '') for a in attempts]
    if attempts and all(a.get('status') == 'rejected' and 'stop_reason refusal' in e for a, e in zip(attempts, errors)):
        categories = sorted({m.group(1) for e in errors for m in [REFUSAL.search(e)] if m})
        return 'refusal', categories
    text = ' '.join([str(row.get('error') or ''), *errors])
    if 'status unknown' in text or 'outcome unknown' in text or 'StreamInterrupted' in text:
        return 'unknown_outcome', []
    return 'other', []


def _judge_failures(judging_dir):
    """Failed judge calls recorded by the judge stage, each tied to the judgment cell it left empty."""
    path = judging_dir / 'errors.jsonl'
    rows = _jsonl(path) if path.is_file() else []
    if not rows:
        return []
    tasks_path = judging_dir / 'tasks.json'
    if not tasks_path.is_file():
        raise ValueError('Recorded judge failures need the stage tasks.json to identify their judgments')
    tasks = {}
    for task in _json(tasks_path):
        if not isinstance(task, dict) or task.get('key') in tasks:
            raise ValueError('The judge stage tasks.json must list each task key once')
        tasks[task['key']] = task
    failures, keys = [], set()
    for row in rows:
        key, task = row.get('key'), tasks.get(row.get('key'))
        if row.get('stage') != 'judge' or not isinstance(key, str) or task is None:
            raise ValueError('Recorded judge failure is not a task of its judge stage')
        if key in keys:
            raise ValueError('Duplicate recorded judge failure')
        if task.get('question_id') != row.get('question_id') or task.get('judge') != row.get('provider'):
            raise ValueError('Recorded judge failure does not match its task')
        keys.add(key)
        if any(f['key'] != key and f['cell'][0] == task['question_id'] and f['pair'] == list(task['pair'])
               and f['order'] == list(task['order']) and f['judge'] == task['judge'] for f in failures):
            raise ValueError('Two recorded judge failures name the same judgment')
        kind, categories = _failure_kind(row)
        failures.append({'key': key, 'question_id': task['question_id'], 'judge': task['judge'],
                         'pair': list(task['pair']), 'order': list(task['order']),
                         'cell': (task['question_id'], tuple(task['pair']), tuple(task['order']), task['judge']),
                         'kind': kind, 'categories': categories,
                         'attempts': len(row.get('attempts') or []) or 1, 'row': row})
    return failures


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
            'judgments': _jsonl(judging_dir / 'judgments.jsonl'), 'judges': _json(judging_dir / 'judges.json'),
            'judge_failures': _judge_failures(judging_dir)}
    agents, judges = _validate(data)
    data['stand_ins'] = _stand_ins(data)
    counts = _counts(data)
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
    scored_keys, prior_keys = {j['key'] for j in data['judgments']} | {f['key'] for f in data['judge_failures']}, {}
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
    audit_records, audit_path, audit_doc = _audit_records(run, audit, data['answers'], counts)
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
    failed = [f['row'] for f in data['judge_failures']]
    data['resources'] = {
        'generation': {agent: _summarize([a for a in data['answers'] if a['agent'] == agent], audit_records) for agent in agents},
        'judging': {judge: _summarize([j for j in data['judgments'] if j['judge'] == judge]
                                      + [f['row'] for f in data['judge_failures'] if f['judge'] == judge], {})
                    for judge in judges},
        'failed_judging': summarize_costs(failed),
        'paid_judging': summarize_costs([*data['judgments'], *failed, *prior]),
        'prior_judging': summarize_costs(prior)}
    return data


def _rubric_version(text):
    """Name a packaged NUS rubric by its exact text; saved stages keep the text they used."""
    for path in sorted((ROOT / 'crest/prompts').glob('nus_pairwise_v*.txt')):
        if path.read_text(encoding='utf-8') == text:
            return path.stem.rsplit('_', 1)[-1]
    return None


def _answer_identity(data):
    return {(a['question_id'], a['agent']): (a['key'], hashlib.sha256(a['result']['text'].encode()).hexdigest())
            for a in data['answers']}


def _cell_winners(data):
    return {(j['question_id'], tuple(j['order']), j['judge']): j['order'][0 if j['verdict']['winner'] == 'A' else 1]
            for j in data['judgments']}


def _judging_total(data):
    judging = data['resources']['judging']
    return math.fsum(judging[j]['known_cost_usd'] or 0 for j in data['ranking']['judges'])


def _rubric_variants(data, runs):
    """Validate runs that judged these exact answers under other packaged NUS rubrics."""
    main_version = _rubric_version((data['judging_dir'] / 'rubric.txt').read_text(encoding='utf-8'))
    if main_version is None:
        raise ValueError('A rubric comparison needs this report to use a packaged NUS rubric')
    identity, presentation = _answer_identity(data), {j.get('presentation_version') for j in data['judgments']}
    protocol = {j.get('protocol_version') for j in data['judgments']}
    entries = [{'version': main_version}]
    for run in runs:
        variant = load_run(run)
        version = _rubric_version((variant['judging_dir'] / 'rubric.txt').read_text(encoding='utf-8'))
        if version is None:
            raise ValueError(f'{Path(run).name}: rubric comparison runs must use a packaged NUS rubric')
        if variant['ranking'].get('rubric_kind', NUS_KIND) != NUS_KIND:
            raise ValueError(f'{Path(run).name}: rubric comparison runs must use an NUS rubric')
        if version in {e['version'] for e in entries}:
            raise ValueError(f'{Path(run).name}: each rubric comparison run must use a different rubric')
        if variant['questions'] != data['questions']:
            raise ValueError(f'{Path(run).name}: rubric comparison runs must use the same questions')
        if (sorted(variant['manifest']['agents']) != sorted(data['manifest']['agents'])
                or _answer_identity(variant) != identity):
            raise ValueError(f'{Path(run).name}: rubric comparison runs must judge the same saved answers')
        if variant['judges'] != data['judges']:
            raise ValueError(f'{Path(run).name}: rubric comparison runs must use the same judges and judge settings')
        if {j.get('protocol_version') for j in variant['judgments']} != protocol:
            raise ValueError(f'{Path(run).name}: rubric comparison runs must use the same judging protocol')
        if {j.get('presentation_version') for j in variant['judgments']} != presentation:
            raise ValueError(f'{Path(run).name}: rubric comparison runs must present answers to judges the same way')
        entries.append(_variant_summary(version, variant))
        del variant  # Each run's answers are large; keep only what the section shows.
    entries[0] = _variant_summary(main_version, data)
    complete = set.intersection(*(e['complete_ids'] for e in entries))
    questions = [q for q in data['questions'] if q['id'] in complete]
    answers = [a for a in data['answers'] if a['question_id'] in complete]
    seed, reference = data['ranking']['bootstrap']['seed'], entries[0]['winners']
    for entry in entries:
        judgments = [j for j in entry.pop('votes') if j['question_id'] in complete]
        entry['common'] = analyze(questions, answers, judgments, agents=data['ranking']['agents'],
                                  judges=data['ranking']['judges'], bootstrap_samples=1000, seed=seed)
        shared = reference.keys() & entry['winners'].keys()
        entry['agreement'] = (sum(reference[c] == entry['winners'][c] for c in shared), len(shared))
    return {'common_questions': len(complete), 'entries': entries}


def _variant_summary(version, data):
    fields = ('key', 'question_id', 'pair', 'order', 'judge', 'verdict', 'status', 'protocol_version', 'rubric_kind')
    return {'version': version, 'complete': data['ranking']['coverage']['complete_questions'],
            'complete_ids': set(data['ranking']['coverage']['complete_question_ids']),
            'votes': [{k: j[k] for k in fields if k in j} for j in data['judgments']],
            'winners': _cell_winners(data), 'judging_total': _judging_total(data),
            'unknown_costs': sum(data['resources']['judging'][j]['unknown_cost_answers'] for j in data['ranking']['judges']),
            'stand_ins': data['stand_ins'],
            'failures': [{k: v for k, v in f.items() if k != 'row'} for f in data['judge_failures']]}


def _pct(value):
    return f'{value * 100:.1f}%' if _number(value) else 'Unavailable'


def _money(value, places=2):
    return f'${value:,.{places}f}' if _number(value) else 'Unknown'


def _duration(value):
    if not _number(value):
        return 'Unknown'
    return f'{value / 60:,.1f} min' if value >= 60 else f'{value:,.1f} s'


def _interval(value):
    return '–'.join(_pct(v) for v in value) if isinstance(value, list) and len(value) == 2 else 'Unavailable'


def _points(value):
    return f'{value * 100:+.1f}'.replace('-', '−')


def _main_models(data):
    """Each system's main answer-writing models, as saved on its answers."""
    models = defaultdict(set)
    for answer in data['answers']:
        model = answer['result'].get('model')
        if isinstance(model, str) and model:
            models[answer['agent']].add(model)
    return models


def _top_group(data):
    """Systems whose paired interval with the leader includes zero, in rank order."""
    report = data['ranking']
    order = [row['agent'] for row in report['ranking']]
    if not order:
        return []
    leader, group = order[0], [order[0]]
    contrasts = {frozenset(c['pair']): c for c in report.get('paired_contrasts', [])}
    for agent in order[1:]:
        contrast = contrasts.get(frozenset((leader, agent)))
        if contrast and contrast['ci95'][0] <= 0 <= contrast['ci95'][1]:
            group.append(agent)
    return group


def _table(headers, rows, label, extra='', *, row_headers=False):
    return (f'<div class="table-scroll" role="region" aria-label="{_text(label)}" tabindex="0">'
            f'<table {extra}><thead><tr>' + ''.join(f'<th scope="col">{_text(h)}</th>' for h in headers)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(
                f'<th scope="row">{c}</th>' if row_headers and index == 0 else f'<td>{c}</td>'
                for index, c in enumerate(row)) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def _system_order(data):
    return [row['agent'] for row in data['ranking']['ranking']]


def _counts(data):
    # Validated runs rank exactly the manifest agents, so the saved ranking fixes the counts.
    ranked = data['ranking'].get('coverage', {}).get('complete_questions', 50)  # Absent only in method-only views.
    counts = _expected(_system_order(data), data['judges'], ranked)
    counts.update(saved=len(data.get('judgments', [])), failed=len(data.get('judge_failures', [])))
    return counts


def _question_numbers(data):
    return {q['id']: index for index, q in enumerate(data['questions'], 1)}


CATEGORY_GLOSSES = {'bio': 'its biology-safety category'}


def _category_gloss(categories):
    glosses = [CATEGORY_GLOSSES[c] for c in categories if c in CATEGORY_GLOSSES]
    return ', ' + _join(glosses) if len(categories) == 1 and glosses else ''


def _stand_in_note(data, stand_ins, *, counted=False):
    """Say which judgments a stand-in model made, and why, grouped by question and pair."""
    numbers, agents, counts = _question_numbers(data), _system_order(data), _counts(data)
    groups = defaultdict(list)
    for row in stand_ins:
        groups[row['judge'], row['model']].append(row)
    sentences = []
    for judge, model in sorted(groups, key=lambda g: (data['ranking']['judges'].index(g[0]), g[1])):
        rows, name, n = groups[judge, model], _judge_label(data, judge), len(groups[judge, model])
        cells = defaultdict(list)
        for row in rows:
            cells[numbers[row['question_id']], tuple(sorted(row['pair'], key=agents.index))].append(row['order'])
        items = []
        for (number, pair), orders in sorted(cells.items(), key=lambda c: (c[0][0], [agents.index(a) for a in c[0][1]])):
            first, second = pair if len(orders) > 1 else orders[0]
            items.append(f'Question {number}, {_label(first)} vs {_label(second)}, '
                         + ('both orders' if len(orders) > 1 else f'{_label(first)} shown first'))
        tries = sorted({row['refusals'] for row in rows})
        each = '' if n == 1 else 'each one '
        asked = ('the only time it was asked' if tries == [1] else f'all {_word(tries[0])} times it was asked'
                 if len(tries) == 1 else f'every time it was asked, from {_word(tries[0])} to {_word(tries[-1])} times')
        sentences.append(f'{name} refused to make {_word(n)} of its {counts["judgments"] // counts["judges"]:,} '
                         f'judgments: {"; ".join(items)}. It refused {each}{asked}.')
        refusals, labeled = sum(r['refusals'] for r in rows), sum(r['labeled'] for r in rows)
        categories = sorted({c for r in rows for c in r['categories']})
        if categories:
            whom = (('the refusal' if refusals == 1 else 'the refusals') if labeled == refusals
                    else f'{_word(labeled)} of the {_word(refusals)} refusals')
            sentences.append(f'The API labeled {whom} ' + _join(f'“{c}”' for c in categories)
                             + _category_gloss(categories) + '.')
        sentences.append(f'{JUDGE_LABELS.get(model, model)} made '
                         + ('that judgment' if n == 1 else f'those {_word(n)} judgments') + ' instead'
                         + ((', and it counts' if n == 1 else ', and they count') + f' toward {name}’s results below'
                            if counted else '') + '.')
    return ' '.join(sentences)


def _failure_reason(data, failure):
    judge, (first, second) = _judge_label(data, failure['judge']), failure['order']
    matchup = f'{_label(first)} (shown first) against {_label(second)} (shown second)'
    if failure['kind'] == 'refusal':
        attempts = failure['attempts']
        tries = 'its only attempt' if attempts == 1 else f'all {attempts} attempts'
        category = ('; the API labeled the refusal ' + _join(f'“{c}”' for c in failure['categories'])
                    + _category_gloss(failure['categories']) if failure['categories'] else '')
        return f'{judge} refused {tries} to judge {matchup}{category}'
    if failure['kind'] == 'unknown_outcome':
        return (f'the call asking {judge} to judge {matchup} timed out or lost its connection, so we cannot tell '
                'whether it was processed, and we do not resend a call that may already have been billed')
    return f'the call asking {judge} to judge {matchup} failed'


def _unranked_note(data):
    failures, counts = data.get('judge_failures', []), _counts(data)
    if not failures:
        return ''
    numbers, by_question = _question_numbers(data), defaultdict(list)
    for failure in failures:
        by_question[failure['question_id']].append(failure)
    parts = []
    for qid in sorted(by_question, key=numbers.get):
        rows, number = by_question[qid], numbers[qid]
        missing = (f'One of its {counts["per_question"]} judgments is missing: ' if len(rows) == 1 else
                   f'{_word(len(rows)).capitalize()} of its {counts["per_question"]} judgments are missing: ')
        parts.append(f'<a href="#question-{number}">Question {number}</a> is not ranked. ' + _text(
            missing + '; '.join(_failure_reason(data, f) for f in rows) + '. '
            f'Its {counts["per_question"] - len(rows)} saved judgments are shown with the question.'))
    return (f'<p class="small" id="unranked">' + ' '.join(parts)
            + _text(f' A question is ranked only when all {counts["per_question"]} judgments exist, '
                    'so every system is compared on the same questions.') + '</p>')


def _ranking(data):
    report, counts = data['ranking'], _counts(data)
    heading = 'AUT-inspired preference ranking' if report.get('rubric_kind') == AUT_KIND else 'Creativity ranking'
    parts = [f'<section id="overall"><h2>{heading}</h2>',
             f'<p>Each system’s win rate is its wins divided by its {counts["per_system"]:,} judgments ({counts["ranked"]} questions, '
             f'{_plural(counts["systems"] - 1, "opponent")}, {_plural(counts["judges"], "judge")}, both answer orders). '
             'The black line on each bar is the 95% interval: the middle 95% of win rates when the questions are resampled. '
             'It shows how much the result depends on which questions were asked, for these answers and judges.</p>']
    for row in report['ranking']:
        agent, value = row['agent'], row['preference_rate']
        low, high = row['ci95']
        description = f'{_label(agent)}: {_pct(value)}, 95% interval {_interval(row["ci95"])}'
        name = _text(_label(agent))
        link = f'<a href="{_text(SOURCE_URLS[agent])}">{name}</a>' if agent in SOURCE_URLS else name
        parts.append(f'<div class="ranking-row" data-agent="{agent}" data-rank="{row["rank"]}">'
                     f'<div class="rank-label"><span class="rank">{row["rank"]}</span>'
                     f'<strong>{link}</strong></div>'
                     f'<svg viewBox="0 0 400 40" role="img" aria-label="{_text(description)}"><title>{_text(description)}</title>'
                     '<rect x="4" y="17" width="392" height="13" fill="#edf2f3"/>'
                     '<path d="M200 5V37" stroke="#91a4ad" stroke-dasharray="3 3"/>'
                     f'<rect x="4" y="17" width="{value * 392:.3f}" height="13" fill="{COLORS.get(agent, DEFAULT_COLOR)}"/>'
                     f'<path d="M{4 + low * 392:.3f} 11H{4 + high * 392:.3f}M{4 + low * 392:.3f} 6V16M{4 + high * 392:.3f} 6V16" stroke="#172c3e" stroke-width="2"/>'
                     f'<circle cx="{4 + value * 392:.3f}" cy="23.5" r="4" fill="#172c3e" stroke="white"/></svg>'
                     f'<div class="score"><strong>{_pct(value)}</strong><small>{row["wins"]:,} of {counts["per_system"]:,} won<br>95% interval <span class="nowrap">{_interval(row["ci95"])}</span></small></div></div>')
    parts.append('<p class="small">Bars run from 0% to 100%; the dashed line marks 50%. '
                 'Factual accuracy has not been independently verified.</p>' + _unranked_note(data))
    parts.append('<details><summary>Differences between systems</summary>')
    position = {agent: index for index, agent in enumerate(_system_order(data))}
    rows = []
    for c in report['paired_contrasts']:
        a, b = c['pair']
        sign, stability = 1, c['ordering_stability']
        higher, equal = stability['first_higher'], stability['equal']
        if position[a] > position[b]:  # List the higher-ranked system first.
            a, b, sign, higher = b, a, -1, stability.get('second_higher')
        low, high = sorted(sign * v for v in c['ci95'])
        rows.append((position[a], position[b], [
            _text(f'{_label(a)} vs {_label(b)}'), f'{_points(sign * c["difference"])} points',
            f'{_points(low)} to {_points(high)} points', _pct(higher), _pct(equal)]))
    parts.append(_table(['Systems', 'Difference in win rate', '95% interval', 'Resamples where the first is higher',
                         'Resamples where they are equal'], [row for *_, row in sorted(rows)],
                        'Differences in win rate between systems'))
    opponents = ('every opponent, not only the direct matchup' if counts['systems'] > 2 else 'the single matchup')
    parts.append(f'<p class="small">A difference compares overall win rates, which count {opponents}. '
                 'An interval that includes zero means the two systems cannot be separated on these questions. '
                 'The last two columns give the share of the 1,000 question resamples in which the first system '
                 'was higher or the two were equal; they are not the probability that one system is better.</p>'
                 '</details></section>')
    return ''.join(parts)


def _head_to_head(data):
    report, counts = data['ranking'], _counts(data)
    agents = _system_order(data)
    rows = []
    for a in agents:
        cells = [f'<strong>{_text(_label(a))}</strong>']
        for b in agents:
            value = report['pairwise']['overall'][a][b]
            cells.append('<span class="diagonal" role="img" aria-label="Same system; no comparison">Same system</span>' if a == b
                         else f'<span class="heat-cell" style="--shade:{.06 + value * .28:.3f}">{_pct(value)}</span>')
        rows.append(cells)
    parts = ['<section id="matchups"><h2>Head-to-head results</h2>'
             f'<p>How often the row system won against the column system, out of {counts["per_matchup"]:,} judgments '
             'for each pair of systems.</p>',
             _table(['Row / column', *[_label(a) for a in agents]], rows,
                    'Overall head-to-head preferences', 'class="matrix"', row_headers=True)]
    ranks = {row['agent']: row['rank'] for row in report['ranking']}
    upsets = [f'{_label(b)} wins {_pct(report["pairwise"]["overall"][b][a])} of its judgments against {_label(a)} '
              'but ranks lower overall, because the overall win rate also counts judgments against every other system.'
              for a, b in combinations(agents, 2)
              if ranks[b] > ranks[a] and report['pairwise']['overall'][b][a] > .5]
    if upsets:
        parts.append('<p>' + _text(' '.join(upsets)) + '</p>')
    cycles = report['diagnostics']['cycles']
    if cycles:
        parts.append('<p class="small">Preference cycle: '
                     + '; '.join(' → '.join(_text(_label(a)) for a in cycle) for cycle in cycles) + '.</p>')
    parts.append('</section>')
    return ''.join(parts)


def _judge_effort(settings):
    return settings.get('reasoning_effort') or settings.get('thinking_level') or settings.get('effort')


def _judges(data):
    report, counts = data['ranking'], _counts(data)
    agents = _system_order(data)
    who = ('The judge' if counts['judges'] == 1 else 'Both judges' if counts['judges'] == 2
           else f'All {_word(counts["judges"])} judges')
    parts = [f'<section id="judges"><h2>{"How the judges compare" if counts["judges"] > 1 else "How the judge decided"}</h2>'
             f'<p>{who} evaluated every pair in both orders, without tools'
             + (', on every ranked question' if counts['failed'] else '') + '.']
    efforts = {judge: _judge_effort(data['judges'][judge]) for judge in report['judges']}
    same = len(set(efforts.values())) == 1 and next(iter(efforts.values()))
    parts.append((f' {"It" if counts["judges"] == 1 else who} ran at {same} reasoning effort.' if same else '') + '</p>')
    if data.get('stand_ins'):
        parts.append('<p>' + _text(_stand_in_note(data, data['stand_ins'], counted=True)) + '</p>')
    rows = []
    for judge in report['judges']:
        by_agent = {r['agent']: r for r in report['per_judge'][judge]}
        diag = report['diagnostics']['by_judge'][judge]
        effort = efforts[judge]
        label = _judge_label(data, judge) + (f', {effort} effort' if effort and not same else '')
        rows.append([_text(label), *[_pct(by_agent[a]['preference_rate']) for a in agents],
                     _pct(diag['position_a_preference']['rate']), _pct(diag['swapped_inconsistency']['rate'])])
    parts.append(_table(['Judge', *[_label(a) + ' win rate' for a in agents], 'First answer won', 'Winner changed when order swapped'], rows, 'Per-judge overall preferences and order diagnostics'))
    diag = report['diagnostics']['judge_disagreement']
    disagreement = (f'Taking any two judges and the same pair in the same order, they picked different winners '
                    f'{_pct(diag["rate"])} of the time ({diag["disagreements"]:,} of {diag["comparisons"]:,} cases). '
                    if counts['judges'] > 1 else '')
    parts.append(f'<p>{disagreement}'
                 '“First answer won” is how often the answer shown first won; 50% means no lean toward either position. '
                 '“Winner changed when order swapped” is how often a judge picked a different system after the two '
                 'answers swapped places. This can come from order effects or from ordinary variation between calls.</p>')
    overlap = _judge_overlap(data)
    if overlap:
        parts.append('<p>' + _text(overlap) + '</p>')
    parts.append('<details><summary>Saved judge settings</summary><pre>'
                 + _text(json.dumps(data['judges'], ensure_ascii=False, indent=2)) + '</pre></details>')
    parts.append('</section>')
    return ''.join(parts)


def _judge_overlap(data):
    """Name judges whose model also writes answers for a system, from the saved settings only."""
    report, agents, models = data['ranking'], _system_order(data), _main_models(data)
    shared, alone = [], []
    for judge in report['judges']:
        model = data['judges'][judge].get('model')
        systems = [a for a in agents if model in models.get(a, ())]
        rates = {r['agent']: r['preference_rate'] for r in report['per_judge'][judge]}
        best = max(rates.values())
        top = _join(_label(a) for a in agents if rates.get(a) == best)
        (shared if systems else alone).append((_judge_label(data, judge), systems, top, best))
    if not shared:
        return ''
    count = len(shared)
    sentences = [(f'{_word(count).capitalize()} judge shares a model with systems it judges: ' if count == 1 else
                  f'{_word(count).capitalize()} judges share a model with systems they judge: ')
                 + '; '.join(f'{name} is also the main model of {_join(_label(a) for a in systems)}'
                             for name, systems, _, _ in shared) + '.']
    sentences += [f'{name} rates {top} highest ({_pct(best)}).' for name, _, top, best in shared]
    sentences += [f'{name} shares no model with any system; it rates {top} highest ({_pct(best)}).'
                  for name, _, top, best in alone]
    return ' '.join(sentences)


RUBRIC_NOTES = {
    'v1': 'is the first version. For New, the judge breaks an answer into parts and tries to name where each part '
          'already appears in prior work.',
    'v2': 'uses the criteria of the 2026-11-05 study. For New, the judge asks what is original about the '
          'central contribution as a whole.',
    'v3': 'adds a baseline to v2: before reading the answers, the judge states the approach a skilled '
          'practitioner would most likely take.',
    'v4': 'is the current default. It rewrites the v2 criteria: before reading the answers, the judge states the '
          'approach a skilled practitioner would most likely take; it judges creative contribution rather than general '
          'answer quality; and it credits what an answer adds to a cited idea, not the idea itself. It also tells the '
          'judge not to credit or penalize wording about an answer’s own research, such as “the supplied material”, '
          'and to treat a claim as a proposal when the answer itself says its evidence does not prove it.'}
RUBRIC_SHARED_NOTE = ('All rubric files now end with the same shared block of rules and output format; that block was '
                      'edited on 2026-11-23, so the v1 and v2 files are not word-for-word the rubrics of earlier studies.')


def _rubric_link(version):
    return f'<a href="../crest/prompts/nus_pairwise_{version}.txt">NUS {version}</a>'


def _rubrics(data):
    comparison = data.get('rubric_variants')
    if not comparison:
        return ''
    entries, common = comparison['entries'], comparison['common_questions']
    main = entries[0]['version']
    names = [f'NUS {main} (this report)', *[f'NUS {e["version"]}' for e in entries[1:]]]
    others = _join(f'NUS {e["version"]}' for e in entries[1:])
    counts, agents = _counts(data), _system_order(data)
    every = 'both rubrics' if len(entries) == 2 else f'all {_word(len(entries))} rubrics'
    by_version = [{row['agent']: row for row in e['common']['ranking']} for e in entries]
    parts = ['<section id="rubrics"><h2>Same answers, other rubrics</h2>',
             f'<p>The rubric is the instruction the judges follow. NUS stands for its three criteria: New, Useful '
             f'and Surprising. The same {counts["answers"]:,} saved answers were judged again under the older {others} rubrics. '
             'Only the rubric changed; the answers, the judges and their settings, and the way answers were shown '
             f'to the judges stayed the same.</p>',
             '<p>' + ' '.join(f'{_rubric_link(e["version"])} {_text(RUBRIC_NOTES.get(e["version"], "is a packaged NUS rubric."))}'
                              for e in entries)
             + (' NUS v3 was a draft that was never used in a study.'
                if 'v3' not in {e['version'] for e in entries} and main != 'v3' else '') + '</p>',
             (f'<p>Every rubric has all {counts["per_question"]} judgments for each of the {common} questions, '
              f'so the NUS {main} column matches the ranking above.</p>'
              if common == counts['ranked'] == counts['questions'] else
              f'<p>To compare like with like, each column uses the {common} questions '
              f'that have every judgment under {every}'
              + (f', so the NUS {main} column matches the ranking above.' if common == counts['ranked'] else
                 f', so the NUS {main} numbers differ slightly from the ranking above, which uses '
                 f'{"all 50" if counts["ranked"] == 50 else counts["ranked"]}.')
              + '</p>'), _rubric_takeaway(agents, by_version)]
    rows = []
    for agent in agents:
        rows.append([_text(_label(agent)), *[
            f'{_pct(view[agent]["preference_rate"])}<br><small>rank {view[agent]["rank"]}; 95% interval <span class="nowrap">{_interval(view[agent]["ci95"])}</span></small>'
            for view in by_version]])
    parts.append(_table(['System', *names], rows, 'Win rates under each rubric', row_headers=True))
    measures = [
        [f'Questions with all {counts["per_question"]} judgments', *[f'{e["complete"]} of 50' for e in entries]],
        ['Same winner as NUS ' + main, 'Baseline', *[
            f'{_pct(e["agreement"][0] / e["agreement"][1]) if e["agreement"][1] else "Unavailable"}'
            f'<br><small>{e["agreement"][0]:,} of {e["agreement"][1]:,} judgments</small>' for e in entries[1:]]],
        ['Judging cost', *[_money(e['judging_total'], 2) + (f'<br><small>plus {_plural(e["unknown_costs"], "call")} of unknown cost</small>'
                                                             if e['unknown_costs'] else '') for e in entries]]]
    parts.append(_table(['Measure', *names], measures, 'Rubric coverage, agreement and cost', row_headers=True))
    parts.append(f'<p class="small">“Same winner” compares each judgment with the NUS {main} judgment of the same question, '
                 'answer order and judge, wherever both exist. Win-rate intervals come from resampling the questions, as above; '
                 'they do not say which rubric is right.</p>')
    parts.append(_rubric_missing(data, entries[1:]))
    notes = defaultdict(list)
    for entry in entries[1:]:
        if entry['stand_ins']:
            notes[_stand_in_note(data, entry['stand_ins'])].append(f'NUS {entry["version"]}')
    for note, versions in notes.items():
        parts.append(f'<p class="small">{_text(f"Under {_join(versions)}, {note}")}</p>')
    if any(e['version'] in ('v1', 'v2') for e in entries):
        parts.append(f'<p class="small">{_text(RUBRIC_SHARED_NOTE)}</p>')
    parts.append('<details><summary>Win rates by judge under each rubric</summary>')
    for e, name in zip(entries, names):
        view = e['common']
        rows = []
        for judge in view['judges']:
            per = {r['agent']: r for r in view['per_judge'][judge]}
            rows.append([_text(_judge_label(data, judge)), *[_pct(per[a]['preference_rate']) for a in agents]])
        parts.append(f'<h3>{_text(name)}</h3>'
                     + _table(['Judge', *[_label(a) for a in agents]], rows, f'Per-judge win rates under {name}', row_headers=True))
    parts.append('</details></section>')
    return ''.join(parts)


ORDINALS = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth')


def _ordinal(rank):
    if not isinstance(rank, int):
        return 'unranked'
    return ORDINALS[rank - 1] if 0 < rank <= len(ORDINALS) else f'number {rank}'


def _rubric_takeaway(agents, views):
    """Say which places hold under every rubric and which change, from the computed ranks only."""
    ranks = {a: {view[a]['rank'] for view in views} for a in agents}
    moving = [a for a in agents if len(ranks[a]) > 1]
    steady = defaultdict(list)
    for agent in agents:
        if len(ranks[agent]) == 1:
            steady[next(iter(ranks[agent]))].append(agent)
    sentences = []
    if moving:
        sentences.append(f'{_join(_label(a) for a in moving)} {"change places" if len(moving) > 1 else "changes place"} '
                         'from one rubric to another.')
    if steady:
        shared = {rank for view in views for rank, n in Counter(view[a]['rank'] for a in agents).items() if n > 1}
        held = [f'{_join(_label(a) for a in group)} tie for {_ordinal(rank)}' if len(group) > 1
                else f'{_label(group[0])} is {_ordinal(rank)} or tied for {_ordinal(rank)}' if rank in shared
                else f'{_label(group[0])} stays {_ordinal(rank)}' for rank, group in sorted(steady.items())]
        sentences.append(f'{_join(held)} under every rubric.')
    return '<p>' + _text(' '.join(sentences)) + '</p>'


def _rubric_missing(data, entries):
    numbers, notes, judges, refusals, unknown = _question_numbers(data), [], set(), [], False
    for entry in entries:
        by_question = defaultdict(list)
        for failure in entry['failures']:
            by_question[failure['question_id']].append(failure)
            judges.add(failure['judge'])
            refusals += [failure] if failure['kind'] == 'refusal' else []
            unknown = unknown or failure['kind'] == 'unknown_outcome'
        if not by_question:
            continue
        items = []
        for qid in sorted(by_question, key=numbers.get):
            kinds = Counter(f['kind'] for f in by_question[qid])
            names = {'refusal': 'refused', 'unknown_outcome': 'unknown outcome', 'other': 'failed'}
            detail = (names[next(iter(kinds))] if len(kinds) == 1 else
                      ', '.join(f'{_word(n)} {names[k]}' for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])))
            items.append(f'{_word(len(by_question[qid]))} on question {numbers[qid]} ({detail})')
        notes.append(f'Missing judgments under NUS {entry["version"]}: {_join(items)}.')
    if not notes:
        return ''
    if len(judges) == 1:
        notes.append(f'Every missing judgment is {_judge_label(data, next(iter(judges)))}’s.')
    if refusals:
        attempts = sorted({f['attempts'] for f in refusals})
        one = len(refusals) == 1
        tries = (_plural(attempts[0], 'attempt') if len(attempts) == 1
                 else f'{_word(attempts[0])} to {_plural(attempts[-1], "attempt")}')
        sentence = ('The refusal came after ' if one else 'The refusals came after ') + tries + (
            ' each' if not one and len(attempts) == 1 else '')
        labels = []
        for category in sorted({c for f in refusals for c in f['categories']}):
            labelled = sum(category in f['categories'] for f in refusals)
            whom = ('it' if one else 'them' if labelled == len(refusals) else
                    'one of them' if labelled == 1 else f'{_word(labelled)} of them')
            labels.append(f'labeled {whom} “{category}”{_category_gloss([category])}')
        notes.append(sentence + (', and the API ' + _join(labels) if labels else '') + '.')
    if unknown:
        notes.append('A call has an unknown outcome when it timed out or lost its connection, so we cannot tell '
                     'whether it was processed. '
                     'We do not resend such a call, because the first request may have been billed.')
    return '<p class="small">' + _text(' '.join(notes)) + '</p>'


def _resources(data):
    generation, judging = data['resources']['generation'], data['resources']['judging']
    agents, judges, counts = _system_order(data), data['ranking']['judges'], _counts(data)
    totals = {a: (generation[a]['audited_known_cost_usd']
                  if _number(generation[a]['audited_known_cost_usd'])
                  else generation[a]['known_cost_usd']) for a in agents}
    audited = bool(data['audit_records'])
    parts = ['<section id="resources"><h2>Cost and time</h2>'
             + ('<p>Costs use the final audit when it covers every answer for a system, including earlier attempts. '
                'Otherwise they use the original records. Dollar figures are estimates, not invoices.</p>' if audited else
                '<p>Costs come from each answer’s saved records. Dollar figures are estimates, not invoices.</p>')]
    averages, incomplete = [], False
    for agent in agents:
        r = generation[agent]
        mean = totals[agent] / r['answers'] if _number(totals[agent]) and r['answers'] else None
        partial = 0 if _number(generation[agent]['audited_known_cost_usd']) else r['missing_cost_answers']
        incomplete = incomplete or bool(partial)
        averages.append([_text(_label(agent)), _money(mean)
                         + (f'<br><small>{partial} of {r["answers"]} estimates incomplete</small>' if partial else ''),
                         _duration(r['mean_duration_seconds'])
                         + (f'<br><small>{r["duration_count"]} of {r["answers"]} answers timed</small>'
                            if r['duration_count'] != r['answers'] else '')]
                        + ([_duration(r['mean_lifetime_duration_seconds'])
                            + f'<br><small>{r["lifetime_duration_count"]} of {r["answers"]} answers timed</small>'] if audited else []))
    parts.append(_table(['System', 'Mean estimated cost', 'Mean job time']
                        + (['Mean time including earlier attempts'] if audited else []), averages, 'Mean cost and time per answer'))
    google = generation.get('gemini')
    parts.append('<p class="small">'
                 + ('An incomplete estimate is missing the cost of some calls, so the mean is a lower bound. ' if incomplete else '')
                 + ('Google’s estimate uses assumed model rates because Google does not report its internal billing. ' if google else '')
                 + 'Charges that were never reported are left out. Job time runs from the start of the job that produced '
                 'the answer to its end, including waiting in queues and retries. '
                 + ('Time including earlier attempts adds failed or interrupted attempts and leaves out known gaps between them. ' if audited else '')
                 + 'Each time average uses only answers with complete timing.</p>')
    exceeded, targets, soft, soft_over = Counter(), set(), {}, Counter()
    for row in data['answers']:
        agent = row['agent']
        audited = data['audit_records'].get((row['question_id'], agent), {})
        amount = audited.get('known_usd')
        if not _number(amount):
            amount = cost_for_row(row).get('cumulative_known_estimate_usd')
        config = data['configurations'].get(row.get('configuration_id'), {})
        settings = config.get('settings') or data['manifest'].get('config', {}).get('research', {}).get(agent, {})
        target = settings.get('budget_usd')
        if _number(target) and target > 0:
            targets.add(target)
        if _number(amount) and _number(target) and target > 0 and amount > target:
            exceeded[agent] += 1
        aim = settings.get('budget_target_usd')
        if _number(aim) and _number(target) and 0 < aim < target:
            soft[agent] = aim
            soft_over[agent] += 1 if _number(amount) and amount > aim else 0
    if exceeded:
        items = [f'{_word(exceeded[a])} {_text(_label(a))} answer{"s" if exceeded[a] != 1 else ""}'
                 for a in agents if exceeded[a]]
        target = (f'the {_money(next(iter(targets)))} per-answer target' if len(targets) == 1
                  else 'its per-answer target')
        parts.append(f'<p class="small">Estimated cost was above {target} for ' + _join(items) + '. '
                     'These costs include earlier failed attempts when they were recorded. '
                     'The target is a soft budget the systems aim for, '
                     'not a spending cap enforced by the provider; actual bills have not been checked.</p>')
    if soft:
        parts.append('<p class="small">' + ' '.join(
            f'{_text(_label(a))}’s own settings use a stricter {_money(soft[a])} target; '
            f'{_word(soft_over[a])} of its answers {"was" if soft_over[a] == 1 else "were"} over it.'
            for a in agents if a in soft) + '</p>')
    parts.append('<details class="resource-details"><summary>Cost totals and timing</summary>')
    if google:
        parts.append('<p>Google’s estimate assumes Gemini 3.1 Pro rates for long inputs, counts tool tokens as extra input, '
                     'and charges every search at full price.</p>')
    parts.append('<p class="small">Each mean above is the total below divided by all of that system’s answers.'
                 + (' The original records are kept even when the final audit gives a corrected total.' if audited else '')
                 + '</p>')
    parts.append(_table(['System', 'Total cost of writing the answers'], [
        [_text(_label(a)), _money(totals[a])] for a in agents], 'Generation cost totals'))
    stand_ins = Counter((r['judge'], r['model']) for r in data.get('stand_ins', []))
    parts.append('<p class="small">Judging costs extra: '
                 + '; '.join(_text(_judge_label(data, j)) + ' ' + _money(judging[j]['known_cost_usd']) + ''.join(
                     f' (including the {_plural(n, "judgment")} {_text(JUDGE_LABELS.get(model, model))} made)'
                     for (judge, model), n in sorted(stand_ins.items()) if judge == j) for j in judges) + '.</p>')
    scored = math.fsum(judging[j]['known_cost_usd'] or 0 for j in judges)
    subject = (f'{counts["saved"]:,} saved judgments and {_plural(counts["failed"], "failed judgment")}'
               if counts['failed'] else f'{counts["judgments"]:,} judgments')
    replaced = bool(data.get('prior_judgments'))
    parts.append(f'<p><strong>Total for {subject}: {_money(scored)}.</strong> Includes the cost of retried calls.'
                 + (' Earlier judging that this round replaced is not included.' if replaced else ''))
    resent = _resent_tries(data)
    if resent:
        one, first = len(resent) == 1, 'first ' if all(t['index'] == 0 for t in resent) else ''
        how = ('timed out at the gateway' if all('gateway' in t['error'] for t in resent)
               else 'timed out or lost its connection' if one else 'timed out or lost their connection')
        again = ('it was sent once more' if one else 'each was sent once more') if all(t['after'] == 1 for t in resent) \
            else ('it was sent again' if one else 'each was sent again')
        parts.append(f' {_word(len(resent)).capitalize()} {first}{"try" if one else "tries"} {how}, so we do not know '
                     f'whether {"it was" if one else "they were"} charged; {again}. '
                     f'{"That" if one else "Those"} {first}{"try is" if one else "tries are"} not in the total.')
    if counts['failed']:
        failed = data['resources']['failed_judging']
        known, unknown = failed['cumulative_known_estimate_usd'], failed['unknown_count']
        if not unknown:
            whose = 'The failed judgment’s attempts' if counts['failed'] == 1 else 'The failed judgments’ attempts'
            parts.append(f' {whose} cost {_money(known)} and are included in the judging total.')
        elif unknown == counts['failed'] and not known:
            parts.append(' The failed call has no known cost, so it is not in the judging total.' if unknown == 1 else
                         f' The {_word(unknown)} failed calls have no known cost, so they are not in the judging total.')
        else:
            parts.append(f' Failed calls with a known cost add {_money(known)}, included in the judging total; '
                         f'{_plural(unknown, "failed call")} {"has" if unknown == 1 else "have"} no known cost and '
                         f'{"is" if unknown == 1 else "are"} not included.')
    parts.append('</p>')
    providers = set(judges) | {PRICING_PROVIDER.get(a, a) for a in agents}
    references = [link for provider, links in PRICING_LINKS.items() if provider in providers for link in links]
    if references:
        parts.append('<p class="small">Prices: ' + _join(references) + '. '
                     'Each answer’s record keeps the prices and the date they were checked.</p>')
    rows = []
    for agent in agents:
        r = generation[agent]
        rows.append([_text(_label(agent)), _duration(r['median_duration_seconds']),
                     _duration(r['min_duration_seconds']) + ' to ' + _duration(r['max_duration_seconds']),
                     f'{r["duration_count"]} of {r["answers"]}']
                    + ([_duration(r['median_lifetime_duration_seconds']),
                        f'{r["lifetime_duration_count"]} of {r["answers"]}'] if audited else []))
    parts.append(_table(['System', 'Median job time', 'Shortest to longest job time', 'Answers timed']
                        + (['Median time including earlier attempts', 'Answers with complete timing'] if audited else []),
                        rows, 'Saved answer elapsed times'))
    parts.append('<p class="small">Answers reused from the cache keep the times of the job that first produced them.</p>')
    differs = any(_number(generation[a]['audited_known_cost_usd'])
                  and (not _number(generation[a]['known_cost_usd']) or not math.isclose(
                      generation[a]['audited_known_cost_usd'], generation[a]['known_cost_usd'])) for a in agents)
    if differs:
        parts.append(_table(['System', 'Estimate in the answer records', 'Audited estimate, all attempts'], [
            [_text(_label(a)), _money(generation[a]['known_cost_usd']),
             _money(generation[a]['audited_known_cost_usd'])] for a in agents],
            'Audited lifetime generation estimates'))
    parts.append('</details></section>')
    return ''.join(parts)


def _models(data):
    research = data['manifest'].get('config', {}).get('research', {})
    agents = _system_order(data)
    rows = []
    for agent in agents:
        settings = research.get(agent) or {}
        models = sorted({str(a['result'].get('model', 'Unavailable')) for a in data['answers'] if a['agent'] == agent})
        if agent == 'gemini':
            detail = (f'Google’s managed agent {settings.get("agent", "(not recorded)")}. Cost is estimated with '
                      f'{settings.get("billing_model", "(not recorded)")} rates; Google chooses the models it runs and does not report them.')
        elif agent == 'openai':
            detail = f'Sol with OpenAI’s hosted web search, through the Responses API; reasoning effort {settings.get("reasoning_effort", "not recorded")}.'
        elif agent == 'anthropic':
            model = str(settings.get('model', ''))
            model = ('Sonnet' if model.startswith('claude-sonnet')
                     else JUDGE_LABELS.get(model, model or 'Claude'))
            tools = ('web search and page fetching run by the test harness' if settings.get('tool_mode') == 'client'
                     else 'Anthropic’s hosted web search')
            detail = f'{model} with {tools}, through the Messages API; effort {settings.get("effort", "not recorded")}.'
        elif agent == 'gpt_researcher':
            detail = (f'GPT Researcher in deep research mode, with {settings.get("model", "(not recorded)")} for every step; '
                      f'reasoning effort {settings.get("reasoning_effort", "not recorded")}. It searches the public web '
                      'through DuckDuckGo, filters pages by keyword, and sets money aside for writing the final answer.')
        elif agent == 'caesar':
            explore, kb = settings.get('exploration_model', '(not recorded)'), settings.get('kb_model', '(not recorded)')
            detail = ((f'Writes with the answer model and uses {explore} to explore the web and build its knowledge base. '
                       if explore == kb else
                       f'Writes with the answer model, explores the web with {explore}, '
                       f'and builds its knowledge base with {kb}. ')
                      + 'Each answer’s saved settings list every model it used.')
        else:
            detail = 'See the saved settings with each answer.'
        rows.append([_text(_label(agent)), _text(', '.join(models)), _text(detail)])
    return ('<details id="systems"><summary>Models and research workflows</summary>'
            + _table(['System', 'Answer model (for Google, the pricing model)' if 'gemini' in agents else 'Answer model',
                      'How it researches'], rows, 'Frozen research systems')
            + ('<p class="small">Google introduced its April 2026 Deep Research agents as built with Gemini 3.1 Pro '
               '(<a href="https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/">Google announcement</a>). '
               'That announcement does not say which models this run used.</p>' if 'gemini' in agents else '')
            + ('<p class="small">OpenAI’s o3-deep-research and o4-mini-deep-research API models shut down July 23, 2026 '
               '(<a href="https://developers.openai.com/api/docs/deprecations">deprecation notice</a>; '
               '<a href="https://developers.openai.com/api/docs/guides/deep-research">deep research guide</a>). '
               'The OpenAI results here come from the Sol setup above, not from those models.</p>' if 'openai' in agents else '')
            + '</details>')


def _questions(data):
    agents, counts = _system_order(data), _counts(data)
    answers = {(a['question_id'], a['agent']): a for a in data['answers']}
    judgments = defaultdict(list)
    for j in data['judgments']:
        judgments[j['question_id']].append(j)
    missing, numbers = Counter(f['question_id'] for f in data.get('judge_failures', [])), _question_numbers(data)
    stand_ins = {r['key']: r['model'] for r in data.get('stand_ins', [])}
    exceptions = _join(f'question {numbers[q]}, which has {counts["per_question"] - n}'
                       for q, n in sorted(missing.items(), key=lambda item: numbers[item[0]]))
    parts = ['<section id="questions"><h2>All questions, answers and judgments</h2>',
             f'<p>Each question lists {"both" if counts["systems"] == 2 else "all " + _word(counts["systems"])} answers and its '
             f'{counts["per_question"]:,} judgments' + (f', except {exceptions}' if missing else '') + '. '
             f'A question’s winner is the system that won the most of its {counts["per_question_system"]:,} judgments '
             'on that question; ties are shown. Open an answer or a judgment to read it.</p>']
    # Category order follows the question files; snapshots without categories are matched by text.
    catalog = [row for name in ('queries_n50_v2.jsonl', 'queries_n50_v1.jsonl') for row in _jsonl(ROOT / 'crest/data' / name)]
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
            saved = len(judgments[qid])
            if missing[qid]:
                outcome = (f'<span class="question-outcome" data-unranked="true" title="Missing judgments keep this question '
                           f'out of the ranking">Not ranked: {saved} of {counts["per_question"]} judgments</span>')
            else:
                votes = Counter(row['order'][0 if row['verdict']['winner'] == 'A' else 1]
                                for row in judgments[qid])
                most_wins = max(votes.values())
                winners = [agent for agent in agents if votes[agent] == most_wins]
                label = ('Winner: ' if len(winners) == 1 else 'Tie: ') + ' / '.join(_label(a) for a in winners)
                outcome = (f'<span class="question-outcome" data-winners="{" ".join(winners)}" data-wins="{most_wins}" '
                           f'title="Won {most_wins} of its {counts["per_question_system"]} judgments">{_text(label)}</span>')
            parts.append(f'<details class="question" id="question-{index}"><summary>'
                         f'<span class="question-number">{index:02d}</span><span class="question-title">{_text(question["text"])}</span>'
                         f'{outcome}</summary><div class="question-content">')
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
                    event_note = (f'<p class="small">Usage events left out of this page: {count:,}. '
                                  f'They are in <code>{_text(source)}</code>, field <code>result.usage.events</code>, '
                                  f'answer key <code>{_text(row["key"])}</code>.</p>')
                audit_note = ''
                if audited:
                    record['final_audit'] = audited
                    active = audited.get('active_attempt_seconds') if audited.get('timing_complete') is True else None
                    audit_note = ('; audited estimate, all attempts, ' + _money(audited.get('known_usd'))
                                  + '; time including earlier attempts ' + _duration(active))
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
                raw = row['result'].get('raw') or {}
                native = raw.get('artifact') if isinstance(raw, dict) else None
                source_urls = native.get('sources', {}) if isinstance(native, dict) else ()
                if not isinstance(source_urls, dict):
                    source_urls = ()
                parts.append(f'<details class="answer" id="answer-{index}-{agent}"><summary>{_text(_label(agent))}</summary>'
                             f'<div class="answer-text" data-answer-sha256="{hashlib.sha256(row["result"]["text"].encode()).hexdigest()}" '
                             f'role="region" tabindex="0" aria-label="{_text(_label(agent))} answer, question {index}">'
                             f'{_markdown_answer(row["result"]["text"], source_urls)}</div>'
                             '<details class="answer-metadata"><summary>Answer metadata and source records</summary>'
                             f'<p class="small">Estimated cost {_money(cost["cumulative_known_estimate_usd"])}'
                             f'{" (incomplete)" if cost.get("estimate_incomplete") else ""}; job time '
                             f'{_duration((row.get("timing") or {}).get("duration_seconds"))}{audit_note}</p>'
                             '<details class="configuration"><summary>Saved research settings</summary>'
                             f'<pre tabindex="0" aria-label="Saved research settings">{_text(json.dumps(configuration, ensure_ascii=False, indent=2))}</pre></details>'
                             f'<details class="cost-record"><summary>Cost, usage and timing record</summary>'
                             f'{event_note}'
                             f'<pre tabindex="0" aria-label="Cost, usage and timing record">{_text(json.dumps(record, ensure_ascii=False, indent=2))}</pre></details>'
                             f'<p class="small">{artifact_note}Answer key: <code>{_text(row["key"])}</code></p></details></details>')
            parts.append(f'<details class="judgments"><summary>Read all {saved:,} {"saved " if missing[qid] else ""}judgments</summary>')
            for pair in combinations(agents, 2):
                parts.append('<section class="judgment-group">'
                             f'<h4>{_text(_label(pair[0]))} vs {_text(_label(pair[1]))}</h4>')
                matched = [j for j in judgments[qid] if frozenset(j['pair']) == frozenset(pair)]
                for failure in data.get('judge_failures', []):
                    if failure['question_id'] == qid and frozenset(failure['pair']) == frozenset(pair):
                        first, second = failure['order']
                        parts.append(f'<p class="small missing-judgment">No saved judgment from '
                                     f'{_text(_judge_label(data, failure["judge"]))} with {_text(_label(first))} shown first and '
                                     f'{_text(_label(second))} second. See <a href="#unranked">why this question is not ranked</a>.</p>')
                for j in sorted(matched, key=lambda r: (r['judge'], r['order'])):
                    order = j['order']
                    winner = order[0 if j['verdict']['winner'] == 'A' else 1]
                    judge = _judge_label(data, j['judge'])
                    if j['key'] in stand_ins:
                        judge = f'{JUDGE_LABELS.get(stand_ins[j["key"]], stand_ins[j["key"]])} in place of {judge}'
                    parts.append(f'<details class="judgment"><summary>{_text(judge)} '
                                 f'· preferred {_text(_label(winner))}</summary>'
                                 f'<p class="presentation">Shown first (A): {_text(_label(order[0]))}; shown second (B): {_text(_label(order[1]))}</p>'
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
    aut = data['ranking'].get('rubric_kind') == AUT_KIND
    winner_guidance = (
        'Each judge chooses A or B using <strong>Fluency</strong> (expressed coverage only when a comparable '
        'task explicitly requests multiple ideas), <strong>Flexibility</strong> (meaningful conceptual directions), '
        'and <strong>Originality</strong> (substantive contributions and relationships). '
        if aut else
        'Each judge reads two answers, A and B, and picks the more creative one, guided by <strong>New</strong> '
        '(what the answer adds beyond known work), <strong>Useful</strong> (whether it works for the task), and '
        '<strong>Surprising</strong> (how far it departs from the approach an expert would expect). '
    )
    scope = (
        '<p>This AUT-inspired rubric is a qualitative adaptation for expressed research contributions. '
        'Raw idea counts are not comparable across paper topics. Scores are preferences under this rubric, '
        'not standardized AUT scores or measures of an author’s divergent-thinking ability. '
        '<a href="aut-inspired-rubric.html">AUT-inspired rubric and limits</a>.</p>' if aut else ''
    )
    creativity_reference = (
        '<ul><li><a href="https://digitalcommons.unomaha.edu/psychfacpub/259/">'
        'Reiter-Palmon, Forthmann, and Barbot, 2019</a>: divergent-thinking scoring choices.</li>'
        '<li><a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC4001084/">'
        'Benedek et al., 2013</a>: subjective top-scoring and fluency–originality confounds.</li>' if aut else
        '<ul><li><a href="https://doi.org/10.1080/10400419.2012.650092">Runco and Jaeger, 2012</a>: '
        'originality and effectiveness as core creativity criteria.</li>'
    )
    counts, agents = _counts(data), _system_order(data)
    cues = {'openai': 'utm_source=openai', 'gemini': 'vertexaisearch.cloud.google.com'}
    revealed = {agent: sum(a['agent'] == agent and marker in a['result']['text'] for a in data['answers'])
                for agent, marker in cues.items() if agent in agents}
    provenance = ''
    revised = bool(data.get('judgments')) and all(
        j.get('protocol_version') in (NUS_PROTOCOL, AUT_PROTOCOL)
        and j.get('presentation_version') in ('citation-neutral-v1', 'citation-neutral-v2') for j in data['judgments'])
    trimmed = revised and all(j.get('presentation_version') == 'citation-neutral-v2' for j in data['judgments'])
    if revised:
        provenance = ('<p>Judges saw every answer with its link addresses hidden in the same way; citation labels and '
                      'the rest of the text were kept. The answers below are the originals. An answer’s wording can still '
                      'reveal which system wrote it.</p>'
                      + ('<p>Some answers end with a list of sources the system collected but never cites. Judges did not '
                         'see that list; the answers below keep it.</p>' if trimmed else '')
                      + ('<p>Originality can come from combining familiar ideas. Elaboration supports evaluating '
                      'the contribution; it is not a word-count score. If a judge cannot support a substantive '
                      'preference, it must say so and choose A. Doing this in both orders gives each system one win.</p>' if aut else
                      '<p>Combining familiar ideas can still be original. Usefulness is judged within the question’s '
                      'premises, and an idea is not new just because it is unfamiliar. A judge that finds no real '
                      'difference must say so and choose A; doing that in both orders gives each system one win.</p>')
                      + '<p>A judgment is retried when its explanation is incomplete or does not compare the two answers. '
                      'These checks do not verify what the judges claim.</p>')
    elif any(revealed.values()):
        provenance = ('<p>Provider labels were withheld, but this run was not fully blinded. '
                      'Links reveal provenance in '
                      + _join(f'{count} / 50 {_text(_label(agent))} answers' for agent, count in revealed.items()) + '. '
                      'These cues do not establish that provider bias caused the ranking.</p>')
    rubric_links = ('' if aut else f'<a href="{page_path("NUS rubric").name}">NUS rubric</a>; '
                    f'<a href="{page_path("Why one overall judgment").name}">Why one overall judgment</a>. ')
    return ('<section id="method"><h2>How the comparison works</h2>'
            f'<p>Each question has {counts["per_question"]:,} judgments: {_plural(counts["pairs"], "answer pair")}, '
            f'each judged by {_plural(counts["judges"], "judge")} in both orders.</p>'
            + scope + '<dl class="method-summary">'
            '<dt>Pick a winner</dt><dd>' + winner_guidance +
            'The judge makes one overall choice and gives no separate scores. ' + rubric_links + '</dd>'
            f'<dt>Count the wins</dt><dd>Every judgment counts equally. Each system appears in {counts["per_system"]:,} judgments; '
            f'its wins divided by {counts["per_system"]:,} is its win rate.</dd>'
            f'<dt>Read the intervals</dt><dd>We resample the {"50" if counts["ranked"] == 50 else str(counts["ranked"]) + " ranked"} questions 1,000 times, keeping each question’s {counts["per_question"]:,} judgments '
            'together. The middle 95% of the resulting win rates is the 95% interval.</dd></dl>'
            '<p class="small">The intervals do not account for regenerating the answers or choosing other judges. '
            'Answer length or style may sway the judges.</p>'
            + _models(data) +
            '<details><summary>Rubric, how answers were shown, and references</summary>' + provenance +
            '<p>Every system is scored on the same resampled question sets, so comparisons between systems are '
            f'like for like. The random seed is {_text(bootstrap["seed"])}.</p>'
            + creativity_reference +
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
.small,small{color:#526574}.small{font-size:.9rem}.nowrap{white-space:nowrap}
.run-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem;margin:1.8rem 0}.run-stats strong{display:block;color:#0b5967;font-size:1.9rem}.run-stats span{font-size:.85rem;color:#526574}
.ranking-row{display:grid;grid-template-columns:minmax(160px,1.1fr) minmax(150px,2fr) 130px;gap:1rem;align-items:center;margin:1.1rem 0}.rank-label{display:flex;align-items:center;gap:.7rem}.rank{color:#526574;font-size:1.3rem}.ranking-row svg{width:100%;height:48px}.score{text-align:right;font-variant-numeric:tabular-nums}.score strong{display:block;font-size:1.4rem}.score small{display:block;font-size:.8rem;line-height:1.5}
.table-scroll{max-width:100%;overflow:auto;background:linear-gradient(to right,#fff 30%,rgba(255,255,255,0)),linear-gradient(to left,#fff 30%,rgba(255,255,255,0)) 100% 0,radial-gradient(farthest-side at 0 50%,rgba(23,44,62,.22),rgba(23,44,62,0)),radial-gradient(farthest-side at 100% 50%,rgba(23,44,62,.22),rgba(23,44,62,0)) 100% 0;background-repeat:no-repeat;background-size:40px 100%,40px 100%,14px 100%,14px 100%;background-attachment:local,local,scroll,scroll}.answer-text .table-scroll{background:none}.table-scroll table{min-width:630px}.table-scroll .matrix{table-layout:fixed;min-width:700px}.matrix th,.matrix td{vertical-align:middle;padding:.9rem}.matrix th:first-child{width:29%}.matrix thead th,.matrix td{text-align:center}.matrix tbody th{font-weight:650;line-height:1.5}.heat-cell,.diagonal{display:flex;align-items:center;justify-content:center;min-height:3rem;padding:.6rem;font-variant-numeric:tabular-nums}.heat-cell{background:rgba(11,89,103,var(--shade))}.diagonal{background:#f0f3f5;color:#71818c;font-size:.85rem}
.question{padding:0;border:1px solid #d7e1e6;border-radius:6px;margin:1rem 0}.question>summary{display:grid;grid-template-columns:2rem minmax(0,1fr) auto 1rem;gap:.8rem;align-items:start;padding:1.2rem;font-size:1rem;list-style:none}.question>summary::-webkit-details-marker{display:none}.question>summary::after{grid-column:-2;grid-row:1;content:"+";font-size:1.2rem;line-height:1.2;text-align:center}.question[open]>summary::after{content:"−"}.question-number{color:#526574;font-weight:400;font-variant-numeric:tabular-nums}.question-title{min-width:0}.question-outcome{max-width:16rem;font-size:.78rem;line-height:1.6;font-weight:500;text-align:right}.question-content{padding:0 1.2rem 1rem}.question .evidence-heading{margin:1rem 0 .5rem}.question .answer{border-top:1px solid #d7e1e6;margin:0;padding:.15rem 0}.question .answer>summary{font-size:1rem;padding:1rem 0}.reason{white-space:pre-wrap;overflow-wrap:anywhere}.answer-text{white-space:normal;overflow-wrap:anywhere;max-height:40rem;overflow:auto;background:#f5f8f9;padding:1.2rem;font-size:.95rem;line-height:1.8}.answer-text>:first-child{margin-top:0}.answer-text>:last-child{margin-bottom:0}.answer-text h4{font-size:1.2rem}.answer-text h5{font-size:1.05rem}.answer-text h6{font-size:1rem}.answer-text pre{white-space:pre;overflow:auto}.answer-text .table-scroll table{min-width:480px}.answer-text .table-scroll th,.answer-text .table-scroll td{padding:.6rem .75rem;border-bottom:1px solid var(--line)}.answer-metadata{margin:1rem 0}.cost-record pre{max-height:32rem;white-space:pre-wrap;overflow-wrap:anywhere}.question .judgments{border-top:1px solid #d7e1e6;margin:1rem 0 0;padding-top:.5rem}.judgment-group{margin:1.5rem 0;padding-top:1rem;border-top:1px solid #d7e1e6}.judgment-group:first-of-type{margin-top:.5rem;padding-top:0;border-top:0}.judgment-group>h4{font-size:1rem;margin:.5rem 0}.question .judgment{margin:.3rem 0;padding:.2rem 0}.judgment .presentation{font-size:.85rem;color:#526574;margin:.2rem 0 1rem}.judgment .reason{margin:.7rem 0 1.5rem}summary{overflow-wrap:anywhere}code{overflow-wrap:anywhere}
@media(max-width:650px){.question-outcome{grid-column:2;grid-row:2;max-width:none;text-align:left}.method-summary{grid-template-columns:1fr;gap:.25rem}.method-summary dd{margin-bottom:1rem}.ranking-row{grid-template-columns:minmax(0,1fr) 125px;gap:.4rem 1rem}.ranking-row svg{grid-column:1/-1;grid-row:2}.score{grid-column:2;grid-row:1}.rank-label{font-size:.9rem}.run-stats{gap:.7rem}.run-stats strong{font-size:1.4rem}.answer-text{max-height:32rem;padding:1rem}.question>summary{grid-template-columns:1.6rem minmax(0,1fr) 1rem;gap:.5rem;padding:1rem .9rem}.question-content{padding:0 .9rem .9rem}}
@media print{.skip-link,main>nav{display:none}.ranking-row{break-inside:avoid}.answer-text{max-height:none;overflow:visible}details>summary{break-after:avoid}}
"""


def _headline(data):
    """State the ranking in order, grouping leaders the paired intervals cannot separate."""
    rows = data['ranking']['ranking']
    group = _top_group(data)
    rest = [row for row in rows if row['agent'] not in group]
    sentences = []
    if len(group) > 1:
        sentences.append(_join(f'{_label(row["agent"])} at {_pct(row["preference_rate"])}' for row in rows
                               if row['agent'] in group) + ' are too close to separate for first place.')
    else:
        rest = rows
    items = [f'{_label(row["agent"])}{" is" if index == 0 else ""} {_ordinal(row["rank"])} at {_pct(row["preference_rate"])}'
             for index, row in enumerate(rest)]
    if items:
        sentences.append(_join(items) + '.')
    return ' '.join(sentences)


def _previous_version(destination):
    match = re.fullmatch(r'(.+-v)(\d+)\.html', destination.name)
    if not match or int(match[2]) < 2:
        return None
    previous = destination.with_name(f'{match[1]}{int(match[2]) - 1}.html')
    return previous if previous.is_file() else None


def _render(data, destination, *, updated=None):
    title = _text(page_title(destination, "Deep research comparison"))
    agents, counts = data['manifest']['agents'], _counts(data)
    judge_phrase = _plural(counts['judges'], 'model judge').capitalize() + (' compares' if counts['judges'] == 1 else ' compare')
    aut = data['ranking'].get('rubric_kind') == AUT_KIND
    rubric = ('an AUT-inspired creativity rubric' if aut else
              'the NUS rubric, which asks how New, Useful and Surprising each answer is')
    shared = [j for j in data['ranking']['judges']
              if any(data['judges'][j].get('model') in models for models in _main_models(data).values())]
    previous = _previous_version(Path(destination))
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">',
             f'<title>{title}</title>', site_favicon(ROOT, destination), f'<style>{SITE_CSS}\n{CSS}</style></head><body>',
             '<a class="skip-link" href="#main-content">Skip to report</a>', site_header(ROOT, destination, research_report=destination, updated=updated),
             f'<main id="main-content" tabindex="-1"><h1>{title}</h1>',
             f'<p>This comparison runs {_text(_join(_label(a) for a in agents))} '
             f'on the same 50 questions. {judge_phrase} the {counts["answers"]:,} answers two at a time, in both orders, '
             f'and pick the more creative one under {rubric}. '
             + (f'The ranking uses {counts["ranked"]} of the 50 questions; <a href="#unranked">'
                f'{"one question is" if 50 - counts["ranked"] == 1 else _word(50 - counts["ranked"]) + " questions are"} not ranked</a>. '
                if counts['ranked'] != 50 else '')
             + 'The models behind each system are listed under <a href="#systems">Models and research workflows</a>.</p>'
             + f'<p><strong>{_text(_headline(data))}</strong>'
             + ((f' {_word(len(shared)).capitalize()} of the {_word(counts["judges"])} judges use' if len(shared) > 1 else
                 ' One judge uses' if counts['judges'] > 1 else ' The judge uses')
                + ' the same model as some of the systems being judged; <a href="#judges">see how each judge ruled</a>.'
                if shared else '')
             + (f' The previous study is <a href="{previous.name}">{_text(page_title(previous, previous.stem))}</a>.' if previous else '')
             + '</p>',
             '<nav aria-label="Report contents"><a href="#overall">Ranking</a><a href="#matchups">Head-to-head</a>'
             '<a href="#judges">Judges</a>' + ('<a href="#rubrics">Rubrics</a>' if data.get('rubric_variants') else '')
             + '<a href="#resources">Cost and time</a>'
             '<a href="#method">Method</a><a href="#questions">Answers</a></nav>',
             (f'<div class="run-stats"><div><strong>{counts["ranked"]}</strong><span>of 50 questions ranked</span></div>'
              if counts['ranked'] != 50 else '<div class="run-stats"><div><strong>50</strong><span>questions</span></div>')
             + f'<div><strong>{counts["answers"]:,}</strong><span>answers</span></div>'
             + (f'<div><strong>{counts["saved"]:,}</strong><span>of {counts["judgments"]:,} pairwise judgments</span></div></div>'
                if counts['failed'] else f'<div><strong>{counts["judgments"]:,}</strong><span>pairwise judgments</span></div></div>'),
             _ranking(data), _head_to_head(data), _judges(data), _rubrics(data), _resources(data), _method(data),
             _questions(data),
             '</main></body></html>\n']
    return ''.join(parts)


def write_report(run_dir, destination, *, audit=None, updated=None, rubric_runs=()):
    """Write a validated final report atomically; errors leave old outputs intact."""
    require_canonical_output(destination)
    updated = page_updated(updated)
    data = load_run(run_dir, audit=audit)
    if rubric_runs:
        data['rubric_variants'] = _rubric_variants(data, rubric_runs)
    destination = Path(destination).expanduser().resolve()
    html = _render(data, destination, updated=updated)
    index_update = prepare_index_date(ROOT, destination, updated)
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
    write_index_date(index_update)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='Render only a complete, frozen CREST report: 50 questions, one answer per '
                                     'agent in the run manifest, and every answer pair judged in both orders by every '
                                     'configured judge, except judgments recorded as failures; no API calls.')
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, help='Optional final lifetime audit; otherwise use latest 04-audit*/audit.json')
    parser.add_argument('--updated', help='Page-update date YYYY-MM-DD; defaults to CREST_PAGE_UPDATED, SOURCE_DATE_EPOCH, or UTC today')
    parser.add_argument('--rubric-run', type=Path, action='append', default=[], dest='rubric_runs',
                        help='A run that judged the same answers under another packaged NUS rubric; repeatable')
    args = parser.parse_args(argv)
    try:
        result = write_report(args.run, args.output, audit=args.audit, updated=args.updated, rubric_runs=args.rubric_runs)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'crest.report: {exc}\n')
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
