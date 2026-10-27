"""Artifact names retain frozen configuration provenance without changing jobs."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import re

import pytest


def artifacts():
    assert importlib.util.find_spec('crest.artifacts') is not None
    return importlib.import_module('crest.artifacts')


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
    module = artifacts()
    original = task()
    changed = deepcopy(original)
    changed.update(key='another-paid-key', question_id='q-other', prompt='Another question')
    changed['settings'].update({key: 99 for key in module.TRANSPORT_SETTINGS})
    first, second = module.configuration_record(original), module.configuration_record(changed)
    assert first == second
    assert re.fullmatch(r'caesar-[0-9a-f]{12}', first['configuration_id'])
    assert len(first['configuration_sha256']) == 64
    assert first['short_id'] == first['configuration_sha256'][:12]
    assert first['adapter_version'] == original['adapter_version']
    assert first['source_identity'] == original['source_identity']
    assert first['settings']['max_completion_tokens'] == 25000
    assert not module.TRANSPORT_SETTINGS.intersection(first['settings'])
    assert 'caesar' in first['label'] and 'gpt-6.1-sol' in first['label']
    assert original == task()


def test_shared_prompt_template_distinguishes_configurations_without_splitting_questions():
    module = artifacts()
    original, other_question = task(), task()
    other_question.update(question_id='another-question', prompt='Another rendered question', key='another-key')
    template = 'Research the following question: {question}'
    first = module.configuration_record(original, prompt_template=template)
    second = module.configuration_record(other_question, prompt_template=template)
    changed = module.configuration_record(original, prompt_template='Answer briefly: {question}')
    assert first == second
    assert first['prompt_template'] == template
    assert first['configuration_id'] != changed['configuration_id']
    metadata = module.answer_metadata(original, 1, prompt_template=template)
    assert metadata['configuration_id'] == first['configuration_id']
    assert metadata['configuration_sha256'] == first['configuration_sha256']
    assert module.configuration_record(original)['prompt_template'] is None
    assert original == task()


@pytest.mark.parametrize('field,value', [
    ('model', 'gpt-6-astra'), ('budget_usd', 4.25),
    ('max_completion_tokens', 16000), ('recovery_from', '/paid/attempt-one'),
    ('budget_history_from', '/paid/attempt-two'), ('synthesis_reserve_usd', 2.0),
])
def test_actual_setting_and_recovery_changes_have_distinct_configuration_ids(field, value):
    module = artifacts()
    original, changed = task(), task()
    changed['settings'][field] = value
    assert module.configuration_record(original)['configuration_id'] != module.configuration_record(changed)['configuration_id']


@pytest.mark.parametrize('field,value', [
    ('agent', 'openai'), ('adapter_version', 'caesar-v2'),
    ('source_identity', {'source_sha256': 'another-source'}),
])
def test_provider_adapter_and_frozen_source_changes_have_distinct_ids(field, value):
    module = artifacts()
    original, changed = task(), task()
    changed[field] = value
    assert module.configuration_record(original)['configuration_id'] != module.configuration_record(changed)['configuration_id']


def test_answer_metadata_is_flat_and_uses_question_ordinal():
    module = artifacts()
    original = task()
    original['question_id'] = 'arbitrary-external-question-id'
    record = module.configuration_record(original)
    metadata = module.answer_metadata(original, 1)
    assert metadata == {'answer_file': f"answers/q01-caesar-{record['short_id']}.md",
                        'configuration_id': record['configuration_id'],
                        'configuration_sha256': record['configuration_sha256']}
    assert module.answer_metadata(original, 50)['answer_file'].startswith('answers/q50-caesar-')
    record['settings']['model'] = 'mutated'
    record['source_identity']['source_sha256'] = 'mutated'
    assert original['settings']['model'] == 'gpt-6.1-sol'
    assert original['source_identity']['source_sha256'] == 'frozen-source'


@pytest.mark.parametrize('number', [0, -1, True, 1.5])
def test_answer_numbers_must_be_positive_ordinals(number):
    with pytest.raises(ValueError):
        artifacts().answer_metadata(task(), number)


def test_directory_names_show_local_seconds_without_changing_event_timestamps():
    module = artifacts()
    event = '20261027T090203.987654Z'
    assert module.run_directory_name(event, 'abcd1234') == '04-02-03-CDT-abcd1234'
    assert module.stage_directory_name(1, 'generate', event) == '01-generate-2026-10-27_04-02-03-CDT'
    assert module.stage_directory_name(2, 'judge', event) == '02-judge-2026-10-27_04-02-03-CDT'
    local = datetime(2026, 10, 27, 4, 2, 3, tzinfo=timezone(timedelta(hours=-5)))
    assert module.run_directory_name(local, 'abcd1234') == '04-02-03-CDT-abcd1234'
    assert event == '20261027T090203.987654Z'


def test_run_date_bucket_and_name_use_the_same_local_day():
    module = artifacts()
    event = '2026-10-27T04:17:53Z'
    assert module.run_date_directory_name(event) == '2026-10-26'
    assert module.run_directory_name(event, '8bbde248') == '23-17-53-CDT-8bbde248'


@pytest.mark.parametrize('event, suffix', [
    ('2026-11-01T06:30:00Z', '01-30-00-CDT'),
    ('2026-11-01T07:30:00Z', '01-30-00-CST'),
])
def test_directory_timezone_suffix_distinguishes_repeated_dst_hour(event, suffix):
    module = artifacts()
    assert module.run_directory_name(event, 'abcd1234') == suffix + '-abcd1234'
    assert module.stage_directory_name(2, 'judge', event) == '02-judge-2026-11-01_' + suffix


def test_offset_timestamp_is_converted_to_the_configured_timezone():
    module = artifacts()
    event = '2026-10-27T21:29:00+04:00'
    assert module.stage_directory_name(2, 'judge', event) == '02-judge-2026-10-27_12-29-00-CDT'
    assert module.run_directory_name(event, 'abcd1234', results_timezone='America/New_York') == '13-29-00-EDT-abcd1234'
    assert module.run_date_directory_name('2026-10-27T04:17:53Z', results_timezone='UTC') == '2026-10-27'


@pytest.mark.parametrize('event', ['2026-10-27T04:17:53', datetime(2026, 10, 27, 4, 17, 53)])
def test_directory_timestamps_must_be_timezone_aware(event):
    module = artifacts()
    with pytest.raises(ValueError, match='timezone'):
        module.run_date_directory_name(event)
    with pytest.raises(ValueError, match='timezone'):
        module.run_directory_name(event, 'abcd1234')


def test_directory_reservation_is_atomic_under_concurrency_and_preserves_existing_files(tmp_path):
    module = artifacts()
    parent = tmp_path / 'new' / 'day'
    first = module.reserve_directory(parent, '01-generate-2026-10-27_09-02-03Z')
    (first / 'answer.md').write_text('Already persisted')
    with ThreadPoolExecutor(max_workers=8) as workers:
        paths = list(workers.map(lambda _: module.reserve_directory(parent, first.name), range(12)))
    assert len(set(paths)) == 12
    assert {path.name for path in paths} == {first.name + f'-{number}' for number in range(2, 14)}
    assert (first / 'answer.md').read_text() == 'Already persisted'


@pytest.mark.parametrize('name', ['../escape', 'a/b', '.', '..', ''])
def test_directory_reservation_rejects_nonlocal_names(tmp_path, name):
    with pytest.raises(ValueError):
        artifacts().reserve_directory(tmp_path, name)
