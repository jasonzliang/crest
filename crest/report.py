"""Offline HTML publication of a complete, frozen CREST research comparison.

Usage: python -m crest.report RUN --output docs/deep-research/deep-research-comparison-v3.html
Only 50-question comparisons of every agent in the frozen run manifest, judged by
every configured judge, can be written. A question may be left unranked only when
each of its missing judgments matches a recorded failure in the judge stage;
the page then names it. Rendering never submits jobs, changes analysis, or reads
mutable generation caches.

Add --rubric-run RUN (repeatable) to show the same answers judged under other
packaged NUS rubrics in small collapsed dropdowns at the bottom of the page.
Category headings use saved metadata or the bundled query dataset.

Optional enrichment uses the existing crest-final-audit-v1 artifact produced by
crest-final-audit.py. It must be complete, ready, and match the frozen answer
identities. No alternative audit or accounting protocol is introduced here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
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
from .cost_imputation import impute_answer_costs, impute_judgment_costs
from .costs import cost_for_row, summarize_costs
from .judging import parse_verdict, validate_verdict
from .rubrics import AUT_KIND, NUS_KIND, STRICT_REASON_PROTOCOLS, protocol_rubric_kind
from crest_ais.navigation import CSS as SITE_CSS, site_favicon, site_header
from crest_ais.site import page_href, page_path, page_title, page_updated, require_canonical_output, prepare_index_date, write_index_date

ROOT = Path(__file__).resolve().parents[1]
# Agents and judges come from each frozen run; these tables only decorate known identifiers.
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')
LABELS = {'caesar': 'Caesar', 'openai': 'OpenAI (Sol + web search)', 'gemini': 'Google Deep Research',
          'anthropic': 'Anthropic (Claude + web search)', 'gpt_researcher': 'GPT Researcher'}
JUDGE_LABELS = {'gpt-6.1-sol': 'GPT-6.1 Sol', 'claude-opus-5-5': 'Claude Opus 5.5', 'gpt-6-astra': 'GPT-6 Astra', 'gemini-4-argon': 'Gemini 4 Argon', 'claude-fable-5-1': 'Claude Fable 5.1',
                'claude-sonnet-5-5': 'Claude Sonnet 5.5', 'gpt-6-luna': 'GPT-6 Luna'}
SOURCE_URLS = {'gpt_researcher': 'https://github.com/assafelovic/gpt-researcher', 'caesar': 'https://github.com/jasonzliang/caesar-agent',
               'openai': 'https://developers.openai.com/api/docs/guides/tools-web-search',
               'gemini': 'https://ai.google.dev/gemini-api/docs/deep-research',
               'anthropic': 'https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool'}
COLORS = {'gpt_researcher': '#8a4d69', 'caesar': '#0b5967', 'gemini': '#b4652b', 'openai': '#5e628c', 'anthropic': '#3d7a4a'}
DEFAULT_COLOR = '#526574'
PRICING_LINKS = {'openai': ('<a href="https://developers.openai.com/api/docs/models/gpt-6.1-sol">GPT-6.1 Sol</a>',
                            '<a href="https://developers.openai.com/api/docs/models/gpt-6-luna">GPT-6 Luna</a>'),
                 'gemini': ('<a href="https://ai.google.dev/gemini-api/docs/pricing">Gemini API</a>',),
                 'anthropic': ('<a href="https://platform.claude.com/docs/en/about-claude/pricing">Claude</a>',)}
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

    def table_open(self, _tokens, _idx, _options, env):
        env['tables'] = env.get('tables', 0) + 1
        label = _text(f'Table {env["tables"]} in {env.get("table_label", "the answer")}')
        return f'<div class="table-scroll" role="region" aria-label="{label}" tabindex="0"><table>'

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


def _markdown_answer(text, source_urls=(), label='the answer'):
    parser = MarkdownIt('js-default', {'breaks': True, 'linkify': True}, renderer_cls=_AnswerMarkdownRenderer)
    parser.inline.ruler.before('linkify', 'known_source_urls', _link_known_source_urls)
    env = {'source_urls': sorted({u for u in source_urls if isinstance(u, str) and ' ' in u
                                and not any(c in u for c in '\r\n\t')
                                and u.lower().startswith(('https://', 'http://'))
                                and parser.validateLink(u)}, key=len, reverse=True),
           'table_label': label}
    tokens = parser.parse(text, env)
    for token in tokens:
        if token.type in {'heading_open', 'heading_close'}:
            level = int(token.tag[1:])
            # The page's question headings are h3/h4, so an answer's own h1 becomes h5. Levels 2 and 3 both
            # become h6, so level 3 and below get a smaller style.
            token.tag = f'h{min(6, level + 4)}'
            if token.type == 'heading_open' and level >= 3:
                token.attrSet('class', 'answer-minor-heading')
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


def _count(count, noun, plural=None):
    """A count in digits, for answers, calls and judgments in cost and judging prose."""
    return f'{count:,} {noun if count == 1 else plural or noun + "s"}'


def _join(items, conjunction='and'):
    items = list(items)
    return (f' {conjunction} '.join(items) if len(items) < 3
            else ', '.join(items[:-1]) + f', {conjunction} ' + items[-1])


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


_PRESENTED = {}  # (SHA-256 of saved text, presentation version) -> text as the judges saw it.


def _presented_text(text, version):
    """An answer as the judges saw it. Formatting is slow, and the rubric runs judge the same
    answers, so each saved text is formatted once per presentation version per process."""
    from .presentation import present_research_answer
    key = (hashlib.sha256(text.encode()).hexdigest(), version)
    if key not in _PRESENTED:
        _PRESENTED[key] = present_research_answer(text, version)
    return _PRESENTED[key]


def _presented_hash(cache, key, text, version):
    """SHA-256 of an answer as the judges saw it, computed once per answer and presentation version."""
    if (key, version) not in cache:
        cache[key, version] = hashlib.sha256(_presented_text(text, version).encode()).hexdigest()
    return cache[key, version]


def _validate(data):
    questions, answers, judgments, ranking = (data[k] for k in ('questions', 'answers', 'judgments', 'ranking'))
    failures = data.get('judge_failures', [])
    presented = {}  # (answer key, presentation version) -> hash of the text the judges saw.
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
        strict_reason = protocol in STRICT_REASON_PROTOCOLS
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
            from .presentation import ANSWER_PRESENTATION_VERSION, PRESENTATION_VERSION
            version = row.get('presentation_version')
            if version not in (PRESENTATION_VERSION, ANSWER_PRESENTATION_VERSION) or row.get('presented_answer_hashes') != [
                    _presented_hash(presented, a['key'], a['result']['text'], version) for a in ordered]:
                raise ValueError('Judgment presentation hashes do not match the saved answers')
    protocols = {j.get('protocol_version') for j in judgments}
    if protocols.intersection(STRICT_REASON_PROTOCOLS) and len(protocols) != 1:
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


def _summarize(rows, audit_records, imputed=None):
    # One shared accounting implementation handles partial estimates and ancestry
    # deduplication. The lifetime audit is displayed separately, never substituted
    # into saved cost_details or added to them. Calls that never reported a cost are
    # counted at an imputed amount (crest.cost_imputation), kept apart from the known total.
    costs = summarize_costs(rows)
    records = [(imputed or {}).get(r.get('key')) for r in rows]
    records = [r for r in records if r]
    with_calls = [r for r in records if r['imputed_calls']]
    imputed_total = math.fsum(r['imputed_usd'] for r in with_calls)
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
    estimated = known_total + imputed_total if known_total is not None else None
    return {'answers': len(rows), 'cost_assessment': costs,
            'known_cost_usd': known_total,
            'mean_known_cost_usd': known_total / len(rows) if known_total is not None and rows else None,
            'imputed_cost_usd': imputed_total, 'imputed_answers': len(with_calls),
            'imputed_calls': sum(r['imputed_calls'] for r in with_calls), 'imputed_records': with_calls,
            'estimated_cost_usd': estimated,
            # Rows still missing some cost after imputation; Google's assumed-price scenario is not one of them.
            'unimputed_missing_answers': sum(r['residual_incomplete'] and r['residual_reason'] != 'conditional_list_price_scenario'
                                             for r in records) if records else None,
            'current_attempt_known_cost_usd': costs['current_attempt_known_estimate_usd'] if current_available else None,
            'unknown_cost_answers': costs['unknown_count'],
            # Google's assumed-price scenario is flagged incomplete by design; only missing calls make a lower bound.
            'missing_cost_answers': sum(bool(c.get('estimate_incomplete'))
                                        and c.get('cost_basis') != 'conditional_list_price_scenario' for c in details),
            'historical_unknown_reserved_usd': costs['historical_unresolved_reserved_exposure_usd'],
            'audited_known_cost_usd': math.fsum(known) if len(known) == len(rows) else None,
            'duration_count': len(durations), 'duration_sum_seconds': math.fsum(durations) if durations else None,
            'mean_duration_seconds': statistics.mean(durations) if durations else None,
            'median_duration_seconds': statistics.median(durations) if durations else None,
            'min_duration_seconds': min(durations) if durations else None,
            'max_duration_seconds': max(durations) if durations else None,
            'unknown_duration_answers': len(rows) - len(durations),
            'lifetime_duration_count': len(lifetime),
            'mean_lifetime_duration_seconds': statistics.mean(lifetime) if lifetime else None,
            'median_lifetime_duration_seconds': statistics.median(lifetime) if lifetime else None}


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


def _attempts(row):
    return [a for a in row.get('attempts') or [] if isinstance(a, dict)]


def _refusal_categories(attempts):
    """The safety category the API gave each refused attempt that named one."""
    return [m.group(1) for a in attempts for m in [REFUSAL.search(str(a.get('error') or ''))] if m]


def _stand_in(data, row):
    """The model that judged in place of the judge's saved model, or None.

    A stand-in is accepted only after the saved model refused every earlier try;
    any other change of model is an error."""
    configured, model = data['judges'][row['judge']].get('model'), (row.get('result') or {}).get('model')
    attempts = _attempts(row)
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
            refused = [a for a in _attempts(row) if not a.get('substitute_model')]
            labels = _refusal_categories(refused)
            found.append({'key': row['key'], 'question_id': row['question_id'], 'pair': list(row['pair']),
                          'order': list(row['order']), 'judge': row['judge'], 'model': model,
                          'refusals': len(refused), 'labeled': len(labels), 'categories': sorted(set(labels))})
    return found


def _resent_tries(data):
    """Earlier tries of saved judgments whose outcome, and so whose cost, is unknown."""
    tries, imputed = [], data.get('cost_imputation', {}).get('judgments', {})
    for row in data['judgments']:
        attempts = _attempts(row)
        calls = {c['attempt_key']: c for c in (imputed.get(row.get('key')) or {}).get('calls', [])}
        for index, attempt in enumerate(attempts[:-1]):
            if attempt.get('submission_unknown') and not _number(attempt.get('cost_usd')):
                call = calls.get(attempt.get('key')) or {}
                tries.append({'index': index, 'after': len(attempts) - index - 1,
                              'error': str(attempt.get('error') or ''),
                              'imputed_usd': call.get('imputed_usd'), 'basis': call.get('basis')})
    return tries


def _resent_sentence(resent):
    """Say which earlier tries never reported a cost, that they were sent again, and how the total counts them."""
    if not resent:
        return ''
    one, first = len(resent) == 1, 'first ' if all(t['index'] == 0 for t in resent) else ''
    timeouts = all(re.search(r'HTTP 408|timeout|timed out', t['error'], re.I) for t in resent)
    how = 'timed out' if timeouts else 'timed out or lost its connection' if one else 'timed out or lost their connection'
    once = all(t['after'] == 1 for t in resent)
    again = ('We sent it once more' if one else 'We sent each once more') if once \
        else ('We sent it again' if one else 'We sent each again')
    what = (f'The {first}try of 1 judgment' if one else f'The {first}tries of {len(resent):,} judgments') if first \
        else f'Earlier tries of {_count(len(resent), "judgment")}'  # A judgment has at most one unknown first try.
    lead = f'{what} {how} and never reported a cost. {again}'
    if not all(_number(t.get('imputed_usd')) for t in resent):
        return f'{lead}. {"That" if one else "Those"} {first}{"try is" if one else "tries are"} not in the total.'
    amount = _money(math.fsum(t['imputed_usd'] for t in resent))
    tries = f'the {first}try' if one else f'each {first}try'
    if once and first and all(t['basis'] == 'same_job_resend' for t in resent):
        cost = 'what the second try cost' if one else 'what its second try cost'
    else:
        cost = 'the cost of similar calls'
    return f'{lead} and count {tries} at {cost} ({amount}{"" if one else " in total"}).'


def _failure_kind(row):
    attempts = _attempts(row)
    if attempts and all(_refused(a) for a in attempts):
        return 'refusal', sorted(set(_refusal_categories(attempts)))
    text = ' '.join([str(row.get('error') or ''), *(str(a.get('error') or '') for a in attempts)])
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
    # Failed judgments have no resend to compare with, so only saved judgments are imputed.
    data['cost_imputation'] = {
        'answers': {r['key']: r for r in impute_answer_costs(data['answers'])},
        'judgments': {r['key']: r for r in impute_judgment_costs(data['judgments'], judges=data['judges'])}}
    data['resources'] = {
        'generation': {agent: _summarize([a for a in data['answers'] if a['agent'] == agent], audit_records,
                                         data['cost_imputation']['answers']) for agent in agents},
        'judging': {judge: _summarize([j for j in data['judgments'] if j['judge'] == judge]
                                      + [f['row'] for f in data['judge_failures'] if f['judge'] == judge], {},
                                      data['cost_imputation']['judgments'])
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
    return math.fsum(judging[j]['estimated_cost_usd'] or 0 for j in data['ranking']['judges'])


def _rubric_variants(data, runs):
    """Validate runs that judged these exact answers under other packaged NUS rubrics."""
    main_version = _rubric_version((data['judging_dir'] / 'rubric.txt').read_text(encoding='utf-8'))
    if main_version is None:
        raise ValueError('A rubric comparison needs this report to use a packaged NUS rubric')
    identity, presentation = _answer_identity(data), {j.get('presentation_version') for j in data['judgments']}
    protocol = {j.get('protocol_version') for j in data['judgments']}
    entries = [_variant_summary(main_version, data)]
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
    entries[1:] = sorted(entries[1:], key=lambda e: int(e['version'].lstrip('v')))
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
            'resent': _resent_sentence(_resent_tries(data)),
            'unknown_costs': sum(data['resources']['judging'][j]['unknown_cost_answers'] for j in data['ranking']['judges']),
            'stand_ins': data['stand_ins'],
            'failures': [{k: v for k, v in f.items() if k != 'row'} for f in data['judge_failures']]}


def _tenths(value):
    """Round a share to tenths of a percent, halves up, from its shortest decimal form (35.25 shows as 35.3)."""
    return (Decimal(str(value)) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP) + 0  # + 0 turns −0.0 into 0.0.


def _pct(value):
    return f'{_tenths(value)}%' if _number(value) else 'Unavailable'


def _money(value, places=2):
    return f'${value:,.{places}f}' if _number(value) else 'Unknown'


def _duration(value):
    if not _number(value):
        return 'Unknown'
    return f'{value / 60:,.1f} min' if value >= 60 else f'{value:,.1f} s'


def _interval(value):
    return '–'.join(_pct(v) for v in value) if isinstance(value, list) and len(value) == 2 else 'Unavailable'


def _points(value):
    return f'{_tenths(value):+}'.replace('-', '−')


def _main_models(data):
    """Each system's main answer-writing models, as saved on its answers."""
    models = defaultdict(set)
    for answer in data['answers']:
        model = answer['result'].get('model')
        if isinstance(model, str) and model:
            models[answer['agent']].add(model)
    return models


WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


def _answer_lengths(data):
    """Each system's mean answer length in words, counted on the text the judges saw when every judgment
    used one presentation, else on the saved text without its appended list of uncited sources."""
    from .presentation import drop_uncited_sources
    versions = {j.get('presentation_version') for j in data.get('judgments', [])}
    version = next(iter(versions)) if len(versions) == 1 else None
    exact = version in ('citation-neutral-v1', 'citation-neutral-v2')
    words = defaultdict(list)
    for answer in data['answers']:
        text = answer['result']['text']
        text = _presented_text(text, version) if exact else drop_uncited_sources(text)
        words[answer['agent']].append(len(WORD.findall(text)))
    label = 'Mean length (words)' if exact else 'Mean length (words, sources list excluded)'
    return {a: statistics.fmean(n) for a, n in words.items()}, label


WIDE_TABLE_COLUMNS = 5  # Tables this wide keep a minimum width and scroll on phones instead of squeezing.


def _table(headers, rows, label, extra='', *, row_headers=False, num_from=None, wide=None):
    """Columns from index num_from on hold numbers: right-aligned, unbroken, tabular figures."""
    def num(index):
        return ' class="num"' if num_from is not None and index >= num_from else ''
    if wide is None:
        wide = len(headers) >= WIDE_TABLE_COLUMNS and 'class="matrix' not in extra  # The matrix has its own width.
    attributes = extra
    if wide:
        attributes = extra.replace('class="', 'class="wide ', 1) if 'class="' in extra else ' '.join(
            part for part in (extra, 'class="wide"') if part)
    return (f'<div class="table-scroll" role="region" aria-label="{_text(label)}" tabindex="0">'
            f'<table{" " + attributes if attributes else ""}><thead><tr>'
            + ''.join(f'<th scope="col"{num(index)}>{_text(h)}</th>' for index, h in enumerate(headers))
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(
                f'<th scope="row">{c}</th>' if row_headers and index == 0 else f'<td{num(index)}>{c}</td>'
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


def _stand_in_items(data, rows):
    """'Question 48, A vs B, both orders' for each question and pair a stand-in model judged."""
    numbers, agents = _question_numbers(data), _system_order(data)
    cells = defaultdict(list)
    for row in rows:
        cells[numbers[row['question_id']], tuple(sorted(row['pair'], key=agents.index))].append(row['order'])
    items = []
    for (number, pair), orders in sorted(cells.items(), key=lambda c: (c[0][0], [agents.index(a) for a in c[0][1]])):
        first, second = pair if len(orders) > 1 else orders[0]
        items.append(f'Question {number}, {_label(first)} vs {_label(second)}, '
                     + ('both orders' if len(orders) > 1 else f'{_label(first)} shown first'))
    return items


def _asked(rows):
    tries = sorted({row['refusals'] for row in rows})
    whom = 'it' if len(rows) == 1 else 'each of them'
    return (f'{whom} on its only try' if tries == [1] else f'{whom} on all {tries[0]:,} tries'
            if len(tries) == 1 else f'{whom} on every try, from {tries[0]:,} to {tries[-1]:,} tries')


def _refusal_labels(rows):
    refusals, labeled = sum(r['refusals'] for r in rows), sum(r['labeled'] for r in rows)
    categories = sorted({c for r in rows for c in r['categories']})
    if not categories:
        return ''
    whom = (('the refusal' if refusals == 1 else 'every refusal') if labeled == refusals
            else f'{labeled:,} of the {refusals:,} refusals')
    return f'the API labeled {whom} ' + _join(f'“{c}”' for c in categories) + _category_gloss(categories)


def _refused_shown(data, rows):
    """Which judgments the stand-in rows are: one system shown first against several, or each item."""
    agents, numbers = _system_order(data), _question_numbers(data)
    firsts = {row['order'][0] for row in rows}
    if len(rows) > 1 and len(firsts) == 1 and len({numbers[row['question_id']] for row in rows}) == 1:
        first = next(iter(firsts))
        against = sorted({row['order'][1] for row in rows}, key=agents.index)
        if len(against) == len(rows):
            return f'all showed {_label(first)} first, against {_join(_label(a) for a in against)}'
    return 'are ' + '; '.join(_stand_in_items(data, rows))


def _stand_in_summary(data, entries=None):
    """One note on every judgment a stand-in model made: the headline rubric's by default, or the given entries'."""
    entries = entries or [{'version': _main_rubric(data), 'stand_ins': data.get('stand_ins', [])}]
    main, numbers = entries[0]['version'], _question_numbers(data)
    groups = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        for row in entry['stand_ins']:
            groups[row['judge'], row['model']][entry['version']].append(row)
    sentences = []
    for (judge, model), by_version in sorted(groups.items(),
                                            key=lambda g: (data['ranking']['judges'].index(g[0][0]), g[0][1])):
        versions = [e['version'] for e in entries if by_version.get(e['version'])]
        rows = [r for v in versions for r in by_version[v]]
        name, substitute, n = _judge_label(data, judge), JUDGE_LABELS.get(model, model), len(rows)
        questions = sorted({numbers[r['question_id']] for r in rows})
        where = ('Question ' if len(questions) == 1 else 'Questions ') + _join(str(q) for q in questions)
        lead = f'{name} refused {_count(n, "judgment")} on {where}'
        if len(versions) == 1 and len(entries) > 1:
            lead += f' under NUS {versions[0]}'
        elif len(versions) > 1:
            lead += ': ' + _join(f'{len(by_version[v]):,} under NUS {v}' for v in versions)
        sentences.append(lead + '.')
        labels = _refusal_labels(rows)
        sentences.append(f'It refused {_asked(rows)}' + (f', and {labels}' if labels else '') + '.')
        sentences.append(f'{substitute} made {"that judgment" if n == 1 else f"those {n:,} judgments"} instead, '
                         f'and {"it counts" if n == 1 else "they count"} toward {name}’s results.')
        shown = by_version.get(main)
        if shown:
            one = len(shown) == 1
            subject = 'the refused judgment' if one else f'the {len(shown):,} refused judgments'
            prefix = f'Under NUS {main}, {subject}' if len(entries) > 1 else subject[0].upper() + subject[1:]
            detail = _refused_shown(data, shown)
            if one:
                detail = 'is ' + _stand_in_items(data, shown)[0]
            sentences.append(f'{prefix} {detail}.')
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
                'whether it was processed or billed')
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
    return ('<p class="small" id="unranked">' + ' '.join(parts)
            + _text(f' A question is ranked only when all {counts["per_question"]} judgments exist, '
                    'so every system is compared on the same questions.') + '</p>')


def _ranking(data):
    report, counts = data['ranking'], _counts(data)
    heading = 'AUT-inspired preference ranking' if report.get('rubric_kind') == AUT_KIND else 'Creativity ranking'
    samples = report.get('bootstrap', {}).get('samples', 1000)
    parts = [f'<section id="overall"><h2>{heading}</h2>',
             f'<p>Each system’s win rate is its wins divided by its {counts["per_system"]:,} judgments ({counts["ranked"]} questions, '
             f'{_plural(counts["systems"] - 1, "opponent")}, {_plural(counts["judges"], "judge")}, both answer orders). '
             'Every judgment counts equally.</p>'
             f'<p>The dark bracket above each bar is the 95% interval. We redrew the {counts["ranked"]} '
             f'{"" if counts["ranked"] == 50 else "ranked "}questions at random '
             f'{samples:,} times, allowing repeats, and recomputed each win rate, keeping each question’s '
             f'{counts["per_question"]:,} judgments together. The bracket covers the middle 95% of those results. '
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
    parts.append('<p class="small">Bars run from 0% to 100%. The dashed line marks 50%, where a system wins as often '
                 'as it loses.</p>' + _unranked_note(data))
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
            _text(f'{_label(a)} vs {_label(b)}'), _points(sign * c['difference']),
            f'{_points(low)} to {_points(high)}', _pct(higher), _pct(equal)]))
    parts.append(_table(['Comparison (first vs second)', 'Difference in win rate (percentage points)', '95% interval',
                         'Redraws where the first system led', 'Redraws with equal win rates'],
                        [row for *_, row in sorted(rows)],
                        'Differences in win rate between systems', row_headers=True, num_from=1))
    opponents = ('every opponent, not only the direct matchup' if counts['systems'] > 2 else 'the single matchup')
    parts.append(f'<p class="small">A difference compares overall win rates, which count {opponents}. '
                 'An interval that includes zero means the two systems cannot be separated on these questions. '
                 'Each redraw of the questions scores every system on the same questions. '
                 f'The last two columns say how often, across the {samples:,} redraws, the first system was ahead '
                 'or the two were tied. They are not the probability that one system is better.</p>'
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
            cells.append('<span class="diagonal"><span class="visually-hidden">Same system; no comparison</span></span>' if a == b
                         else f'<span class="heat-cell" style="--shade:{.06 + value * .28:.3f}">{_pct(value)}</span>')
        rows.append(cells)
    parts = ['<section id="matchups"><h2>Head-to-head</h2>'
             f'<p>How often the row system won against the column system, out of {counts["per_matchup"]:,} judgments '
             'for each pair of systems.</p>',
             _table(['Win rate of row system against column system', *[_label(a) for a in agents]], rows,
                    'Overall head-to-head preferences', 'class="matrix"', row_headers=True)]
    overall = {row['agent']: row for row in report['ranking']}
    upsets = []
    for a, b in combinations(agents, 2):
        if overall[b]['rank'] > overall[a]['rank'] and report['pairwise']['overall'][b][a] > .5:
            gap = _tenths(overall[a]['preference_rate']) - _tenths(overall[b]['preference_rate'])
            upsets.append(f'{_label(b)} wins {_pct(report["pairwise"]["overall"][b][a])} of its judgments against '
                          f'{_label(a)}, yet its overall win rate is {gap} {"point" if gap == 1 else "points"} lower, '
                          'because the overall rate also counts judgments against every other system.')
    if upsets:
        parts.append('<p>' + _text(' '.join(upsets)) + '</p>')
    cycles = report['diagnostics']['cycles']
    if cycles:
        parts.append('<p class="small">Preference cycle: '
                     + '; '.join(' → '.join(_text(_label(a)) for a in cycle) for cycle in cycles) + '.</p>')
    parts.append('</section>')
    return ''.join(parts)

V3_CONFIGURATIONS = frozenset({
    'caesar-20e432af12a9', 'openai-974f65684704', 'anthropic-7e2861dc91b0',
    'gpt_researcher-0837d201f5e0', 'gemini-d2cebf130803'})

PROFILES = {
    'caesar': {
        'summary': (
            'Caesar treats each prompt as a systems-design and stress-testing problem. Before proposing an invention, '
            'it defines what counts as a valid solution, rules out shortcuts, and works out the mechanics, equations, '
            'and failure modes in detail. That thoroughness puts it far ahead on counterfactuals (85.0%) and '
            'cross-domain designs (82.5%), though its answers often read like long compliance manuals and sometimes '
            'shrink a bold prompt into a small, cautious case so the proof holds.'),
        'strengths': [
            ('Solves the hardest physical constraint first',
             'Caesar spots where standard designs cheat and builds around the bottleneck. On '
             '<a href="#answer-4-caesar">Question 4</a> (three-piece wooden latch), it notes that an ordinary '
             'sliding dovetail can slide backward out of its track unless a fourth piece blocks it, so it carves '
             'the weighted catch captive inside a single cabinet post. On <a href="#answer-23-caesar">Question 23</a> '
             '(babysitting network), it catches a hidden boundary flaw: calling in a backup parent can add that '
             'parent’s own child to the room, breaking the three-child limit unless all five children are '
             'pre-assigned across the two active rooms.'),
            ('Writes out formal mechanisms and calculates where they break',
             'Rather than asserting that an invention works, Caesar models its operating limits. On '
             '<a href="#answer-11-caesar">Question 11</a> (wood that regrows into trees), it models how cutting a '
             '12.1 kg table quadruples exposed surface area and lets regrowth outrun the decomposition bay. On '
             '<a href="#answer-13-caesar">Question 13</a> (letters that double in weight every two miles from the '
             'writer), it derives both the 22-mile co-author midpoint limit and the queueing threshold where delayed '
             'mail gains weight faster than clerks can clear it. On <a href="#answer-24-caesar">Question 24</a> '
             '(error-correcting treasure hunt), it prints a 25-vault Reed-Solomon codebook over GF(5) and proves that '
             'under a one-lie limit, two witnesses who contradict each other prove the single lie is spent and make '
             'the remaining stations trustworthy.'),
            ('Traces second-order institutional traps and perverse incentives',
             'On <a href="#answer-19-caesar">Question 19</a> (Eurasia without horses), it identifies a safe-frontier '
             'trap: fewer steppe raids tempt rulers to plow winter grazing valleys for taxable grain, starving their '
             'own draft cattle and army logistics years later. On <a href="#answer-37-caesar">Question 37</a> '
             '(pottery insurance), it proves that deducting a surviving pot’s sale value from a research payout '
             'rewards potters for smashing good work, so the research fee must stay fixed whether the pot cracks '
             'or survives.'),
        ],
        'weaknesses': [
            ('Heavy procedural bloat and policy-manual prose',
             'At 5,868 words on average, Caesar turns almost every creative task into a multi-ledger charter packed '
             'with administrative rules, appeals boards, and custom terminology. Clearing a cluttered hallway bench '
             'for 15 minutes on <a href="#answer-30-caesar">Question 30</a> requires a 10-part Small-Disturbance '
             'Permit; a silent riverbank wedding on <a href="#answer-7-caesar">Question 7</a> gets a seven-signal '
             'protocol table and legal notices that participation is not consent; a travel keepsake on '
             '<a href="#answer-45-caesar">Question 45</a> buries a small folded paper card under pages of '
             'governance rules.'),
            ('Narrows the scope or over-mechanizes to stay verifiable',
             'To keep every claim defensible, Caesar sometimes scales the task down to a minimal toy case or bolts '
             'on heavy machinery. On <a href="#answer-10-caesar">Question 10</a> (13th-century live eels to Vienna), '
             'it hauls just 0.5 kg of eels (four 50 g tasting portions) in 150 liters of water on a 780 kg wagon. On '
             '<a href="#answer-1-caesar">Question 1</a> (five-tone continuous script), its test language has only '
             'two consonants and two vowels. On <a href="#answer-50-caesar">Question 50</a> (domestic posture '
             'furniture), it turns a living-room leaning rest into a motorized screw-drive carriage that lowers into '
             'a chair-like seat.'),
            ('Thin integration of retrieved web sources',
             'Caesar relies mainly on its own mathematical and structural modeling; several reference lists include '
             'generic search portals or homepages rather than specific studies, and on historical counterfactuals '
             'such as <a href="#answer-18-caesar">Question 18</a> (compassless 15th-century Portugal) it strips away '
             'period detail in favor of abstract decision trees.'),
        ],
    },
    'openai': {
        'summary': (
            'OpenAI (Sol + web search) writes compact, well-structured proposals (1,903 words on average) that pair '
            'a clear geometric or mechanical design with targeted checks against published research. It leads on '
            'meta-creativity (74.2%), where it builds clean rule systems and ablation tests, and it regularly uses '
            'retrieved papers to expose and patch flaws in its own design. Its main weaknesses are repetitive '
            'disclaimers and a tendency to smooth unruly prompts into polite checklists or safe hybrids.'),
        'strengths': [
            ('Clean, buildable mechanisms and mathematical constructions',
             'OpenAI turns hard constraints into clear geometry or compact hardware. On '
             '<a href="#answer-29-openai">Question 29</a> (loom-based 12-team soccer schedule), it adapts a '
             'Partitioned Balanced Tournament Design so every team visits all six field-time slots once in Rounds '
             '1–6 and once in Rounds 6–11, and proves a maximum streak of two early or late kickoffs is optimal '
             'because strict alternation splits the league into two six-team halves that never meet. On '
             '<a href="#answer-41-openai">Question 41</a> (spectator sport), it scores reactive balance by the 2D '
             'polygon area of cleared impulses across eight directions. On <a href="#answer-49-openai">Question 49</a> '
             '(gait-driven garment), fastening the waist clasp winds a spring while a walking pendulum trips a '
             'three-step catch, so the rear hem stays raised when the wearer stops at a puddle.'),
            ('Uses retrieved papers to catch and fix flaws in its own proposal',
             'Rather than citing literature only as background, OpenAI uses it to audit its own mechanism. On '
             '<a href="#answer-1-openai">Question 1</a> (Turnweave, a closed-loop script whose lower edge returns as '
             'a 180°-rotated copy, with a runnable single-path SVG), it cites a Mandarin tone-learning study showing '
             'that mismatched visual contours hurt recall, notes that writers draw a rising tone downward on the '
             'inverted return stroke, and adds a masked teaching test. On <a href="#answer-8-openai">Question 8</a> '
             '(edible vial tag), it catches that a 2025 paper’s water-resistant zein adhesive required curing at '
             '80°C for two hours, which would ruin heat-sensitive drugs. On <a href="#answer-14-openai">Question 14</a> '
             '(two-week spring conception), it spots that the first national healthcare bottleneck is not winter '
             'delivery wards, but the five-week summer window for 18-to-20-week fetal-anomaly ultrasound scans.'),
            ('Pre-empts behavioral loopholes and designs controlled ablation tests',
             'On <a href="#answer-23-openai">Question 23</a> (babysitting network), it notices that if the third '
             'adult in a three-adult pool covers routine bathroom breaks, the network loses its cancellation backup '
             'during every break, so it separates relief from reserve with a fourth committed adult. On '
             '<a href="#answer-40-openai">Question 40</a> (redrawing a two-mile trail map), it prevents hikers from '
             'drawing barren maps to hoard observations for later turns by locking credit to the first map on which '
             'a feature appears.'),
        ],
        'weaknesses': [
            ('Repetitive scientific, legal, and safety disclaimers',
             'Nearly every answer pauses every few paragraphs to remind the reader that its creative proposal is not '
             'an empirically validated clinical trial, legal advice, or a certified safety product, or to warn '
             'teachers not to crowd real school hallways when demonstrating Braess’s paradox on '
             '<a href="#answer-34-openai">Question 34</a>.'),
            ('Sidesteps the hardest part of some open-ended or cross-domain prompts',
             'On <a href="#answer-42-openai">Question 42</a> (city garden where wind and rain play a recognizable '
             'tune), it offloads the melody to a mechanical wind-and-rain music box cylinder while leaving the '
             'plants as unpitched background rustle. On <a href="#answer-43-openai">Question 43</a> (manual trade '
             'for a town of 5,000), it invents a soft-robotics textile repairer and stipulates a near-future town '
             'where pneumatic garments are already everyday goods. On <a href="#answer-22-openai">Question 22</a> '
             '(canal-lock mediation) and <a href="#answer-36-openai">Question 36</a> (imaginary religion’s ritual), '
             'it domesticates physical or ritual premises into polite workshop checklists.'),
            ('Ergonomic costs in tidy geometric solutions',
             'On <a href="#answer-1-openai">Question 1</a>, writing every word twice (once left-to-right, then '
             'upside-down and right-to-left) doubles pen travel and demands ambigram-level handwriting control. On '
             '<a href="#answer-6-openai">Question 6</a> (coat to backpack), keeping all four pockets in a rigid '
             'uncreased front panel leaves 6.1 liters of protruding boxes strapped across the wearer’s chest in '
             'coat mode.'),
        ],
    },
    'anthropic': {
        'summary': (
            'Anthropic (Claude + web search) leads on open-ended synthesis (74.6%) and constrained synthesis '
            '(71.2%). Its signature move is to find an unexpected empirical fact, physical law, or historical '
            'practice, or the exact point where a requested analogy breaks, and turn that friction into a simple, '
            'workable rule. It writes direct prose (2,527 words on average) and checks its ideas with '
            'back-of-the-envelope math, though its essays sometimes bend a strict premise or leave loose joints in '
            'hand-worked hardware.'),
        'strengths': [
            ('Reframes the problem so the hardest constraint dissolves',
             'On <a href="#answer-1-anthropic">Question 1</a> (Vine), it uses the fact that a plane curve’s signed '
             'curvature is unchanged by rotation: every mark turns toward the pen’s local left ("sun") or right '
             '("soil") from a widening starter curl, so the script reads identically at any angle on the page, '
             'verified with a 22-line Python turtle script. On <a href="#answer-6-anthropic">Question 6</a> '
             '(Turncoat), it treats a buttoned coat as an already-formed torso cylinder (button the front, cinch '
             'the hem over a sit-flap floor, flip the hood over as a lid, and loop the sleeves as straps), keeping '
             'all seven pockets upright without inverting. On <a href="#answer-48-anthropic">Question 48</a> '
             '(forensic evidence), it flips Locard’s transfer principle from what a suspect deposits to the '
             'biological stopwatch started inside a living shrub when brushed (calcium spikes at 1–2 minutes, '
             'touch-gene expression at 10–30 minutes, callose plugs at 9 hours), using untouched branches of the '
             'same plant to cancel out weather.'),
            ('Finds where an analogy flips and grounds rules in empirical literature',
             'On <a href="#answer-23-anthropic">Question 23</a> (electrical babysitting network), it notes that '
             'electrical transfer switches use break-before-make, whereas childcare requires make-before-break '
             '(nobody releases a child until the incoming adult reads back the handoff), and cites fragile-care '
             'anxiety data to cap backups to a familiar six-adult pool. On <a href="#answer-25-anthropic">Question 25</a> '
             '(perfumery boutique hotel), it pairs hotel-memory and olfactory-adaptation studies to show that first '
             'impressions grow in weight over 30 days ("the top note turns into the fixative") while an always-on '
             'home diffuser desensitizes the nose inside two weeks, arguing for single-use sealed sachets instead. '
             'On <a href="#answer-28-anthropic">Question 28</a> (honeybee swarming bakery handover), it uses actual '
             'bee biology, where the old queen leaves with two-thirds of the workers while the daughter inherits the '
             'existing comb on the signal of a 3–5% quorum of veteran scouts, to have the founder depart to run a '
             'baking school while senior staff trigger the handover.'),
            ('Back-of-the-envelope math that reshapes the invention',
             'On <a href="#answer-46-anthropic">Question 46</a> (drinking fountain that builds a structure), it '
             'combines London fountain meter data (14 L/day average), sip-volume studies (~0.2 L runoff per drink), '
             'and water hardness (266 mg/L) to show that electrochemical deposition yields only 10–27 mg of '
             'limestone per drink (~one grain of rice), prompting it to grow annual fist-sized year-stones at quiet '
             'fountains and reserve steel bench frames for busy rail stations. On '
             '<a href="#answer-44-anthropic">Question 44</a> (eelgrass domestication), it checks a 3.5 t/ha press '
             'claim against measured seed weights (1.4–4.3 mg) to show it would require 2–7 times natural shoot '
             'density, scaling its Year 10 breeding target down to 1 t/ha.'),
        ],
        'weaknesses': [
            ('Bends strict prompt rules when physical reality pushes back',
             'On <a href="#answer-5-anthropic">Question 5</a> (soap bar where even wear changes rabbit to fish to '
             'tortoise), it cites pebble-abrasion theorems showing hand washing flattens thin protrusions first, '
             'then casts the three tiers from three different soap hardnesses and admits it breaks the even-wear '
             'premise on purpose. On <a href="#answer-15-anthropic">Question 15</a> (all terrestrial flora rely '
             'exclusively on wind or water), it includes a pattern where humans hand-pollinate crops as the '
             'planet’s first animal pollinators. On <a href="#answer-34-anthropic">Question 34</a> (contradictions '
             'between two standard textbooks), half of its examples pit a single textbook or food label against '
             'raw study data.'),
            ('Mechanical and cost weak spots in hand-worked designs',
             'On <a href="#answer-4-anthropic">Question 4</a> (The Heron Latch), the stationary frame piece sits in '
             'shelf-pin holes on two unglued 5 mm wooden pegs that a child reaching inside can pull sideways out of '
             'the cabinet wall. On <a href="#answer-39-anthropic">Question 39</a> (Drift building set), putting '
             'asthma-inhaler dose counters and click domes into every socket requires 2,400 micro-counters in a '
             '150-piece toy box. On <a href="#answer-29-anthropic">Question 29</a> (soccer schedule), its '
             'hand-checked slot assignment leaves a streak of three consecutive early or late games where OpenAI '
             'proves a maximum streak of two is achievable.'),
            ('Occasionally adapts a near-existing concept rather than inventing from scratch',
             'On <a href="#answer-41-anthropic">Question 41</a> (Drop), scoring first-minute heart-rate recovery '
             'after a 45-second air-bike sprint repackages a metric already used in FEI endurance horse racing and '
             'the Harvard Step Test into a head-to-head arena format; on <a href="#answer-45-anthropic">Question 45</a> '
             '(The Return Deck), its scheduled envelopes of observation cards sit close to existing prompt decks, '
             'differing mainly in being self-written from a trip’s surprise log.'),
        ],
    },
    'gpt_researcher': {
        'summary': (
            'Running GPT-6.1 Sol in every step with DuckDuckGo keyword search, GPT Researcher writes the shortest '
            'answers in the comparison (1,583 words on average). At its best, it produces crisp, playable '
            'prototypes and catches subtle conceptual traps. Because it shares its base model with OpenAI (Sol + '
            'web search) while retrieving fewer sources (a median of 9 URLs vs. OpenAI’s 29) and stopping earlier, '
            'it repeatedly lands on the exact same core idea and even the same title as OpenAI, but in a thinner, '
            'sketchier form.'),
        'strengths': [
            ('Sharp, playable prototypes when an experimental paradigm or simple geometry fits',
             'Its single outright question win is <a href="#answer-41-gpt_researcher">Question 41</a> (Ghostline, '
             '17 of 24 judgments won), which turns motor-adaptation force-channel trials into a spectator sport: '
             'athletes reach through a lateral force field for 90 seconds, then face hidden ghost reaches where '
             'the robot clamps the path straight to measure how accurately their muscles predict the absent force '
             'profile. On <a href="#answer-5-gpt_researcher">Question 5</a> (soap bar), it gives a clean 2D '
             'contour inversion where an eroding slab’s right-facing rabbit ears shorten into a left-facing fish’s '
             'forked tail while the rabbit’s tail becomes the fish’s snout and tortoise’s head. On '
             '<a href="#answer-24-gpt_researcher">Question 24</a> (treasure hunt), it builds a seven-witness '
             'Hamming-code board where two broken parity triples intersect directly at the lying witness without '
             'algebra. On <a href="#answer-32-gpt_researcher">Question 32</a> (quartet notation), hitting an '
             'instrument’s physical limit triggers a rule flip that swaps the changing and preserved sound '
             'qualities before propagating silence around the ring.'),
            ('Catches premise distinctions and states mathematical trade-offs plainly',
             'On <a href="#answer-15-gpt_researcher">Question 15</a> (wind or water pollination only), it notes '
             'that modern wheat mostly self-pollinates inside closed florets, so strict wind-only reproduction '
             'rules out closed selfing and tuber cloning and forces selection for extruded anthers and synchronized '
             'bloom. On <a href="#answer-13-gpt_researcher">Question 13</a> (doubling-weight letters), it writes '
             'out the logarithmic radius allowance R = l log2(Q / q0), showing right away that cutting paper weight '
             '1,000-fold buys only about 10 extra miles.'),
        ],
        'weaknesses': [
            ('Converges with OpenAI on the same ideas and titles, with half the depth',
             'Because both systems write with GPT-6.1 Sol, GPT Researcher repeatedly arrives at the same title and '
             'concept as OpenAI: Turnweave and the sample word ma-nu (<a href="#answer-1-gpt_researcher">Question 1</a>), '
             'Countersign (<a href="#answer-32-gpt_researcher">Question 32</a>), The Hinge Library '
             '(<a href="#answer-33-gpt_researcher">Question 33</a>), Kiln Commons '
             '(<a href="#answer-37-gpt_researcher">Question 37</a>), Elsewhere '
             '(<a href="#answer-39-gpt_researcher">Question 39</a>), and The Unfinished Two Miles '
             '(<a href="#answer-40-gpt_researcher">Question 40</a>). In each case it omits the runnable SVG, '
             'quantitative load checks, or real book titles that make OpenAI’s version work.'),
            ('Stops at a brief conceptual sketch on open-ended engineering tasks',
             'On prompts such as <a href="#answer-48-gpt_researcher">Question 48</a> (forensic exposure negatives), '
             '<a href="#answer-49-gpt_researcher">Question 49</a> (gait-driven reflective fan), and '
             '<a href="#answer-50-gpt_researcher">Question 50</a> (domestic leaning rail), its answers run 70 to '
             '100 lines, stating what a device should do and what a future pilot would test instead of working out '
             'forces, kinetics, or dimensions. On <a href="#answer-33-gpt_researcher">Question 33</a> (library '
             'shelving), it names no real books, offering only placeholders like "a bridge-engineering handbook" '
             'next to "a quilt-making manual."'),
            ('Flat workarounds and meta-apologies for its own search results',
             'On <a href="#answer-7-gpt_researcher">Question 7</a> (wordless riverbank wedding), it works around '
             'the ban on speech by mounting full English sentences on large reversible signboards; on '
             '<a href="#answer-39-gpt_researcher">Question 39</a> (physical building pieces that resist '
             'repetition), it puts a battery, microprocessor, and electrical contacts inside the blocks. It also '
             'breaks frame to apologize for what its search hits lacked, such as noting on '
             '<a href="#answer-34-gpt_researcher">Question 34</a> that "the supplied research does not establish a '
             'verified pair of standard textbooks making contradictory predictions."'),
        ],
    },
    'gemini': {
        'summary': (
            'Google Deep Research searches heavily (a median of 68 cited URLs per answer) and pulls in striking '
            'technical mechanisms from distant fields, but wins only 14 of 1,200 judgments (1.2%). Every answer is '
            'formatted as an un-tabulated academic essay (0 of 50 answers use a table or code block) that piles on '
            'buzzwords such as blockchain DAOs, CRISPR, generative AI, drones, and relativistic physics while '
            'violating explicit prompt rules, contradicting its own mechanics, or omitting the requested artifact.'),
        'strengths': [
            ('Surfaces unexpected technical mechanisms when anchored in biology or physics',
             'Half of its 14 wins come on <a href="#answer-15-gemini">Question 15</a> (no animal pollination, 8 of '
             '24 judgments won), where it replaces legume nitrogen fixation with actinorhizal alder alley cropping '
             'and Azolla paddies, pairs Persian badgir windcatcher towers with 40–60% porosity shelterbelts to '
             'create pollen-trapping eddies, and breeds cereals for stalk harmonic oscillation. It also surfaces '
             'vivid domain mechanisms on <a href="#answer-44-gemini">Question 44</a> (3 wins, identifying the '
             'phosphorus-toxicity paradox in the rare-earth-hyperaccumulating fern Dicranopteris linearis), '
             '<a href="#answer-1-gemini">Question 1</a> (writing words as an outward Archimedean spiral from a '
             'central knot so page orientation never matters), <a href="#answer-27-gemini">Question 27</a> (mapping '
             'the four Seidel optical lens aberrations onto cross-examination distortions), '
             '<a href="#answer-28-gemini">Question 28</a> (using honeybee dance decay, 350 Hz head-butt stop '
             'signals, and the audience effect for bakery succession), and <a href="#answer-31-gemini">Question 31</a> '
             '(using heat-sensitive TRPM5 taste ion channels so a chilled dish shifts from sour-salty at 5°C to '
             'sweet-umami as it warms to 37°C in the mouth).'),
        ],
        'weaknesses': [
            ('Writes academic literature surveys instead of building the requested artifact',
             'When asked for a concrete schedule, script, or plan, Google Deep Research often summarizes dozens of '
             'papers and skips the constructive work. On <a href="#answer-29-gemini">Question 29</a> (12-team '
             'soccer schedule), it cites perfect 1-factorizations, Skolem sequences, and Ant Colony Optimization '
             'but never lists the 66 matches or field assignments. On <a href="#answer-3-gemini">Question 3</a> '
             '(five-minute silent murder mystery play), it spends 80% of the answer lecturing on Grotowski, Lecoq, '
             'and proxemics before giving a five-paragraph plot summary where the killer mimes an invisible garrote '
             'in plain sight at minute three.'),
            ('Breaks explicit prompt constraints and basic physical reality',
             'On <a href="#answer-11-gemini">Question 11</a> (all wooden objects regrow into trees), it ignores '
             'that dead wood regrows, writing instead about grafting living saplings indoors and reserving pruners '
             '"for dead, dry wood." On <a href="#answer-2-gemini">Question 2</a> (teaching inflation with blocks, '
             'no spoken numbers, and no play money), it bans eight-year-olds from speaking or grunting at all while '
             'using unit blocks as fiat play currency. On <a href="#answer-13-gemini">Question 13</a> (letters '
             'doubling in weight with distance from the writer), instead of keeping letters near writers or sending '
             'copies, it hauls mail in 810-ton mining dump trucks and builds nuclear fusion reactors at post '
             'offices to vaporize 171,000-ton letters with inertial-confinement lasers. On '
             '<a href="#answer-46-gemini">Question 46</a> (drinking fountain), it claims a 68-milliwatt pipe '
             'piezoelectric harvester can electrolytically 3D-print solid limestone benches (which takes '
             'kilowatt-hours per kilogram). On <a href="#answer-50-gemini">Question 50</a> (The Procliner), it puts '
             'users face-down in a massage-chair forehead cradle with their gaze angled at the floor while claiming '
             'radial circles of Procliners force face-to-face conversation.'),
            ('Reflexive sci-fi and Web3 buzzword piling across everyday prompts',
             'Regardless of the setting, it bolts on Marshall Islands blockchain DAOs and Proof-of-Burn NFTs '
             '(<a href="#answer-37-gemini">Question 37</a>, pottery insurance), LiDAR drones, Ethereum smart '
             'contracts, and cryptographic gates (<a href="#answer-47-gemini">Question 47</a>, village orchard), '
             'DeFi keeper bots and federated dApps (<a href="#answer-23-gemini">Question 23</a>, five-family '
             'babysitting), semiconductor pogo-pin test kiosks running reinforcement learning '
             '(<a href="#answer-35-gemini">Question 35</a>, neighborhood lending shop), and Diffusion Transformers '
             'with high-voltage electrostatic clutches (<a href="#answer-49-gemini">Question 49</a>, gait-driven '
             'garment).'),
        ],
    },
}


def _profiles(data):
    """Summary of each research system's creative strengths and weaknesses from the v3 study answers."""
    configs = {a.get('configuration_id') for a in data.get('answers', [])}
    if configs != V3_CONFIGURATIONS or data.get('judge_failures'):
        return ''
    agents, counts = _system_order(data), _counts(data)
    lengths, _ = _answer_lengths(data)
    by_q = defaultdict(list)
    for j in data.get('judgments', []):
        by_q[j['question_id']].append(j)
    outright, shared = Counter(), Counter()
    for q in data.get('questions', []):
        if by_q[q['id']]:
            winners, _ = _question_winners(by_q[q['id']], agents)
            if len(winners) == 1:
                outright[winners[0]] += 1
            else:
                for a in winners:
                    shared[a] += 1
    ranked = {row['agent']: row for row in data['ranking']['ranking']}
    parts = [
        '<section id="profiles"><h2>Strengths and weaknesses</h2>',
        '<p>What a reading of all 250 answers shows about how each system approaches creative problems, where it '
        'works best, and where it falls short. The top three systems win in different ways: Caesar leads on '
        'counterfactuals (85.0%) and cross-domain designs (82.5%) by building and stress-testing formal mechanisms, '
        'Anthropic (Claude + web search) leads on open-ended (74.6%) and constrained synthesis (71.2%) by finding '
        'unexpected real-world parallels and checking its own numbers, and OpenAI (Sol + web search) leads on '
        'meta-creativity (74.2%) with compact rule systems and literature audits.</p>',
    ]
    for agent in agents:
        profile, row = PROFILES[agent], ranked[agent]
        wins = outright[agent]
        ties = shared[agent]
        q_note = (f'{wins} of {counts["ranked"]} {"question" if wins == 1 else "questions"} won outright'
                  + (f' ({ties} tied)' if ties else ''))
        items = {}
        for side in ('strengths', 'weaknesses'):
            items[side] = ''.join(f'<li><strong>{_text(title)}.</strong> {body}</li>'
                                  for title, body in profile[side])
        parts.append(
            f'<article class="profile" data-agent="{agent}"><h3>{_text(_label(agent))}</h3>'
            f'<p class="profile-meta">{_pct(row["preference_rate"])} win rate '
            f'({row["wins"]:,} of {counts["per_system"]:,} judgments won) · {q_note} · '
            f'{lengths[agent]:,.0f} words on average</p>'
            f'<p>{_text(profile["summary"])}</p>'
            '<div class="profile-columns">'
            f'<div><h4>Strengths</h4><ul class="profile-list">{items["strengths"]}</ul></div>'
            f'<div><h4>Weaknesses</h4><ul class="profile-list">{items["weaknesses"]}</ul></div>'
            '</div></article>')
    parts.append('</section>')
    return ''.join(parts)


def _judge_effort(settings):
    return settings.get('reasoning_effort') or settings.get('thinking_level') or settings.get('effort')


def _judge_settings(data):
    """A small table of each judge's saved settings; endpoints, keys and prices stay in the saved records."""
    entries = data.get('rubric_variants', {}).get('entries') or [{'stand_ins': data.get('stand_ins', [])}]
    used = defaultdict(set)
    for entry in entries:
        for row in entry['stand_ins']:
            used[row['judge']].add(row['model'])
    rows = []
    for judge in data['ranking']['judges']:
        settings = data['judges'][judge]
        substitute = settings.get('refusal_substitute')
        substitutes = ({substitute} if isinstance(substitute, str) and substitute
                       else (substitute or {}).get('model') and {substitute['model']} if isinstance(substitute, dict)
                       else used[judge])
        timeout = settings.get('timeout_seconds')
        tokens = settings.get('max_output_tokens')
        rows.append([_text(_judge_label(data, judge)),
                     f'<span class="nowrap">{_text(settings.get("model", "Not recorded"))}</span>',
                     _text(str(_judge_effort(settings) or 'Not recorded').capitalize()),
                     f'{tokens:,}' if isinstance(tokens, int) else 'Not recorded',
                     _duration(timeout) if _number(timeout) else 'Not recorded',
                     _text(_join(sorted(JUDGE_LABELS.get(m, m) for m in substitutes)) or 'None')])
    return _table(['Judge', 'Model', 'Reasoning effort', 'Max output tokens', 'Timeout', 'Stand-in model after refusals'],
                  rows, 'Saved judge settings', row_headers=True)


def _judges(data):
    report, counts = data['ranking'], _counts(data)
    agents = _system_order(data)
    who = ('The judge' if counts['judges'] == 1 else 'Both judges' if counts['judges'] == 2
           else f'All {_word(counts["judges"])} judges')
    efforts = {judge: _judge_effort(data['judges'][judge]) for judge in report['judges']}
    same = len(set(efforts.values())) == 1 and next(iter(efforts.values()))
    parts = [f'<section id="judges"><h2>Judges</h2>'
             f'<p>{who} saw every pair in both orders'
             + (', on every ranked question' if counts['failed'] else '') + ', with no web access'
             + (f', at {same} reasoning effort' if same else '') + '.</p>']
    labels, rates, order = {}, [], []
    for judge in report['judges']:
        by_agent = {r['agent']: r for r in report['per_judge'][judge]}
        diag = report['diagnostics']['by_judge'][judge]
        effort = efforts[judge]
        labels[judge] = _text(_judge_label(data, judge) + (f', {effort} effort' if effort and not same else ''))
        rates.append([labels[judge], *[_pct(by_agent[a]['preference_rate']) for a in agents]])
        order.append([labels[judge], _pct(diag['position_a_preference']['rate']),
                      _pct(diag['swapped_inconsistency']['rate'])])
    parts.append('<p>Win rate of each system under each judge:</p>'
                 + _table(['Judge', *[_label(a) for a in agents]], rates, 'Win rates by judge',
                          row_headers=True, num_from=1))
    summary = _stand_in_summary(data) if data.get('stand_ins') else ''
    if summary:
        parts.append('<p class="small">' + _text(summary) + '</p>')
    parts.append('<p>Answer-order checks:</p>'
                 + _table(['Judge', 'Share won by the answer shown first',
                           'Pairs whose winner changed when the order was swapped'], order,
                          'Answer-order checks by judge', row_headers=True, num_from=1))
    diag = report['diagnostics']['judge_disagreement']
    disagreement = ''
    if counts['judges'] > 1:
        judge_pairs = math.comb(counts['judges'], 2)
        ordered = diag['comparisons'] // judge_pairs
        disagreement = (f'When two judges saw the same pair in the same order, they picked different winners '
                        f'{_pct(diag["rate"])} of the time ({diag["disagreements"]:,} of {diag["comparisons"]:,} '
                        f'comparisons, from {_plural(judge_pairs, "pair")} of judges on each of {ordered:,} ordered '
                        'answer pairs). ')
    parts.append(f'<p>{disagreement}'
                 'A share of 50% for the answer shown first means no lean toward either position. '
                 'A winner can change when the order is swapped because of order effects, ordinary variation '
                 'between calls, or the rule that a judge who sees no real difference picks the answer shown first.</p>')
    overlap = ' '.join(filter(None, (_judge_overlap(data), _judge_authorship(data))))
    if overlap:
        parts.append('<p>' + _text(overlap) + '</p>')
    parts.append('<details><summary>Saved judge settings</summary>' + _judge_settings(data) + '</details>')
    parts.append('</section>')
    return ''.join(parts)


def _judge_models(data):
    report, agents, models = data['ranking'], _system_order(data), _main_models(data)
    for judge in report['judges']:
        model = data['judges'][judge].get('model')
        yield judge, [a for a in agents if model in models.get(a, ())]


def _judge_overlap(data):
    """Name judges whose model also writes answers for a system, from the saved settings only."""
    shared = [(_judge_label(data, judge), systems) for judge, systems in _judge_models(data) if systems]
    if not shared:
        return ''
    count = len(shared)
    return ((f'{_word(count).capitalize()} judge shares a model with systems it judges: ' if count == 1 else
             f'{_word(count).capitalize()} judges share a model with systems they judge: ')
            + '; '.join(f'{name} is also the main model of {_join(_label(a) for a in systems)}'
                        for name, systems in shared) + '.')


def _question_author_counts(data):
    authors = [q.get('generated_by') for q in data['questions']]
    if not authors or not all(isinstance(a, str) and a for a in authors):
        return []
    return Counter(authors).most_common()  # Ties keep the order the authors first appear in.


def _question_authors(data):
    """Say which models wrote the questions, when every question records its author."""
    counts = _question_author_counts(data)
    return ('The questions were written by AI models: '
            + _join(f'{n:,} by {JUDGE_LABELS.get(m, m)}' for m, n in counts) + '.') if counts else ''


def _judge_authorship(data):
    """Name judges whose model also wrote some of the questions."""
    written = dict(_question_author_counts(data))
    return ' '.join(f'{_judge_label(data, judge)} also wrote {written[model]:,} of the {len(data["questions"])} questions.'
                    for judge in data['ranking']['judges']
                    if (model := data['judges'][judge].get('model')) in written)


UNREPORTED_MODELS = {'gemini': 'Google'}  # Systems whose maker does not report the models they run.


def _judge_picks(data):
    """The system each judge gives its highest win rate, when some judge shares a model with a system."""
    report, agents = data['ranking'], _system_order(data)
    judges = list(_judge_models(data))
    if not any(systems for _, systems in judges):
        return ''
    unreported = [f'{UNREPORTED_MODELS[a]} does not report which models {_label(a)} runs'
                  for a in agents if a in UNREPORTED_MODELS]
    picked = []
    for judge, systems in sorted(judges, key=lambda item: not item[1]):  # Judges that share a model first.
        rates = {r['agent']: r['preference_rate'] for r in report['per_judge'][judge]}
        best = max(rates.values())
        picked.append((_judge_label(data, judge), systems, [a for a in agents if rates.get(a) == best], best))
    sharing = [p for p in picked if p[1]]
    sentences = []
    if all(set(top) <= set(systems) for _, systems, top, _ in sharing):
        gives = [f'{name}{f", the main model of {_join(_label(a) for a in systems)}," if len(systems) > 1 else ""} '
                 f'gives {_join(_label(a) for a in top)} {_pct(best)}{" each" if len(top) > 1 else ""}'
                 for name, systems, top, best in sharing]
        lead = ('Each judge that shares a model with one or more systems ranks one of those systems highest: '
                if len(sharing) > 1
                else 'The only judge that shares a model with any system ranks '
                     + ('that system' if len(sharing[0][1]) == 1 else 'one of those systems') + ' highest: ')
        sentences.append(lead + ', and '.join(gives) + '.')
    else:
        for name, systems, top, best in sharing:
            picks = (f'gives {_join(_label(a) for a in top)} the same win rate ({_pct(best)} each)' if len(top) > 1
                     else f'gives its highest win rate to {_label(top[0])}, {_pct(best)}')
            sentences.append(f'{name}, the main model of {_join(_label(a) for a in systems)}, {picks}.')
    why = f' ({"; ".join(unreported)})' if unreported else ''
    for name, _, top, best in (p for p in picked if not p[1]):
        picks = (f'gives {_join(_label(a) for a in top)} the same win rate, {_pct(best)}' if len(top) > 1
                 else f'gives its highest win rate to {_label(top[0])}, {_pct(best)}')
        sentences.append(f'{name}, which is not the main model of any system here{why}, {picks}.')
    return ' '.join(sentences)


NUS_DEFINITION = ('NUS stands for New (what the answer adds beyond known work), Useful (whether it works for the task), '
                  'and Surprising (how far it departs from the approach an expert would most likely take).')
RUBRIC_NOTES = {
    'v1': 'For New, the judge breaks each answer into parts and tries to name where each part already appears in '
          'prior work. How the parts combine counts toward Surprising instead.',
    'v2': 'For New, the judge asks what is original about the central contribution as a whole, including how its '
          'parts combine. For Surprising, the judge first names the approach a competent answer would most likely take.',
    'v3': 'Before reading the answers, the judge states the approach a skilled practitioner would most likely take. '
          'The judge weighs creative contribution rather than general answer quality, and credits what an answer adds '
          'to a cited idea, not the idea itself. It neither credits nor penalizes wording about an answer’s own '
          'research, such as “the supplied material”, and it treats a claim as a proposal when the answer itself says '
          'its evidence does not prove it.'}
# These packaged files share their closing rules and output format with the others, so their text differs
# from the files earlier studies used.
EARLIER_TEXT_DIFFERS = ('v1', 'v2')


# Links in the rendered text are relative to the folder the comparison pages are published in.
PAGE = 'Deep Research Comparison v3'
PROMPTS = Path(os.path.relpath(ROOT / 'crest/prompts', (ROOT / page_path(PAGE)).parent)).as_posix()


def _rubric_link(version):
    return f'<a href="{PROMPTS}/nus_pairwise_{version}.txt">NUS {version}</a>'


def _earlier_note(version, *, name_others=True):
    if version not in EARLIER_TEXT_DIFFERS:
        return ''
    if not name_others:
        return (f'The closing rules and output format in the NUS {version} file differ from those in the file '
                'earlier studies used.')
    others = sorted((p.stem.rsplit('_', 1)[-1] for p in (ROOT / 'crest/prompts').glob('nus_pairwise_v*.txt')),
                    key=lambda v: int(v.lstrip('v')))
    others = [v for v in others if v != version]
    return (f'The NUS {version} file shares its closing rules and output format with '
            f'{_join(f"NUS {v}" for v in others)}, so its wording differs from the file earlier studies used.')


def _main_rubric(data):
    """The packaged NUS version this report's judges used, or None for unpackaged or AUT rubrics."""
    if data['ranking'].get('rubric_kind') == AUT_KIND or 'judging_dir' not in data:
        return None
    path = data['judging_dir'] / 'rubric.txt'
    return _rubric_version(path.read_text(encoding='utf-8')) if path.is_file() else None


def _rank_changes(agents, views):
    """Systems whose rank differs across views, the rank each other system keeps, and ranks a view shares."""
    ranks = {a: {view[a]['rank'] for view in views} for a in agents}
    moving = [a for a in agents if len(ranks[a]) > 1]
    steady = {a: next(iter(ranks[a])) for a in agents if a not in moving}
    shared = {rank for view in views for rank, n in Counter(view[a]['rank'] for a in agents).items() if n > 1}
    return moving, steady, shared


def _rubric_dropdown(data, entry, main, common, every):
    counts, version, view = _counts(data), entry['version'], entry['common']
    name = f'NUS {version}'
    judges = 'the same judge' if counts['judges'] == 1 else f'the same {_word(counts["judges"])} judges'
    if entry['complete'] == common == counts['ranked'] == counts['questions']:
        coverage = (f'All {counts["judgments"]:,} judgments are present, {counts["per_question"]} for each of the '
                    f'{counts["questions"]} questions.')
    else:
        coverage = (f'These numbers use the {common} questions that have every judgment under {every}'
                    + (f', the same questions as the NUS {main} ranking at the top of the page.' if common == counts['ranked']
                       else f', so they differ slightly from the NUS {main} ranking at the top of the page, which uses '
                            f'{"all 50" if counts["ranked"] == 50 else counts["ranked"]}.'))
    parts = [f'<details class="rubric-results" id="rubric-{version}"><summary>{name} results</summary><div class="rubric-body">',
             f'<p>Here the same {counts["answers"]:,} answers are judged by {judges}, with the same settings, under the '
             f'{_rubric_link(version)} rubric. '
             + _text(' '.join(s for s in (RUBRIC_NOTES.get(version, ''), _earlier_note(version)) if s)) + '</p>',
             f'<p>{_text(coverage)}</p>', f'<p>{_text(_headline({"ranking": view}))}</p>']
    differences = _cluster_differences(view)
    if differences:
        parts.append(f'<p class="small">{_text(differences)}</p>')
    rows = [[_text(_label(row['agent'])), str(row['rank']), _pct(row['preference_rate']),
             f'<span class="nowrap">{_interval(row["ci95"])}</span>'] for row in view['ranking']]
    parts.append(_table(['System', 'Rank', 'Win rate', '95% interval'], rows, f'Ranking under {name}', row_headers=True, num_from=1))
    same, total = entry['agreement']
    if total:
        parts.append(f'<p>The judges pick the same winner as under NUS {main} in {_pct(same / total)} of judgments '
                     f'({same:,} of {total:,}). Each judgment is compared with the NUS {main} judgment of the same '
                     'question, answer order, and judge.</p>')
    parts.append(f'<p>Judging cost: {_money(entry["judging_total"], 2)}'
                 + (f'. {_text(entry["resent"])}' if entry.get('resent') else
                    f', plus {_plural(entry["unknown_costs"], "call")} of unknown cost.' if entry['unknown_costs'] else '.')
                 + '</p>')
    rows = []
    for judge in view['judges']:
        per = {r['agent']: r for r in view['per_judge'][judge]}
        rows.append([_text(_judge_label(data, judge)), *[_pct(per[a]['preference_rate']) for a in _system_order(data)]])
    parts.append('<p>Win rates by judge:</p>'
                 + _table(['Judge', *[_label(a) for a in _system_order(data)]], rows, f'Win rates by judge under {name}',
                          row_headers=True, num_from=1))
    if entry['stand_ins']:
        parts.append('<p class="small">' + _text(_stand_in_summary(data, [entry])) + '</p>')
    parts.append(_rubric_missing(data, [entry]))
    parts.append('</div></details>')
    return ''.join(parts)


def _rubrics(data):
    """Small collapsed dropdowns for the other rubrics, placed after everything else on the page."""
    comparison = data.get('rubric_variants')
    if not comparison:
        return ''
    entries, common = comparison['entries'], comparison['common_questions']
    main = entries[0]['version']
    every = 'both rubrics' if len(entries) == 2 else f'all {_word(len(entries))} rubrics'
    parts = ['<section id="other-rubrics" class="other-rubrics" aria-labelledby="other-rubrics-heading">'
             '<h2 id="other-rubrics-heading" class="visually-hidden">Results under other rubrics</h2>']
    parts += [_rubric_dropdown(data, entry, main, common, every) for entry in entries[1:]]
    agents = _system_order(data)
    views = [{row['agent']: row for row in e['common']['ranking']} for e in entries]
    rows = [[_text(_label(agent)), *[f'{_pct(view[agent]["preference_rate"])}<br><small>rank {view[agent]["rank"]}</small>'
                                     for view in views]] for agent in agents]
    parts.append(f'<details class="rubric-results" id="rubric-comparison"><summary>Win rates under {every}</summary>'
                 '<div class="rubric-body">' + _table(['System', f'NUS {main} (top of page)', *[f'NUS {e["version"]}' for e in entries[1:]]], rows,
                          f'Win rates under {every}', row_headers=True, num_from=1)
                 + _rubric_takeaway(agents, entries)
                 + '<p class="small">The 95% intervals in each dropdown come from resampling the questions, as for the '
                   'ranking at the top of the page. They do not say which rubric is right. Whether two systems can be '
                   'separated depends on the interval for their difference, which each rubric’s results list for '
                   'the systems that are close.</p>'
                   '</div></details>')
    parts.append('</section>')
    return ''.join(parts)


ORDINALS = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth')


def _ordinal(rank):
    if not isinstance(rank, int):
        return 'unranked'
    return ORDINALS[rank - 1] if 0 < rank <= len(ORDINALS) else f'number {rank}'


def _rubric_takeaway(agents, entries):
    """Say which places hold under every rubric and which change, and whether the paired intervals
    separate the systems that change places, from the computed ranks and contrasts only."""
    views = [{row['agent']: row for row in e['common']['ranking']} for e in entries]
    moving, steady, shared = _rank_changes(agents, views)
    sentences = []
    if moving:
        top = sorted(views[0][a]['rank'] for a in moving) == list(range(1, len(moving) + 1))
        who = f'The top {_word(len(moving))}' if top and len(moving) > 1 else _join(_label(a) for a in moving)
        pairs = [(entry, a, b) for entry in entries for a, b in combinations(moving, 2)]
        close = sum(_separable(entry['common'])(a, b) for entry, a, b in pairs)
        share = ('all' if close == len(pairs) else 'most' if 2 * close > len(pairs) else 'some' if close else 'none')
        verb = 'trade places' if len(moving) > 1 else 'changes place'
        sentences.append(f'{who} {verb} from one rubric to another' + (
            '.' if len(moving) == 1 else
            ', and the 95% intervals separate every pair of them.' if share == 'none' else
            f', and for {share} pairs of them the 95% interval for the difference includes zero, so the two cannot '
            'be separated.'))
        for entry, view in zip(entries, views):
            near, order = _separable(entry['common']), sorted(moving, key=lambda a: view[a]['rank'])
            behind = defaultdict(list)
            for a, b in combinations(order, 2):
                if not near(a, b):
                    behind[a].append(b)
            if not behind:
                continue
            clauses = []
            for a, bs in behind.items():
                text = f'{_label(a)} is ahead of {_join(_label(b) for b in bs)}'
                second = order[order.index(a) + 1] if order.index(a) + 1 < len(order) else None
                if second and second not in bs and near(a, second):
                    first, other = view[a], view[second]
                    gap = first['wins'] - other['wins']
                    of = f' of {first["choices"]:,}' if first['choices'] == other['choices'] else ''
                    score = f'{first["wins"]:,} to {other["wins"]:,}{of}'
                    text += (f', and it ties {_label(second)}, {score}' if not gap else
                             f', and its {gap:,}-judgment lead over {_label(second)}, {score}, is too small to '
                             'separate them')
                clauses.append(text)
            sentences.append(f'Under NUS {entry["version"]}, {_join(clauses)}.')
    if steady:
        groups = defaultdict(list)
        for agent, rank in steady.items():
            groups[rank].append(agent)
        held = [f'{_join(_label(a) for a in group)} tie for {_ordinal(rank)}' if len(group) > 1
                else f'{_label(group[0])} is {_ordinal(rank)} or tied for {_ordinal(rank)}' if rank in shared
                else f'{_label(group[0])} stays {_ordinal(rank)}' for rank, group in sorted(groups.items())]
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
                     'Such a call is sent again at most once, because the first request may have been billed.')
    return '<p class="small">' + _text(' '.join(notes)) + '</p>'


IN_ANSWER_BASES = {'same_reservation_in_answer', 'nearest_reservation_in_answer', 'same_model_mean_in_answer',
                   'same_kind_turns_in_round', 'same_kind_turns_in_answer', 'any_turn_in_answer'}


def _an(label):
    return ('an ' if label[:1].lower() in 'aeiou' else 'a ') + label


def _imputed_sentence(generation, agents):
    """One plain note on answer calls that never reported a cost and how the means count them."""
    shown = [a for a in agents if generation[a]['imputed_calls'] and not _number(generation[a]['audited_known_cost_usd'])]
    if not shown:
        return ''
    calls = sum(generation[a]['imputed_calls'] for a in shown)
    records = [r for a in shown for r in generation[a]['imputed_records']]
    added = _money(math.fsum(generation[a]['imputed_cost_usd'] for a in shown))
    number = '{:,}'.format  # Counts of calls and answers in cost prose are digits.
    unfinished = any(c.get('source') == 'in_flight' for r in records for c in r['calls'])
    how = 'failed or never finished' if unfinished else 'failed with a server or network error'
    where = ('similar calls in the same answer' if all(c['basis'] in IN_ANSWER_BASES for r in records for c in r['calls'])
             else 'similar calls by the same system')

    def answers(agent):
        n = generation[agent]['imputed_answers']
        return _an(_label(agent)) + ' answer' if n == 1 else f'{number(n)} {_label(agent)} answers'
    if calls == 1:
        return (f'1 call in {answers(shown[0])} {how} and never reported a cost. '
                f'We count it at the average cost of {where}, which adds {added}.')
    items = [f'{number(generation[a]["imputed_calls"])}{" call" if generation[a]["imputed_calls"] == 1 else " calls"}'
             f' in {answers(a)}' if i == 0 else f'{number(generation[a]["imputed_calls"])} in {answers(a)}'
             for i, a in enumerate(shown)]
    return (f'Some calls {how} and never reported a cost: {_join(items)}. '
            f'We count each at the average cost of {where}, which adds {added} in total.')


def _time_range(low, high):
    """'99.2–202.6 min' when both ends share a unit, else each end with its own."""
    first, last = _duration(low), _duration(high)
    if first == last:
        return first
    unit = first.rsplit(' ', 1)[-1]
    return (f'{first.rsplit(" ", 1)[0]}–{last}' if unit == last.rsplit(' ', 1)[-1] and unit in ('min', 's')
            else f'{first}–{last}')


def _answer_amounts(data):
    """Per answer: the known cost and the known cost plus the imputed cost of calls that never reported one."""
    for row in data['answers']:
        record = data['audit_records'].get((row['question_id'], row['agent']), {})
        known = record.get('known_usd')
        if _number(known):
            yield row, known, known
            continue
        known = cost_for_row(row).get('cumulative_known_estimate_usd')
        extra = (data['cost_imputation']['answers'].get(row['key']) or {}).get('imputed_usd', 0)
        yield row, known, known + extra if _number(known) else None


def _reused_sentence(data):
    reused, total = sum(bool(a.get('cache_hit')) for a in data['answers']), len(data['answers'])
    if not reused:
        return ''
    if reused == total:
        return (f'All {total:,} answers were reused from earlier runs, so each time is that of the job that first '
                'wrote the answer.')
    return (f'Of the {total:,} answers, {reused:,} {"was" if reused == 1 else "were"} reused from earlier runs, so '
            f'{"its time is" if reused == 1 else "their times are"} that of the job that first wrote the answer.')


def _resources(data):
    generation, judging = data['resources']['generation'], data['resources']['judging']
    agents, judges, counts = _system_order(data), data['ranking']['judges'], _counts(data)
    # Means, totals and the target count all use the same amounts: the audit when it covers a
    # system, otherwise the known estimate plus the imputed cost of calls that never reported one.
    totals = {a: (generation[a]['audited_known_cost_usd']
                  if _number(generation[a]['audited_known_cost_usd'])
                  else generation[a]['estimated_cost_usd']) for a in agents}
    audited = bool(data['audit_records'])
    google = generation.get('gemini')
    lengths, length_label = _answer_lengths(data)
    exact_lengths = 'sources list excluded' not in length_label
    parts = ['<section id="resources"><h2>Cost and time</h2>'
             + ('<p>Costs are estimates, not invoices. They use the final audit when it covers every answer for a '
                'system, and the original records otherwise. They include earlier failed attempts when those were recorded.</p>'
                if audited else
                '<p>Costs are estimates from each answer’s saved records, not invoices. They include earlier failed '
                'attempts when those were recorded.</p>')]
    averages, incomplete = [], False
    for agent in agents:
        r = generation[agent]
        mean = totals[agent] / r['answers'] if _number(totals[agent]) and r['answers'] else None
        missing = r['unimputed_missing_answers']
        partial = 0 if _number(generation[agent]['audited_known_cost_usd']) else (
            r['missing_cost_answers'] if missing is None else missing)
        incomplete = incomplete or bool(partial)
        averages.append([_text(_label(agent)), _money(mean)
                         + (f'<br><small>{partial} of {r["answers"]} estimates incomplete</small>' if partial else '')
                         + ('<br><small>assumed prices</small>' if agent in UNREPORTED_MODELS else ''),
                         _duration(r['mean_duration_seconds'])
                         + (f'<br><small>{r["duration_count"]} of {r["answers"]} answers timed</small>'
                            if r['duration_count'] != r['answers'] else '')]
                        + ([_duration(r['mean_lifetime_duration_seconds'])
                            + f'<br><small>{r["lifetime_duration_count"]} of {r["answers"]} answers timed</small>'] if audited else [])
                        + [f'{lengths[agent]:,.0f}' if agent in lengths else 'Unavailable'])
    parts.append(_table(['System', 'Mean estimated cost', 'Mean job time']
                        + (['Mean time including earlier attempts'] if audited else []) + [length_label],
                        averages, 'Mean cost, time, and length per answer', row_headers=True, num_from=1))
    untimed = any(generation[a]['duration_count'] != generation[a]['answers'] for a in agents) or (audited and any(
        generation[a]['lifetime_duration_count'] != generation[a]['answers'] for a in agents))
    imputed = _imputed_sentence(generation, agents)
    reused = _reused_sentence(data)
    parts.append(('<p class="small">'
                 + (_text(imputed) + ' ' if imputed else '')
                 + ('An incomplete estimate is missing the cost of some calls, so the mean is a lower bound. ' if incomplete else '')
                 + ('Google does not report its billing, so its estimate assumes Gemini 3.1 Pro rates for long inputs, '
                    'counts the text its tools send and receive as extra input, and charges every search at full price. '
                    if google else '')
                 + ('' if imputed and not incomplete else 'Charges that were never reported are left out. ')
                 + 'Job time runs from the start of the job that produced '
                 'the answer to its end, including waiting in queues and retries. '
                 + (_text(reused) + ' ' if reused else '')
                 + ('Time including earlier attempts adds failed or interrupted attempts and leaves out known gaps between them. ' if audited else '')
                 + ('Each time average uses only answers with complete timing. ' if untimed else '')
                 + (('Length counts the words in the copy of each answer the judges saw, including citation labels and '
                     'reference lists but not lists of uncited sources.' if exact_lengths else
                     'Length counts the words in each saved answer without its list of uncited sources.')
                    if lengths else '')).rstrip() + '</p>')
    exceeded, imputed_over, targets, soft, soft_over, reserve = Counter(), Counter(), set(), {}, Counter(), {}
    for row, known, amount in _answer_amounts(data):
        agent = row['agent']
        config = data['configurations'].get(row.get('configuration_id'), {})
        settings = config.get('settings') or data['manifest'].get('config', {}).get('research', {}).get(agent, {})
        target = settings.get('budget_usd')
        if _number(target) and target > 0:
            targets.add(target)
        if _number(amount) and _number(target) and target > 0 and amount > target:
            exceeded[agent] += 1
            imputed_over[agent] += not (_number(known) and known > target)
        aim = settings.get('budget_target_usd')
        if _number(aim) and _number(target) and 0 < aim < target:
            soft[agent] = aim
            soft_over[agent] += 1 if _number(amount) and amount > aim else 0
            if _number(settings.get('synthesis_reserve_usd')) and 0 < settings['synthesis_reserve_usd'] < aim:
                reserve[agent] = settings['synthesis_reserve_usd']
    if exceeded:
        items = [f'{exceeded[a]:,} {_text(_label(a))} answer{"s" if exceeded[a] != 1 else ""}'
                 + (' (' + ('' if exceeded[a] == 1 else 'all of them ' if imputed_over[a] == exceeded[a]
                           else f'{imputed_over[a]:,} of them ')
                    + 'only after adding the calls that never reported a cost)' if imputed_over[a] else '')
                 for a in agents if exceeded[a]]
        under = [a for a in agents if not exceeded[a]]
        one = len(targets) == 1
        target = f'the {_money(next(iter(targets)))} per-answer target' if one else 'its per-answer target'
        parts.append(f'<p class="small">Estimated cost was above {target} for ' + _join(items) + '. '
                     + (_text(_join(_label(a) for a in under)) + ' had no answer over it. ' if under else '')
                     + (f'The {_money(next(iter(targets)))} target is a goal' if one else 'Each target is a goal')
                     + ', and no system is stopped when it goes over.</p>')
    if soft:
        parts.append('<p class="small">' + ' '.join(
            f'{_text(_label(a))}’s own settings use a stricter {_money(soft[a])} target, and '
            + (f'{soft_over[a]:,} of its answers went over it.' if soft_over[a]
               else 'none of its answers went over it.')
            + (f' It starts no new research round once its spending reaches {_money(soft[a] - reserve[a])}, which '
               f'leaves {_money(reserve[a])} of that target for writing the final answer.' if a in reserve else '')
            for a in agents if a in soft) + '</p>')
    parts.append('<details class="resource-details"><summary>Cost totals and timing</summary>')
    if audited:
        parts.append('<p class="small">The original records are kept even when the final audit gives a corrected total.</p>')
    parts.append(_table(['System', 'Total cost of writing the answers'], [
        [_text(_label(a)), _money(totals[a])] for a in agents], 'Generation cost totals', row_headers=True, num_from=1))
    stand_ins = Counter((r['judge'], r['model']) for r in data.get('stand_ins', []))
    parts.append('<p class="small">Judging cost '
                 + _join(_money(judging[j]['estimated_cost_usd']) + ' for ' + _text(_judge_label(data, j)) + ''.join(
                     f' (including the {_count(n, "judgment")} {_text(JUDGE_LABELS.get(model, model))} made)'
                     for (judge, model), n in sorted(stand_ins.items()) if judge == j) for j in judges) + '.</p>')
    scored = math.fsum(judging[j]['estimated_cost_usd'] or 0 for j in judges)
    subject = (f'{counts["saved"]:,} saved judgments and {_count(counts["failed"], "failed judgment")}'
               if counts['failed'] else f'{counts["judgments"]:,} judgments')
    replaced = bool(data.get('prior_judgments'))
    parts.append(f'<p><strong>The {subject} cost {_money(scored)} in total, including retried calls.</strong>'
                 + (' Earlier judging that this round replaced is not included.' if replaced else ''))
    resent = _resent_sentence(_resent_tries(data))
    if resent:
        parts.append(' ' + resent)
    if counts['failed']:
        failed = data['resources']['failed_judging']
        known, unknown = failed['cumulative_known_estimate_usd'], failed['unknown_count']
        if not unknown:
            whose = 'The failed judgment’s attempts' if counts['failed'] == 1 else 'The failed judgments’ attempts'
            parts.append(f' {whose} cost {_money(known)} and are included in the judging total.')
        elif unknown == counts['failed'] and not known:
            parts.append(' The failed call has no known cost, so it is not in the judging total.' if unknown == 1 else
                         f' The {unknown:,} failed calls have no known cost, so they are not in the judging total.')
        else:
            parts.append(f' Failed calls with a known cost add {_money(known)}, included in the judging total. '
                         f'{_count(unknown, "failed call")} {"has" if unknown == 1 else "have"} no known cost and '
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
                     _time_range(r['min_duration_seconds'], r['max_duration_seconds'])]
                    + ([f'{r["duration_count"]} of {r["answers"]}'] if untimed else [])
                    + ([_duration(r['median_lifetime_duration_seconds'])] if audited else [])
                    + ([f'{r["lifetime_duration_count"]} of {r["answers"]}'] if audited and untimed else []))
    parts.append(_table(['System', 'Median job time', 'Shortest to longest job time'] + (['Answers timed'] if untimed else [])
                        + (['Median time including earlier attempts'] if audited else [])
                        + (['Answers with complete timing'] if audited and untimed else []),
                        rows, 'Saved answer elapsed times', row_headers=True, num_from=1))
    differs = any(_number(generation[a]['audited_known_cost_usd'])
                  and (not _number(generation[a]['known_cost_usd']) or not math.isclose(
                      generation[a]['audited_known_cost_usd'], generation[a]['known_cost_usd'])) for a in agents)
    if differs:
        parts.append(_table(['System', 'Estimate in the answer records', 'Audited estimate, all attempts'], [
            [_text(_label(a)), _money(generation[a]['known_cost_usd']),
             _money(generation[a]['audited_known_cost_usd'])] for a in agents],
            'Audited lifetime generation estimates', row_headers=True, num_from=1))
    parts.append('</details></section>')
    return ''.join(parts)


def _model_name(model):
    return JUDGE_LABELS.get(model, model) if isinstance(model, str) and model else '(not recorded)'


def _reasoning_effort(agent, settings):
    """The reasoning effort each system's saved research settings give, in plain words."""
    if agent == 'gemini':
        return 'Not reported (Google manages it)'
    main = settings.get('effort' if agent == 'anthropic' else 'reasoning_effort')
    if not main:
        return 'Not recorded'
    parts = [str(main).capitalize() + (' (main model)' if agent == 'caesar' else '')]
    if agent == 'caesar':
        final, explore, kb = (settings.get(k) for k in (
            'synthesis_reasoning_effort', 'exploration_reasoning_effort', 'kb_reasoning_effort'))
        if final:
            parts.append(f'{final} (final write-up)')
        if explore and explore == kb:
            parts.append(f'{explore} (exploration and knowledge base)')
        else:
            parts += [f'{value} ({step})' for value, step in ((explore, 'exploration'), (kb, 'knowledge base')) if value]
    return _join(parts) if len(parts) > 1 else parts[0]


def _models(data):
    research = data['manifest'].get('config', {}).get('research', {})
    agents = _system_order(data)
    rows = []
    for agent in agents:
        settings = research.get(agent) or {}
        models = sorted({str(a['result'].get('model', 'Unavailable')) for a in data['answers'] if a['agent'] == agent})
        if agent in UNREPORTED_MODELS:
            detail = (f'Google’s managed agent {settings.get("agent", "(not recorded)")}. Google chooses the models it '
                      'runs and does not report them.')
        elif agent == 'openai':
            detail = (f'{_model_name(settings.get("model") or (models[0] if len(models) == 1 else None))} '
                      'with OpenAI’s built-in web search.')
        elif agent == 'anthropic':
            model = str(settings.get('model', ''))
            model = ('Sonnet' if model.startswith('claude-sonnet')
                     else JUDGE_LABELS.get(model, model or 'Claude'))
            tools = ('web search and page reading tools we provide' if settings.get('tool_mode') == 'client'
                     else 'Anthropic’s built-in web search')
            detail = f'{model} with {tools}.'
        elif agent == 'gpt_researcher':
            detail = (f'GPT Researcher in deep research mode, with {_model_name(settings.get("model"))} for every step. '
                      'It searches the public web through DuckDuckGo and filters pages by keyword.')
        elif agent == 'caesar':
            main = _model_name(settings.get('model') or (models[0] if len(models) == 1 else None))
            explore, kb = _model_name(settings.get('exploration_model')), _model_name(settings.get('kb_model'))
            detail = ((f'Writes with {main} and uses {explore} to explore the web and build its knowledge base. '
                       if explore == kb else
                       f'Writes with {main}, explores the web with {explore}, '
                       f'and builds its knowledge base with {kb}. ')
                      + 'Each answer’s saved settings list every model it used.')
        else:
            detail = 'See the saved settings with each answer.'
        # Google's saved model is only its pricing model.
        shown = 'Not reported' if agent in UNREPORTED_MODELS else ', '.join(_model_name(m) for m in models)
        rows.append([_text(_label(agent)), ', '.join(f'<span class="nowrap">{_text(m)}</span>' for m in shown.split(', ')),
                     _text(_reasoning_effort(agent, settings)), _text(detail)])
    return ('<details id="systems" open><summary>Models and research workflows</summary>'
            + _table(['System', 'Main model', 'Reasoning effort', 'How it researches'], rows, 'Frozen research systems',
                     wide=True, row_headers=True)
            + ('<p class="small">Google introduced its April 2026 Deep Research agents as built with Gemini 3.1 Pro '
               '(<a href="https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/">Google announcement</a>). '
               'That announcement does not say which models this run used.</p>' if 'gemini' in agents else '')
            + ('<p class="small">OpenAI’s o3-deep-research and o4-mini-deep-research API models shut down July 23, 2026 '
               '(<a href="https://developers.openai.com/api/docs/deprecations">deprecation notice</a>; '
               '<a href="https://developers.openai.com/api/docs/guides/deep-research">deep research guide</a>). '
               f'The {_label("openai")} results come from '
               f'{_model_name(research.get("openai", {}).get("model"))} with web search, not from those models.</p>'
               if 'openai' in agents else '')
            + '</details>')


LOCAL_PATH = re.compile(r'(?:~|/(?:Users|home|opt|private|var|tmp|usr|Volumes|mnt))/|[A-Za-z]:[\\/]')
HOME_PATH = re.compile(r'(?<![\w.:/~-])/(?:Users|home)/[^/\s"]+')  # Not inside URLs or relative paths.


def _local_path(value):
    return isinstance(value, str) and bool(LOCAL_PATH.match(value))


def _without_local_paths(value, removed, key=None):
    """Settings as shown on the page: machine-specific absolute paths are left out; the saved records keep them.

    The name of every field that lost a path is appended to removed."""
    if isinstance(value, dict):
        removed.extend(k for k, v in value.items() if _local_path(v))
        return {k: _without_local_paths(v, removed, k) for k, v in value.items() if not _local_path(v)}
    if isinstance(value, list):
        if any(_local_path(v) for v in value):
            removed.append(key)
        return [_without_local_paths(v, removed, key) for v in value if not _local_path(v)]
    return HOME_PATH.sub('~', value) if isinstance(value, str) else value


GATEWAY_KEYS = ('api_base', 'api_key_env', 'api_url')


def _gateway_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in GATEWAY_KEYS:
                yield k
            yield from _gateway_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _gateway_keys(v)


def _without_gateway(value):
    """A record without the gateway address and key-variable fields; the saved records keep them."""
    if isinstance(value, dict):
        return {k: _without_gateway(v) for k, v in value.items() if k not in GATEWAY_KEYS}
    if isinstance(value, list):
        return [_without_gateway(v) for v in value]
    return value


def _answer_configuration(data, row):
    """Return (key, record) for the research settings an answer was run with."""
    identity = row.get('configuration_id')
    configuration = data['configurations'].get(identity) if identity else None
    if configuration is None:
        return f'legacy-{row["agent"]}', {'source': 'legacy run manifest; per-answer configuration was not recorded',
                                          'settings': data['manifest'].get('config', {}).get('research', {}).get(row['agent'])}
    return identity, configuration


def _settings_anchor(key):
    return 'settings-' + re.sub(r'[^A-Za-z0-9_-]', '-', str(key))


def _saved_settings(data):
    """Each distinct saved research configuration once; every answer links here instead of repeating it."""
    order = _system_order(data)
    groups = {}
    for row in sorted(data['answers'], key=lambda r: order.index(r['agent']) if r['agent'] in order else len(order)):
        key, configuration = _answer_configuration(data, row)
        groups.setdefault(key, [row['agent'], configuration, 0])[2] += 1
    per_agent = Counter(agent for agent, _, _ in groups.values())
    parts = []
    for key, (agent, configuration, count) in groups.items():
        removed = []
        shown = _without_local_paths(configuration, removed)
        removed = list(dict.fromkeys(k for k in removed if k))
        label = _text(_label(agent))
        gateway = list(dict.fromkeys(_gateway_keys(shown)))
        shown = _without_gateway(shown)
        left_out = _join(part for part in (
            'Local file paths' if removed else '', 'gateway connection fields' if gateway else '') if part)
        parts.append(f'<details class="configuration"><summary>Saved research settings: {label}'
                     + (f' <small>{_text(key)}</small>' if per_agent[agent] > 1 else '') + '</summary>'
                     f'<div class="configuration-body" id="{_settings_anchor(key)}">'
                     f'<p class="small">Used by {_count(count, "answer")}.'
                     + (f' {left_out[0].upper() + left_out[1:]} are left out: '
                        + _join(f'<code>{_text(k)}</code>' for k in removed + gateway) + '.' if left_out else '') + '</p>'
                     f'<pre tabindex="0" aria-label="Saved research settings for {label}">'
                     f'{_text(json.dumps(shown, ensure_ascii=False, indent=2))}</pre></div></details>')
    return ''.join(parts)


def _question_winners(judgments, agents):
    votes = Counter(row['order'][0 if row['verdict']['winner'] == 'A' else 1] for row in judgments)
    most_wins = max(votes.values())
    return [agent for agent in agents if votes[agent] == most_wins], most_wins


def _question_tally(data, judgments, missing):
    """How many ranked questions each system wins outright, and how many end in ties."""
    agents, outright, ties = _system_order(data), Counter(), 0
    for question in data['questions']:
        if missing[question['id']] or not judgments[question['id']]:
            continue
        winners, _ = _question_winners(judgments[question['id']], agents)
        if len(winners) == 1:
            outright[winners[0]] += 1
        else:
            ties += 1
    first = outright[agents[0]]
    items = [f'{_label(agents[0])} wins {first or "no"} question{"" if first == 1 else "s"} outright',
             *(f'{_label(a)} {outright[a] or "none"}' for a in agents[1:])]
    tie = f', with {ties} {"tie" if ties == 1 else "ties"}' if ties else ''
    return f'{_join(items)}{tie}.'


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
    opponents = counts['systems'] - 1
    parts = ['<section id="questions"><h2>Answers and judgments</h2>',
             f'<p>Each question lists {"both" if counts["systems"] == 2 else "all " + str(counts["systems"])} answers and its '
             f'{counts["per_question"]:,} judgments' + (f', except {exceptions}' if missing else '') + '. '
             f'A question’s winner is the system that won the most of its {counts["per_question_system"]:,} judgments '
             f'on that question ({_plural(opponents, "opponent")}, {_plural(counts["judges"], "judge")}, two orders). '
             'A tie is shown when two or more systems share the most wins. ' + _text(_question_tally(data, judgments, missing)) + ' Open an answer or a judgment to read it.</p>']
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
                winners, most_wins = _question_winners(judgments[qid], agents)
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
                imputation = data['cost_imputation']['answers'].get(row['key']) or {}
                record = {'cost_details': cost, 'usage': row['result'].get('usage'), 'timing': row.get('timing')}
                if imputation.get('imputed_calls'):
                    record['imputed_cost'] = {k: imputation[k] for k in (
                        'version', 'known_usd', 'imputed_usd', 'imputed_calls', 'upper_bound_usd', 'estimate_usd', 'calls')}
                    calls = imputation['imputed_calls']
                    part = imputation['imputed_usd']
                    part = _money(part) if round(part, 2) else 'less than $0.01'
                    cost_note = (f'{_money(imputation["estimate_usd"])}, including {part} for '
                                 + ('a call that never reported a cost' if calls == 1 else f'{_word(calls)} calls that never reported a cost'))
                else:
                    cost_note = _money(cost['cumulative_known_estimate_usd'])
                cost_note += ' (incomplete)' if (imputation.get('residual_incomplete') if imputation
                                                 else cost.get('estimate_incomplete')) else ''
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
                gateway = list(dict.fromkeys(_gateway_keys(record)))
                gateway_note = ('<p class="small">Gateway connection fields are left out: '
                                + _join(f'<code>{k}</code>' for k in gateway) + '.</p>' if gateway else '')
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
                settings_key = _answer_configuration(data, row)[0]
                settings_link = (f'<p class="small"><a href="#{_settings_anchor(settings_key)}">Saved research settings</a>'
                                 + ('' if settings_key.startswith('legacy-') else f' (configuration <code>{_text(settings_key)}</code>)')
                                 + '</p>')
                raw = row['result'].get('raw') or {}
                native = raw.get('artifact') if isinstance(raw, dict) else None
                source_urls = native.get('sources', {}) if isinstance(native, dict) else ()
                if not isinstance(source_urls, dict):
                    source_urls = ()
                parts.append(f'<details class="answer" id="answer-{index}-{agent}"><summary>{_text(_label(agent))}</summary>'
                             f'<div class="answer-text" data-answer-sha256="{hashlib.sha256(row["result"]["text"].encode()).hexdigest()}" '
                             f'role="region" tabindex="0" aria-label="{_text(_label(agent))} answer, question {index}">'
                             f'{_markdown_answer(row["result"]["text"], source_urls, f"{_label(agent)} answer, question {index}")}</div>'
                             '<details class="answer-metadata"><summary>Answer metadata and source records</summary>'
                             f'<p class="small">Estimated cost {cost_note}; job time '
                             f'{_duration((row.get("timing") or {}).get("duration_seconds"))}{audit_note}</p>'
                             f'{settings_link}'
                             f'<details class="cost-record"><summary>Cost, usage and timing record</summary>'
                             f'{event_note}{gateway_note}'
                             f'<pre tabindex="0" aria-label="Cost, usage and timing record">{_text(json.dumps(_without_gateway(record), ensure_ascii=False, indent=2))}</pre></details>'
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
                                 f'· {_text(_label(order[0]))} shown first · preferred {_text(_label(winner))}</summary>'
                                 f'<p class="presentation">Shown first (A): {_text(_label(order[0]))}; shown second (B): {_text(_label(order[1]))}</p>'
                                 f'<p class="reason">{_evidence_text(j["verdict"]["reason"])}</p>'
                                 '<details class="judgment-metadata"><summary>Judgment source record</summary>'
                                 f'<p class="small">Judgment key: <code>{_text(j["key"])}</code></p></details></details>')
                parts.append('</section>')
            parts.append('</details></div></details>')
        parts.append('</section>')
    parts.append('</section>')
    return ''.join(parts)


def _length_sentence(data):
    if not data.get('answers'):
        return ''
    means, _ = _answer_lengths(data)
    order = sorted(means, key=means.get)
    if len(order) < 2:
        return ''
    return (f'In the text the judges saw, {_label(order[-1])} answers are the longest, at {means[order[-1]]:,.0f} '
            'words on average, and '
            f'{_label(order[0])} answers the shortest, at {means[order[0]]:,.0f}.')


def _method(data, previous=''):
    aut = data['ranking'].get('rubric_kind') == AUT_KIND
    winner_guidance = (
        'Each judge chooses A or B using <strong>Fluency</strong> (expressed coverage only when a comparable '
        'task explicitly requests multiple ideas), <strong>Flexibility</strong> (meaningful conceptual directions), '
        'and <strong>Originality</strong> (substantive contributions and relationships). '
        if aut else
        'Each judge reads two answers, A and B, and picks the more creative one, guided by the three NUS criteria: '
        '<strong>New</strong>, <strong>Useful</strong>, and <strong>Surprising</strong>. '
        'Combining familiar ideas can still be original. Judges assess usefulness within the question’s '
        'premises, and an idea is not new just because it is unfamiliar. A judge that finds no real '
        'difference must say so and choose A. Doing that in both orders gives each system one win. '
    )
    scope = (
        '<p>This AUT-inspired rubric is a qualitative adaptation for expressed research contributions. '
        'Raw idea counts are not comparable across paper topics. Scores are preferences under this rubric, '
        'not standardized AUT scores or measures of an author’s divergent-thinking ability. '
        f'<a href="{page_href("AUT-Inspired Rubric", PAGE)}">AUT-inspired rubric and limits</a>.</p>' if aut else ''
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
        j.get('protocol_version') in STRICT_REASON_PROTOCOLS
        and j.get('presentation_version') in ('citation-neutral-v1', 'citation-neutral-v2') for j in data['judgments'])
    trimmed = revised and all(j.get('presentation_version') == 'citation-neutral-v2' for j in data['judgments'])
    if revised:
        provenance = ('<p>We hid the link addresses in every answer the same way and kept the citation labels and all '
                      'other text. The answers below are the originals.</p>'
                      + ('<p>Some answers end with a list of sources the system collected but never cites. Judges did not '
                         'see that list, but the answers below keep it.</p>' if trimmed else '')
                      + ('<p>Originality can come from combining familiar ideas. Elaboration supports evaluating '
                      'the contribution; it is not a word-count score. If a judge cannot support a substantive '
                      'preference, it must say so and choose A. Doing this in both orders gives each system one win.</p>' if aut else
                      '')
                      + '<p>We resend a judgment when its explanation is incomplete or does not compare the two answers. '
                      'This check does not verify what the judge claims.</p>')
    elif any(revealed.values()):
        provenance = ('<p>Provider labels were withheld, but this run was not fully blinded. '
                      'Links reveal provenance in '
                      + _join(f'{count} / 50 {_text(_label(agent))} answers' for agent, count in revealed.items()) + '. '
                      'These cues do not establish that provider bias caused the ranking.</p>')
    # Link text follows each page's catalog title, so a retitled page reads the same here.
    rubric, why = (f'<a href="{page_href(label, PAGE)}">{_text(label)}</a>'
                   for label in ('NUS Rubric', 'Why One Overall Judgment'))
    rubric_links = '' if aut else f'The {rubric} page has the full rubric, and {why} explains the single pick.'
    version = _main_rubric(data)
    rubric_used = (f'The ranking uses the {_rubric_link(version)} rubric. ' + _text(RUBRIC_NOTES.get(version, '')) + ' '
                   if version else '')
    note = _earlier_note(version, name_others=False) if version else ''
    earlier = f'<p>{_text(note)}</p>' if note else ''
    lengths = _length_sentence(data)
    return ('<section id="method"><h2>Method</h2>'
            f'<p>Each question has {counts["per_question"]:,} judgments, from {_count(counts["pairs"], "answer pair")} '
            f'that {_word(counts["judges"])} {"judge" if counts["judges"] == 1 else "judges each"} saw in both orders. '
            f'Each system takes part in {counts["per_system"] // counts["ranked"]:,} of them per question and '
            f'{counts["per_system"]:,} in total.</p>'
            + scope + '<dl class="method-summary">'
            '<dt>Pick a winner</dt><dd>' + winner_guidance
            + rubric_used + 'The judge makes one overall choice and gives no separate scores. ' + rubric_links + '</dd></dl>'
            '<p class="small">The intervals do not account for regenerating the answers or choosing other judges. '
            'Answer length or style may sway the judges.' + (' ' + _text(lengths) if lengths else '') + '</p>'
            + _models(data) + _saved_settings(data) +
            '<details><summary>Rubric, how answers were shown, and references</summary>' + earlier + provenance
            + creativity_reference +
            '<li><a href="https://jmlr.org/papers/v18/16-206.html">Shah and Wainwright, 2018</a>: '
            'ranking by pairwise win counts (Borda counting).</li>'
            '<li><a href="https://aclanthology.org/P18-1128/">Dror et al., 2018</a>: '
            'resampling methods and their assumptions in evaluation.</li>'
            '<li><a href="https://arxiv.org/abs/2306.05685">Zheng et al., 2023</a>: '
            'position and verbosity biases in LLM judging.</li></ul>'
            '<p class="small">These sources shaped the design. None of them validates this rubric or its judgments '
            'against human experts.</p>'
            '</details>' + (f'<p class="small">{previous}</p>' if previous else '') + '</section>')


CSS = """
#judges>details{margin:.3rem 0}
#main-content>.other-rubrics{margin-top:4rem;padding-top:.6rem;border-top:1px solid var(--line);font-size:.78rem}.other-rubrics>details{display:inline-block;margin:0 1.2rem 0 0;padding:0;vertical-align:top}.other-rubrics>details[open]{display:block;margin:.6rem 0 1rem;padding-bottom:1rem;border-bottom:1px solid var(--line)}
.other-rubrics>details>summary{display:inline-block;list-style:none;padding:.3rem 0;margin:0;font-size:.75rem;font-weight:400;line-height:1.6;color:#68788a;cursor:pointer}.other-rubrics>details>summary::-webkit-details-marker{display:none}.other-rubrics>details>summary::after{content:" ▸";content:" ▸" / ""}.other-rubrics>details[open]>summary::after{content:" ▾";content:" ▾" / ""}.other-rubrics>details[open]>summary{font-size:.9rem;font-weight:650;color:#526574}.other-rubrics>details>summary:hover{text-decoration:underline}.other-rubrics>details>summary:focus-visible{outline:2px solid #0b5967;outline-offset:2px}.other-rubrics .rubric-body{font-size:.92rem;margin-top:.5rem}
.question-category{margin-top:2rem}.question-category>h3{display:flex;flex-wrap:wrap;align-items:baseline;gap:.4rem .8rem}
.method-summary{display:grid;grid-template-columns:10rem minmax(0,1fr);gap:1rem 1.5rem}.method-summary dt{font-weight:650;color:#0b5967}.method-summary dd{margin:0}
.small,small{color:#526574}.small{font-size:.9rem}.nowrap{white-space:nowrap}.visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
main table{font-variant-numeric:tabular-nums}main td.num,main th.num{text-align:right}main td.num{white-space:nowrap}main td.num small{white-space:normal}.table-scroll tbody th,.table-scroll tbody th a{overflow-wrap:normal;word-break:normal;hyphens:none}.table-scroll table:not(.matrix) tbody th{white-space:nowrap}
.run-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1.5rem;margin:1.8rem 0}.run-stats strong{display:block;color:#0b5967;font-size:1.9rem}.run-stats span{font-size:.85rem;color:#526574}
.ranking-row{display:grid;grid-template-columns:minmax(160px,1.1fr) minmax(150px,2fr) 130px;gap:1rem;align-items:center;margin:1.1rem 0}.rank-label{display:flex;align-items:center;gap:.7rem}.rank{color:#526574;font-size:1.3rem}.ranking-row svg{width:100%;height:48px}.score{text-align:right;font-variant-numeric:tabular-nums}.score strong{display:block;font-size:1.4rem}.score small{display:block;font-size:.8rem;line-height:1.5}
.table-scroll{max-width:100%;overflow:auto;background:linear-gradient(to right,#fff 30%,rgba(255,255,255,0)),linear-gradient(to left,#fff 30%,rgba(255,255,255,0)) 100% 0,radial-gradient(farthest-side at 0 50%,rgba(23,44,62,.22),rgba(23,44,62,0)),radial-gradient(farthest-side at 100% 50%,rgba(23,44,62,.22),rgba(23,44,62,0)) 100% 0;background-repeat:no-repeat;background-size:40px 100%,40px 100%,14px 100%,14px 100%;background-attachment:local,local,scroll,scroll}.answer-text .table-scroll{background:none}.table-scroll table{min-width:630px}.table-scroll .matrix{table-layout:fixed;min-width:700px}.matrix th,.matrix td{vertical-align:middle;padding:.9rem}.matrix th:first-child{width:29%}.matrix thead th,.matrix td{text-align:center}.matrix tbody th{font-weight:650;line-height:1.5}.heat-cell,.diagonal{position:relative;display:flex;align-items:center;justify-content:center;min-height:3rem;padding:.6rem;font-variant-numeric:tabular-nums}.heat-cell{background:rgba(11,89,103,var(--shade))}.diagonal{background:repeating-linear-gradient(135deg,#f7f9fa 0 5px,#e1e8ec 5px 6px);color:#5f6f7b;font-size:.85rem}.matrix thead th:first-child{text-align:left}
.question{padding:0;border:1px solid #d7e1e6;border-radius:6px;margin:1rem 0}.question>summary{display:grid;grid-template-columns:2rem minmax(0,1fr) auto 1rem;gap:.8rem;align-items:start;padding:1.2rem;font-size:1rem;list-style:none}.question>summary::-webkit-details-marker{display:none}.question>summary::after{grid-column:-2;grid-row:1;content:"+";content:"+" / "";font-size:1.2rem;line-height:1.2;text-align:center}.question[open]>summary::after{content:"−";content:"−" / ""}.question-number{color:#526574;font-weight:400;font-variant-numeric:tabular-nums}.question-title{min-width:0}.question-outcome{max-width:16rem;font-size:.78rem;line-height:1.6;font-weight:500;text-align:right}.question-content{padding:0 1.2rem 1rem}.question .evidence-heading{margin:1rem 0 .5rem}.question .answer{border-top:1px solid #d7e1e6;margin:0;padding:.15rem 0}.question .answer>summary{font-size:1rem;padding:1rem 0}.reason{white-space:pre-wrap;overflow-wrap:anywhere}.answer-text{white-space:normal;overflow-wrap:anywhere;max-height:40rem;overflow:auto;background:#f5f8f9;padding:1.2rem;font-size:.95rem;line-height:1.8}.answer-text>:first-child{margin-top:0}.answer-text>:last-child{margin-bottom:0}.answer-text h5{font-size:1.2rem}.answer-text h6{font-size:1.05rem}.answer-text h6.answer-minor-heading{font-size:.95rem;font-weight:600;color:#3b5060}details.configuration pre{white-space:pre-wrap;overflow-wrap:break-word}.configuration-body{scroll-margin-top:4.5rem}.answer-text pre{white-space:pre;overflow:auto}.answer-text .table-scroll table{min-width:480px}.answer-text .table-scroll th,.answer-text .table-scroll td{padding:.6rem .75rem;border-bottom:1px solid var(--line)}.answer-metadata{margin:1rem 0}.cost-record pre{max-height:32rem;white-space:pre;overflow-wrap:normal}.question .judgments{border-top:1px solid #d7e1e6;margin:1rem 0 0;padding-top:.5rem}.judgment-group{margin:1.5rem 0;padding-top:1rem;border-top:1px solid #d7e1e6}.judgment-group:first-of-type{margin-top:.5rem;padding-top:0;border-top:0}.judgment-group>h4{font-size:1rem;margin:.5rem 0}.question .judgment{margin:.3rem 0;padding:.2rem 0}.judgment .presentation{font-size:.85rem;color:#526574;margin:.2rem 0 1rem}.judgment .reason{margin:.7rem 0 1.5rem}summary{overflow-wrap:anywhere}code{overflow-wrap:anywhere}
.profile{padding:1.1rem 1.25rem;border:1px solid #d7e1e6;border-radius:6px;margin:1.2rem 0}.profile h3{margin:0;color:#0b5967}.profile-meta{margin:.2rem 0 .7rem;font-size:.85rem;color:#526574}.profile-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1.4rem;margin-top:.8rem}.profile h4{font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;color:#0b5967;margin:.4rem 0}.profile-list{margin:0;padding-left:1.2rem}.profile-list li{margin:.55rem 0}
@media(max-width:999px){.table-scroll table:not(.matrix) tbody th{white-space:normal}}
@media(max-width:650px){.profile{padding:1rem .9rem}.profile-columns{grid-template-columns:1fr;gap:.6rem}.answer-text .table-scroll table{min-width:100%;width:max-content;max-width:480px}.run-stats{grid-template-columns:repeat(6,minmax(0,1fr))}.run-stats>div{grid-column:span 2}.run-stats>div:nth-last-child(-n+2){grid-column:span 3}.matrix th,.matrix td{padding:.5rem .4rem}.matrix th:first-child{width:24%}.matrix thead th{font-size:.8rem}.matrix tbody th,.matrix thead th:first-child{position:sticky;left:0;z-index:1;background:#fff}.table-scroll table{min-width:0}.table-scroll table:not(.matrix) tbody th{white-space:normal;min-width:6rem}main .table-scroll table:not(.matrix) th,main .table-scroll table:not(.matrix) td{padding:.6rem .45rem}.table-scroll table.wide{min-width:560px}.table-scroll .matrix{min-width:620px}.answer-text{max-height:none;overflow:visible}.question-outcome{grid-column:2;grid-row:2;max-width:none;text-align:left}.method-summary{grid-template-columns:1fr;gap:.25rem}.method-summary dd{margin-bottom:1rem}.ranking-row{grid-template-columns:minmax(0,1fr) 125px;gap:.4rem 1rem}.ranking-row svg{grid-column:1/-1;grid-row:2}.score{grid-column:2;grid-row:1}.rank-label{font-size:.9rem}.run-stats{gap:.7rem}.run-stats strong{font-size:1.4rem}.answer-text{padding:1rem}.question>summary{grid-template-columns:1.6rem minmax(0,1fr) 1rem;gap:.5rem;padding:1rem .9rem}.question-content{padding:0 .9rem .9rem}}
@media print{.skip-link,main>nav,#main-content>nav[aria-label]{display:none}.ranking-row{break-inside:avoid}.answer-text{max-height:none;overflow:visible}details>summary{break-after:avoid}}
"""


def _separable(report):
    """close(a, b) is true when the paired 95% interval of two systems' difference includes zero."""
    contrasts = {frozenset(c['pair']): c for c in report.get('paired_contrasts', [])}

    def close(a, b):
        c = contrasts.get(frozenset((a, b)))
        return bool(c) and c['ci95'][0] <= 0 <= c['ci95'][1]
    return close


def _cluster_differences(report):
    """The paired 95% interval for every pair inside each group the intervals cannot fully separate."""
    contrasts, rows = {frozenset(c['pair']): c for c in report.get('paired_contrasts', [])}, report['ranking']
    sentences = []
    for i, j in _clusters(report):
        members = [row['agent'] for row in rows[i:j + 1]]
        items = []
        for a, b in combinations(members, 2):
            c = contrasts[frozenset((a, b))]
            low, high = sorted((1 if c['pair'][0] == a else -1) * v for v in c['ci95'])
            items.append(f'{_label(a)} vs {_label(b)} {_points(low)} to {_points(high)}')
        who = f'the top {_word(len(members))}' if i == 0 else _join(_label(a) for a in members)
        sentences.append(f'The 95% interval for each difference among {who}, in percentage points: '
                         + '; '.join(items) + '.')
    return ' '.join(sentences)


def _clusters(report):
    """(first, last) row indexes of each run of ranked systems that the paired intervals cannot fully separate.

    A group is a maximal run of neighbors in which every pair is too close to separate;
    groups that share a system join into one cluster."""
    rows, close = report['ranking'], _separable(report)
    clusters, end = [], -1
    for i in range(len(rows)):
        j = i
        while j + 1 < len(rows) and all(close(rows[k]['agent'], rows[j + 1]['agent']) for k in range(i, j + 1)):
            j += 1
        if j > i and j > end:
            if clusters and i <= clusters[-1][1]:
                clusters[-1] = (clusters[-1][0], j)
            else:
                clusters.append((i, j))
            end = j
    return clusters


def _split_clause(report, a, b):
    """For a system ahead of another overall: a clause when their own judgments split about evenly."""
    rate = ((report.get('pairwise') or {}).get('overall') or {}).get(a, {}).get(b)
    if not _number(rate) or not .45 <= rate <= .55:
        return ''
    how = 'evenly' if _tenths(rate) == 50 else 'nearly evenly'
    return f', although the two split their own head-to-head judgments {how} ({_pct(rate)})'


def _headline(data):
    """State the ranking in order. Systems whose paired interval includes zero are never given separate places."""
    report = data['ranking']
    rows, close, clusters = report['ranking'], _separable(report), dict(_clusters(report))
    sentences, named, singles = [], set(), []

    def mention(row):
        first = row['agent'] not in named
        named.add(row['agent'])
        return _label(row['agent']) + (f' at {_pct(row["preference_rate"])}' if first else '')

    def flush():
        if singles:
            sentences.append(_join(f'{_label(r["agent"])}{" is" if n == 0 else ""} {_ordinal(r["rank"])} at '
                                   f'{_pct(r["preference_rate"])}' for n, r in enumerate(singles)) + '.')
            named.update(r['agent'] for r in singles)
            singles.clear()

    index = 0
    while index < len(rows):
        if index not in clusters:
            singles.append(rows[index])
            index += 1
            continue
        flush()
        members = rows[index:clusters[index] + 1]
        agents = [r['agent'] for r in members]
        apart = [(a, b) for a, b in combinations(agents, 2) if not close(a, b)]
        if not apart:
            sentences.append(f'{_join(mention(r) for r in members)} are too close to separate for '
                             f'{_ordinal(members[0]["rank"])} place.')
        else:
            # A chain: name the leader, then whom each later system cannot be separated from, then who is ahead.
            lead = members[0]
            named.add(lead['agent'])
            sentences.append(f'{_label(lead["agent"])} {"leads" if index == 0 else "is next"} at '
                             f'{_pct(lead["preference_rate"])}.')
            stated, told = set(), set()
            for row in members[1:]:
                partners = [p for p in members if p is not row and close(row['agent'], p['agent'])
                            and frozenset((row['agent'], p['agent'])) not in stated]
                if not partners:
                    continue
                stated.update(frozenset((row['agent'], p['agent'])) for p in partners)
                sentence = f'{mention(row)} cannot be separated ' + _join((f'from {mention(p)}' for p in partners), 'or')
                among = {p['agent'] for p in partners}
                plain = [(a, b) for a, b in apart if {a, b} <= among and not _split_clause(report, a, b)]
                if plain:
                    sentence += ', but ' + _join(f'{_label(a)} is ahead of {_label(b)}' for a, b in plain)
                    told.update(plain)
                sentences.append(sentence + '.')
            behind = defaultdict(list)
            for a, b in apart:
                if (a, b) in told:
                    continue
                split = _split_clause(report, a, b)
                if split:
                    sentences.append(f'{_label(a)} is ahead of {_label(b)}{split}.')
                else:
                    behind[a].append(b)
            sentences += [f'{_label(a)} is ahead of {_join(_label(b) for b in bs)}.' for a, bs in behind.items()]
        index += len(members)
    flush()
    return ' '.join(sentences)


def _cost_summary(data):
    """Per-answer cost and time of the first-ranked system against the range of the others, linked to the details."""
    generation, agents = data['resources']['generation'], _system_order(data)
    if len(agents) < 2:
        return ''
    cost, minutes = {}, {}
    for agent in agents:
        r = generation[agent]
        total = r['audited_known_cost_usd'] if _number(r['audited_known_cost_usd']) else r['estimated_cost_usd']
        cost[agent] = total / r['answers'] if _number(total) and r['answers'] else None
        minutes[agent] = r['mean_duration_seconds'] / 60 if _number(r['mean_duration_seconds']) else None
    first, others = agents[0], agents[1:]
    if cost[first] is None or minutes[first] is None or any(cost[a] is None or minutes[a] is None for a in others):
        return ''

    def spread(values, show):
        low, high = show(min(values)), show(max(values))
        return low if low == high else f'{low} to {high}'
    assumed = [a for a in others if a in UNREPORTED_MODELS]
    note = (f', with {_join(_label(a) + "’s" for a in assumed)} cost at assumed prices' if assumed else '')
    return _text(f'Per answer, {_label(first)} cost {_money(cost[first])} on average and took '
                 f'{minutes[first]:,.0f} minutes. The other systems cost {spread([cost[a] for a in others], _money)} '
                 f'and took {spread([minutes[a] for a in others], lambda m: f"{m:,.0f}")} minutes{note} (see ') \
        + '<a href="#resources">Cost and time</a>).'


def _previous_version(destination):
    match = re.fullmatch(r'(.+-v)(\d+)\.html', destination.name)
    if not match or int(match[2]) < 2:
        return None
    previous = destination.with_name(f'{match[1]}{int(match[2]) - 1}.html')
    return previous if previous.is_file() else None


def _render(data, destination, *, updated=None):
    title = _text(page_title(destination, "Deep Research Comparison"))
    agents, counts = _system_order(data), _counts(data)
    one = counts['judges'] == 1
    judge_phrase = ('One AI model acts as the judge. It compares' if one else
                    f'{_word(counts["judges"]).capitalize()} AI models act as judges. They compare')
    aut = data['ranking'].get('rubric_kind') == AUT_KIND
    version = None if aut else _main_rubric(data)
    rubric = ('an AUT-inspired creativity rubric.' if aut else
              f'the {_rubric_link(version) if version else "NUS"} rubric. ' + NUS_DEFINITION)
    pointer = ''
    previous = _previous_version(Path(destination))
    if previous:
        systems = previous.read_text(encoding='utf-8').count('class="ranking-row"')
        link = f'<a href="{previous.name}">{_text(page_title(previous, previous.stem))}</a>'
        pointer = (f'An earlier study, {link}, compared {_word(systems)} systems.' if systems > 1
                   else f'An earlier study is {link}.')
    picks, cost, profiles = _judge_picks(data), _cost_summary(data), _profiles(data)
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">',
             f'<title>{title}</title>', site_favicon(ROOT, destination), f'<style>{SITE_CSS}\n{CSS}</style></head><body>',
             '<a class="skip-link" href="#main-content">Skip to report</a>', site_header(ROOT, destination, research_report=destination, updated=updated),
             f'<main id="main-content" tabindex="-1"><h1>{title}</h1>',
             f'<p>This comparison runs {_text(_join(_label(a) for a in agents))} '
             f'on the same 50 questions. ' + (_text(_question_authors(data)) + ' ' if _question_authors(data) else '') + f'{judge_phrase} the {counts["answers"]:,} answers two at a time, in both orders, '
             f'and {"picks" if one else "pick"} the more creative one under {rubric} '
             + (f'The ranking uses {counts["ranked"]} of the 50 questions; <a href="#unranked">'
                f'{"one question is" if 50 - counts["ranked"] == 1 else _word(50 - counts["ranked"]) + " questions are"} not ranked</a>. '
                if counts['ranked'] != 50 else '')
             + ('A judgment is the judge picking the more creative of two answers.' if one else
                'A judgment is one judge picking the more creative of two answers.')
             + ' A system’s win rate is the share of its judgments it won.</p>'
             + f'<p><strong>{_text(_headline(data))}</strong></p>'
             + ('<p>The judge did not check facts. A high win rate means the judge found the answers more creative, '
                'not that they are more correct. The judge is an AI model whose choices have not' if one else
                '<p>The judges did not check facts. A high win rate means the judges found the answers more creative, '
                'not that they are more correct. The judges are AI models whose choices have not')
             + ' been checked against human experts, and an answer’s wording or length can reveal or favor the system '
               'that wrote it.</p>'
             + (f'<p>{cost}</p>' if cost else '')
             + (f'<p>{_text(picks)} <a href="#judges">See how each judge ruled</a>.</p>' if picks else ''),
             '<nav aria-label="Report contents"><a href="#overall">Creativity ranking</a><a href="#matchups">Head-to-head</a>'
             + ('<a href="#profiles">Strengths and weaknesses</a>' if profiles else '')
             + '<a href="#judges">Judges</a><a href="#resources">Cost and time</a>'
             '<a href="#method">Method</a><a href="#questions">Answers and judgments</a></nav>',
             (f'<div class="run-stats"><div><strong>{counts["ranked"]}</strong><span>of 50 questions ranked</span></div>'
              if counts['ranked'] != 50 else '<div class="run-stats"><div><strong>50</strong><span>questions</span></div>')
             + f'<div><strong>{counts["systems"]}</strong><span>systems</span></div>'
             + f'<div><strong>{counts["judges"]}</strong><span>{"judge" if one else "judges"}</span></div>'
             + f'<div><strong>{counts["answers"]:,}</strong><span>answers</span></div>'
             + (f'<div><strong>{counts["saved"]:,}</strong><span>of {counts["judgments"]:,} pairwise judgments</span></div></div>'
                if counts['failed'] else f'<div><strong>{counts["judgments"]:,}</strong><span>pairwise judgments</span></div></div>'),
             _ranking(data), _head_to_head(data), profiles, _judges(data), _resources(data), _method(data, pointer),
             _questions(data), _rubrics(data),
             '</main></body></html>\n']
    return ''.join(parts)


def write_report(run_dir, destination, *, audit=None, updated=None, rubric_runs=()):
    """Write a validated final report atomically; errors leave old outputs intact."""
    require_canonical_output(destination, ROOT)
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
