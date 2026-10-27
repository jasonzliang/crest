"""Local result paths retain UTC event timestamps and frozen stage references."""
import json
from types import SimpleNamespace

import pytest

from crest.config import load_config
from crest.pipeline import Pipeline


@pytest.mark.parametrize('zone, date, run_name, stage_name', [
    (None, '2026-10-26', '23-17-53-CDT-8bbde248', '01-generate-2026-10-26_23-17-53-CDT'),
    ('UTC', '2026-10-27', '04-17-53-UTC-8bbde248', '01-generate-2026-10-27_04-17-53-UTC'),
    ('Asia/Kathmandu', '2026-10-27', '10-02-53-+0545-8bbde248', '01-generate-2026-10-27_10-02-53-+0545'),
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
