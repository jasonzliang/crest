"""Offline publication, provenance, accounting and escaping contracts for CREST HTML."""
from copy import deepcopy
from html.parser import HTMLParser
from itertools import combinations
import json
import hashlib
import re

import pytest

from crest.analysis import analyze


AGENTS = ['caesar', 'gemini', 'openai']
JUDGES = ['gemini', 'openai']


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def make_run(root, *, choose=None):
    choose = choose or (lambda q, pair, judge, order: pair[q % 2])
    questions = [{'id': f'q{i:03}', 'text': f'Invent a useful research proposal for question {i}.'} for i in range(50)]
    answers, judgments = [], []
    for i, q in enumerate(questions):
        for agent in AGENTS:
            answers.append({'question_id': q['id'], 'agent': agent, 'key': f'answer-{q["id"]}-{agent}',
                            'result': {'text': f'Complete substantive answer from {agent} for {q["id"]}.',
                                       'model': 'gpt-6.1-sol' if agent != 'gemini' else 'gemini-3.1-pro-preview',
                                       'cost_usd': 1.0, 'cost_estimated': True, 'usage': {},
                                       'raw': {'agent': 'deep-research-preview-04-2026'} if agent == 'gemini' else {}},
                            'timing': {'started_at': '2026-10-27T00:00:00+00:00',
                                       'completed_at': '2026-10-27T00:01:40+00:00', 'duration_seconds': 100,
                                       'source': 'checkpoint:first_started_at/completed_at',
                                       'definition': 'Client elapsed; excludes local scheduling.'}})
        for pair in combinations(AGENTS, 2):
            for judge in JUDGES:
                for order in (pair, pair[::-1]):
                    winner = choose(i, pair, judge, order)
                    verdict = {'reason': 'A comparative reason about overall creative quality.',
                               'winner': 'A' if winner == order[0] else 'B'}
                    judgments.append({'question_id': q['id'], 'pair': list(pair), 'order': list(order),
                                      'judge': judge, 'key': f'{q["id"]}-{pair}-{judge}-{order}',
                                      'answer_keys': [f'answer-{q["id"]}-{agent}' for agent in order],
                                      'verdict': verdict, 'cost_usd': .1,
                                      'result': {'text': json.dumps(verdict), 'cost_usd': .1, 'raw': {}},
                                      'timing': {'duration_seconds': 10, 'source': 'checkpoint'}})
    generation, judging, analysis = '01-generate-test', '02-judge-test', '03-analysis-test'
    manifest = {'schema': 'crest-run-v1', 'agents': AGENTS, 'questions': questions,
                'config': {'research': {
                    'caesar': {'model': 'gpt-6.1-sol', 'exploration_model': 'gpt-6-luna', 'kb_model': 'gpt-6-luna', 'budget_usd': 5},
                    'openai': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'budget_usd': 5},
                    'gemini': {'agent': 'deep-research-preview-04-2026', 'billing_model': 'gemini-3.1-pro-preview', 'budget_usd': 5}}},
                'stages': [{'name': name, 'directory': directory, 'status': 'completed'} for name, directory in
                           [('generate', generation), ('judge', judging), ('analysis', analysis)]]}
    dump(root / 'run.json', manifest)
    dump(root / generation / 'manifest.json', {'status': 'completed'})
    dump(root / judging / 'manifest.json', {'status': 'completed', 'generation_directory': generation})
    dump(root / analysis / 'manifest.json', {'status': 'completed', 'judgment_directory': judging})
    dump(root / judging / 'questions.json', questions)
    dump(root / judging / 'answers.json', answers)
    dump(root / judging / 'judges.json', {'openai': {'model': 'gpt-6-astra', 'reasoning_effort': 'high'},
                                        'gemini': {'model': 'gemini-4-argon', 'thinking_level': 'high'}})
    (root / judging / 'judgments.jsonl').write_text(''.join(json.dumps(j) + '\n' for j in judgments))
    (root / judging / 'rubric.txt').write_text('New, Useful and Surprising guide one overall A/B winner.')
    ranking = analyze(questions, answers, judgments, agents=AGENTS, judges=JUDGES, bootstrap_samples=1000, seed=2026)
    dump(root / analysis / 'ranking.json', ranking)
    return root


@pytest.fixture
def run(tmp_path):
    return make_run(tmp_path / 'experiment')


def answers_path(run):
    return run / '02-judge-test/answers.json'


def ranking_path(run):
    return run / '03-analysis-test/ranking.json'


def test_revised_publication_rejects_meta_only_reason(run):
    from crest.report import load_run
    path = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row['protocol_version'] = 'nus-overall-pairwise-v3'
    rows[0]['verdict']['reason'] = 'Wait, no markdown!'
    rows[0]['result']['text'] = json.dumps(rows[0]['verdict'])
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError):
        load_run(run)


def test_revised_method_describes_judge_presentations_not_raw_url_metadata():
    from crest.report import _method
    data = {'ranking': {'bootstrap': {'seed': 2026}},
            'judgments': [{'protocol_version': 'nus-overall-pairwise-v3',
                           'presentation_version': 'citation-neutral-v1'}],
            'answers': [{'agent': 'openai', 'result': {'text': 'https://example.com?utm_source=openai'}},
                        {'agent': 'gemini', 'result': {'text': 'https://vertexaisearch.cloud.google.com/source'}}]}
    html = _method(data)
    assert 'URL destinations were hidden' in html
    assert 'Original answers are preserved' in html
    assert 'this run was not fully blinded' not in html


def test_judging_summary_keeps_verdict_count_when_jobs_retry(run):
    from crest.report import load_run, _resources
    data = load_run(run)
    data['judgments'][0]['attempts'] = [{'status': 'rejected'}, {'status': 'completed'}]
    html = _resources(data)
    assert 'Total for 600 judgments: $60.0000' in html
    assert 'Includes retries' in html


def test_retry_audit_details_stay_out_of_cost_summary(run):
    from crest.report import load_run, _resources
    data = load_run(run)
    data['audit_path'] = run / 'audit.json'
    data['audit_doc'] = {'judging': {
        'rejected_attempts': 7, 'rejected_attempt_estimated_usd': .5254,
        'failed_jobs': 0, 'failed_known_usd': 0,
        'failed_unknown_cost_count': 2, 'failed_partial_observed_usd': 0}}
    original = deepcopy(data['audit_doc'])
    html = _resources(data)
    assert 'rejected attempts' not in html
    assert 'Unknown charges' not in html
    assert data['audit_doc'] == original


def test_judging_estimate_includes_rejected_attempt_without_changing_receipts(run):
    from crest.report import load_run, _resources
    path = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0].update(cost_usd=.15, cost_scope='all_judgment_attempts', attempts=[
        {'key': 'rejected-attempt', 'status': 'rejected', 'cost_usd': .05},
        {'key': 'selected-attempt', 'status': 'completed', 'cost_usd': .1}])
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    original = path.read_bytes()
    data = load_run(run)
    html = _resources(data)
    assert 'Total for 600 judgments: $60.0500' in html
    assert 'Includes retries' in html
    assert path.read_bytes() == original
    assert data['judgments'][0]['result']['cost_usd'] == .1


def test_model_notes_cite_provider_history_and_preserve_run_uncertainty(run):
    from crest.report import load_run, _models
    html = _models(load_run(run))
    assert 'reasoning effort: high' in html
    assert 'built with Gemini 3.1 Pro' in html
    assert 'Per-loop backend models are not reported for this run' in html
    assert 'not an override' in html
    assert 'July 23, 2026' in html
    assert 'o3-deep-research' in html and 'o4-mini-deep-research' in html
    for source in [
        'https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/',
        'https://developers.openai.com/api/docs/deprecations',
        'https://developers.openai.com/api/docs/guides/deep-research',
    ]:
        assert f'href="{source}"' in html


def test_refuses_incomplete_publication_without_overwriting_destination(run, tmp_path):
    from crest.report import write_report
    answers = json.loads(answers_path(run).read_text())
    dump(answers_path(run), answers[:-1])
    output = tmp_path / 'docs/deep-research-creativity.html'
    output.parent.mkdir()
    output.write_text('previous verified report')
    with pytest.raises(ValueError, match='150|answer'):
        write_report(run, output)
    assert output.read_text() == 'previous verified report'


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'invalid_winner', 'wrong_answer_key'])
def test_refuses_missing_duplicate_or_mismatched_judgment_cells(run, tmp_path, kind):
    from crest.report import write_report
    file = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    if kind == 'missing': rows.pop()
    elif kind == 'duplicate': rows[-1] = deepcopy(rows[0])
    elif kind == 'invalid_winner': rows[0]['verdict']['winner'] = 'tie'
    else: rows[0]['answer_keys'][0] = 'some-other-paid-answer'
    file.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError):
        write_report(run, tmp_path / 'page.html')
    assert not (tmp_path / 'page.html').exists()


def test_rejects_stale_ranking_and_nonquestion_uncertainty(run, tmp_path):
    from crest.report import write_report
    original = json.loads(ranking_path(run).read_text())
    for field in ('wins', 'bootstrap'):
        ranking = deepcopy(original)
        if field == 'wins': ranking['ranking'][0]['wins'] += 1
        else: ranking['bootstrap'].update(unit='paper_pair', method='Serfling finite-pool bound')
        dump(ranking_path(run), ranking)
        with pytest.raises(ValueError):
            write_report(run, tmp_path / 'page.html')


def test_uses_saved_bootstrap_intervals_preserves_exact_ties_and_all_evidence(tmp_path):
    from crest.report import load_run, write_report
    run = make_run(tmp_path / 'run', choose=lambda q, pair, judge, order: order[0])
    data = load_run(run)
    assert [row['rank'] for row in data['ranking']['ranking']] == [1, 1, 1]
    assert [row['wins'] for row in data['ranking']['ranking']] == [200, 200, 200]
    output = tmp_path / 'preview.html'
    write_report(run, output)
    text = output.read_text()
    assert text.count('class="question"') == 50
    assert text.count('class="answer"') == 150
    assert text.count('class="judgment"') == 600
    assert '200 / 400' in text
    assert '1,000' in text and 'question' in text
    assert 'Serfling' not in text
    assert 'OpenAI (Sol + web search)' in text
    assert 'this run was not fully blinded' not in text
    assert 'not an override' in text
    assert 'Lifetime budget compliance is not established' not in text
    assert 'fetch(' not in text and '<script src=' not in text
    outcomes = re.findall(r'class="question-outcome" data-winners="([^"]+)" data-wins="(\d+)"', text)
    assert len(outcomes) == 50
    assert all(set(winners.split()) == set(AGENTS) and wins == '4' for winners, wins in outcomes)


def test_answer_markdown_renders_structure_and_preserves_source(run, tmp_path):
    from crest.report import write_report
    source = ('# Example\n\nA **strong** idea and *emphasis*.\n\n'
              '- First\n- Second\n\n| Part | Use |\n| --- | --- |\n| Shade | Cooling |\n\n'
              '```python\nx = "<safe>"\n```\n\n[Source](https://example.com/source)\n\n'
              '> A quoted passage.\n')
    rows = json.loads(answers_path(run).read_text())
    rows[0]['result']['text'] = source
    dump(answers_path(run), rows)
    original = answers_path(run).read_bytes()
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    for markup in ['<h4>Example</h4>', '<strong>strong</strong>', '<em>emphasis</em>',
                   '<li>First</li>', '<th scope="col">Part</th>', '<td>Cooling</td>',
                   '<code class="language-python">', '&lt;safe&gt;', '<blockquote>',
                   '<a href="https://example.com/source">Source</a>']:
        assert markup in html
    assert html.count('<h1>') == 1
    assert hashlib.sha256(source.encode()).hexdigest() in html
    assert answers_path(run).read_bytes() == original


@pytest.mark.parametrize('source', [
    '<script>alert(1)</script><img src="https://example.com/pixel" onerror="alert(1)">',
    '[link](javascript:alert(1))', '[link](vbscript:msgbox(1))',
    '[link](data:text/html;base64,PHNjcmlwdD4=)', '[link](file:///private/local.txt)',
    '![Diagram](https://example.com/image.png)',
])
def test_answer_markdown_disables_active_content_and_automatic_image_requests(source):
    from crest.report import _markdown_answer
    from urllib.parse import urlsplit

    class Content(HTMLParser):
        def handle_starttag(self, tag, attrs):
            assert tag not in {'script', 'style', 'img', 'iframe', 'object', 'embed'}
            for name, value in attrs:
                assert not name.startswith('on') and name != 'src'
                if name == 'href':
                    assert urlsplit(value).scheme not in {'javascript', 'vbscript', 'data', 'file'}

    html = _markdown_answer(source)
    Content().feed(html)
    if source.startswith('!'):
        assert '<a href="https://example.com/image.png">Diagram</a>' in html


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_answer_markdown_preserves_single_line_breaks_without_changing_blocks(newline):
    from crest.report import _markdown_answer
    source = ('First line\nSecond line\n\nNext paragraph.\n\n'
              '- Item one\n- Item two\n\n```\nalpha\nbeta\n```\n').replace('\n', newline)
    html = _markdown_answer(source)
    assert '<p>First line<br>\nSecond line</p>' in html
    assert '<p>Next paragraph.</p>' in html
    assert '<li>Item one</li>\n<li>Item two</li>' in html
    assert '<pre><code>alpha\nbeta\n</code></pre>' in html
    assert html.count('<br>') == 1


def test_answer_markdown_links_bare_source_urls_without_altering_underscores():
    from crest.report import _markdown_answer
    url = ('https://socialsci.libretexts.org/Bookshelves/Linguistics/'
           'Analyzing_Meaning_-_An_Introduction_to_Semantics_and_Pragmatics_(Kroeger)')
    html = _markdown_answer(f'[1] {url}')
    assert f'<a href="{url}">{url}</a>' in html
    assert '<em>' not in html


def test_markdown_linked_image_preserves_outer_link_without_nested_anchors():
    from crest.report import _markdown_answer
    html = _markdown_answer('[![Diagram](https://example.com/image.png)](https://example.com/source)')
    assert html == '<p><a href="https://example.com/source">Diagram</a></p>\n'


def test_partial_unknown_ledger_is_not_dropped_or_double_counted_as_zero(run):
    from crest.report import load_run
    rows = json.loads(answers_path(run).read_text())
    caesar = next(row for row in rows if row['agent'] == 'caesar')
    caesar['result'].update(cost_usd=None, raw={
        'usage_audit': {'known_cost_usd': 3., 'cost_usd': None, 'unknown_cost': True,
                        'budget_history_previous_unknown_reserved_usd': .4},
        'new_attempt_usage_audit': {'known_cost_usd': 1., 'cost_usd': 1., 'unknown_cost': False, 'events': []},
        'budget_history': {'previous_known_cost_usd': 2., 'previous_unknown_reserved_usd': .4}})
    dump(answers_path(run), rows)
    resources = load_run(run)['resources']['generation']['caesar']
    assert resources['known_cost_usd'] == 52  # 49 ordinary dollars + 3 cumulative known.
    assert resources['current_attempt_known_cost_usd'] == 50
    assert resources['historical_unknown_reserved_usd'] == .4
    assert resources['unknown_cost_answers'] == 1


def test_html_omits_usage_events_without_changing_canonical_usage_or_costs(run, tmp_path):
    from crest.report import load_run, write_report
    rows = json.loads(answers_path(run).read_text())
    marker = 'BULKY_USAGE_EVENT_RETAINED_ONLY_IN_CANONICAL_JSON'
    rows[0]['result']['usage'] = {'input_tokens': 1234, 'output_tokens': 567, 'known_cost_usd': 1.,
        'per_model_costs_usd': {'gpt-6.1-sol': 1.},
        'events': [{'request': marker + 'x' * 10000}, {'response': marker}]}
    dump(answers_path(run), rows)
    original = answers_path(run).read_bytes()
    output = tmp_path / 'page.html'; write_report(run, output)
    html = output.read_text()
    assert marker not in html
    assert 'Usage events omitted from this HTML: 2.' in html
    assert '01-generate-test/answers.jsonl' in html and 'result.usage.events' in html
    assert rows[0]['key'] in html
    assert '&quot;input_tokens&quot;: 1234' in html and '&quot;output_tokens&quot;: 567' in html
    assert '&quot;per_model_costs_usd&quot;' in html
    assert answers_path(run).read_bytes() == original
    assert load_run(run)['resources']['generation']['caesar']['known_cost_usd'] == 50


def test_missing_times_remain_unknown_and_cache_hits_keep_original_duration(run):
    from crest.report import load_run
    rows = json.loads(answers_path(run).read_text())
    selected = [row for row in rows if row['agent'] == 'openai']
    selected[0]['timing'] = None
    selected[1]['cache_hit'] = True
    selected[1]['timing']['duration_seconds'] = 75
    dump(answers_path(run), rows)
    resources = load_run(run)['resources']['generation']['openai']
    assert resources['duration_count'] == 49
    assert resources['duration_sum_seconds'] == 4875
    assert resources['median_duration_seconds'] == 100
    assert resources['mean_duration_seconds'] == pytest.approx(4875 / 49)
    assert resources['unknown_duration_answers'] == 1


def test_escapes_every_question_answer_reason_and_model_label(run, tmp_path):
    from crest.report import write_report
    payload = '<script>alert("unsafe")</script><img src=x onerror=alert(1)>'
    rows = json.loads(answers_path(run).read_text())
    rows[0]['result']['text'] = payload
    dump(answers_path(run), rows)
    file = run / '02-judge-test/judgments.jsonl'
    judgments = [json.loads(line) for line in file.read_text().splitlines()]
    judgments[0]['verdict']['reason'] = payload
    judgments[0]['result']['text'] = json.dumps(judgments[0]['verdict'])
    file.write_text(''.join(json.dumps(row) + '\n' for row in judgments))
    settings = json.loads((run / '02-judge-test/judges.json').read_text())
    settings['openai']['model'] = payload
    dump(run / '02-judge-test/judges.json', settings)
    # Changing wording doesn't alter the saved numerical preference results.
    questions = json.loads((run / '02-judge-test/questions.json').read_text())
    questions[0]['text'] = payload
    dump(run / '02-judge-test/questions.json', questions)
    manifest = json.loads((run / 'run.json').read_text()); manifest['questions'] = questions; dump(run / 'run.json', manifest)
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert payload not in html
    assert '&lt;script&gt;' in html and '&lt;img' in html
    class Tags(HTMLParser):
        def __init__(self): super().__init__(); self.images = []
        def handle_starttag(self, tag, attrs):
            if tag == 'img': self.images.append(attrs)
    parser = Tags(); parser.feed(html)
    assert not parser.images


def test_audit_requires_matching_run_and_answer_identity(run, tmp_path):
    from crest.report import write_report
    audit = tmp_path / 'audit.json'
    dump(audit, {'audit_version': 'crest-final-audit-v1', 'status': 'complete', 'ready': True, 'run_dir': 'another-run'})
    with pytest.raises(ValueError, match='audit'):
        write_report(run, tmp_path / 'page.html', audit=audit)


def test_manifest_stage_paths_cannot_escape_run_directory(run, tmp_path):
    from crest.report import write_report
    manifest = json.loads((run / '03-analysis-test/manifest.json').read_text())
    manifest['judgment_directory'] = '../outside'
    dump(run / '03-analysis-test/manifest.json', manifest)
    with pytest.raises(ValueError, match='stage|directory|run'):
        write_report(run, tmp_path / 'page.html')


def final_audit(run):
    rows = json.loads(answers_path(run).read_text())
    return {'audit_version': 'crest-final-audit-v1', 'status': 'complete', 'ready': True,
            'run_dir': str(run), 'errors': [], 'pending': [],
            'warnings': ['Billing remains estimated; no invoice has been verified.'],
            'generation': {'completed_answers': 150, 'snapshot_answer_rows': 150,
                'answer_details': [{'question_id': row['question_id'], 'agent': row['agent'], 'key': row['key'],
                    'status': 'completed', 'known_usd': 1., 'unknown_attempt_count': 0,
                    'exposure_upper_usd': 1., 'attempt_keys': [row['key']],
                    'active_attempt_seconds': 175., 'active_time_limit_seconds': 7200,
                    'timing_complete': True} for row in rows]},
            'judging': {'valid_calls': 600, 'complete_questions': 50, 'known_estimated_usd': 60.,
                        'failed_known_usd': .25, 'failed_unknown_cost_count': 1,
                        'failed_partial_observed_usd': .1},
            'ranking': {'matches_independent_calculation': True},
            'ledger': {'known_generation_attempt_usd': 151., 'unknown_reserved_usd': .4,
                       'failed_known_usd': 1., 'unbounded_unknown_attempts': 0},
            'input_sha256': {str(path): __import__('hashlib').sha256(path.read_bytes()).hexdigest()
                            for path in [run / 'run.json', ranking_path(run),
                                         run / '02-judge-test/questions.json', answers_path(run),
                                         run / '02-judge-test/judgments.jsonl', run / '02-judge-test/judges.json']}}


def test_final_audit_enriches_timing_without_repeating_audit_notes(run, tmp_path):
    from crest.report import load_run, write_report
    audit = run / '04-audit-test/audit.json'
    dump(audit, final_audit(run))
    data = load_run(run)
    assert data['resources']['generation']['caesar']['median_duration_seconds'] == 100
    assert data['resources']['generation']['caesar']['median_lifetime_duration_seconds'] == 175
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert data['audit_doc']['warnings'] == ['Billing remains estimated; no invoice has been verified.']
    assert 'Billing remains estimated; no invoice has been verified.' not in html
    assert 'model-based reserved exposure' not in html.lower()
    assert 'Audited cumulative attempt estimate' not in html


def test_cost_history_notes_are_omitted_without_mutating_audit(run, tmp_path):
    from crest.report import write_report
    doc = final_audit(run)
    raw_warning = '10 completed answers have uncertain final billing; see bounded exposure'
    doc['warnings'] = [raw_warning]
    caesar = [r for r in doc['generation']['answer_details'] if r['agent'] == 'caesar']
    for row in caesar[:10]: row['unknown_attempt_count'] = 1
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    original = audit.read_bytes()
    output = tmp_path / 'page.html'; write_report(run, output, audit=audit)
    html = output.read_text()
    assert raw_warning not in html
    assert '10 Caesar answers have unresolved prior charges' not in html
    assert 'model-based estimates, not invoice bounds' not in html
    assert 'Final audit notes' not in html
    assert audit.read_bytes() == original


def test_audit_hashes_must_match_selected_frozen_snapshot(run, tmp_path):
    from crest.report import write_report
    doc = final_audit(run)
    doc['input_sha256'][str(answers_path(run))] = '0' * 64
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    with pytest.raises(ValueError, match='audit|hash|snapshot'):
        write_report(run, tmp_path / 'page.html', audit=audit)


def test_identical_answers_are_not_arbitrarily_published_as_complete(run, tmp_path):
    from crest.report import write_report
    rows = json.loads(answers_path(run).read_text())
    rows[1]['result']['text'] = rows[0]['result']['text']
    dump(answers_path(run), rows)
    with pytest.raises(ValueError, match='Identical'):
        write_report(run, tmp_path / 'page.html')


def test_cost_totals_use_shared_assessment_and_keep_google_scenarios_conditional(run, tmp_path):
    from crest.costs import summarize_costs
    from crest.report import load_run, write_report
    rows = json.loads(answers_path(run).read_text())
    google = [row for row in rows if row['agent'] == 'gemini']
    google[0]['result']['usage'] = {'input_tokens': 1000, 'cached_input_tokens': 100,
        'output_tokens': 200, 'reasoning_tokens': 300, 'tool_use_tokens': 400,
        'grounding_tool_count': [{'type': 'google_search', 'count': 2}]}
    dump(answers_path(run), rows)
    resource = load_run(run)['resources']['generation']['gemini']
    assert resource['cost_assessment'] == summarize_costs(google)
    assert resource['cost_assessment']['conditional_scenario_estimate_usd'] == 50
    assert resource['cost_assessment']['usage_priced_estimate_usd'] == 0
    assert resource['cost_assessment']['actual_billed_usd'] is None
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert 'Cost, usage and timing record' in html
    assert 'high_tool_input_included_full_price_search' in html
    assert '&quot;actual_billed_usd&quot;: null' in html


def test_lifetime_audit_costs_are_separate_from_saved_attempt_assessment(run, tmp_path):
    from crest.report import load_run, write_report
    doc = final_audit(run)
    doc['generation']['answer_details'][0]['known_usd'] = 2.5
    path = tmp_path / 'audit.json'; dump(path, doc)
    data = load_run(run, audit=path)
    caesar = data['resources']['generation']['caesar']
    assert caesar['known_cost_usd'] == 50
    assert caesar['audited_known_cost_usd'] == 51.5
    output = tmp_path / 'page.html'
    write_report(run, output, audit=path)
    assert 'Audited cumulative attempt estimate' in output.read_text()


def test_all_unpriced_answers_and_incomplete_lifetime_times_remain_unknown(run, tmp_path):
    from crest.report import load_run
    rows = json.loads(answers_path(run).read_text())
    for row in rows:
        if row['agent'] == 'openai':
            row['result']['cost_usd'] = None
    dump(answers_path(run), rows)
    doc = final_audit(run)
    for row in doc['generation']['answer_details']:
        if row['agent'] == 'openai':
            row.update(timing_complete=False, active_attempt_seconds=100)
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    resources = load_run(run, audit=audit)['resources']['generation']['openai']
    assert resources['known_cost_usd'] is None
    assert resources['mean_known_cost_usd'] is None
    assert resources['current_attempt_known_cost_usd'] is None
    assert resources['unknown_cost_answers'] == 50
    assert resources['median_lifetime_duration_seconds'] is None
    assert resources['mean_lifetime_duration_seconds'] is None
    assert resources['lifetime_duration_count'] == 0


def test_per_question_means_preserve_partial_costs_and_use_observed_times(run, tmp_path):
    from crest.report import load_run, write_report
    rows = json.loads(answers_path(run).read_text())
    caesar = [row for row in rows if row['agent'] == 'caesar']
    caesar[0]['result'].update(cost_usd=None, raw={
        'usage_audit': {'known_cost_usd': 3., 'unknown_cost': True},
        'new_attempt_usage_audit': {'known_cost_usd': 1., 'unknown_cost': False},
        'budget_history': {'previous_known_cost_usd': 2., 'previous_unknown_reserved_usd': .4}})
    caesar[0]['timing']['duration_seconds'] = 10
    caesar[1]['timing']['duration_seconds'] = 400
    google = [row for row in rows if row['agent'] == 'gemini']
    google[0]['result']['cost_usd'], google[1]['result']['cost_usd'] = 3., 5.
    dump(answers_path(run), rows)
    doc = final_audit(run)
    audited_caesar = [row for row in doc['generation']['answer_details'] if row['agent'] == 'caesar']
    audited_caesar[0].update(active_attempt_seconds=300, known_usd=3., exposure_upper_usd=3.4,
                             unknown_attempt_count=1)
    audited_caesar[1]['active_attempt_seconds'] = 600
    audited_google = [row for row in doc['generation']['answer_details'] if row['agent'] == 'gemini']
    for row, amount in zip(audited_google, (3., 5.)):
        row.update(known_usd=amount, exposure_upper_usd=amount)
    doc['ledger']['known_generation_attempt_usd'] = 159.
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    data = load_run(run, audit=audit)
    c = data['resources']['generation']['caesar']
    assert c['mean_known_cost_usd'] == pytest.approx(52 / 50)
    assert c['mean_duration_seconds'] == pytest.approx(5210 / 50)
    assert c['mean_lifetime_duration_seconds'] == pytest.approx(9300 / 50)
    assert c['median_duration_seconds'] == 100
    assert c['median_lifetime_duration_seconds'] == 175
    assert c['unknown_cost_answers'] == 1
    assert data['resources']['generation']['gemini']['mean_known_cost_usd'] == pytest.approx(56 / 50)
    output = tmp_path / 'page.html'
    write_report(run, output, audit=audit)
    html = output.read_text()
    assert 'Average estimated cost' in html
    assert 'Average generation time' in html
    assert 'Average active time, all attempts' in html
    assert '$1.0400' in html and '$1.1200' in html
    assert 'Caesar has unpriced' not in html
    assert 'Google’s estimate uses assumed model rates' in html
    assert '<small>partial estimate</small>' not in html
    assert '<small>conditional estimate</small>' not in html
    assert '<small>estimate</small>' not in html


def test_native_answer_disclosures_and_full_configuration_provenance(run, tmp_path):
    from crest.artifacts import answer_metadata, configuration_record
    from crest.report import write_report
    rows = json.loads(answers_path(run).read_text())
    rows[1]['result']['text'] += ' https://vertexaisearch.cloud.google.com/grounding-api-redirect/example'
    rows[2]['result']['text'] += ' https://example.org/?utm_source=openai'
    row = rows[0]
    task = {'agent': 'caesar', 'settings': {'model': 'gpt-6.1-sol', 'note': '<img src=x onerror=alert(1)>'},
            'adapter_version': 1, 'source_identity': None}
    configuration = configuration_record(task)
    configuration_id = configuration['configuration_id']
    row.update(answer_metadata(task, 1))
    dump(answers_path(run), rows)
    artifact = run / '01-generate-test' / row['answer_file']
    artifact.parent.mkdir(parents=True)
    artifact.write_text(row['result']['text'])
    registry = run / '01-generate-test/configurations.json'
    dump(registry, {configuration_id: configuration})
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert 'class="answer-links"' not in html
    assert 'class="full-question"' not in html
    assert html.count('Invent a useful research proposal for question 0.') == 1
    assert 'this run was not fully blinded' in html
    assert 'Links reveal provenance in 1 / 50 OpenAI (Sol + web search) answers' in html
    assert 'and 1 / 50 Google Deep Research answers' in html
    assert 'These cues do not establish that provider bias caused the ranking.' in html
    for label, source in [('Caesar', 'https://github.com/jasonzliang/caesar-agent'),
                          ('OpenAI (Sol + web search)', 'https://developers.openai.com/api/docs/guides/tools-web-search'),
                          ('Google Deep Research', 'https://ai.google.dev/gemini-api/docs/deep-research')]:
        assert f'<a href="{source}">{label}</a>' in html
    for index in range(1, 51):
        for agent, label in [('caesar', 'Caesar'),
                             ('gemini', 'Google Deep Research'),
                             ('openai', 'OpenAI (Sol + web search)')]:
            assert (f'<details class="answer" id="answer-{index}-{agent}">'
                    f'<summary>{label}</summary>') in html
            assert f'aria-label="{label} answer, question {index}"' in html
    assert '<summary>GPT-6 Astra · preferred' in html
    assert '<summary>Gemini 4 Argon · preferred' in html
    assert '&quot;model&quot;: &quot;gpt-6-astra&quot;' in html
    assert row['answer_file'] in html
    assert 'Local Markdown:' in html
    assert not re.search(r'href="[^\"]*' + re.escape(row['answer_file']) + r'"', html)
    assert configuration_id in html
    assert '&quot;configuration_sha256&quot;' in html
    assert '<img src=x' not in html and '&lt;img src=x' in html
    configuration['settings']['model'] = 'a different model'
    dump(registry, {configuration_id: configuration})
    with pytest.raises(ValueError, match='configuration|registry'):
        write_report(run, output)


def test_concise_results_keep_limits_visible_and_metadata_expandable(run, tmp_path):
    from crest.report import write_report
    rows = json.loads(answers_path(run).read_text())
    rows[1]['result']['text'] += ' https://vertexaisearch.cloud.google.com/grounding-api-redirect/example'
    rows[2]['result']['text'] += ' https://example.org/?utm_source=openai'
    dump(answers_path(run), rows)
    questions_file = run / '02-judge-test/questions.json'
    questions = json.loads(questions_file.read_text())
    questions[0]['text'] = 'A long question that needs its full text preserved. ' * 5
    dump(questions_file, questions)
    manifest = json.loads((run / 'run.json').read_text())
    manifest['questions'] = questions
    dump(run / 'run.json', manifest)
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()

    class Visibility(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.visible_text, self.visible_tables = [], [], []
            self.keys = {'Answer key:': 0, 'Judgment key:': 0}

        def visible(self):
            return all(i + 1 < len(self.stack) and self.stack[i + 1][0] == 'summary'
                       for i, (tag, _) in enumerate(self.stack) if tag == 'details')

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'table' and self.visible():
                self.visible_tables.append(next(a['aria-label'] for _, a in reversed(self.stack)
                                                if 'aria-label' in a))
            if tag not in {'meta', 'br'}:
                self.stack.append((tag, attrs))

        def handle_endtag(self, tag):
            assert self.stack.pop()[0] == tag

        def handle_data(self, text):
            if any(tag == 'main' for tag, _ in self.stack) and self.visible():
                self.visible_text.append(text)
            for key, cls in [('Answer key:', 'answer-metadata'), ('Judgment key:', 'judgment-metadata')]:
                if key in text:
                    assert any(cls in a.get('class', '').split() for _, a in self.stack)
                    self.keys[key] += 1

    parser = Visibility()
    parser.feed(html)
    visible = ' '.join(parser.visible_text)
    assert parser.visible_tables == ['Overall head-to-head preferences',
                                     'Per-question cost and elapsed-time means',
                                     'Per-judge overall preferences and order diagnostics']
    assert 'Google’s estimate uses assumed model rates' in visible
    assert 'internal billing breakdown is unavailable' in visible
    assert 'this run was not fully blinded' in html
    assert 'These cues do not establish that provider bias caused the ranking.' in html
    assert 'Factual accuracy has not been verified' in visible
    assert 'Chose A' in visible
    for detail in ['Paired 95% interval', 'Historical unknown reservations',
                   'gpt-6-astra', 'configuration_sha256', 'Answer key:', 'Judgment key:']:
        assert detail not in visible
    assert parser.keys == {'Answer key:': 150, 'Judgment key:': 600}
    assert html.count('class="answer-metadata"') == 150
    assert 'class="full-question"' not in html
    assert html.count(questions[0]['text']) == 1
    sections = ['overall', 'matchups', 'resources', 'method', 'judges', 'systems', 'questions']
    assert [html.index(f'id="{name}"') for name in sections] == sorted(html.index(f'id="{name}"') for name in sections)


def test_matrix_and_evidence_follow_saved_ranking_with_four_judgments_per_matchup(tmp_path):
    from crest.report import load_run, write_report
    preference = {'openai': 0, 'caesar': 1, 'gemini': 2}
    run = make_run(tmp_path / 'run', choose=lambda q, pair, judge, order: min(pair, key=preference.get))
    assert [r['agent'] for r in load_run(run)['ranking']['ranking']] == ['openai', 'caesar', 'gemini']
    output = tmp_path / 'page.html'
    write_report(run, output)

    class Layout(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.columns, self.rows, self.answers, self.groups, self.presentations = [], [], [], [], [], []
            self.outcomes = []
            self.diagonals = self.question_numbers = self.question_titles = 0

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            classes = attrs.get('class', '').split()
            if 'answer' in classes:
                self.answers.append(attrs['id'])
            if 'question-outcome' in classes:
                assert self.stack[-1][0] == 'summary'
                self.outcomes.append((attrs['data-winners'], attrs['data-wins']))
            if 'judgment-group' in classes:
                self.groups.append(0)
            if 'judgment' in classes:
                self.groups[-1] += 1
            if 'diagonal' in classes:
                assert attrs['aria-label'] == 'Same system; no comparison'
                assert attrs['role'] == 'img'
                self.diagonals += 1
            self.question_numbers += 'question-number' in classes
            self.question_titles += 'question-title' in classes
            if tag not in {'meta', 'br'}:
                self.stack.append((tag, attrs))

        def handle_endtag(self, tag):
            assert self.stack.pop()[0] == tag

        def handle_data(self, text):
            if any(tag == 'table' and a.get('class') == 'matrix' for tag, a in self.stack):
                scope = next((a.get('scope') for tag, a in reversed(self.stack) if tag == 'th'), None)
                if scope == 'col':
                    self.columns.append(text)
                elif scope == 'row':
                    self.rows.append(text)
            if any('presentation' in a.get('class', '').split() for _, a in self.stack):
                self.presentations.append(text)

    parser = Layout()
    parser.feed(output.read_text())
    names = ['OpenAI (Sol + web search)', 'Caesar', 'Google Deep Research']
    assert parser.columns == ['Row / column', *names]
    assert parser.rows == names and parser.diagonals == 3
    assert parser.answers == [f'answer-{i}-{agent}' for i in range(1, 51) for agent in ['openai', 'caesar', 'gemini']]
    assert parser.groups == [4] * 150
    assert len(parser.presentations) == 600
    assert set(parser.presentations) == {f'A: {a} · B: {b}' for a in names for b in names if a != b}
    assert parser.question_numbers == parser.question_titles == 50
    assert parser.outcomes == [('openai', '8')] * 50


def test_questions_group_by_dataset_category_without_changing_snapshot_order_or_ids(run, tmp_path):
    from crest.report import ROOT, write_report
    source = [json.loads(line) for line in (ROOT / 'crest/data/queries_n50.jsonl').read_text().splitlines()]
    path = run / '02-judge-test/questions.json'
    questions = json.loads(path.read_text())
    for question, row in zip(questions, reversed(source)):
        question['text'] = row['query']
    dump(path, questions)
    manifest = json.loads((run / 'run.json').read_text())
    manifest['questions'] = questions
    dump(run / 'run.json', manifest)
    original = path.read_bytes()
    output = tmp_path / 'page.html'
    write_report(run, output)

    class Groups(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sections, self.groups = [], {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'section':
                self.sections.append(attrs.get('data-category'))
            if attrs.get('class') == 'question':
                category = next((c for c in reversed(self.sections) if c), None)
                self.groups.setdefault(category, []).append(attrs['id'])

        def handle_endtag(self, tag):
            if tag == 'section':
                self.sections.pop()

    parser = Groups()
    parser.feed(output.read_text())
    lookup = {row['query']: row['category'] for row in source}
    expected = {row['category']: [] for row in source}
    for index, question in enumerate(questions, 1):
        expected[lookup[question['text']]].append(f'question-{index}')
    assert list(parser.groups) == list(expected)
    assert parser.groups == expected
    assert all(len(group) == 10 for group in parser.groups.values())
    assert path.read_bytes() == original


def test_all_frozen_configurations_render_with_nonnull_shared_prompt_template(run, tmp_path):
    from crest.artifacts import answer_metadata, configuration_record
    from crest.report import load_run, write_report
    manifest_path = run / 'run.json'
    manifest = json.loads(manifest_path.read_text())
    template = 'Research the shared question carefully: {question}\nPreserve <primary> evidence.'
    manifest['config']['research_prompt'] = template
    dump(manifest_path, manifest)
    rows = json.loads(answers_path(run).read_text())
    registry = {}
    for index, row in enumerate(rows):
        settings = deepcopy(manifest['config']['research'][row['agent']])
        if row['agent'] == 'caesar' and index // 3 < 10:
            settings['budget_history_from'] = f'prior/question-{index // 3}'
        task = {'agent': row['agent'], 'settings': settings,
                'adapter_version': 1, 'source_identity': None}
        record = configuration_record(task, prompt_template=manifest['config']['research_prompt'])
        registry[record['configuration_id']] = record
        row.update(answer_metadata(task, index // 3 + 1, prompt_template=template))
    dump(answers_path(run), rows)
    dump(run / '02-judge-test/configurations.json', registry)
    output = tmp_path / 'page.html'
    write_report(run, output)
    data = load_run(run)
    assert len(data['configurations']) == 13
    assert all(record['prompt_template'] == template for record in data['configurations'].values())
    html = output.read_text()
    assert html.count('class="answer"') == 150
    assert html.count('class="judgment"') == 600
    assert '&lt;primary&gt;' in html
    assert 'fully-priced-only' not in html


def test_legacy_answer_link_fallback_and_unsafe_artifact_path_refusal(run, tmp_path):
    from crest.report import write_report
    old = run / '01-generate-test/answers/q000/caesar.md'
    old.parent.mkdir(parents=True); old.write_text('legacy readable copy')
    output = tmp_path / 'page.html'
    write_report(run, output)
    assert 'answers/q000/caesar.md' in output.read_text()
    rows = json.loads(answers_path(run).read_text())
    rows[0]['answer_file'] = '../../private.md'
    dump(answers_path(run), rows)
    with pytest.raises(ValueError, match='answer.*path|artifact.*path'):
        write_report(run, output)


def test_superseded_judgments_are_retained_but_excluded_from_published_cost_and_votes(run, tmp_path):
    from crest.report import load_run, write_report
    current = [json.loads(line) for line in (run / '02-judge-test/judgments.jsonl').read_text().splitlines()]
    prior = [{'key': f'prior-{i}', 'stage': 'judge', 'cost_usd': .2, 'usage': {}, 'model': 'gpt-6-astra',
              'replacement_key': current[i]['key'], 'correction_id': 'duplicate-answer-correction',
              'valid_for_ranking': False} for i in range(4)]
    file = run / '02-judge-test/prior_judgment_costs.jsonl'
    file.write_text(''.join(json.dumps(row) + '\n' for row in [*prior, prior[0]]))
    before = load_run(run)
    assert before['resources']['prior_judging']['records'] == 4
    assert before['resources']['prior_judging']['cumulative_known_estimate_usd'] == pytest.approx(.8)
    assert before['ranking']['coverage']['valid_judgments'] == 600
    output = tmp_path / 'page.html'
    write_report(run, output)
    text = output.read_text()
    assert 'superseded' not in text
    assert 'Total for 600 judgments: $60.0000' in text
    assert '$60.8000' not in text
    assert text.count('class="judgment"') == 600
    # An old paid key cannot also be counted as a currently scored verdict.
    prior[0]['key'] = current[0]['key']
    file.write_text(json.dumps(prior[0]) + '\n')
    with pytest.raises(ValueError, match='prior|superseded'):
        load_run(run)


def test_duplicate_prior_jobs_do_not_change_published_current_cost(run):
    from crest.report import load_run, _resources
    prior = {'key': 'prior-job', 'stage': 'judge', 'valid_for_ranking': False,
             'cost_usd': .3, 'cost_scope': 'all_judgment_attempts', 'attempts': [
                 {'key': 'prior-rejected', 'status': 'rejected', 'cost_usd': .2},
                 {'key': 'prior-completed', 'status': 'completed', 'cost_usd': .1}]}
    path = run / '02-judge-test/prior_judgment_costs.jsonl'
    path.write_text(''.join(json.dumps(prior) + '\n' for _ in range(2)))
    data = load_run(run)
    html = _resources(data)
    assert data['resources']['prior_judging']['records'] == 1
    assert data['resources']['paid_judging']['cumulative_known_estimate_usd'] == pytest.approx(60.3)
    assert 'Total for 600 judgments: $60.0000' in html
    assert '$60.3000' not in html
    assert 'superseded' not in html
    assert data['ranking']['coverage']['valid_judgments'] == 600


@pytest.mark.parametrize('ledger_directory', ['02-judge-test', ''])
def test_prior_ledger_stays_in_source_records_and_out_of_html(run, tmp_path, ledger_directory):
    from crest.report import load_run, write_report, _questions
    evidence = _questions(load_run(run))
    marker = 'PRIOR_RAW_PAYLOAD_RETAINED_ONLY_IN_CANONICAL_JSONL'
    payload = marker + 'x' * 20000
    prior = {'key': 'prior-paid-job', 'judge': 'openai', 'stage': 'judge',
             'source_judgment_directory': '02-judge-previous', 'valid_for_ranking': False,
             'cost_usd': None, 'known_cost_usd': .2, 'unknown_cost_count': 1,
             'cost_scope': 'all_judgment_attempts', 'cache_record': 'cache/prior-paid-job.json',
             'usage': {'events': [payload]}, 'raw': {'request': payload},
             'result': {'text': payload, 'raw': {'prompt': payload}}, 'attempts': [
                 {'key': 'prior-rejected', 'status': 'rejected', 'cost_usd': .2,
                  'cache_record': 'cache/attempts/prior-rejected.json',
                  'result': {'text': payload, 'raw': {'prompt': payload}}},
                 {'key': 'prior-unpriced', 'status': 'failed', 'cost_usd': None,
                  'cache_record': 'cache/attempts/prior-unpriced.json',
                  'usage': {'events': [payload]}, 'result': {'raw': {'answers': payload}}}]}
    ledger = run / ledger_directory / 'prior_judgment_costs.jsonl'
    ledger.write_text(''.join(json.dumps(prior) + '\n' for _ in range(2)))
    original = ledger.read_bytes()
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert marker not in html
    assert ledger.relative_to(run).as_posix() not in html
    assert 'prior-paid-job' not in html
    data = load_run(run)
    assert data['prior_judgments'] == [prior, prior]
    assert data['resources']['prior_judging']['cumulative_known_estimate_usd'] == .2
    assert data['resources']['prior_judging']['unknown_count'] == 1
    assert 'Total for 600 judgments: $60.0000' in html
    assert '$60.2000' not in html
    assert evidence in html
    assert html.count('class="answer"') == 150 and html.count('class="reason"') == 600
    assert ledger.read_bytes() == original
