"""Artifact names and result paths.

Configuration records retain frozen provenance without changing jobs; run and stage
directories use local-time names while event timestamps stay UTC; attached runs keep
frozen stage references; later stages find the latest run through its pointer.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
from types import SimpleNamespace

import pytest

from crest import artifacts
from crest.cache import write_json
from crest.cli import main
from crest.config import load_config
from crest.pipeline import Pipeline


def task():
    return {'agent': 'caesar', 'key': 'paid-key', 'question_id': 'q-original',
            'prompt': 'Original question', 'adapter_version': 'caesar-v1',
            'source_identity': {'source_sha256': 'frozen-source'},
            'settings': {'model': 'gpt-6.1-sol', 'budget_usd': 5.0,
                         'max_completion_tokens': 25000, 'concurrency': 4,
                         'initial_concurrency': 1, 'poll_interval_seconds': 5,
                         'retry_attempts': 4, 'retry_backoff_base_seconds': 1,
                         'retry_backoff_max_seconds': 30}}


def test_configuration_identity_ignores_question_and_transport_but_keeps_provenance():
    original = task()
    changed = deepcopy(original)
    changed.update(key='another-paid-key', question_id='q-other', prompt='Another question')
    changed['settings'].update({key: 99 for key in artifacts.TRANSPORT_SETTINGS})
    first, second = artifacts.configuration_record(original), artifacts.configuration_record(changed)
    assert first == second
    assert re.fullmatch(r'caesar-[0-9a-f]{12}', first['configuration_id'])
    assert len(first['configuration_sha256']) == 64
    assert first['short_id'] == first['configuration_sha256'][:12]
    assert first['adapter_version'] == original['adapter_version']
    assert first['source_identity'] == original['source_identity']
    assert first['settings']['max_completion_tokens'] == 25000
    assert not artifacts.TRANSPORT_SETTINGS.intersection(first['settings'])
    assert 'caesar' in first['label'] and 'gpt-6.1-sol' in first['label']
    assert original == task()


def test_shared_prompt_template_distinguishes_configurations_without_splitting_questions():
    original, other_question = task(), task()
    other_question.update(question_id='another-question', prompt='Another rendered question', key='another-key')
    template = 'Research the following question: {question}'
    first = artifacts.configuration_record(original, prompt_template=template)
    second = artifacts.configuration_record(other_question, prompt_template=template)
    changed = artifacts.configuration_record(original, prompt_template='Answer briefly: {question}')
    assert first == second
    assert first['prompt_template'] == template
    assert first['configuration_id'] != changed['configuration_id']
    metadata = artifacts.answer_metadata(original, 1, prompt_template=template)
    assert metadata['configuration_id'] == first['configuration_id']
    assert metadata['configuration_sha256'] == first['configuration_sha256']
    assert artifacts.configuration_record(original)['prompt_template'] is None
    assert original == task()


@pytest.mark.parametrize('path,value', [
    (('settings', 'model'), 'gpt-6-astra'), (('settings', 'budget_usd'), 4.25),
    (('settings', 'max_completion_tokens'), 16000), (('settings', 'recovery_from'), '/paid/attempt-one'),
    (('settings', 'budget_history_from'), '/paid/attempt-two'), (('settings', 'synthesis_reserve_usd'), 2.0),
    (('agent',), 'openai'), (('adapter_version',), 'caesar-v2'),
    (('source_identity',), {'source_sha256': 'another-source'}),
])
def test_setting_recovery_adapter_and_source_changes_have_distinct_configuration_ids(path, value):
    original, changed = task(), task()
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert artifacts.configuration_record(original)['configuration_id'] != artifacts.configuration_record(changed)['configuration_id']


def test_answer_metadata_is_flat_and_uses_question_ordinal():
    original = task()
    original['question_id'] = 'arbitrary-external-question-id'
    record = artifacts.configuration_record(original)
    metadata = artifacts.answer_metadata(original, 1)
    assert metadata == {'answer_file': f"answers/q01-caesar-{record['short_id']}.md",
                        'configuration_id': record['configuration_id'],
                        'configuration_sha256': record['configuration_sha256']}
    assert artifacts.answer_metadata(original, 50)['answer_file'].startswith('answers/q50-caesar-')
    record['settings']['model'] = 'mutated'
    record['source_identity']['source_sha256'] = 'mutated'
    assert original['settings']['model'] == 'gpt-6.1-sol'
    assert original['source_identity']['source_sha256'] == 'frozen-source'


@pytest.mark.parametrize('number', [0, -1, True, 1.5])
def test_answer_numbers_must_be_positive_ordinals(number):
    with pytest.raises(ValueError):
        artifacts.answer_metadata(task(), number)


def test_directory_names_show_local_seconds_without_changing_event_timestamps():
    event = '20261027T090203.987654Z'
    assert artifacts.run_directory_name(event, 'abcd1234') == '04-02-03-CDT-abcd1234'
    assert artifacts.stage_directory_name(1, 'generate', event) == '01-generate-2026-10-27_04-02-03-CDT'
    assert artifacts.stage_directory_name(2, 'judge', event) == '02-judge-2026-10-27_04-02-03-CDT'
    local = datetime(2026, 10, 27, 4, 2, 3, tzinfo=timezone(timedelta(hours=-5)))
    assert artifacts.run_directory_name(local, 'abcd1234') == '04-02-03-CDT-abcd1234'
    assert event == '20261027T090203.987654Z'


@pytest.mark.parametrize('event,results_timezone,prefix', [
    ('2026-11-21T22:30:36Z', 'America/Chicago', '16-30-36-CST'),
    ('2026-11-01T06:30:00Z', 'America/Chicago', '01-30-00-CDT'),
    ('2026-11-01T07:30:00Z', 'America/Chicago', '01-30-00-CST'),
    ('2026-11-21T22:30:36Z', 'UTC', '22-30-36-UTC'),
])
def test_run_directory_name_adds_stable_selected_agent_slug(event, results_timezone, prefix):
    agents = ['gpt_researcher', 'anthropic', 'anthropic']
    name = artifacts.run_directory_name(event, '58cee12d', agents=agents,
                                         question_count=1, results_timezone=results_timezone)
    assert name == prefix + '-anthropic-gpt-researcher-q1-58cee12d'
    assert agents == ['gpt_researcher', 'anthropic', 'anthropic']
    assert artifacts.run_directory_name(event, '58cee12d', agents=list(reversed(agents)),
                                         question_count=1, results_timezone=results_timezone) == name


@pytest.mark.parametrize('agents,label', [
    (['caesar', 'openai', 'gemini', 'anthropic', 'gpt_researcher'], '5-research-agents'),
    (['a' * 300], '1-research-agents'),
    ([f'agent{i}' for i in range(100)], '100-research-agents'),
])
def test_run_directory_name_summarizes_long_agent_lists_without_truncating_count_or_nonce(agents, label):
    name = artifacts.run_directory_name('2026-11-21T22:30:36Z', '58cee12d',
                                         agents=agents, question_count=50)
    assert name == f'16-30-36-CST-{label}-q50-58cee12d'
    assert len(name.encode('ascii')) <= 96
    assert re.fullmatch(r'[a-zA-Z0-9-]+', name)


# None is a question count without agents, which must not silently drop the context.
@pytest.mark.parametrize('agents', [None, [], 'openai', ['../secret'], ['/private/key'],
                                  ['user prompt'], ['agent/other'], ['Ünicode'], [None], [42]])
def test_run_directory_name_rejects_nonidentifier_agent_context(agents):
    with pytest.raises(ValueError, match='[Aa]gent'):
        artifacts.run_directory_name('2026-11-21T22:30:36Z', '58cee12d',
                                       agents=agents, question_count=1)


@pytest.mark.parametrize('count', [None, 0, -1, True, 1.5, '1'])
def test_run_directory_name_requires_positive_question_count_with_agents(count):
    with pytest.raises(ValueError, match='[Qq]uestion'):
        artifacts.run_directory_name('2026-11-21T22:30:36Z', '58cee12d',
                                       agents=['openai'], question_count=count)


def test_run_directory_name_rejects_context_exceeding_component_bound():
    with pytest.raises(ValueError, match='too long'):
        artifacts.run_directory_name('2026-11-21T22:30:36Z', '58cee12d',
                                       agents=['openai'], question_count=10 ** 100)


def test_run_date_bucket_and_name_use_the_same_local_day():
    event = '2026-10-27T04:17:53Z'
    assert artifacts.run_date_directory_name(event) == '2026-10-26'
    assert artifacts.run_directory_name(event, '8bbde248') == '23-17-53-CDT-8bbde248'


@pytest.mark.parametrize('event, suffix', [
    ('2026-11-01T06:30:00Z', '01-30-00-CDT'),
    ('2026-11-01T07:30:00Z', '01-30-00-CST'),
])
def test_directory_timezone_suffix_distinguishes_repeated_dst_hour(event, suffix):
    assert artifacts.run_directory_name(event, 'abcd1234') == suffix + '-abcd1234'
    assert artifacts.stage_directory_name(2, 'judge', event) == '02-judge-2026-11-01_' + suffix


def test_offset_timestamp_is_converted_to_the_configured_timezone():
    event = '2026-10-27T21:29:00+04:00'
    assert artifacts.stage_directory_name(2, 'judge', event) == '02-judge-2026-10-27_12-29-00-CDT'
    assert artifacts.run_directory_name(event, 'abcd1234', results_timezone='America/New_York') == '13-29-00-EDT-abcd1234'
    assert artifacts.run_date_directory_name('2026-10-27T04:17:53Z', results_timezone='UTC') == '2026-10-27'


@pytest.mark.parametrize('event', ['2026-10-27T04:17:53', datetime(2026, 10, 27, 4, 17, 53)])
def test_directory_timestamps_must_be_timezone_aware(event):
    with pytest.raises(ValueError, match='timezone'):
        artifacts.run_date_directory_name(event)
    with pytest.raises(ValueError, match='timezone'):
        artifacts.run_directory_name(event, 'abcd1234')


@pytest.mark.parametrize('name', ['01-generate-2026-10-27_09-02-03Z',
                                  '16-30-36-CST-anthropic-gpt-researcher-q1-58cee12d'])
def test_directory_reservation_is_atomic_under_concurrency_and_preserves_existing_files(tmp_path, name):
    parent = tmp_path / 'new' / 'day'
    first = artifacts.reserve_directory(parent, name)
    (first / 'answer.md').write_text('Already persisted')
    with ThreadPoolExecutor(max_workers=8) as workers:
        paths = list(workers.map(lambda _: artifacts.reserve_directory(parent, first.name), range(12)))
    assert len(set(paths)) == 12
    assert {path.name for path in paths} == {first.name + f'-{number}' for number in range(2, 14)}
    assert (first / 'answer.md').read_text() == 'Already persisted'


@pytest.mark.parametrize('name', ['../escape', 'a/b', '.', '..', ''])
def test_directory_reservation_rejects_nonlocal_names(tmp_path, name):
    with pytest.raises(ValueError):
        artifacts.reserve_directory(tmp_path, name)


@pytest.mark.parametrize('zone, date, run_name, stage_name', [
    (None, '2026-10-26', '23-17-53-CDT-openai-q1-8bbde248', '01-generate-2026-10-26_23-17-53-CDT'),
    ('UTC', '2026-10-27', '04-17-53-UTC-openai-q1-8bbde248', '01-generate-2026-10-27_04-17-53-UTC'),
    ('Asia/Kathmandu', '2026-10-27', '10-02-53-+0545-openai-q1-8bbde248', '01-generate-2026-10-27_10-02-53-+0545'),
])
def test_production_run_uses_local_date_and_keeps_utc_manifest_timestamps(
        tmp_path, monkeypatch, zone, date, run_name, stage_name):
    import crest.pipeline as pipeline_module

    questions = tmp_path / 'questions.jsonl'
    questions.write_text('{"query":"Offline naming check"}\n')
    source = tmp_path / 'crest.yaml'
    source.write_text(f'questions: {questions}\ncache_dir: cache\noutput_dir: results\n')
    if zone:
        with source.open('a') as stream:
            stream.write(f'results_timezone: {zone}\n')
    config = load_config(source)
    config['research'] = {'openai': config['research']['openai']}
    pipeline = Pipeline(config, providers={'openai': SimpleNamespace(ADAPTER_VERSION='offline-v1')})
    stamp = '20261027T041753.123456Z'
    monkeypatch.setattr(pipeline_module, 'timestamp', lambda: stamp)
    monkeypatch.setattr(pipeline_module.uuid, 'uuid4', lambda: SimpleNamespace(hex='8bbde248' + '0' * 24))

    pipeline._ensure_run()
    assert pipeline.run_dir == tmp_path / 'results' / date / run_name
    stage = pipeline._new_stage(1, 'generate')
    assert stage.name == stage_name
    manifest = json.loads((pipeline.run_dir / 'run.json').read_text())
    assert manifest['created_at'] == stamp
    assert manifest['stages'][0]['started_at'] == stamp
    assert json.loads((stage / 'manifest.json').read_text())['started_at'] == stamp
    latest = json.loads((tmp_path / 'results' / '.cache' / 'latest.json').read_text())
    assert latest == {'run_dir': str(pipeline.run_dir), 'created_at': stamp}
    assert not (tmp_path / 'results' / 'latest.json').exists()


def test_attached_run_keeps_frozen_stage_names_and_uses_current_results_timezone(tmp_path, monkeypatch):
    import crest.pipeline as pipeline_module

    old_stage = '01-generate-2026-10-27_04-17-53Z'
    (tmp_path / old_stage).mkdir()
    (tmp_path / 'run.json').write_text(json.dumps({
        'schema': 'crest-run-v1', 'created_at': '20261027T041753.123456Z',
        'questions': [], 'stages': [{'name': 'generate', 'directory': old_stage,
                                   'status': 'completed'}],
    }))
    config_path = tmp_path / 'crest.yaml'
    config_path.write_text('results_timezone: America/New_York\ncache_dir: cache\n')
    pipeline = Pipeline(load_config(config_path), run_dir=tmp_path)
    monkeypatch.setattr(pipeline_module, 'timestamp', lambda: '20261027T172900.000000Z')

    stage = pipeline._new_stage(2, 'judge')
    assert stage.name == '02-judge-2026-10-27_13-29-00-EDT'
    assert pipeline._latest_stage('generate') == tmp_path / old_stage
    assert pipeline.manifest['stages'][0]['directory'] == old_stage


@pytest.mark.parametrize('setting', ['Mars/Olympus', '', None, 5, True, '/America/Chicago'])
def test_config_rejects_invalid_results_timezone(tmp_path, setting):
    config_path = tmp_path / 'crest.yaml'
    config_path.write_text('results_timezone: ' + json.dumps(setting) + '\n')
    with pytest.raises(ValueError, match='results_timezone must be a valid IANA timezone'):
        load_config(config_path)


def _later_stage_config(tmp_path, pointers):
    """A results tree whose latest run is reachable through the hidden and/or legacy pointer."""
    results = tmp_path / 'results'
    run = results / '2026-10-26' / '23-17-53-CDT-8bbde248'
    write_json(run / 'run.json', {
        'schema': 'crest-run-v1', 'created_at': '20261027T041753.123456Z',
        'questions': [], 'agents': ['openai', 'gemini'],
        'generation_jobs': [], 'stages': [],
    })
    pointer = {'run_dir': str(run), 'created_at': '20261027T041753.123456Z'}
    if pointers in {'hidden', 'both'}:
        write_json(results / '.cache' / 'latest.json', pointer)
    if pointers in {'legacy', 'both'}:
        legacy = pointer if pointers == 'legacy' else pointer | {'run_dir': str(results / 'old-run')}
        write_json(results / 'latest.json', legacy)
    rubric = tmp_path / 'rubric_v2.txt'
    rubric.write_text('Compare New, Useful and Surprising. Choose A or B.')
    config = tmp_path / 'crest.yaml'
    config.write_text(f'output_dir: {results}\ncache_dir: {results / ".cache/generation"}\nrubric: {rubric}\n')
    return config, results, run


@pytest.mark.parametrize('stage', ['judge', 'analyze'])
@pytest.mark.parametrize('pointers', ['hidden', 'legacy', 'both'])
def test_later_stage_defaults_to_hidden_latest_with_legacy_fallback(tmp_path, capsys, stage, pointers):
    config, results, run = _later_stage_config(tmp_path, pointers)
    assert main([stage, '--config', str(config), '--dry-run']) == 0
    assert json.loads(capsys.readouterr().out)['run_dir'] == str(run)
    if pointers == 'hidden':
        assert not (results / 'latest.json').exists()


@pytest.mark.parametrize('stage', ['judge', 'analyze'])
def test_later_stage_on_latest_run_rejects_agent_subset(tmp_path, capsys, stage):
    """Regression: --agents was silently ignored when the run came from the latest pointer."""
    config, _, _ = _later_stage_config(tmp_path, 'hidden')
    with pytest.raises(SystemExit) as exc:
        main([stage, '--config', str(config), '--agents', 'openai', '--dry-run'])
    assert exc.value.code == 2
    assert 'existing run keeps its agent snapshot' in capsys.readouterr().err


def test_later_stage_without_any_latest_pointer_reports_how_to_select_a_run(tmp_path, capsys):
    config = tmp_path / 'crest.yaml'
    config.write_text('output_dir: results\n')
    with pytest.raises(SystemExit) as exc:
        main(['judge', '--config', str(config), '--dry-run'])
    assert exc.value.code == 2
    assert 'generate first or pass --run PATH' in capsys.readouterr().err
