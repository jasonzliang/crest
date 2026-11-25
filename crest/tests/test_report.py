"""Offline publication, provenance, accounting and escaping contracts for CREST HTML."""
from copy import deepcopy
from html.parser import HTMLParser
from itertools import combinations
import json
import hashlib
import re

import pytest

from crest import analysis


_ANALYSES = {}


def analyze(questions, answers, judgments, **options):
    """Pure `crest.analysis.analyze`, memoized per worker on its exact inputs.

    Each fixture run and each `load_run` validation repeats the same 1000-sample
    bootstrap; reusing identical results keeps the comparison in report.py intact."""
    key = hashlib.sha256(json.dumps([questions, answers, judgments, options], sort_keys=True,
                                    default=str).encode()).hexdigest()
    if key not in _ANALYSES:
        _ANALYSES[key] = analysis.analyze(deepcopy(questions), deepcopy(answers), deepcopy(judgments),
                                          **options)
    return deepcopy(_ANALYSES[key])


@pytest.fixture(autouse=True)
def memoized_analysis(monkeypatch):
    monkeypatch.setattr('crest.report.analyze', analyze)


AGENTS = ['caesar', 'gemini', 'openai']
JUDGES = ['gemini', 'openai']
FOUR_AGENTS = ['caesar', 'gemini', 'openai', 'anthropic']
THREE_JUDGES = ['gemini', 'openai', 'anthropic']
MODELS = {'caesar': 'gpt-6.1-sol', 'openai': 'gpt-6.1-sol', 'gemini': 'gemini-3.1-pro-preview',
          'anthropic': 'claude-sonnet-5-5'}
RESEARCH = {'caesar': {'model': 'gpt-6.1-sol', 'exploration_model': 'gpt-6-luna', 'kb_model': 'gpt-6-luna', 'budget_usd': 5},
            'openai': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'budget_usd': 5},
            'gemini': {'agent': 'deep-research-preview-04-2026', 'billing_model': 'gemini-3.1-pro-preview', 'budget_usd': 5},
            'anthropic': {'model': 'claude-sonnet-5-5', 'effort': 'max', 'budget_usd': 4}}
JUDGE_SETTINGS = {'openai': {'model': 'gpt-6-astra', 'reasoning_effort': 'high'},
                  'gemini': {'model': 'gemini-4-argon', 'thinking_level': 'high'},
                  'anthropic': {'model': 'claude-fable-5-1', 'effort': 'high'}}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def make_run(root, *, choose=None, agents=AGENTS, judges=JUDGES):
    choose = choose or (lambda q, pair, judge, order: pair[q % 2])
    questions = [{'id': f'q{i:03}', 'text': f'Invent a useful research proposal for question {i}.'} for i in range(50)]
    answers, judgments = [], []
    for i, q in enumerate(questions):
        for agent in agents:
            answers.append({'question_id': q['id'], 'agent': agent, 'key': f'answer-{q["id"]}-{agent}',
                            'result': {'text': f'Complete substantive answer from {agent} for {q["id"]}.',
                                       'model': MODELS.get(agent, 'unrecorded-model'),
                                       'cost_usd': 1.0, 'cost_estimated': True, 'usage': {},
                                       'raw': {'agent': 'deep-research-preview-04-2026'} if agent == 'gemini' else {}},
                            'timing': {'started_at': '2026-10-27T00:00:00+00:00',
                                       'completed_at': '2026-10-27T00:01:40+00:00', 'duration_seconds': 100,
                                       'source': 'checkpoint:first_started_at/completed_at',
                                       'definition': 'Client elapsed; excludes local scheduling.'}})
        for pair in combinations(sorted(agents), 2):  # judging.make_judgment_jobs stores sorted pairs
            for judge in judges:
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
    manifest = {'schema': 'crest-run-v1', 'agents': list(agents), 'questions': questions,
                'config': {'research': {agent: RESEARCH.get(agent, {'budget_usd': 5}) for agent in agents}},
                'stages': [{'name': name, 'directory': directory, 'status': 'completed'} for name, directory in
                           [('generate', generation), ('judge', judging), ('analysis', analysis)]]}
    dump(root / 'run.json', manifest)
    dump(root / generation / 'manifest.json', {'status': 'completed'})
    dump(root / judging / 'manifest.json', {'status': 'completed', 'generation_directory': generation})
    dump(root / analysis / 'manifest.json', {'status': 'completed', 'judgment_directory': judging})
    dump(root / judging / 'questions.json', questions)
    dump(root / judging / 'answers.json', answers)
    judge_settings = {judge: JUDGE_SETTINGS[judge] for judge in JUDGE_SETTINGS if judge in judges}
    dump(root / judging / 'judges.json', judge_settings)
    (root / judging / 'judgments.jsonl').write_text(''.join(json.dumps(j) + '\n' for j in judgments))
    (root / judging / 'rubric.txt').write_text('New, Useful and Surprising guide one overall A/B winner.')
    # Same judge order load_run reads from judges.json, so its validation reuses this analysis.
    ranking = analyze(questions, answers, judgments, agents=list(agents), judges=list(judge_settings),
                      bootstrap_samples=1000, seed=2026)
    dump(root / analysis / 'ranking.json', ranking)
    return root


@pytest.fixture
def run(tmp_path):
    return make_run(tmp_path / 'experiment')


def answers_path(run):
    return run / '02-judge-test/answers.json'


def ranking_path(run):
    return run / '03-analysis-test/ranking.json'


def make_aut_run(run):
    from crest.presentation import PRESENTATION_VERSION, present_answer
    path = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    answers = json.loads(answers_path(run).read_text())
    answer_map = {(a['question_id'], a['agent']): a for a in answers}
    for row in rows:
        row.update(protocol_version='aut-inspired-overall-pairwise-v1', rubric_kind='aut-inspired',
                   presentation_version=PRESENTATION_VERSION)
        row['presented_answer_hashes'] = [hashlib.sha256(present_answer(
            answer_map[row['question_id'], agent]['result']['text']).encode()).hexdigest()
            for agent in row['order']]
        row['verdict']['reason'] = 'A develops a distinct causal mechanism, while B supplies a familiar explanation.'
        row['result']['text'] = json.dumps(row['verdict'])
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    questions = json.loads((run / '02-judge-test/questions.json').read_text())
    agents = json.loads((run / 'run.json').read_text())['agents']
    judges = list(json.loads((run / '02-judge-test/judges.json').read_text()))
    dump(ranking_path(run), analyze(questions, answers, rows, agents=agents, judges=judges,
                                    bootstrap_samples=1000, seed=2026))
    return rows


def test_aut_publication_labels_the_actual_rubric_and_preserves_frozen_evidence(run, tmp_path):
    from crest.report import write_report
    make_aut_run(run)
    evidence = (run / '02-judge-test/judgments.jsonl').read_bytes()
    output = write_report(run, tmp_path / 'aut.html')
    html = output.read_text()
    assert 'AUT-inspired' in html
    assert all(f'<strong>{name}</strong>' in html for name in ('Fluency', 'Flexibility', 'Originality'))
    assert 'aut-inspired-rubric.html' in html
    assert 'qualitative adaptation' in html
    assert 'not comparable across paper topics' in html
    assert 'preferences under this rubric' in html
    assert '<strong>Useful</strong>' not in html and '<strong>Surprising</strong>' not in html
    assert (run / '02-judge-test/judgments.jsonl').read_bytes() == evidence


@pytest.mark.parametrize('kind', ['invalid', 'wrong_family', 'missing_aut_kind', 'mixed', 'row_mislabeled', 'bad_presentation', 'bad_reason'])
def test_publication_rejects_inconsistent_aut_metadata(run, kind):
    from crest.report import load_run
    rows = make_aut_run(run)
    ranking = json.loads(ranking_path(run).read_text())
    if kind == 'invalid':
        ranking['rubric_kind'] = 'unknown'
    elif kind == 'wrong_family':
        ranking['rubric_kind'] = 'nus'
    elif kind == 'missing_aut_kind':
        ranking.pop('rubric_kind')
    elif kind == 'mixed':
        rows[0].update(protocol_version='nus-overall-pairwise-v3', rubric_kind='nus')
    elif kind == 'row_mislabeled':
        rows[0]['rubric_kind'] = 'nus'
    elif kind == 'bad_presentation':
        rows[0]['presented_answer_hashes'] = ['wrong', 'wrong']
    else:
        rows[0]['verdict']['reason'] = 'Return JSON only.'
        rows[0]['result']['text'] = json.dumps(rows[0]['verdict'])
    dump(ranking_path(run), ranking)
    (run / '02-judge-test/judgments.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError):
        load_run(run)


def test_legacy_nus_rendering_matches_explicit_family_and_model_notes_cite_provider_history(run, tmp_path):
    from crest.report import load_run, _models, _render
    data = load_run(run)
    # Model notes cite provider history and preserve this run's uncertainty.
    html = _models(data)
    assert '<td>High</td>' in html
    assert 'built with Gemini 3.1 Pro' in html
    assert 'Google chooses the models it runs and does not report them' in html
    assert 'July 23, 2026' in html
    assert 'o3-deep-research' in html and 'o4-mini-deep-research' in html
    for source in [
        'https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/',
        'https://developers.openai.com/api/docs/deprecations',
        'https://developers.openai.com/api/docs/guides/deep-research',
    ]:
        assert f'href="{source}"' in html
    data['ranking'].pop('rubric_kind', None)
    legacy = _render(data, tmp_path / 'nus.html')
    data['ranking']['rubric_kind'] = 'nus'
    assert _render(data, tmp_path / 'nus.html') == legacy
    assert '<strong>Useful</strong>' in legacy and 'AUT-inspired' not in legacy
    assert 'href="nus-rubric.html">NUS Rubric</a>' in legacy
    assert 'href="why-one-overall-judgment.html">Why One Overall Judgment</a>' in legacy
    assert '<link rel="icon" type="image/svg+xml"' in legacy


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
    data = {'ranking': {'bootstrap': {'seed': 2026},
                        'ranking': [{'agent': agent} for agent in AGENTS]}, 'manifest': {},
            'judges': {judge: JUDGE_SETTINGS[judge] for judge in JUDGES},
            'judgments': [{'protocol_version': 'nus-overall-pairwise-v3',
                           'presentation_version': 'citation-neutral-v1'}],
            'answers': [{'agent': 'openai', 'result': {'text': 'https://example.com?utm_source=openai'}},
                        {'agent': 'gemini', 'result': {'text': 'https://vertexaisearch.cloud.google.com/source'}}]}
    html = _method(data)
    assert 'We hid the link addresses in every answer the same way and kept the citation labels and all other text.' in html
    assert 'The answers below are the originals.' in html
    assert 'this run was not fully blinded' not in html


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
    assert 'The 600 judgments cost $60.05 in total, including retried calls.' in html
    assert 'Includes the cost of retried calls.' not in html
    assert 'replaced' not in html
    assert path.read_bytes() == original
    assert data['judgments'][0]['result']['cost_usd'] == .1


def test_refuses_incomplete_publication_without_overwriting_destination(run, tmp_path):
    from crest.report import write_report
    answers = json.loads(answers_path(run).read_text())
    dump(answers_path(run), answers[:-1])
    output = tmp_path / 'docs/deep-research-comparison-v1.html'
    output.parent.mkdir()
    output.write_text('previous verified report')
    with pytest.raises(ValueError, match='150|answer'):
        write_report(run, output)
    assert output.read_text() == 'previous verified report'


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'invalid_winner', 'wrong_answer_key', 'unsorted_pair'])
def test_refuses_missing_duplicate_or_mismatched_judgment_cells(run, tmp_path, kind):
    from crest.report import write_report
    file = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    if kind == 'missing': rows.pop()
    elif kind == 'duplicate': rows[-1] = deepcopy(rows[0])
    elif kind == 'invalid_winner': rows[0]['verdict']['winner'] = 'tie'
    elif kind == 'unsorted_pair': rows[0]['pair'].reverse()  # analysis scores only canonical sorted pairs
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
    assert '200 of 400 won' in text
    assert '1,000' in text and 'question' in text
    assert 'Serfling' not in text
    assert 'OpenAI (Sol + web search)' in text
    assert 'this run was not fully blinded' not in text
    assert 'does not report them' in text
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
    for markup in ['<h5>Example</h5>', '<strong>strong</strong>', '<em>emphasis</em>',
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
    assert 'Usage events left out of this page: 2.' in html
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


def test_manifest_stage_paths_cannot_escape_run_directory(run, tmp_path):
    from crest.report import write_report
    manifest = json.loads((run / '03-analysis-test/manifest.json').read_text())
    manifest['judgment_directory'] = '../outside'
    dump(run / '03-analysis-test/manifest.json', manifest)
    with pytest.raises(ValueError, match='stage|directory|run'):
        write_report(run, tmp_path / 'page.html')


def final_audit(run):
    rows = json.loads(answers_path(run).read_text())
    judgments = sum(1 for line in (run / '02-judge-test/judgments.jsonl').read_text().splitlines() if line.strip())
    return {'audit_version': 'crest-final-audit-v1', 'status': 'complete', 'ready': True,
            'run_dir': str(run), 'errors': [], 'pending': [],
            'warnings': ['Billing remains estimated; no invoice has been verified.'],
            'generation': {'completed_answers': len(rows), 'snapshot_answer_rows': len(rows),
                'answer_details': [{'question_id': row['question_id'], 'agent': row['agent'], 'key': row['key'],
                    'status': 'completed', 'known_usd': 1., 'unknown_attempt_count': 0,
                    'exposure_upper_usd': 1., 'attempt_keys': [row['key']],
                    'active_attempt_seconds': 175., 'active_time_limit_seconds': 7200,
                    'timing_complete': True} for row in rows]},
            'judging': {'valid_calls': judgments, 'complete_questions': 50, 'known_estimated_usd': 60.,
                        'failed_known_usd': .25, 'failed_unknown_cost_count': 1,
                        'failed_partial_observed_usd': .1},
            'ranking': {'matches_independent_calculation': True},
            'ledger': {'known_generation_attempt_usd': 151., 'unknown_reserved_usd': .4,
                       'failed_known_usd': 1., 'unbounded_unknown_attempts': 0},
            'input_sha256': {str(path): __import__('hashlib').sha256(path.read_bytes()).hexdigest()
                            for path in [run / 'run.json', ranking_path(run),
                                         run / '02-judge-test/questions.json', answers_path(run),
                                         run / '02-judge-test/judgments.jsonl', run / '02-judge-test/judges.json']}}


@pytest.mark.parametrize('kind', ['another_run', 'changed_snapshot'])
def test_audit_requires_matching_run_identity_and_selected_frozen_snapshot_hashes(run, tmp_path, kind):
    from crest.report import write_report
    if kind == 'another_run':
        doc = {'audit_version': 'crest-final-audit-v1', 'status': 'complete', 'ready': True, 'run_dir': 'another-run'}
        match = 'audit'
    else:
        doc = final_audit(run)
        doc['input_sha256'][str(answers_path(run))] = '0' * 64
        match = 'audit|hash|snapshot'
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    with pytest.raises(ValueError, match=match):
        write_report(run, tmp_path / 'page.html', audit=audit)


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
    assert 'Audited lifetime generation estimates' not in html


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


def test_without_final_audit_the_cost_section_omits_total_recorded_time(run, tmp_path):
    from crest.report import write_report
    from lxml import html
    output = write_report(run, tmp_path / 'page.html')
    section = html.fromstring(output.read_text()).xpath('//section[@id="resources"]')[0]
    text = ' '.join(section.text_content().split())
    headers = [' '.join(th.text_content().split()) for th in section.xpath('.//th')]
    assert 'Mean total recorded time' not in headers and 'Median total recorded time' not in headers
    assert 'Answers with complete total time' not in headers
    assert 'final audit' not in text and 'Total recorded time' not in text
    assert 'Costs are estimates from each answer’s saved records, not invoices.' in text


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
    assert 'Audited lifetime generation estimates' in output.read_text()
    assert '$50.00' in output.read_text() and '$51.50' in output.read_text()


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
    assert 'Mean estimated cost' in html
    assert 'Mean job time' in html
    assert 'Mean time including earlier attempts' in html
    assert '$1.04' in html and '$1.12' in html
    assert 'Caesar has unpriced' not in html
    assert 'Google does not report its billing, so its estimate assumes Gemini 3.1 Pro rates' in html
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
    for judge in ['GPT-6 Astra', 'Gemini 4 Argon']:
        assert re.search(f'<summary>{judge} · [^<·]+ shown first · preferred [^<]+</summary>', html)
    assert '<span class="nowrap">gpt-6-astra</span>' in section(html, 'judges')
    assert 'api_key_env' not in section(html, 'judges') and 'api_base' not in section(html, 'judges')
    assert row['answer_file'] in html
    assert 'Local Markdown:' in html
    assert not re.search(r'href="[^\"]*' + re.escape(row['answer_file']) + r'"', html)
    assert configuration_id in html
    assert '&quot;configuration_sha256&quot;' in html
    # The settings are printed once and the answer links to them.
    assert html.count(f'id="settings-{configuration_id}"') == 1
    assert html.count('&quot;configuration_sha256&quot;') == 1
    assert f'<a href="#settings-{configuration_id}">Saved research settings</a>' in html
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
            if tag not in {'meta', 'link', 'br'}:
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
    assert parser.visible_tables == ['Overall head-to-head preferences', 'Win rates by judge',
                                     'Answer-order checks by judge', 'Mean cost, time, and length per answer']
    assert visible.count('assumes Gemini 3.1 Pro rates') == 1
    assert 'this run was not fully blinded' in html
    assert 'These cues do not establish that provider bias caused the ranking.' in html
    assert 'The judges did not check facts.' in visible
    assert 'Share won by the answer shown first' in visible
    for detail in ['How often the first led', 'Historical unknown reservations',
                   'gpt-6-astra', 'configuration_sha256', 'Answer key:', 'Judgment key:']:
        assert detail not in visible
    assert parser.keys == {'Answer key:': 150, 'Judgment key:': 600}
    assert html.count('class="answer-metadata"') == 150
    assert 'class="full-question"' not in html
    assert html.count(questions[0]['text']) == 1
    sections = ['overall', 'matchups', 'judges', 'resources', 'method', 'systems', 'questions']
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
            self.diagonal_text, self.diagonal_texts = False, []

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
                assert 'role' not in attrs and 'aria-label' not in attrs  # The hidden text names the cell.
                self.diagonal_text = True
                self.diagonals += 1
            self.question_numbers += 'question-number' in classes
            self.question_titles += 'question-title' in classes
            if tag not in {'meta', 'link', 'br'}:
                self.stack.append((tag, attrs))

        def handle_endtag(self, tag):
            assert self.stack.pop()[0] == tag
            if self.diagonal_text:  # The diagonal cell closed without text.
                self.diagonal_texts.append('')
                self.diagonal_text = False

        def handle_data(self, text):
            if self.diagonal_text:
                self.diagonal_texts.append(text)
                self.diagonal_text = False
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
    assert parser.columns == ['Win rate of row system against column system', *names]
    assert parser.rows == names and parser.diagonals == 3 and parser.diagonal_texts == ['Same system; no comparison'] * 3
    assert parser.answers == [f'answer-{i}-{agent}' for i in range(1, 51) for agent in ['openai', 'caesar', 'gemini']]
    assert parser.groups == [4] * 150
    assert len(parser.presentations) == 600
    assert set(parser.presentations) == {f'Shown first (A): {a}; shown second (B): {b}' for a in names for b in names if a != b}
    assert parser.question_numbers == parser.question_titles == 50
    assert parser.outcomes == [('openai', '8')] * 50


def test_questions_group_by_dataset_category_without_changing_snapshot_order_or_ids(run, tmp_path):
    from crest.report import ROOT, write_report
    source = [json.loads(line) for line in (ROOT / 'crest/data/queries_n50_v1.jsonl').read_text().splitlines()]
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
    assert 'Earlier judging that this round replaced is not included.' in text
    assert 'The 600 judgments cost $60.00 in total, including retried calls.' in text
    assert '$60.80' not in text
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
    assert 'The 600 judgments cost $60.00 in total, including retried calls.' in html
    assert '$60.30' not in html
    assert 'Earlier judging that this round replaced is not included.' in html
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
    assert 'The 600 judgments cost $60.00 in total, including retried calls.' in html
    assert '$60.20' not in html
    assert evidence in html
    assert html.count('class="answer"') == 150 and html.count('class="reason"') == 600
    assert ledger.read_bytes() == original


def test_four_agent_three_judge_run_renders_computed_totals_and_anthropic_labels(tmp_path):
    from crest.report import load_run, write_report
    run = make_run(tmp_path / 'run', agents=FOUR_AGENTS, judges=THREE_JUDGES)
    data = load_run(run)
    assert data['ranking']['agents'] == sorted(FOUR_AGENTS)
    assert data['ranking']['coverage']['valid_judgments'] == 1800
    assert set(data['resources']['generation']) == set(FOUR_AGENTS)
    assert set(data['resources']['judging']) == set(THREE_JUDGES)
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert html.count('class="question"') == 50
    assert html.count('class="answer"') == 200
    assert html.count('class="judgment"') == 1800
    assert '<strong>200</strong><span>answers</span>' in html
    assert '<strong>1,800</strong><span>pairwise judgments</span>' in html
    assert 'Three AI models act as judges. They compare the 200 answers two at a time' in html
    assert 'The 1,800 judgments cost $180.00 in total, including retried calls.' in html
    # 50 questions × 3 opponents × 2 orders × 3 judges = 900 judgments per system.
    assert 'its wins divided by its 900 judgments (50 questions, three opponents, three judges, both answer orders)' in html
    assert 'of 900 won' in html and 'of 400 won' not in html
    assert 'out of 300 judgments for each pair of systems' in html
    assert ('Each question has 36 judgments, from 6 answer pairs that three judges each saw in both orders. Each '
            'system takes part in 18 of them per question and 900 in total.') in html
    assert 'lists all 4 answers and its 36 judgments.' in html
    assert 'Read all 36 judgments' in html
    assert 'of its 18 judgments' in html
    assert 'All three judges saw every pair in both orders, with no web access' in html and 'Both judges' not in html
    assert ('<a href="https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool">'
            'Anthropic (Claude + web search)</a>') in html
    assert '<td>Max</td><td>Sonnet with Anthropic’s built-in web search.</td>' in html
    assert re.search('<summary>Claude Fable 5.1 · [^<·]+ shown first · preferred', html)
    assert '<span class="nowrap">claude-fable-5-1</span>' in section(html, 'judges')
    assert 'https://platform.claude.com/docs/en/about-claude/pricing' in html
    for index in range(1, 51):
        assert (f'<details class="answer" id="answer-{index}-anthropic">'
                '<summary>Anthropic (Claude + web search)</summary>') in html
    # A final audit must carry the computed totals (200 answers, 1,800 valid calls), not the old 150/600.
    audit = final_audit(run)
    dump(run / '04-audit-test/audit.json', audit)
    assert load_run(run)['audit_path'] == run / '04-audit-test/audit.json'
    audit['judging']['valid_calls'] = 600
    dump(run / '04-audit-test/audit.json', audit)
    with pytest.raises(ValueError, match='Final audit'):
        load_run(run)
    (run / '04-audit-test/audit.json').unlink()
    outcomes = re.findall(r'class="question-outcome" data-winners="([^"]+)" data-wins="(\d+)"', html)
    assert len(outcomes) == 50 and all(int(wins) <= 18 for _, wins in outcomes)


def test_two_agent_single_judge_run_renders_singular_counts_and_skips_absent_providers(tmp_path):
    from crest.report import load_run, write_report
    run = make_run(tmp_path / 'run', agents=['caesar', 'openai'], judges=['openai'])
    data = load_run(run)
    assert data['ranking']['coverage']['valid_judgments'] == 100
    assert data['ranking']['diagnostics']['judge_disagreement']['comparisons'] == 0
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert html.count('class="answer"') == 100 and html.count('class="judgment"') == 100
    assert '<strong>100</strong><span>answers</span>' in html
    assert '<strong>100</strong><span>pairwise judgments</span>' in html
    assert 'runs Caesar and OpenAI (Sol + web search) on the same 50 questions' in html
    assert 'One AI model acts as the judge. It compares the 100 answers two at a time' in html
    assert 'its wins divided by its 100 judgments (50 questions, one opponent, one judge, both answer orders)' in html
    assert ('Each question has 2 judgments, from 1 answer pair that one judge saw in both orders. Each system '
            'takes part in 2 of them per question and 100 in total.') in html
    assert 'out of 100 judgments for each pair of systems' in html
    assert 'of its 2 judgments' in html
    assert 'The judge saw every pair in both orders, with no web access' in html
    assert 'Judges disagree' not in html and 'Unavailable' not in html
    assert 'The 100 judgments cost $10.00 in total, including retried calls.' in html
    assert 'Google' not in html and 'Gemini' not in html
    assert 'Links reveal provenance' not in html
    assert '>GPT-6.1 Sol</a>' in html and 'platform.claude.com' not in html


def test_unknown_agent_falls_back_to_identifier_label_default_color_and_no_link(tmp_path):
    from crest.report import DEFAULT_COLOR, write_report
    run = make_run(tmp_path / 'run', agents=['caesar', 'openai', 'mystery'], judges=['openai'])
    output = tmp_path / 'page.html'
    write_report(run, output)
    html = output.read_text()
    assert html.count('class="answer"') == 150 and html.count('class="judgment"') == 300
    assert '<strong>mystery</strong></div>' in html
    assert f'fill="{DEFAULT_COLOR}"' in html
    assert ('<th scope="row">mystery</th><td><span class="nowrap">unrecorded-model</span></td><td>Not recorded</td>'
            '<td>See the saved settings with each answer.</td>') in html
    assert '<summary>mystery</summary>' in html
    assert not re.search(r'<a href="[^"]*">mystery</a>', html)


@pytest.mark.parametrize('kind', ['extra_agent', 'missing_agent', 'duplicate', 'single', 'not_a_list', 'bad_identifier'])
def test_manifest_agents_must_match_saved_answers_and_be_valid_identifiers(run, tmp_path, kind):
    from crest.report import write_report
    manifest = json.loads((run / 'run.json').read_text())
    manifest['agents'] = {'extra_agent': [*AGENTS, 'anthropic'], 'missing_agent': AGENTS[:2],
                          'duplicate': [*AGENTS[:2], AGENTS[0]], 'single': AGENTS[:1],
                          'not_a_list': ' '.join(AGENTS), 'bad_identifier': [*AGENTS[:2], 'open ai']}[kind]
    dump(run / 'run.json', manifest)
    expected = ('unique complete answers' if kind in ('extra_agent', 'missing_agent')
                else 'at least two unique research agent identifiers')
    with pytest.raises(ValueError, match=expected):
        write_report(run, tmp_path / 'page.html')
    assert not (tmp_path / 'page.html').exists()


@pytest.mark.parametrize('kind', ['extra', 'missing', 'empty', 'not_settings'])
def test_judges_file_must_match_saved_judgments(run, tmp_path, kind):
    from crest.report import write_report
    path = run / '02-judge-test/judges.json'
    settings = json.loads(path.read_text())
    if kind == 'extra': settings['anthropic'] = JUDGE_SETTINGS['anthropic']
    elif kind == 'missing': settings.pop('gemini')
    elif kind == 'empty': settings = {}
    else: settings['openai'] = 'gpt-6-astra'
    dump(path, settings)
    expected = {'extra': 'valid overall judgments', 'missing': 'invalid judgment cell',
                'empty': 'judges.json must map', 'not_settings': 'judges.json must map'}[kind]
    with pytest.raises(ValueError, match=expected):
        write_report(run, tmp_path / 'page.html')
    assert not (tmp_path / 'page.html').exists()


def test_audited_cost_drives_headline_without_changing_frozen_records(run, tmp_path):
    from crest.report import load_run, _resources
    doc = final_audit(run)
    next(r for r in doc['generation']['answer_details'] if r['agent'] == 'caesar')['known_usd'] = 6.
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    before_answers, before_audit = answers_path(run).read_bytes(), audit.read_bytes()
    data = load_run(run, audit=audit)
    html = _resources(data)
    headline = html.split('<details', 1)[0]
    assert '$1.10' in headline  # (49 original dollars + 6 checked dollars) / 50
    assert 'for 1 Caesar answer.' in headline  # $6 exceeds this fixture's $5 target.
    assert data['resources']['generation']['caesar']['known_cost_usd'] == 50.
    assert answers_path(run).read_bytes() == before_answers
    assert audit.read_bytes() == before_audit


def test_incomplete_audit_cost_does_not_mix_partial_totals_into_headline(run, tmp_path):
    from crest.report import load_run, _resources
    doc = final_audit(run)
    caesar = [r for r in doc['generation']['answer_details'] if r['agent'] == 'caesar']
    caesar[0]['known_usd'] = 6.
    caesar[1]['known_usd'] = None
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    data = load_run(run, audit=audit)
    assert data['resources']['generation']['caesar']['audited_known_cost_usd'] is None
    headline = _resources(data).split('<details', 1)[0]
    assert '$1.00' in headline
    assert '$1.10' not in headline


def test_partial_active_timing_coverage_is_visible_without_expanding_details(run, tmp_path):
    from crest.report import load_run, _resources
    doc = final_audit(run)
    rows = [r for r in doc['generation']['answer_details'] if r['agent'] == 'openai']
    for row in rows[:20]: row.update(timing_complete=False, active_attempt_seconds=None)
    audit = tmp_path / 'audit.json'; dump(audit, doc)
    headline = _resources(load_run(run, audit=audit)).split('<details', 1)[0]
    assert '30 of 50 answers timed' in headline


def test_known_citation_url_with_spaces_keeps_full_link_and_original_text(run, tmp_path):
    # End to end once; the URL-shape variants are unit-tested on _markdown_answer below.
    from html import escape
    from crest.report import write_report
    url = 'https://example.test/search?keywords=Science _and_ Engineering'
    encoded = 'https://example.test/search?keywords=Science%20_and_%20Engineering'
    rows = json.loads(answers_path(run).read_text())
    row = next(r for r in rows if r['agent'] == 'caesar')
    source = f'A supported proposal [1].\n\n## Sources\n[1] {url}\n\n`{url}`\n'
    row['result']['text'] = source
    row['result']['raw'] = {'artifact': {'sources': {url: 1}}}
    dump(answers_path(run), rows)
    original = answers_path(run).read_bytes()
    output = tmp_path / 'page.html'; write_report(run, output)
    html = output.read_text()
    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.hrefs = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a': self.hrefs.append(dict(attrs).get('href'))
    parser = Links(); parser.feed(html)
    assert encoded in parser.hrefs
    assert f'<code>{escape(url, quote=False)}</code>' in html
    assert escape(url, quote=False) in html
    assert hashlib.sha256(source.encode()).hexdigest() in html
    assert answers_path(run).read_bytes() == original


@pytest.mark.parametrize('url,encoded', [
    ('https://example.test/search?keywords=Science and Engineering',
     'https://example.test/search?keywords=Science%20and%20Engineering'),
    ('http://example.test/import?paper=abc&description=The Value of Experiments',
     'http://example.test/import?paper=abc&description=The%20Value%20of%20Experiments'),
    ('https://example.test/search?keywords=Science _and_ Engineering',
     'https://example.test/search?keywords=Science%20_and_%20Engineering'),
    ('https://example.test/search?description=The *Value* of Experiments',
     'https://example.test/search?description=The%20*Value*%20of%20Experiments'),
    ('https://example.test/search?description=The `Value` of Experiments',
     'https://example.test/search?description=The%20%60Value%60%20of%20Experiments'),
    ('https://example.test/search?description=The [Value](test) of Experiments&x=1',
     'https://example.test/search?description=The%20%5BValue%5D(test)%20of%20Experiments&x=1'),
])
def test_known_source_urls_are_atomic_before_inline_markdown(url, encoded):
    from html import escape
    from crest.report import _markdown_answer
    assert _markdown_answer(f'Source: {url}.', {url: 1}) == (
        f'<p>Source: <a href="{escape(encoded, quote=True)}">{escape(url)}</a>.</p>\n')


@pytest.mark.parametrize('source', [
    '`{url}`', '```text\n{url}\n```',
    '[{url}](https://author.example/destination)',
    '[{url}][ref]\n\n[ref]: https://author.example/destination',
    '[![{url}](https://author.example/image)](https://author.example/destination)',
])
def test_known_source_urls_preserve_explicit_links_and_code(source):
    from crest.report import _markdown_answer
    url = 'https://example.test/search?keywords=Science _and_ Engineering'
    source = source.format(url=url)
    # Source metadata must not change author-controlled links or code rendering.
    assert _markdown_answer(source, {url: 1}) == _markdown_answer(source)


def test_known_source_urls_use_longest_match_without_inventing_sources():
    from crest.report import _markdown_answer
    from lxml import html
    short = 'https://example.test/search?q=Science _and_ Engineering'
    long = short + ' Practices'
    absent = 'https://example.test/search?q=Absent source'
    sources = {short: 1, long: 2, absent: 3}
    before = dict(sources)
    source = f'**Sources**: {long}; {short}. Ordinary _emphasis_ remains.'
    rendered = html.fragment_fromstring(_markdown_answer(source, sources), create_parent=True)
    assert rendered.xpath('.//a/@href') == [
        'https://example.test/search?q=Science%20_and_%20Engineering%20Practices',
        'https://example.test/search?q=Science%20_and_%20Engineering']
    assert rendered.xpath('.//a/text()') == [long, short]
    assert rendered.xpath('.//strong/text()') == ['Sources']
    assert rendered.xpath('.//em/text()') == ['emphasis']
    assert sources == before


def test_known_source_urls_keep_untrusted_markup_inert():
    from crest.report import _markdown_answer
    from lxml import html
    safe = 'https://example.test/search?q=<script>alert(1)</script> _and_ "quotes"'
    unsafe = 'javascript:alert(1) dangerous source'
    source = f'{safe}\n\n{unsafe}'
    rendered = html.fragment_fromstring(_markdown_answer(source, {safe: 1, unsafe: 2}), create_parent=True)
    assert not rendered.xpath('.//script|.//img|.//iframe|.//*[@onerror]|.//*[@onclick]')
    assert rendered.xpath('.//a/@href') == [
        'https://example.test/search?q=%3Cscript%3Ealert(1)%3C/script%3E%20_and_%20%22quotes%22']
    assert rendered.xpath('.//a/text()') == [safe]
    assert unsafe in rendered.text_content()


def test_current_static_document_headers_link_to_latest_research_report():
    from pathlib import Path
    from lxml import html
    docs = Path(__file__).resolve().parents[2] / 'docs'
    # Evidence remains frozen; publication wrappers use canonical versioned names.
    for path in sorted(docs.glob('*.html')):
        if path.name in {'deep-research-comparison-v1.html', 'deep-research-comparison-v2.html',
                         'deep-research-comparison-v3.html'}:
            continue
        page = html.fromstring(path.read_bytes())
        links = page.xpath('//header[@class="crest-site-header"]//a[starts-with(text(), "Deep Research Comparison")]/@href')
        if links:
            assert links == ['deep-research-comparison-v3.html'], path.name
    for name in ('index.html', 'research-pipeline.html'):
        page = html.fromstring((docs / name).read_bytes())
        links = page.xpath('//a[@href="deep-research-comparison-v1.html"]')
        assert links, name
        assert any('v1' in a.text_content().lower() or 'previous' in a.text_content().lower() for a in links), name


def test_historical_v1_report_uses_versioned_publication_wrapper():
    from pathlib import Path
    from lxml import html
    path = Path(__file__).resolve().parents[2] / 'docs/deep-research-comparison-v1.html'
    source = path.read_bytes()
    page = html.fromstring(source)
    assert page.xpath('//h1/text()') == ['Deep Research Comparison v1']
    assert page.xpath('//header//time/@datetime') == ['2026-11-05']
    assert page.xpath('//header//a[starts-with(text(), "Deep Research Comparison")]/@href') == ['deep-research-comparison-v1.html']


def test_canonical_research_report_title_date_navigation_and_unchanged_run(run, tmp_path):
    from lxml import html
    from crest.report import write_report
    before = {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in run.rglob('*') if p.is_file()}
    output = tmp_path / 'deep-research-comparison-v2.html'
    write_report(run, output, updated='2026-11-05')
    page = html.fromstring(output.read_bytes())
    assert page.findtext('.//title') == 'Deep Research Comparison v2'
    assert page.xpath('//h1/text()') == ['Deep Research Comparison v2']
    assert page.xpath('//header//time/@datetime') == ['2026-11-05']
    # Navigation returns to the generated report, not an older version.
    header = output.read_text().split('</header>', 1)[0]
    assert 'href="deep-research-comparison-v2.html"' in header
    assert 'href="deep-research-comparison-v1.html"' not in header
    assert before == {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in run.rglob('*') if p.is_file()}


def test_research_publication_keeps_index_date_in_sync(run, tmp_path, monkeypatch):
    from lxml import html
    import crest.report as renderer
    import shutil
    shutil.copytree(renderer.ROOT / 'crest/data', tmp_path / 'crest/data')
    monkeypatch.setattr(renderer, 'ROOT', tmp_path)
    docs = tmp_path / 'docs'; docs.mkdir()
    index = docs / 'index.html'
    index.write_text('<main><li><a href="deep-research-comparison-v2.html">Deep Research Comparison v2</a>'
                     '<time class="page-link-date" datetime="2026-11-05">Updated 2026-11-05</time></li></main>')
    renderer.write_report(run, docs / 'deep-research-comparison-v2.html', updated='2026-11-06')
    assert html.fromstring(index.read_bytes()).xpath('//time/@datetime') == ['2026-11-06']
    assert html.fromstring(index.read_bytes()).xpath('//time/text()') == ['Updated 2026-11-06']


def test_research_generator_does_not_overwrite_compatibility_redirect(run, tmp_path):
    from crest.report import write_report
    output = tmp_path / 'deep-research-creativity.html'
    output.write_text('Original compatibility redirect')
    with pytest.raises(ValueError, match='deep-research-comparison-v1.html'):
        write_report(run, output)
    assert output.read_text() == 'Original compatibility redirect'


@pytest.mark.parametrize("dated_entries", [0, 2])
def test_research_invalid_index_wrapper_preserves_existing_report(run, tmp_path, monkeypatch, dated_entries):
    import shutil
    import crest.report as renderer
    shutil.copytree(renderer.ROOT / 'crest/data', tmp_path / 'crest/data')
    monkeypatch.setattr(renderer, 'ROOT', tmp_path)
    docs = tmp_path / 'docs'; docs.mkdir()
    index = docs / 'index.html'
    entry = '<a href="deep-research-comparison-v2.html">Deep Research Comparison v2</a>'
    stamp = '<time class="page-link-date" datetime="2026-11-05">Updated 2026-11-05</time>'
    original_index = '<main>' + ((entry + stamp) * dated_entries if dated_entries else entry) + '</main>'
    index.write_text(original_index)
    output = docs / 'deep-research-comparison-v2.html'
    output.write_text('Previously published report')
    with pytest.raises(ValueError, match='Expected one dated index entry'):
        renderer.write_report(run, output, updated='2026-11-06')
    assert output.read_text() == 'Previously published report'
    assert index.read_text() == original_index


def mark_nus_judgments(run, version):
    """Label fixture judgments as current NUS rows presented with the given version."""
    from crest.presentation import present_research_answer
    path = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    answers = json.loads(answers_path(run).read_text())
    answer_map = {(a['question_id'], a['agent']): a for a in answers}
    for row in rows:
        row.update(protocol_version='nus-overall-pairwise-v3', presentation_version=version)
        row['presented_answer_hashes'] = [hashlib.sha256(present_research_answer(
            answer_map[row['question_id'], agent]['result']['text'], version).encode()).hexdigest()
            for agent in row['order']]
        row['verdict']['reason'] = 'A develops a distinct causal mechanism, while B supplies a familiar explanation.'
        row['result']['text'] = json.dumps(row['verdict'])
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return rows


@pytest.mark.parametrize('version', ['citation-neutral-v1', 'citation-neutral-v2'])
def test_publication_validates_each_saved_presentation_version(run, version):
    from crest.report import load_run
    answers = json.loads(answers_path(run).read_text())
    answers[0]['result']['text'] += '\n\nSources:\nhttps://uncited.test/a'
    dump(answers_path(run), answers)
    rows = mark_nus_judgments(run, version)
    load_run(run)
    # The first judgment compares the answer that carries the appended list.
    assert answers[0]['agent'] in rows[0]['order'] and rows[0]['question_id'] == answers[0]['question_id']
    rows[0]['presentation_version'] = 'citation-neutral-v2' if version.endswith('v1') else 'citation-neutral-v1'
    (run / '02-judge-test/judgments.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError, match='presentation'):
        load_run(run)


def test_models_name_the_saved_anthropic_model_and_its_client_web_tools():
    from crest.report import _models
    data = {'ranking': {'ranking': [{'agent': 'anthropic'}]},
            'manifest': {'config': {'research': {'anthropic': {
                'model': 'claude-opus-5-5', 'effort': 'high', 'tool_mode': 'client'}}}},
            'answers': [{'agent': 'anthropic', 'result': {'model': 'claude-opus-5-5'}}]}
    html = _models(data)
    assert 'Claude Opus 5.5 with web search and page reading tools we provide.' in html
    assert 'API' not in html and 'harness' not in html
    assert 'claude-opus-5-5 +' not in html


def test_v3_comparison_is_a_catalog_page_linked_from_the_header():
    from pathlib import Path
    from crest_ais.site import PAGES, page_title
    entry = next(p for p in PAGES if p['canonical'] == 'docs/deep-research-comparison-v3.html')
    assert entry['label'] == 'Deep Research Comparison v3'
    assert page_title(Path('docs/deep-research-comparison-v3.html'), 'x') == 'Deep Research Comparison v3'


def test_method_says_judges_did_not_see_the_appended_uncited_sources():
    from crest.report import _method
    data = {'ranking': {'bootstrap': {'seed': 2026}, 'ranking': [{'agent': agent} for agent in AGENTS]},
            'manifest': {}, 'judges': {judge: JUDGE_SETTINGS[judge] for judge in JUDGES},
            'judgments': [{'protocol_version': 'nus-overall-pairwise-v3',
                           'presentation_version': 'citation-neutral-v2'}],
            'answers': [{'agent': 'openai', 'result': {'text': 'Answer.'}}]}
    html = _method(data)
    assert 'We hid the link addresses' in html
    assert 'Judges did not see that list, but the answers below keep it.' in html
    data['judgments'][0]['presentation_version'] = 'citation-neutral-v1'
    assert 'never cites' not in _method(data)


REFUSAL = ('ProviderError: Anthropic stop_reason refusal; '
           'stop_details={"type": "refusal", "category": "bio", "explanation": null}')


def record_judge_failure(run, question_index=47, pair=('caesar', 'gemini'), judge='openai', attempts=3):
    """Drop one saved judgment and record it as the stage's failure, as the pipeline does."""
    path = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    qid = f'q{question_index:03}'
    order = list(pair[::-1])
    failed = next(r for r in rows if r['question_id'] == qid and r['pair'] == list(pair)
                  and r['order'] == order and r['judge'] == judge)
    rows.remove(failed)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    tasks = [{'key': r['key'], 'question_id': r['question_id'], 'pair': r['pair'], 'order': r['order'],
              'judge': r['judge']} for r in [*rows, failed]]
    dump(run / '02-judge-test/tasks.json', tasks)
    error = {'key': failed['key'], 'question_id': qid, 'stage': 'judge', 'provider': judge,
             'error': f'ValueError: Judge response rejected after {attempts} attempts',
             'cost_usd': .4, 'known_cost_usd': .4, 'unknown_cost_count': 0, 'cost_scope': 'all_judgment_attempts',
             'attempts': [{'attempt': i + 1, 'key': f'refused-{i}', 'status': 'rejected', 'error': REFUSAL,
                           'cost_usd': .4 / attempts, 'result': {'cost_usd': .4 / attempts, 'usage': {}}}
                          for i in range(attempts)]}
    (run / '02-judge-test/errors.jsonl').write_text(json.dumps(error) + '\n')
    questions = json.loads((run / '02-judge-test/questions.json').read_text())
    answers = json.loads(answers_path(run).read_text())
    judges = list(json.loads((run / '02-judge-test/judges.json').read_text()))
    agents = json.loads((run / 'run.json').read_text())['agents']
    dump(ranking_path(run), analyze(questions, answers, rows, agents=agents, judges=judges,
                                    bootstrap_samples=1000, seed=2026))
    return failed, error


def test_recorded_judge_failure_publishes_remaining_questions_with_disclosure(run, tmp_path):
    from crest.report import load_run, write_report
    record_judge_failure(run)
    data = load_run(run)
    assert data['ranking']['coverage']['complete_questions'] == 49
    output = write_report(run, tmp_path / 'page.html')
    html = output.read_text()
    assert '<strong>49</strong><span>of 50 questions ranked</span>' in html
    assert '<strong>599</strong><span>of 600 pairwise judgments</span>' in html
    # 49 questions × 2 opponents × 2 orders × 2 judges.
    assert 'its wins divided by its 392 judgments (49 questions, two opponents, two judges, both answer orders)' in html
    assert 'of 392 won' in html and 'of 400 won' not in html
    assert 'out of 196 judgments for each pair of systems' in html
    assert '<a href="#question-48">Question 48</a> is not ranked.' in html
    assert ('One of its 12 judgments is missing: GPT-6 Astra refused all 3 attempts to judge '
            'Google Deep Research (shown first) against Caesar (shown second); the API labeled the refusal “bio”, its biology-safety category.') in html
    assert 'A question is ranked only when all 12 judgments exist, so every system is compared on the same questions.' in html
    assert 'Its 11 saved judgments are shown with the question.' in html
    assert 'The failed judgment’s attempts cost $0.40 and are included in the judging total.' in html
    assert 'The 599 saved judgments and 1 failed judgment cost $60.30 in total, including retried calls.' in html
    assert 'We redrew the 49 ranked questions at random 1,000 times' in html
    assert 'The ranking uses 49 of the 50 questions' in html
    assert html.count('class="judgment"') == 599
    assert 'Read all 11 saved judgments' in html
    assert re.search(r'id="question-48".{0,400}Not ranked: 11 of 12 judgments', html, re.S)


@pytest.mark.parametrize('kind', ['no_tasks', 'unknown_key', 'scored_cell', 'wrong_judge', 'two_rows', 'duplicate_task'])
def test_missing_judgments_publish_only_for_matching_recorded_failures(run, kind):
    from crest.report import load_run
    failed, error = record_judge_failure(run)
    errors = run / '02-judge-test/errors.jsonl'
    if kind == 'no_tasks':
        (run / '02-judge-test/tasks.json').unlink()
    elif kind == 'unknown_key':
        error['key'] = 'never-scheduled'
    elif kind == 'scored_cell':
        rows = [json.loads(line) for line in (run / '02-judge-test/judgments.jsonl').read_text().splitlines()]
        error.update(key=rows[0]['key'], question_id=rows[0]['question_id'], provider=rows[0]['judge'])
    elif kind == 'wrong_judge':
        error['provider'] = 'gemini'
    elif kind == 'duplicate_task':
        tasks = json.loads((run / '02-judge-test/tasks.json').read_text())
        dump(run / '02-judge-test/tasks.json', [*tasks, dict(tasks[0])])
    else:
        errors.write_text((json.dumps(error) + '\n') * 2)
    if kind not in ('no_tasks', 'two_rows', 'duplicate_task'):
        errors.write_text(json.dumps(error) + '\n')
    with pytest.raises(ValueError, match='failure|task'):
        load_run(run)


def unknown_outcome(error):
    """Turn a recorded refusal into a call whose connection dropped after it was sent."""
    message = 'ProviderError: gateway HTTP 408; submission status unknown'
    error.update(error=message, cost_usd=None, known_cost_usd=0, unknown_cost_count=1,
                 attempts=[{'attempt': 1, 'key': 'unknown-0', 'status': 'failed', 'error': message, 'cost_usd': None}])
    return error


def test_unknown_outcome_failure_reports_no_known_cost_instead_of_zero(run, tmp_path):
    from crest.report import write_report
    _, error = record_judge_failure(run)
    (run / '02-judge-test/errors.jsonl').write_text(json.dumps(unknown_outcome(error)) + '\n')
    body = write_report(run, tmp_path / 'page.html').read_text()
    assert '$0.00' not in body.split('id="resources"')[1].split('</section>')[0]
    assert 'The failed call has no known cost, so it is not in the judging total.' in body
    assert 'timed out or lost its connection, so we cannot tell whether it was processed' in body
    assert 'CREST' not in body.split('<main', 1)[1]


def test_failure_disclosures_use_singular_attempts_and_per_refusal_categories(tmp_path):
    from crest.report import write_report
    main_run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    v2 = use_packaged_rubric(make_run(tmp_path / 'v2'), 'v2')
    _, error = record_judge_failure(v2, attempts=1)
    rows = [json.loads(line) for line in (v2 / '02-judge-test/judgments.jsonl').read_text().splitlines()]
    lost = next(r for r in rows if r['question_id'] == 'q010' and r['judge'] == 'openai')
    rows.remove(lost)
    (v2 / '02-judge-test/judgments.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    uncategorized = {**error, 'key': lost['key'], 'question_id': 'q010',
                     'attempts': [{**error['attempts'][0], 'error': 'stop_reason refusal'}]}
    (v2 / '02-judge-test/errors.jsonl').write_text(json.dumps(error) + '\n' + json.dumps(uncategorized) + '\n')
    questions = json.loads((v2 / '02-judge-test/questions.json').read_text())
    answers = json.loads(answers_path(v2).read_text())
    dump(ranking_path(v2), analyze(questions, answers, rows, agents=AGENTS, judges=JUDGES,
                                   bootstrap_samples=1000, seed=2026))
    body = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v2]).read_text()
    assert '1 attempts' not in body
    assert 'The refusals came after one attempt each, and the API labeled one of them “bio”, its biology-safety category.' in body


def test_failure_validation_messages_do_not_call_every_failure_paid():
    import crest.report as report
    from pathlib import Path
    source = Path(report.__file__).read_text()
    assert 'paid failure' not in source


def use_packaged_rubric(run, version):
    from crest.report import ROOT
    text = (ROOT / f'crest/prompts/nus_pairwise_{version}.txt').read_text(encoding='utf-8')
    (run / '02-judge-test/rubric.txt').write_text(text, encoding='utf-8')
    return run


def test_other_rubrics_sit_in_small_dropdowns_at_the_bottom_in_ascending_order(tmp_path):
    from crest.report import main
    from lxml import html as lxml_html
    first = lambda q, pair, judge, order: order[0]
    main_run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    v3 = use_packaged_rubric(make_run(tmp_path / 'v3'), 'v3')
    v2 = use_packaged_rubric(make_run(tmp_path / 'v2', choose=first), 'v2')
    output = tmp_path / 'page.html'
    # The flags come in v3, v2 order; the dropdowns still read v2 then v3.
    assert main([str(main_run), '--output', str(output), '--rubric-run', str(v3), '--rubric-run', str(v2)]) == 0
    text = output.read_text()
    assert 'href="#rubrics"' not in text and 'id="rubrics"' not in text
    assert 'Same answers, other rubrics' not in text
    page = lxml_html.fromstring(text)
    bottom = page.get_element_by_id('other-rubrics')
    # Nothing follows the dropdowns inside main, not even the questions.
    main_element = page.xpath('//main')[0]
    assert main_element.getchildren()[-1] is bottom
    assert text.index('id="questions"') < text.index('id="other-rubrics"')
    dropdowns = bottom.xpath('./details')
    summaries = [d.xpath('./summary')[0].text_content() for d in dropdowns]
    assert summaries == ['NUS v2 results', 'NUS v3 results', 'Win rates under all three rubrics']
    assert all(d.get('open') is None for d in dropdowns)
    # One visually hidden heading names the section for screen readers; the dropdowns stay small links.
    assert [h.text_content() for h in bottom.xpath('./h2')] == ['Results under other rubrics']
    assert bottom.xpath('./h2')[0].get('class') == 'visually-hidden'
    assert bottom.get('aria-labelledby') == bottom.xpath('./h2')[0].get('id')
    assert len(bottom.xpath('.//h2')) == 1
    v2_box, v3_box = dropdowns[:2]
    assert '../crest/prompts/nus_pairwise_v3.txt' in v3_box.xpath('.//a/@href')
    headers = [th.text_content() for th in v3_box.xpath('.//table')[0].xpath('.//thead//th')]
    assert headers == ['System', 'Rank', 'Win rate', '95% interval']
    rows = {tr.xpath('./th')[0].text_content(): [td.text_content() for td in tr.xpath('./td')]
            for tr in v3_box.xpath('.//table')[0].xpath('.//tbody/tr')}
    assert set(rows) == {'Caesar', 'Google Deep Research', 'OpenAI (Sol + web search)'}
    assert all(cells[0] == '1' and cells[1] == '50.0%' for cells in rows.values())
    judge_tables = v3_box.xpath('.//table')[1:]
    assert judge_tables and [th.text_content() for th in judge_tables[0].xpath('.//thead//th')][0] == 'Judge'
    # Judge columns follow the main ranking order, as in the comparison table, not this rubric's own ranking.
    main_order = [tr.xpath('./th')[0].text_content() for tr in dropdowns[2].xpath('.//tbody/tr')]
    assert [th.text_content() for th in judge_tables[0].xpath('.//thead//th')][1:] == main_order
    assert judge_tables[0].xpath('.//tbody/tr/td')[0].get('class') == 'num'
    # v3 repeats every v1 choice; v2 picks the first answer, matching v1 in one order of each pair.
    assert 'The judges pick the same winner as under NUS v1 in 100.0% of judgments (600 of 600).' in v3_box.text_content()
    assert 'The judges pick the same winner as under NUS v1 in 50.0% of judgments (300 of 600).' in v2_box.text_content()
    assert 'Judging cost: $' in v3_box.text_content()
    assert 'All 600 judgments are present, 12 for each of the 50 questions.' in v3_box.text_content()
    compare = dropdowns[2]
    assert compare.xpath('./summary')[0].text_content() == 'Win rates under all three rubrics'
    assert [th.text_content() for th in compare.xpath('.//thead//th')] == ['System', 'NUS v1 (top of page)', 'NUS v2', 'NUS v3']
    assert 'Caesar, Google Deep Research, and OpenAI (Sol + web search) tie for first under every rubric.' in compare.text_content()
    # The per-question evidence stays the v1 judging.
    assert text.count('class="judgment"') == 600


def test_intro_and_method_name_the_rubric_the_ranking_uses(tmp_path):
    from crest.report import write_report
    main_run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    v3 = use_packaged_rubric(make_run(tmp_path / 'v3', choose=lambda q, pair, judge, order: order[0]), 'v3')
    body = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v3]).read_text()
    intro = body.split('<main', 1)[1].split('<nav', 1)[0]
    assert 'under the <a href="../crest/prompts/nus_pairwise_v1.txt">NUS v1</a> rubric' in intro
    assert 'href="#other-rubrics"' in intro
    method = section(body, 'method')
    assert 'The ranking uses the <a href="../crest/prompts/nus_pairwise_v1.txt">NUS v1</a> rubric.' in method
    assert ('The NUS v1 file shares its closing rules and output format with NUS v2 and NUS v3, so its wording '
            'differs from the file earlier studies used.') in method


def test_intro_without_other_rubrics_points_nowhere(tmp_path):
    from crest.report import write_report
    main_run = use_packaged_rubric(make_run(tmp_path / 'v3'), 'v3')
    body = write_report(main_run, tmp_path / 'page.html').read_text()
    assert 'under the <a href="../crest/prompts/nus_pairwise_v3.txt">NUS v3</a> rubric' in body
    assert 'id="other-rubrics"' not in body and 'href="#other-rubrics"' not in body
    assert 'earlier studies used' not in body


def _rubric_entry(version, order, close=(), wins=None):
    """A rubric entry whose common analysis ranks `order`; pairs in `close` have intervals that include zero."""
    rows = [{'agent': a, 'rank': i, 'preference_rate': 1 - i / 10, 'wins': (wins or {}).get(a, 100 - i),
             'choices': 120} for i, a in enumerate(order, 1)]
    contrasts = [{'pair': [a, b], 'ci95': [-.1, .1] if {a, b} in [set(p) for p in close] else [.1, .2]}
                 for i, a in enumerate(order) for b in order[i + 1:]]
    return {'version': version, 'common': {'ranking': rows, 'paired_contrasts': contrasts}}


def test_rubric_pointer_follows_the_headline_rule_and_groups_rubrics_that_read_the_same():
    from crest.report import _rubric_pointer
    agents = ['caesar', 'openai', 'anthropic', 'gpt_researcher', 'gemini']
    chain = [('caesar', 'openai'), ('openai', 'anthropic')]
    entries = [_rubric_entry('v1', agents, chain),
               _rubric_entry('v2', ['anthropic', 'openai', 'caesar', 'gpt_researcher', 'gemini'],
                             [('anthropic', 'openai'), ('anthropic', 'caesar'), ('openai', 'caesar')]),
               _rubric_entry('v3', ['anthropic', 'caesar', 'openai', 'gpt_researcher', 'gemini'],
                             [('anthropic', 'caesar'), ('caesar', 'openai')])]
    assert _rubric_pointer(agents, entries) == (
        'Under the NUS v2 and NUS v3 rubrics, the top three cannot be fully separated.')
    separate = _rubric_entry('v1', agents)
    assert _rubric_pointer(agents, [separate, {**separate, 'version': 'v2'}]) == (
        'Under the NUS v2 rubric, every system keeps its place.')
    apart = _rubric_entry('v2', ['openai', 'caesar', 'anthropic', 'gpt_researcher', 'gemini'])
    assert _rubric_pointer(agents, [entries[0], apart]) == (
        'Under the NUS v2 rubric, OpenAI (Sol + web search) is first, Caesar is second, and Anthropic (Claude + web '
        'search) is third.')


@pytest.mark.parametrize('kind', ['same_rubric', 'unknown_rubric', 'other_questions', 'other_answers', 'other_agents',
                                  'other_protocol', 'other_judges', 'aut'])
def test_rubric_comparison_refuses_runs_that_differ_beyond_the_rubric(tmp_path, kind):
    from crest.report import write_report
    main_run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    variant = use_packaged_rubric(make_run(tmp_path / 'variant'), 'v1' if kind == 'same_rubric' else 'v2')
    if kind == 'unknown_rubric':
        (variant / '02-judge-test/rubric.txt').write_text('Some unpublished rubric.')
    elif kind == 'other_questions':
        variant = use_packaged_rubric(make_run(tmp_path / 'variant2'), 'v2')
        manifest = json.loads((variant / 'run.json').read_text())
        manifest['questions'][0]['text'] += ' Changed.'
        dump(variant / 'run.json', manifest)
        questions = json.loads((variant / '02-judge-test/questions.json').read_text())
        questions[0]['text'] += ' Changed.'
        dump(variant / '02-judge-test/questions.json', questions)
    elif kind == 'other_answers':
        rows = json.loads(answers_path(variant).read_text())
        rows[0]['result']['text'] += ' Edited.'
        dump(answers_path(variant), rows)
    elif kind == 'other_agents':
        variant = use_packaged_rubric(make_run(tmp_path / 'variant3', agents=['caesar', 'gemini', 'mystery']), 'v2')
    elif kind == 'other_protocol':
        path = variant / '02-judge-test/judgments.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row['protocol_version'] = 'nus-overall-pairwise-v2'
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    elif kind == 'other_judges':
        variant = use_packaged_rubric(make_run(tmp_path / 'variant4', judges=['openai']), 'v2')
    elif kind == 'aut':
        make_aut_run(variant)
    expected = {'same_rubric': 'different rubric', 'unknown_rubric': 'packaged NUS rubric',
                'other_questions': 'same questions', 'other_answers': 'same saved answers',
                'other_agents': 'same saved answers', 'other_protocol': 'same judging protocol',
                'other_judges': 'same judges', 'aut': 'NUS rubric'}[kind]
    with pytest.raises(ValueError, match=expected):
        write_report(main_run, tmp_path / 'page.html', rubric_runs=[variant])
    assert not (tmp_path / 'page.html').exists()


def test_rubric_section_groups_missing_judgments_by_rubric_and_question(tmp_path):
    from crest.report import write_report
    main_run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    v2 = use_packaged_rubric(make_run(tmp_path / 'v2'), 'v2')
    record_judge_failure(v2, question_index=47)
    errors = v2 / '02-judge-test/errors.jsonl'
    rows = [json.loads(line) for line in (v2 / '02-judge-test/judgments.jsonl').read_text().splitlines()]
    lost = next(r for r in rows if r['question_id'] == 'q010' and r['judge'] == 'openai')
    rows.remove(lost)
    (v2 / '02-judge-test/judgments.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    errors.write_text(errors.read_text() + json.dumps({
        'key': lost['key'], 'question_id': 'q010', 'stage': 'judge', 'provider': 'openai',
        'error': 'ProviderError: gateway HTTP 408; submission status unknown', 'cost_usd': None,
        'attempts': [{'attempt': 1, 'key': 'unknown-0', 'status': 'failed',
                      'error': 'ProviderError: gateway HTTP 408; submission status unknown', 'cost_usd': None}]}) + '\n')
    questions = json.loads((v2 / '02-judge-test/questions.json').read_text())
    answers = json.loads(answers_path(v2).read_text())
    judges = list(json.loads((v2 / '02-judge-test/judges.json').read_text()))
    dump(ranking_path(v2), analyze(questions, answers, rows, agents=AGENTS, judges=judges,
                                   bootstrap_samples=1000, seed=2026))
    output = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v2])
    body = output.read_text()
    assert ('Missing judgments under NUS v2: one on question 11 (unknown outcome) and one on question 48 (refused).') in body
    assert 'Every missing judgment is GPT-6 Astra’s.' in body
    assert 'The refusal came after three attempts, and the API labeled it “bio”, its biology-safety category.' in body
    assert ('A call has an unknown outcome when it timed out or lost its connection, so we cannot tell '
            'whether it was processed. '
            'Such a call is sent again at most once, because the first request may have been billed.') in body
    v2_box = section(body, 'other-rubrics')
    assert 'These numbers use the 48 questions that have every judgment under both rubrics' in v2_box
    assert 'so they differ slightly from the NUS v1 ranking at the top of the page, which uses all 50' in v2_box


def test_intro_states_the_ranking_in_order(tmp_path):
    from crest.report import write_report
    preference = {'openai': 0, 'caesar': 1, 'gemini': 2}
    run = make_run(tmp_path / 'run', choose=lambda q, pair, judge, order: min(pair, key=preference.get))
    html = write_report(run, tmp_path / 'page.html').read_text()
    intro = html.split('<nav aria-label="Report contents">')[0]
    assert ('OpenAI (Sol + web search) is first at 100.0%, Caesar second at 50.0%, '
            'and Google Deep Research third at 0.0%.') in intro
    assert 'too close to separate' not in intro


def test_intro_groups_systems_whose_paired_interval_includes_zero(run, tmp_path):
    from crest.report import write_report
    intro = write_report(run, tmp_path / 'page.html').read_text().split('<nav aria-label="Report contents">')[0]
    # Every fixture system wins half its judgments, so no pair can be separated.
    assert ('Caesar at 50.0%, Google Deep Research at 50.0%, and OpenAI (Sol + web search) at 50.0% '
            'are too close to separate for first place') in intro


def test_judge_section_names_judges_that_share_a_model_with_a_system(tmp_path):
    from crest.report import load_run, _judges, _judge_picks
    preference = {'openai': 0, 'caesar': 1, 'gemini': 2}
    data = load_run(make_run(tmp_path / 'run', choose=lambda q, pair, judge, order: min(pair, key=preference.get)))
    assert 'shares a model' not in _judges(data)
    data['judges']['openai'] = {**data['judges']['openai'], 'model': 'gpt-6.1-sol'}
    html = _judges(data)
    assert ('One judge shares a model with systems it judges: GPT-6.1 Sol is also the main model of '
            'OpenAI (Sol + web search) and Caesar.') in html
    assert 'Win rates by judge' in html
    intro = _judge_picks(data)
    assert 'GPT-6.1 Sol, the main model of OpenAI (Sol + web search) and Caesar, gives OpenAI (Sol + web search) 100.0%' in intro
    assert 'Gemini 4 Argon, which is not the main model of any system here' in intro


def test_head_to_head_explains_a_lower_ranked_system_winning_the_direct_matchup(tmp_path):
    from crest.report import load_run, _head_to_head
    def choose(q, pair, judge, order):
        if set(pair) == {'caesar', 'openai'}:
            return 'openai' if q % 5 < 3 else 'caesar'
        if set(pair) == {'caesar', 'gemini'}:
            return 'caesar'
        return 'openai' if q % 5 == 0 else 'gemini'
    data = load_run(make_run(tmp_path / 'run', choose=choose))
    assert [r['agent'] for r in data['ranking']['ranking']][0] == 'caesar'
    html = _head_to_head(data)
    assert ('OpenAI (Sol + web search) wins 60.0% of its judgments against Caesar, yet its overall win rate is '
            '30.0 points lower, because the overall rate also counts judgments against every other system.') in html


def test_paired_differences_list_the_higher_ranked_system_first_in_points(tmp_path):
    from crest.report import load_run, _ranking
    from lxml import html as lxml_html
    preference = {'openai': 0, 'caesar': 1, 'gemini': 2}
    data = load_run(make_run(tmp_path / 'run', choose=lambda q, pair, judge, order: min(pair, key=preference.get)))
    page = lxml_html.fromstring(_ranking(data))
    rows = [[cell.text_content() for cell in tr.xpath('./th|./td')] for tr in page.xpath('.//details//tbody/tr')]
    assert all(tr.xpath('./th[@scope="row"]') for tr in page.xpath('.//details//tbody/tr'))
    assert all(td.get('class') == 'num' for td in page.xpath('.//details//tbody/tr/td'))
    assert [row[0] for row in rows] == ['OpenAI (Sol + web search) vs Caesar',
                                        'OpenAI (Sol + web search) vs Google Deep Research',
                                        'Caesar vs Google Deep Research']
    assert rows[0][1] == '+50.0' and ' to ' in rows[0][2] and 'points' not in rows[0][2]
    assert rows[0][3] == '100.0%'
    assert ' pp' not in _ranking(data)


def test_judge_disagreement_counts_judge_pairings_with_thousands_separators(tmp_path):
    from crest.report import load_run, _judges
    html = _judges(load_run(make_run(tmp_path / 'run', agents=FOUR_AGENTS, judges=THREE_JUDGES)))
    assert re.search(r'When two judges saw the same pair in the same order, they picked different winners '
                     r'[0-9.]+% of the time \([0-9,]+ of 1,800 comparisons, from three pairs of judges on each of '
                     r'600 ordered answer pairs\)', html)
    assert 'judge pairings' not in html


def test_cost_means_flag_answers_with_incomplete_estimates(run, tmp_path):
    from crest.report import load_run, _resources
    rows = json.loads(answers_path(run).read_text())
    caesar = next(row for row in rows if row['agent'] == 'caesar')
    caesar['result'].update(cost_usd=None, raw={'usage_audit': {'known_cost_usd': 3., 'unknown_cost': True}})
    dump(answers_path(run), rows)
    headline = _resources(load_run(run)).split('<details', 1)[0]
    assert '1 of 50 estimates incomplete' in headline
    assert 'An incomplete estimate is missing the cost of some calls' in headline


def caesar_with_failed_call(row, *, known=.96, reserved=.9, lost_reserved=1.0):
    """Five priced Sol calls and one that failed with a server error and never reported a cost."""
    events = [{'model': 'gpt-6.1-sol', 'reserved_usd': reserved, 'unknown_cost': False, 'status': 'completed',
               'cost_usd': known} for _ in range(5)]
    events.append({'model': 'gpt-6.1-sol', 'reserved_usd': lost_reserved, 'unknown_cost': True, 'status': 'failed',
                   'status_code': 520, 'cost_usd': None})
    ledger = {'known_cost_usd': 5 * known, 'cost_usd': None, 'unknown_cost': True, 'events': events, 'in_flight': []}
    row['result'].update(cost_usd=None, usage=ledger, raw={'usage_audit': ledger})


def anthropic_with_lost_turn(row):
    """Two priced turns, then a POST whose outcome, and so whose cost, is unknown."""
    rates = {'input': 4.4, 'cached_input': .22, 'cache_write_5m': 5.5, 'output': 22.0, 'web_search': 0}
    turns = [{'model': 'claude-sonnet-5-5', 'stop_reason': 'tool_use', '_round': 1,
              '_pricing': {'rates': rates, 'source': 'configured'},
              'usage': {'input_tokens': 2, 'cache_read_input_tokens': read, 'cache_creation_input_tokens': write,
                        'output_tokens': out}} for read, write, out in ((0, 10000, 5000), (10000, 2000, 1000))]
    known = ((2 * 4.4 + 10000 * 5.5 + 5000 * 22) + (2 * 4.4 + 10000 * .22 + 2000 * 5.5 + 1000 * 22)) / 1e6
    row['result'].update(cost_usd=None, known_cost_usd=known, estimate_incomplete=True,
                         usage={'known_cost_usd': known},
                         raw={'turns': turns, 'tool_mode': 'client', 'unresolved_submission': True,
                              'pricing': {'rates_by_model': {'claude-sonnet-5-5': rates}}})
    return (2 * 4.4 + 10000 * .22 + 2000 * 5.5 + 1000 * 22) / 1e6  # The lost turn is counted like the last one.


def test_cost_means_count_failed_calls_at_the_cost_of_similar_calls(run):
    from crest.report import load_run, _resources
    rows = json.loads(answers_path(run).read_text())
    caesar_with_failed_call(next(row for row in rows if row['agent'] == 'caesar'))
    dump(answers_path(run), rows)
    data = load_run(run)
    assert data['resources']['generation']['caesar']['imputed_cost_usd'] == pytest.approx(.96)
    html = _resources(data)
    headline = html.split('<details', 1)[0]
    # Known $4.80 + $0.96 counted for the failed call: (49 + 5.76) / 50 = $1.10, not the known-only $1.08.
    assert '$1.10' in headline and '$1.08' not in headline
    assert 'estimates incomplete' not in headline and 'lower bound' not in headline
    assert ('1 call in a Caesar answer failed with a server or network error and never reported a cost. '
            'We count it at the average cost of similar calls in the same answer, which adds $0.96.') in headline
    assert 'Charges that were never reported are left out.' not in headline
    # The answer is over the $5.00 target only once its failed call is counted.
    assert ('Estimated cost was above the $5.00 per-answer target for 1 Caesar answer (only after adding the calls '
            'that never reported a cost).') in headline
    assert '$54.76' in html.split('Generation cost totals', 1)[1]
    assert '—' not in html


def test_cost_note_lists_failed_calls_by_system(tmp_path):
    from crest.report import load_run, _resources
    run = make_run(tmp_path / 'run', agents=FOUR_AGENTS)
    rows = json.loads(answers_path(run).read_text())
    caesar = [row for row in rows if row['agent'] == 'caesar']
    caesar_with_failed_call(caesar[0])
    caesar_with_failed_call(caesar[1], known=.5)
    lost = anthropic_with_lost_turn(next(row for row in rows if row['agent'] == 'anthropic'))
    dump(answers_path(run), rows)
    headline = _resources(load_run(run)).split('<details', 1)[0]
    added = f'${.96 + .5 + lost:,.2f}'
    # Systems are listed in ranking order, as in the table above the note.
    assert ('Some calls failed with a server or network error and never reported a cost: 1 call in an Anthropic '
            '(Claude + web search) answer and 2 in 2 Caesar answers. We count each at the average cost of '
            f'similar calls in the same answer, which adds {added} in total.') in headline
    assert 'estimates incomplete' not in headline and 'lower bound' not in headline


def test_over_target_note_counts_answers_over_only_after_adding_imputed_costs(tmp_path):
    from crest.report import load_run, _resources
    run = make_run(tmp_path / 'run')
    rows = json.loads(answers_path(run).read_text())
    caesar = [row for row in rows if row['agent'] == 'caesar']
    caesar[0]['result']['cost_usd'] = 6.  # Over on its known cost.
    caesar_with_failed_call(caesar[1])  # Known $4.80, over $5.00 only once its failed call is counted.
    caesar_with_failed_call(caesar[2])
    dump(answers_path(run), rows)
    headline = _resources(load_run(run)).split('<details', 1)[0]
    assert ('Estimated cost was above the $5.00 per-answer target for 3 Caesar answers (2 of them only after adding '
            'the calls that never reported a cost).') in headline
    assert 'Google Deep Research and OpenAI (Sol + web search) had no answer over it.' in headline


def test_answer_metadata_shows_the_amount_counted_for_failed_calls(run, tmp_path):
    from crest.report import write_report
    rows = json.loads(answers_path(run).read_text())
    caesar_with_failed_call(next(row for row in rows if row['agent'] == 'caesar'))
    dump(answers_path(run), rows)
    body = write_report(run, tmp_path / 'page.html').read_text()
    assert 'Estimated cost $5.76, including $0.96 for a call that never reported a cost; job time' in body
    assert 'Estimated cost $5.76 (incomplete)' not in body
    assert '&quot;imputed_usd&quot;: 0.96' in body


def test_answer_metadata_says_less_than_a_cent_for_a_tiny_failed_call(run, tmp_path):
    from crest.report import write_report
    rows = json.loads(answers_path(run).read_text())
    caesar_with_failed_call(next(row for row in rows if row['agent'] == 'caesar'), known=.0004, reserved=.006,
                            lost_reserved=.0065)
    dump(answers_path(run), rows)
    body = write_report(run, tmp_path / 'page.html').read_text()
    assert 'Estimated cost $0.00, including less than $0.01 for a call that never reported a cost' in body
    assert 'including $0.00' not in body


def test_google_assumed_price_estimates_are_not_called_incomplete_or_a_lower_bound(run):
    # Google's estimate is an assumed-price scenario at high rates, explained in its own note;
    # it is not missing calls, so it must not be counted as incomplete or called a lower bound.
    from crest.report import load_run, _resources
    rows = json.loads(answers_path(run).read_text())
    for row in rows:
        if row['agent'] == 'gemini':
            row['result']['raw'] = {'agent': 'deep-research-preview-04-2026', 'model': 'gemini-3.1-pro-preview'}
    dump(answers_path(run), rows)
    data = load_run(run)
    assert data['resources']['generation']['gemini']['unknown_cost_answers'] == 50
    headline = _resources(data).split('<details', 1)[0]
    assert 'estimates incomplete' not in headline
    assert 'lower bound' not in headline
    assert 'Google does not report its billing, so its estimate assumes Gemini 3.1 Pro rates' in headline


def test_cost_target_sentence_names_one_shared_target(tmp_path):
    from crest.report import load_run, _resources
    run = make_run(tmp_path / 'run')
    rows = json.loads(answers_path(run).read_text())
    for row in rows[:3]:
        row['result']['cost_usd'] = 6.
    dump(answers_path(run), rows)
    headline = _resources(load_run(run)).split('<details', 1)[0]
    assert ('Estimated cost was above the $5.00 per-answer target for 1 Caesar answer, 1 Google Deep Research answer, '
            'and 1 OpenAI (Sol + web search) answer.') in headline
    assert 'only after adding' not in headline


def test_rubric_notes_cover_the_packaged_rubrics_without_edit_history():
    from crest.report import RUBRIC_NOTES, ROOT
    packaged = sorted(p.stem.rsplit('_', 1)[-1] for p in (ROOT / 'crest/prompts').glob('nus_pairwise_v*.txt'))
    assert sorted(RUBRIC_NOTES) == packaged == ['v1', 'v2', 'v3']
    assert 'skilled practitioner' in RUBRIC_NOTES['v3'] and 'supplied material' in RUBRIC_NOTES['v3']
    assert RUBRIC_NOTES['v3'].endswith('when the answer itself says its evidence does not prove it.')
    assert 'what is original about the central contribution' in RUBRIC_NOTES['v2']
    assert 'name where each part already appears' in RUBRIC_NOTES['v1']
    for note in RUBRIC_NOTES.values():
        for word in ('rewrites', 'older', 'first version', 'study', 'than v', 'default', 'previous', ' now ', 'edited', 'renamed', 'v4', 'no longer', '—'):
            assert word not in note


def test_rubric_takeaway_does_not_say_stays_when_a_rank_is_shared():
    from crest.report import _rubric_takeaway
    agents = ['caesar', 'anthropic', 'gpt_researcher']
    first = _rubric_entry('v1', agents)
    first['common']['ranking'][1]['rank'] = 1  # Caesar and Anthropic share first place.
    text = _rubric_takeaway(agents, [first, _rubric_entry('v2', agents)])
    assert 'Caesar is first or tied for first' in text
    assert 'Caesar stays first' not in text
    assert 'GPT Researcher stays third' in text


def test_ordinal_handles_a_missing_rank():
    from crest.report import _ordinal
    assert _ordinal(None) == 'unranked'
    assert _ordinal(2) == 'second'


def test_cost_section_names_a_lower_soft_target(tmp_path):
    from crest.report import load_run, _resources
    run = make_run(tmp_path / 'run')
    rows = json.loads(answers_path(run).read_text())
    for row in rows:
        row['result']['cost_usd'] = 6. if row['agent'] == 'caesar' else 1.
    dump(answers_path(run), rows)
    data = load_run(run)
    for row in data['answers']:
        if row['agent'] == 'caesar':
            data['configurations'].setdefault(row.get('configuration_id'), {}).setdefault('settings', {}).update(
                {'budget_usd': 5., 'budget_target_usd': 4.25, 'synthesis_reserve_usd': .5})
    headline = _resources(data).split('<details', 1)[0]
    assert 'Caesar’s own settings use a stricter $4.25 target, and 50 of its answers went over it.' in headline
    assert 'none of its answers went over it.' in headline  # This fixture shares one configuration across systems.
    assert ('It starts no new research round once its spending reaches $3.75, which leaves $0.50 of that target '
            'for writing the final answer.') in headline
    assert 'also aims for a lower' not in headline


def test_rubric_takeaway_says_whether_the_intervals_separate_the_systems_that_trade_places():
    from crest.report import _rubric_takeaway
    agents = ['caesar', 'openai', 'anthropic', 'gpt_researcher']
    entries = [_rubric_entry('v1', agents, [('caesar', 'openai'), ('openai', 'anthropic')],
                             wins={'caesar': 90, 'openai': 82}),
               _rubric_entry('v2', ['anthropic', 'openai', 'caesar', 'gpt_researcher'],
                             [('anthropic', 'openai'), ('anthropic', 'caesar'), ('openai', 'caesar')]),
               _rubric_entry('v3', ['anthropic', 'caesar', 'openai', 'gpt_researcher'],
                             [('anthropic', 'caesar'), ('caesar', 'openai')], wins={'anthropic': 89, 'caesar': 88})]
    text = _rubric_takeaway(agents, entries)
    assert text == (
        '<p>The top three trade places from one rubric to another, and for most pairs of them the 95% interval for '
        'the difference includes zero, so the two cannot be separated. Under NUS v1, Caesar is ahead of '
        'Anthropic (Claude + web search), and its 8-judgment lead over OpenAI (Sol + web search), 90 to 82 of 120, '
        'is too small to separate them. Under NUS v3, Anthropic (Claude + web search) is ahead of OpenAI (Sol + web '
        'search), and its 1-judgment lead over Caesar, 89 to 88 of 120, is too small to separate them. GPT '
        'Researcher stays fourth under every rubric.</p>')
    assert 'overlap' not in text


def test_rubric_dropdowns_carry_no_edit_history(tmp_path):
    from crest.report import write_report
    from pathlib import Path
    import crest.report as report
    main_run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    v2 = use_packaged_rubric(make_run(tmp_path / 'v2'), 'v2')
    body = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v2]).read_text()
    for phrase in ('never used', 'was a draft', 'edited on', 'now end', 'current default', 'this report)'):
        assert phrase not in body
    assert 'never used' not in Path(report.__file__).read_text()
    assert ('The NUS v2 file shares its closing rules and output format with NUS v1 and NUS v3, so its wording '
            'differs from the file earlier studies used.') in section(body, 'other-rubrics')


def test_page_wording_avoids_jargon_and_shows_effort_once(run, tmp_path):
    from crest.report import write_report
    body = write_report(run, tmp_path / 'page.html').read_text()
    assert 'how each judge voted' not in body
    assert '<summary>Rubric, how answers were shown, and references</summary>' in body
    assert 'random seed' not in body and 'like for like' not in body
    assert 'are paired' not in body
    judges = body.split('id="judges"', 1)[1].split('</section>', 1)[0]
    assert 'high effort' not in judges
    assert 'Both judges saw every pair in both orders, with no web access, at high reasoning effort.' in judges
    assert 'They include earlier failed attempts when those were recorded.' in body
    assert 'Earlier attempts are included when recorded' not in body
    assert '<span class="nowrap">' in body and '.nowrap{white-space:nowrap}' in body
    assert 'background-attachment:local' in body


def test_shared_judge_model_note_links_to_each_judges_results(tmp_path):
    from crest.report import load_run, _render
    data = load_run(make_run(tmp_path / 'run'))
    data['judges']['openai'] = {**data['judges']['openai'], 'model': 'gpt-6.1-sol'}
    html = _render(data, tmp_path / 'page.html')
    assert '<a href="#judges">See how each judge ruled</a>' in html


def test_caesar_model_note_names_one_model_when_both_roles_match():
    from crest.report import _models
    settings = {'model': 'gpt-6.1-sol', 'exploration_model': 'gpt-6-luna', 'kb_model': 'gpt-6-luna'}
    data = {'ranking': {'ranking': [{'agent': 'caesar'}]},
            'manifest': {'config': {'research': {'caesar': settings}}},
            'answers': [{'agent': 'caesar', 'result': {'model': 'gpt-6.1-sol'}}]}
    html = _models(data)
    assert 'Writes with GPT-6.1 Sol and uses GPT-6 Luna to explore the web and build its knowledge base.' in html
    settings['kb_model'] = 'gpt-6-nova'
    html = _models(data)
    assert ('Writes with GPT-6.1 Sol, explores the web with GPT-6 Luna, '
            'and builds its knowledge base with gpt-6-nova.') in html


def test_over_target_note_says_earlier_failed_attempts_are_included(tmp_path):
    from crest.report import load_run, _resources
    run = make_run(tmp_path / 'run')
    rows = json.loads(answers_path(run).read_text())
    for row in rows:
        row['result']['cost_usd'] = 6. if row['agent'] == 'caesar' and row['question_id'] == 'q001' else 1.
    dump(answers_path(run), rows)
    headline = _resources(load_run(run)).split('<details', 1)[0]
    assert 'They include earlier failed attempts when those were recorded.' in headline
    assert 'per-answer target for 1 Caesar answer.' in headline
    assert 'Actual bills' not in headline


STAND_IN = 'claude-sonnet-5-5'
GATEWAY_TIMEOUT = 'ProviderError: Anthropic gateway HTTP 408; submission status unknown'
RANKED = {'openai': 0, 'caesar': 1, 'gemini': 2}  # Fixes the system order, so pair labels are predictable.


def opus_judged_run(root):
    """Three judges, with the anthropic judge saved as Claude Opus 5.5 as in the real study."""
    run = make_run(root, judges=THREE_JUDGES, choose=lambda q, pair, judge, order: min(pair, key=RANKED.get))
    judges = json.loads((run / '02-judge-test/judges.json').read_text())
    judges['anthropic'] = {**judges['anthropic'], 'model': 'claude-opus-5-5'}
    dump(run / '02-judge-test/judges.json', judges)
    return run


def edit_judgments(run, edit, *, question_index, pair, judge='anthropic', orders=None):
    path = run / '02-judge-test/judgments.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    edited = 0
    for row in rows:
        if (row['question_id'] == f'q{question_index:03}' and row['pair'] == sorted(pair) and row['judge'] == judge
                and (orders is None or row['order'] in [list(o) for o in orders])):
            edit(row)
            edited += 1
    assert edited
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def stand_in(row, refusals=24, model=STAND_IN):
    """The judge refused every try, then the stand-in model judged, as the re-judge records it."""
    row['result']['model'] = model
    row.update(cost_scope='all_judgment_attempts', cost_usd=.1 + .01 * refusals, attempts=[
        *({'attempt': i + 1, 'key': f'{row["key"]}-refused-{i}', 'status': 'rejected', 'error': REFUSAL,
           'cost_usd': .01, 'substitute_model': None, 'result': {'cost_usd': .01, 'usage': {}}} for i in range(refusals)),
        {'attempt': refusals + 1, 'key': f'{row["key"]}-stand-in', 'status': 'completed', 'cost_usd': .1,
         'substitute_model': model, 'result': {'cost_usd': .1, 'usage': {}}}])


def resend(row, error=GATEWAY_TIMEOUT):
    """The first try's outcome is unknown, so its cost is too; the second try succeeded."""
    row.update(cost_scope='all_judgment_attempts', cost_usd=None, known_cost_usd=.1, unknown_cost_count=1, attempts=[
        {'attempt': 1, 'key': f'{row["key"]}-unknown', 'status': 'rejected', 'submission_unknown': True,
         'error': error, 'cost_usd': None, 'substitute_model': None},
        {'attempt': 2, 'key': f'{row["key"]}-resent', 'status': 'completed', 'cost_usd': .1,
         'substitute_model': None, 'result': {'cost_usd': .1, 'usage': {}}}])


def section(body, name):
    return body.split(f'id="{name}"', 1)[1].split('</section>', 1)[0]


def test_stand_in_judgments_are_disclosed_where_the_judges_are_described(tmp_path):
    from crest.report import write_report
    run = opus_judged_run(tmp_path / 'run')
    edit_judgments(run, stand_in, question_index=47, pair=('caesar', 'gemini'))
    body = write_report(run, tmp_path / 'page.html').read_text()
    judges = section(body, 'judges')
    assert ('Claude Opus 5.5 refused 2 judgments on Question 48. It refused each of them on all 24 tries, and the '
            'API labeled every refusal “bio”, its biology-safety category. Claude Sonnet 5.5 made those 2 judgments '
            'instead, and they count toward Claude Opus 5.5’s results. The 2 refused judgments are Question 48, '
            'Caesar vs Google Deep Research, both orders.') in judges
    # Every question still has all its judgments, so nothing is left unranked.
    assert 'not ranked' not in body and 'id="unranked"' not in body
    assert body.count('Claude Sonnet 5.5 in place of Claude Opus 5.5 · Caesar shown first · preferred') == 1
    assert body.count('Claude Sonnet 5.5 in place of Claude Opus 5.5 · Google Deep Research shown first · preferred') == 1
    resources = section(body, 'resources')
    assert '$30.48 for Claude Opus 5.5 (including the 2 judgments Claude Sonnet 5.5 made)' in resources
    assert '—' not in judges + resources


def test_stand_in_disclosure_groups_by_question_and_pair_and_counts_tries(tmp_path):
    from crest.report import load_run, _judges
    run = opus_judged_run(tmp_path / 'run')
    edit_judgments(run, stand_in, question_index=47, pair=('caesar', 'gemini'))
    edit_judgments(run, lambda row: stand_in(row, refusals=3), question_index=10, pair=('caesar', 'openai'),
                   orders=[('caesar', 'openai')])
    html = _judges(load_run(run))
    assert ('Claude Opus 5.5 refused 3 judgments on Questions 11 and 48. It refused each of them on every try, '
            'from 3 to 24 tries,') in html
    assert ('The 3 refused judgments are Question 11, Caesar vs OpenAI (Sol + web search), Caesar shown first; '
            'Question 48, Caesar vs Google Deep Research, both orders.') in html


def test_single_stand_in_judgment_reads_in_the_singular(tmp_path):
    from crest.report import load_run, _judges
    run = opus_judged_run(tmp_path / 'run')
    edit_judgments(run, lambda row: stand_in(row, refusals=1), question_index=47, pair=('caesar', 'gemini'),
                   orders=[('gemini', 'caesar')])
    html = _judges(load_run(run))
    assert ('Claude Opus 5.5 refused 1 judgment on Question 48. It refused it on its only try, and the API labeled '
            'the refusal “bio”, its biology-safety category. Claude Sonnet 5.5 made that judgment instead, and it '
            'counts toward Claude Opus 5.5’s results. The refused judgment is Question 48, Google Deep Research vs '
            'Caesar, Google Deep Research shown first.') in html


def test_rubric_section_discloses_stand_ins_in_the_other_rubric_runs(tmp_path):
    from crest.report import write_report
    main_run = use_packaged_rubric(opus_judged_run(tmp_path / 'v1'), 'v1')
    v3 = use_packaged_rubric(opus_judged_run(tmp_path / 'v3'), 'v3')
    v2 = use_packaged_rubric(opus_judged_run(tmp_path / 'v2'), 'v2')
    edit_judgments(v2, stand_in, question_index=47, pair=('caesar', 'gemini'))
    body = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v3, v2]).read_text()
    # Only v2 had stand-ins, so the judges section names v2 and never claims any under v1.
    assert 'NUS v1' not in section(body, 'judges')
    bottom = section(body, 'other-rubrics')
    # The judges section holds the only stand-in note; the dropdowns repeat none of it.
    assert 'Sonnet' not in bottom and 'refused' not in bottom
    assert ('Claude Opus 5.5 refused 2 judgments on Question 48 under NUS v2. It refused each of them on all 24 '
            'tries, and the API labeled every refusal “bio”, its biology-safety category. Claude Sonnet 5.5 made those '
            '2 judgments instead, and they count toward Claude Opus 5.5’s results.') in section(body, 'judges')
    assert 'refused judgments are' not in section(body, 'judges')  # NUS v1 had none to list.


@pytest.mark.parametrize('kind', ['silent_swap', 'no_attempts', 'not_refused', 'unmarked_last', 'other_substitute',
                                  'marked_without_swap', 'stand_in_not_completed'])
def test_a_judgment_from_another_model_needs_the_judge_to_have_refused_first(tmp_path, kind):
    from crest.report import load_run
    run = opus_judged_run(tmp_path / 'run')

    def edit(row):
        stand_in(row)
        if kind == 'silent_swap':
            row['attempts'] = [{**row['attempts'][-1], 'substitute_model': None}]
        elif kind == 'no_attempts':
            row.pop('attempts')
        elif kind == 'not_refused':
            row['attempts'][0]['error'] = 'ValueError: judge response was not JSON'
        elif kind == 'unmarked_last':
            row['attempts'][-1]['substitute_model'] = None
        elif kind == 'other_substitute':
            row['attempts'][-1]['substitute_model'] = 'claude-haiku-5-5'
        elif kind == 'marked_without_swap':
            row['result']['model'] = 'claude-opus-5-5'
        elif kind == 'stand_in_not_completed':
            row['attempts'][-1]['status'] = 'rejected'
    edit_judgments(run, edit, question_index=47, pair=('caesar', 'gemini'), orders=[('caesar', 'gemini')])
    with pytest.raises(ValueError, match='saved model'):
        load_run(run)


def test_resent_judgments_say_their_first_tries_have_unknown_cost(tmp_path):
    from crest.report import load_run, _resources
    run = opus_judged_run(tmp_path / 'run')
    edit_judgments(run, resend, question_index=3, pair=('caesar', 'gemini'))
    edit_judgments(run, resend, question_index=20, pair=('gemini', 'openai'))
    data = load_run(run)
    assert data['resources']['judging']['anthropic']['unknown_cost_answers'] == 4
    html = _resources(data)
    assert 'The 900 judgments cost $90.40 in total, including retried calls.' in html
    assert ('The first tries of 4 judgments timed out and never reported a cost. We sent each once more and count '
            'each first try at what its second try cost ($0.40 in total).') in html
    assert 'gateway' not in html and 'in all' not in html
    assert 'not in the total' not in html
    assert 'not ranked' not in html


def test_one_resent_judgment_after_a_dropped_connection_reads_in_the_singular(tmp_path):
    from crest.report import load_run, _resources
    run = opus_judged_run(tmp_path / 'run')
    dropped = 'StreamInterrupted: Anthropic stream interrupted after generation started; the attempt is recorded'
    edit_judgments(run, lambda row: resend(row, dropped), question_index=3, pair=('caesar', 'gemini'),
                   orders=[('caesar', 'gemini')])
    html = _resources(load_run(run))
    assert ('The first try of 1 judgment timed out or lost its connection and never reported a cost. We sent it '
            'once more and count the first try at what the second try cost ($0.10).') in html


def _synthetic_ranking(rates, contrasts):
    rows = [{'agent': a, 'rank': i, 'preference_rate': r} for i, (a, r) in enumerate(rates, 1)]
    return {'ranking': {'ranking': rows, 'paired_contrasts': [{'pair': list(pair), 'ci95': list(ci)}
                                                              for pair, ci in contrasts.items()]}}


def test_headline_never_gives_a_clean_place_to_a_system_it_cannot_separate():
    from crest.report import _headline
    # NUS v1 numbers: Caesar vs OpenAI and OpenAI vs Anthropic include zero; Caesar vs Anthropic does not.
    data = _synthetic_ranking(
        [('caesar', .7475), ('openai', .6858333), ('anthropic', .6775), ('gpt_researcher', .3775), ('gemini', .0116667)],
        {('anthropic', 'caesar'): (-.135, -.0017), ('anthropic', 'openai'): (-.0692, .0558),
         ('caesar', 'openai'): (-.0158, .1367), ('anthropic', 'gemini'): (.62, .71), ('anthropic', 'gpt_researcher'): (.25, .35),
         ('caesar', 'gemini'): (.68, .78), ('caesar', 'gpt_researcher'): (.30, .43), ('gemini', 'gpt_researcher'): (-.41, -.33),
         ('gemini', 'openai'): (-.71, -.64), ('gpt_researcher', 'openai'): (-.36, -.25)})
    assert _headline(data) == (
        'Caesar leads at 74.8%. OpenAI (Sol + web search) at 68.6% cannot be separated from Caesar or from '
        'Anthropic (Claude + web search) at 67.8%, but Caesar is ahead of Anthropic (Claude + web search). '
        'GPT Researcher is fourth at 37.8% and Google Deep Research fifth at 1.2%.')


def test_headline_adds_the_head_to_head_split_when_separated_systems_split_their_own_judgments():
    from crest.report import _headline
    data = _synthetic_ranking(
        [('caesar', .7475), ('openai', .6858333), ('anthropic', .6775), ('gpt_researcher', .3775)],
        {('anthropic', 'caesar'): (-.135, -.0017), ('anthropic', 'openai'): (-.0692, .0558),
         ('caesar', 'openai'): (-.0158, .1367), ('anthropic', 'gpt_researcher'): (.25, .35),
         ('caesar', 'gpt_researcher'): (.30, .43), ('gpt_researcher', 'openai'): (-.36, -.25)})
    pairwise = {'caesar': {'anthropic': .5}, 'anthropic': {'caesar': .5}}
    data['ranking']['pairwise'] = {'overall': pairwise}
    assert _headline(data) == (
        'Caesar leads at 74.8%. OpenAI (Sol + web search) at 68.6% cannot be separated from Caesar or from '
        'Anthropic (Claude + web search) at 67.8%. Caesar is ahead of Anthropic (Claude + web search), although the '
        'two split their own head-to-head judgments evenly (50.0%). GPT Researcher is fourth at 37.8%.')
    pairwise['caesar']['anthropic'] = .53
    assert ('although the two split their own head-to-head judgments nearly evenly (53.0%).'
            in _headline(data))
    pairwise['caesar']['anthropic'] = .6
    assert 'but Caesar is ahead of Anthropic (Claude + web search). GPT' in _headline(data)


def test_headline_keeps_the_single_group_shape():
    from crest.report import _headline
    data = _synthetic_ranking([('anthropic', .723), ('openai', .708), ('caesar', .70), ('gemini', .013)],
                              {('anthropic', 'openai'): (-.05, .07), ('anthropic', 'caesar'): (-.04, .09),
                               ('caesar', 'openai'): (-.06, .04), ('anthropic', 'gemini'): (.6, .8),
                               ('caesar', 'gemini'): (.6, .8), ('gemini', 'openai'): (-.8, -.6)})
    assert _headline(data) == ('Anthropic (Claude + web search) at 72.3%, OpenAI (Sol + web search) at 70.8%, and '
                               'Caesar at 70.0% are too close to separate for first place. Google Deep Research is '
                               'fourth at 1.3%.')


def test_headline_names_a_clear_leader_then_a_tied_pair():
    from crest.report import _headline
    data = _synthetic_ranking([('caesar', .8), ('openai', .5), ('gemini', .2)],
                              {('caesar', 'openai'): (.1, .4), ('caesar', 'gemini'): (.5, .7), ('gemini', 'openai'): (-.35, .02)})
    assert _headline(data) == ('Caesar is first at 80.0%. OpenAI (Sol + web search) at 50.0% and Google Deep Research '
                               'at 20.0% are too close to separate for second place.')


def test_displayed_percentages_and_points_round_half_up():
    from crest.report import _pct, _points, _interval
    assert _pct(423 / 1200) == '35.3%'
    assert _pct(.7475) == '74.8%' and _pct(.6775) == '67.8%'
    assert _points(.0025) == '+0.3' and _points(-.0025) == '−0.3'
    assert _interval([.0005, .3525]) == '0.1%–35.3%'


def test_intro_defines_nus_once_and_says_the_judges_did_not_check_facts(tmp_path):
    from crest.report import write_report
    run = use_packaged_rubric(make_run(tmp_path / 'v1'), 'v1')
    body = write_report(run, tmp_path / 'page.html').read_text()
    intro = body.split('<main', 1)[1].split('<nav', 1)[0]
    assert 'Three AI models act as judges.' not in intro  # Two judges here.
    assert 'Two AI models act as judges. They compare the 150 answers two at a time' in intro
    assert ('NUS stands for New (what the answer adds beyond known work), Useful (whether it works for the task), '
            'and Surprising (how far it departs from the approach an expert would most likely take).') in intro
    assert body.count('what the answer adds beyond known work') == 1
    assert ('<p>The judges did not check facts. A high win rate means the judges found the answers more creative, '
            'not that they are more correct. The judges are AI models whose choices have not been checked against '
            'human experts') in intro
    assert 'Factual accuracy' not in body


def test_ranking_defines_win_rate_and_interval_once(tmp_path):
    from crest.report import write_report
    body = write_report(make_run(tmp_path / 'run'), tmp_path / 'page.html').read_text()
    ranking, method = section(body, 'overall'), section(body, 'method')
    assert ('We redrew the 50 questions at random 1,000 times, allowing repeats, and recomputed each win rate, '
            'keeping each question’s 12 judgments together. The bracket covers the middle 95% of those results.') in ranking
    assert 'Every judgment counts equally.' in ranking
    assert 'Redraws where the first system led' in ranking and 'Redraws with equal win rates' in ranking
    assert 'Resamples where' not in ranking
    for gone in ('Count the wins', 'Read the intervals', 'random seed', 'its wins divided by', 'middle 95%'):
        assert gone not in method


def test_method_links_rubric_pages_in_a_sentence_and_states_the_rules_where_the_winner_is_picked(tmp_path):
    from crest.report import write_report
    from crest_ais.site import page_title
    from pathlib import Path
    body = write_report(make_run(tmp_path / 'run'), tmp_path / 'page.html').read_text()
    method = section(body, 'method')
    rubric, why = (page_title(Path(n), n) for n in ('nus-rubric.html', 'why-one-overall-judgment.html'))
    assert (f'The <a href="nus-rubric.html">{rubric}</a> page has the full rubric, and '
            f'<a href="why-one-overall-judgment.html">{why}</a> explains the single pick.') in method
    pick = method.split('<dt>Pick a winner</dt>', 1)[1].split('</dd>', 1)[0]
    assert 'Combining familiar ideas can still be original.' in pick
    assert 'guided by the three NUS criteria' in pick


def test_intro_says_which_system_each_judge_picks_most_often(tmp_path):
    from crest.report import write_report, load_run, _judge_picks
    preference = {'openai': 0, 'caesar': 1, 'gemini': 2}
    run = make_run(tmp_path / 'run', choose=lambda q, pair, judge, order: min(pair, key=preference.get))
    judges = json.loads((run / '02-judge-test/judges.json').read_text())
    judges['openai'] = {**judges['openai'], 'model': 'gpt-6.1-sol'}
    dump(run / '02-judge-test/judges.json', judges)
    data = load_run(run)
    assert _judge_picks(data) == (
        'The only judge that shares a model with any system ranks one of those systems highest: GPT-6.1 Sol, the '
        'main model of OpenAI (Sol + web search) and Caesar, gives OpenAI (Sol + web search) 100.0%. Gemini 4 Argon, '
        'which is not the main model of any system here (Google does not report which models Google Deep Research '
        'runs), gives its highest win rate to OpenAI (Sol + web search), 100.0%.')
    for row in data['ranking']['per_judge']['gemini']:
        row['preference_rate'] = .5 if row['agent'] in ('openai', 'caesar') else 0
    assert _judge_picks(data).endswith('gives OpenAI (Sol + web search) and Caesar the same win rate, 50.0%.')
    # A judge whose model is also the main model of the one system it favors says so in the singular.
    for row in data['ranking']['per_judge']['openai']:
        row['preference_rate'] = 1 if row['agent'] == 'caesar' else 0
    for answer in data['answers']:
        if answer['agent'] == 'openai':
            answer['result']['model'] = 'gpt-6-astra'
    assert _judge_picks(data).startswith(
        'The only judge that shares a model with any system ranks that system highest: GPT-6.1 Sol gives Caesar 100.0%.')
    # A judge that ranks some other system highest gets no summary claim, only its own pick.
    for row in data['ranking']['per_judge']['openai']:
        row['preference_rate'] = 1 if row['agent'] == 'gemini' else 0
    assert _judge_picks(data).startswith(
        'GPT-6.1 Sol, the main model of Caesar, gives its highest win rate to Google Deep Research, 100.0%.')
    body = write_report(run, tmp_path / 'page.html').read_text()
    intro = body.split('<main', 1)[1].split('<nav', 1)[0]
    assert 'GPT-6.1 Sol, the main model of OpenAI (Sol + web search) and Caesar, gives OpenAI (Sol + web search) 100.0%' in intro
    assert 'See how each judge ruled' in intro


def test_previous_study_pointer_counts_its_systems(run, tmp_path):
    from crest.report import write_report
    (tmp_path / 'deep-research-comparison-v2.html').write_text(
        '<main>' + '<div class="ranking-row"></div>' * 3 + '</main>')
    body = write_report(run, tmp_path / 'deep-research-comparison-v3.html').read_text()
    assert ('An earlier study, <a href="deep-research-comparison-v2.html">Deep Research Comparison v2</a> (its '
            'version number is unrelated to the NUS rubric versions), compared three systems.') in section(body, 'method')
    assert 'The previous study is' not in body


def test_cost_section_states_estimates_once_and_drops_empty_qualifiers(run, tmp_path):
    from crest.report import load_run, _resources
    html = _resources(load_run(run))
    assert html.startswith('<section id="resources"><h2>Cost and time</h2><p>Costs are estimates from each answer’s '
                           'saved records, not invoices. They include earlier failed attempts when those were recorded.</p>')
    assert html.count('include earlier failed attempts') == 1
    assert html.count('assumes Gemini 3.1 Pro rates') == 1
    for gone in ('Each mean above', 'Each time average', 'Answers timed', 'soft budget', 'internal billing'):
        assert gone not in html


def test_cost_overruns_use_digits_when_counts_mix_sizes_and_call_the_target_a_goal(tmp_path):
    from crest.report import load_run, _resources
    run = make_run(tmp_path / 'run')
    rows = json.loads(answers_path(run).read_text())
    over = {'caesar': 2, 'gemini': 12}
    for row in rows:
        if over.get(row['agent'], 0) > 0:
            row['result']['cost_usd'] = 6.
            over[row['agent']] -= 1
    dump(answers_path(run), rows)
    html = _resources(load_run(run))
    assert 'for 2 Caesar answers and 12 Google Deep Research answers.' in html
    assert 'The $5.00 target is a goal, and no system is stopped when it goes over.' in html
    assert 'Actual bills' not in html


def test_models_table_uses_plain_tool_names_and_a_plain_header(tmp_path):
    from crest.report import load_run, _models
    html = _models(load_run(make_run(tmp_path / 'run')))
    assert '<th scope="col">Main model</th>' in html
    assert 'Sol with OpenAI’s built-in web search.' in html
    assert 'Responses API' not in html and 'pricing model' not in html and 'estimated with' not in html


def test_stand_ins_across_rubrics_are_described_once_near_the_judges(tmp_path):
    from crest.report import write_report
    main_run = use_packaged_rubric(opus_judged_run(tmp_path / 'v1'), 'v1')
    v3 = use_packaged_rubric(opus_judged_run(tmp_path / 'v3'), 'v3')
    v2 = use_packaged_rubric(opus_judged_run(tmp_path / 'v2'), 'v2')
    edit_judgments(main_run, stand_in, question_index=47, pair=('caesar', 'gemini'))
    edit_judgments(v3, stand_in, question_index=47, pair=('caesar', 'gemini'), orders=[('caesar', 'gemini')])
    body = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v3, v2]).read_text()
    judges = section(body, 'judges')
    assert ('Claude Opus 5.5 refused 3 judgments on Question 48: 2 under NUS v1 and 1 under NUS v3. It refused '
            'each of them on all 24 tries, and the API labeled every refusal “bio”, its biology-safety category. '
            'Claude Sonnet 5.5 made those 3 judgments instead, and they count toward Claude Opus 5.5’s results.') in judges
    assert 'Under NUS v1, the 2 refused judgments are Question 48, Caesar vs Google Deep Research, both orders.' in judges
    bottom = section(body, 'other-rubrics')
    assert 'biology-safety' not in bottom and 'refused to make' not in bottom
    assert 'Sonnet' not in bottom


def test_rubric_dropdown_explains_judging_cost_it_cannot_count(tmp_path):
    from crest.report import write_report
    from lxml import html as lxml_html
    main_run = use_packaged_rubric(opus_judged_run(tmp_path / 'v1'), 'v1')
    v2 = use_packaged_rubric(opus_judged_run(tmp_path / 'v2'), 'v2')
    edit_judgments(v2, resend, question_index=3, pair=('caesar', 'gemini'))
    body = write_report(main_run, tmp_path / 'page.html', rubric_runs=[v2]).read_text()
    box = lxml_html.fromstring(body).get_element_by_id('rubric-v2').text_content()
    assert ('Judging cost: $90.20. The first tries of 2 judgments timed out and never reported a cost. We sent '
            'each once more and count each first try at what its second try cost ($0.20 in total).') in box
    assert 'of unknown cost' not in box


def test_models_table_gives_each_system_its_reasoning_effort_in_its_own_column():
    from crest.report import _models
    from lxml import html as lxml_html
    agents = ['caesar', 'openai', 'anthropic', 'gpt_researcher', 'gemini', 'other']
    research = {
        'caesar': {'exploration_model': 'gpt-5-mini', 'kb_model': 'gpt-5-mini', 'reasoning_effort': 'medium',
                   'synthesis_reasoning_effort': 'high', 'exploration_reasoning_effort': 'low',
                   'kb_reasoning_effort': 'low'},
        'openai': {'reasoning_effort': 'high'},
        'anthropic': {'model': 'claude-opus-5-5', 'effort': 'high', 'tool_mode': 'client'},
        'gpt_researcher': {'model': 'gpt-6-astra', 'reasoning_effort': 'high'},
        'gemini': {'agent': 'deep-research-preview-04-2026'}, 'other': {}}
    data = {'ranking': {'ranking': [{'agent': a} for a in agents]}, 'manifest': {'config': {'research': research}},
            'answers': [{'agent': a, 'result': {'model': 'm'}} for a in agents]}
    table = lxml_html.fromstring(_models(data)).xpath('.//table')[0]
    headers = [th.text_content() for th in table.xpath('.//thead//th')]
    assert headers == ['System', 'Main model', 'Reasoning effort', 'How it researches']
    rows = [[cell.text_content() for cell in tr.xpath('./th|./td')] for tr in table.xpath('.//tbody/tr')]
    assert all(tr.xpath('./*')[0].tag == 'th' for tr in table.xpath('.//tbody/tr'))
    effort = {row[0]: row[2] for row in rows}
    assert effort == {
        'Caesar': 'Medium (main model), high (final write-up), and low (exploration and knowledge base)',
        'OpenAI (Sol + web search)': 'High', 'Anthropic (Claude + web search)': 'High', 'GPT Researcher': 'High',
        'Google Deep Research': 'Not reported (Google manages it)', 'other': 'Not recorded'}
    how = ' '.join(row[3] for row in rows)
    assert 'effort' not in how
    assert 'm with OpenAI’s built-in web search.' in how  # Falls back to the answers' saved model.
    assert 'Claude Opus 5.5 with web search and page reading tools we provide.' in how


def test_caesar_effort_names_each_step_when_exploration_and_knowledge_base_differ():
    from crest.report import _reasoning_effort
    assert _reasoning_effort('caesar', {'reasoning_effort': 'medium', 'synthesis_reasoning_effort': 'high',
                                        'exploration_reasoning_effort': 'low', 'kb_reasoning_effort': 'medium'}) == (
        'Medium (main model), high (final write-up), low (exploration), and medium (knowledge base)')
    assert _reasoning_effort('caesar', {'reasoning_effort': 'medium'}) == 'Medium (main model)'
    assert _reasoning_effort('caesar', {}) == 'Not recorded'


def test_table_marks_numeric_columns_and_wide_tables():
    from crest.report import _table
    plain = _table(['System', 'Win rate'], [['A', '50.0%']], 'Plain', row_headers=True)
    assert '<table>' in plain and '<table >' not in plain and 'class="num"' not in plain
    numeric = _table(['System', 'Win rate', '95% interval'], [['A', '50.0%', '40.0%–60.0%']], 'Numbers',
                     row_headers=True, num_from=1)
    assert '<th scope="col">System</th><th scope="col" class="num">Win rate</th>' in numeric
    assert '<tr><th scope="row">A</th><td class="num">50.0%</td><td class="num">40.0%–60.0%</td></tr>' in numeric
    wide = _table(list('ABCDE'), [list('12345')], 'Wide')
    assert '<table class="wide">' in wide
    assert '<table class="matrix">' in _table(list('ABCDE'), [list('12345')], 'Matrix', 'class="matrix"')
    assert '<table class="wide matrix">' in _table(list('AB'), [list('12')], 'Both', 'class="matrix"', wide=True)
    assert '<table>' in _table(list('ABCDE'), [list('12345')], 'Narrow', wide=False)


def test_answer_headings_sit_below_the_page_question_headings():
    from crest.report import _markdown_answer
    html = _markdown_answer('# One\n\n## Two\n\n### Three\n\ntext')
    assert '<h5>One</h5>' in html and '<h6>Two</h6>' in html and '<h6 class="answer-minor-heading">Three</h6>' in html
    assert not re.search('<h[1-4]', html)


def test_saved_settings_print_once_per_configuration_without_local_paths(run, tmp_path):
    from crest.artifacts import answer_metadata, configuration_record
    from crest.report import write_report
    rows = json.loads(answers_path(run).read_text())
    registry = {}
    for index, row in enumerate(rows):
        settings = {'model': 'gpt-6.1-sol', 'rome_path': '/Users/someone/Desktop/rome',
                    'python_executable': '/opt/homebrew/bin/python', 'note': 'run from /Users/someone/work'}
        task = {'agent': row['agent'], 'settings': settings, 'adapter_version': 1, 'source_identity': None}
        record = configuration_record(task)
        registry[record['configuration_id']] = record
        row.update(answer_metadata(task, index // 3 + 1))
    dump(answers_path(run), rows)
    dump(run / '01-generate-test/configurations.json', registry)
    html = write_report(run, tmp_path / 'page.html').read_text()
    assert len(registry) == 3
    assert html.count('class="configuration"') == 3
    assert html.count('&quot;configuration_sha256&quot;') == 3
    for configuration_id in registry:
        assert html.count(f'id="settings-{configuration_id}"') == 1
        assert html.count(f'href="#settings-{configuration_id}"') == 50
    assert 'Used by 50 answers.' in html
    assert 'Local file paths are left out: <code>rome_path</code> and <code>python_executable</code>.' in html
    assert '/Users/someone' not in html and '/opt/homebrew' not in html
    assert 'run from ~/work' in html
    # The saved records keep the paths.
    assert '/Users/someone/Desktop/rome' in (run / '01-generate-test/configurations.json').read_text()


def test_questions_section_counts_outright_question_wins_and_ties(tmp_path):
    from crest.report import load_run, _questions
    cycle = {('caesar', 'openai'): 'caesar', ('gemini', 'openai'): 'openai', ('caesar', 'gemini'): 'gemini'}
    def choose(q, pair, judge, order):
        if q < 30:
            return 'openai' if 'openai' in pair else 'caesar'
        if q < 40:
            return 'caesar' if 'caesar' in pair else 'openai'
        return cycle[tuple(sorted(pair))]  # Each system wins one pair, so the question is a three-way tie.
    html = _questions(load_run(make_run(tmp_path / 'run', choose=choose)))
    assert ('A tie is shown when two or more systems share the most wins. OpenAI (Sol + web search) wins 30 questions outright, Caesar 10, and Google Deep '
            'Research none, with 10 ties. Open an answer') in html


def test_answer_tables_are_numbered_within_their_answer():
    from crest.report import _markdown_answer
    html = _markdown_answer('|a|\n|-|\n|1|\n\ntext\n\n|b|\n|-|\n|2|', label='Caesar answer, question 3')
    assert 'aria-label="Table 1 in Caesar answer, question 3"' in html
    assert 'aria-label="Table 2 in Caesar answer, question 3"' in html
    assert 'aria-label="Answer table"' not in html


def test_saved_settings_hide_gateway_fields_and_open_from_their_link():
    from crest.report import _saved_settings, _settings_anchor
    from lxml import html as lxml_html
    settings = {'model': 'claude-opus-5-5', 'api_base': 'https://gateway.example', 'api_key_env': 'GATEWAY_KEY',
                'nested': {'api_url': 'https://gateway.example/v1/messages', 'kept': 1}}
    data = {'ranking': {'ranking': [{'agent': 'anthropic'}]}, 'manifest': {},
            'configurations': {'cfg-1': {'settings': settings}},
            'answers': [{'agent': 'anthropic', 'configuration_id': 'cfg-1'}]}
    html = _saved_settings(data)
    assert 'gateway.example' not in html and 'GATEWAY_KEY' not in html and '&quot;kept&quot;: 1' in html
    assert ('Gateway connection fields are left out: <code>api_base</code>, <code>api_key_env</code>, and '
            '<code>api_url</code>.') in html
    box = lxml_html.fromstring(html)
    # The link target sits inside the block, so following the link opens it.
    assert box.get('id') is None
    assert box.xpath('.//div[@class="configuration-body"]')[0].get('id') == _settings_anchor('cfg-1')


def test_rubric_dropdowns_list_the_difference_intervals_behind_their_headline():
    from crest.report import _cluster_differences
    entry = _rubric_entry('v3', ['anthropic', 'caesar', 'openai', 'gpt_researcher'],
                          [('anthropic', 'caesar'), ('caesar', 'openai')])
    view = entry['common']
    assert _cluster_differences(view) == (
        'The 95% interval for each difference among the top three, in percentage points: Anthropic (Claude + web '
        'search) vs Caesar −10.0 to +10.0; Anthropic (Claude + web search) vs OpenAI (Sol + web search) +10.0 to '
        '+20.0; Caesar vs OpenAI (Sol + web search) −10.0 to +10.0.')
    # A contrast saved in the other order is flipped so the higher-ranked system comes first.
    for c in view['paired_contrasts']:
        if c['pair'] == ['anthropic', 'openai']:
            c['pair'], c['ci95'] = ['openai', 'anthropic'], [-.2, -.1]
    assert 'Anthropic (Claude + web search) vs OpenAI (Sol + web search) +10.0 to +20.0;' in _cluster_differences(view)
    assert _cluster_differences(_rubric_entry('v1', ['caesar', 'openai'])['common']) == ''


def test_page_says_which_models_wrote_the_questions(tmp_path):
    from crest.report import load_run, write_report, _judges
    run = make_run(tmp_path / 'run')
    authors = ['gemini-4-argon'] * 20 + ['gpt-6-astra'] * 20 + ['claude-fable-5-1'] * 10
    manifest = json.loads((run / 'run.json').read_text())
    for question, author in zip(manifest['questions'], authors):
        question['generated_by'] = author
    dump(run / 'run.json', manifest)
    questions = json.loads((run / '02-judge-test/questions.json').read_text())
    for question, author in zip(questions, authors):
        question['generated_by'] = author
    dump(run / '02-judge-test/questions.json', questions)
    body = write_report(run, tmp_path / 'page.html').read_text()
    intro = body.split('<main', 1)[1].split('<nav', 1)[0]
    assert ('The questions were written by AI models: 20 by Gemini 4 Argon, 20 by GPT-6 Astra, and 10 by '
            'Claude Fable 5.1.') in intro
    # A judge that also wrote questions says so where the judges are described.
    assert 'Gemini 4 Argon also wrote 20 of the 50 questions.' in _judges(load_run(run))


def test_question_authors_are_left_out_when_any_question_lacks_one(tmp_path):
    from crest.report import load_run, _question_authors
    data = load_run(make_run(tmp_path / 'run'))
    assert _question_authors(data) == ''
