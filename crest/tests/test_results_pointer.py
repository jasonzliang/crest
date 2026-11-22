"""Later-stage defaults follow hidden metadata while accepting old pointers."""
import json

import pytest

from crest.cache import write_json
from crest.cli import main


@pytest.mark.parametrize('stage', ['judge', 'analyze'])
@pytest.mark.parametrize('pointers', ['hidden', 'legacy', 'both'])
def test_later_stage_defaults_to_hidden_latest_with_legacy_fallback(
        tmp_path, capsys, stage, pointers):
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

    assert main([stage, '--config', str(config), '--dry-run']) == 0
    assert json.loads(capsys.readouterr().out)['run_dir'] == str(run)
    if pointers == 'hidden':
        assert not (results / 'latest.json').exists()


def test_later_stage_without_any_latest_pointer_reports_how_to_select_a_run(tmp_path, capsys):
    config = tmp_path / 'crest.yaml'
    config.write_text('output_dir: results\n')
    with pytest.raises(SystemExit) as exc:
        main(['judge', '--config', str(config), '--dry-run'])
    assert exc.value.code == 2
    assert 'generate first or pass --run PATH' in capsys.readouterr().err
