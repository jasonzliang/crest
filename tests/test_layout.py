"""Repository entry points must work without an installed CREST package."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from crest.config import ROOT, load_config, load_questions


def test_default_config_resolves_the_packaged_layout():
    config = load_config()
    assert Path(config['_config_path']) == ROOT / 'crest/configs/crest.yaml'
    assert Path(config['questions']) == ROOT / 'crest/data/queries_n50_v2.jsonl'
    assert len(load_questions(config['questions'])) == 50
    assert Path(config['rubric']) == ROOT / 'crest/prompts/nus_pairwise_v2.txt'
    assert Path(config['output_dir']) == ROOT / 'crest/results'
    assert Path(config['cache_dir']) == ROOT / 'crest/results/.cache/generation'
    assert Path(config['research']['caesar']['rome_path']) == ROOT.parent / 'rome'


def test_master_config_is_the_only_profile_and_names_every_default_flag():
    configs = sorted(p.name for p in (ROOT / 'crest/configs').glob('*.yaml'))
    assert configs == ['crest.yaml']
    supplied = yaml.safe_load((ROOT / 'crest/configs/crest.yaml').read_text())
    config = load_config()
    # Every research agent and judge in the defaults is spelled out in the master file.
    assert set(supplied['research']) == set(config['research'])
    assert set(supplied['judges']) == set(config['judges'])
    assert supplied['answer_word_limit'] == config['answer_word_limit'] == 600
    assert '{max_words}' in supplied['research_prompt'] and '{question}' in supplied['research_prompt']
    assert supplied['research']['caesar']['use_research_prompt'] is False
    assert all(supplied['research'][name]['use_research_prompt'] is True
               for name in supplied['research'] if name != 'caesar')
    for name, settings in config['research'].items():
        assert settings['answer_word_limit'] == 600, name
        assert 'budget_usd' in supplied['research'][name], name


@pytest.fixture
def isolated_checkout(tmp_path):
    checkout = tmp_path / 'checkout'
    package = checkout / 'crest'
    package.mkdir(parents=True)
    for source in (ROOT / 'crest').glob('*.py'):
        shutil.copy2(source, package / source.name)
    dependencies = tmp_path / 'dependencies'
    shutil.copytree(Path(yaml.__file__).parent, dependencies / 'yaml')
    # -S skips site-packages and editable-install .pth files. Supply only PyYAML,
    # so an installed copy of CREST cannot hide a broken checkout entry point.
    return checkout, dependencies


@pytest.mark.parametrize('stage', ['generate', 'judge', 'analyze'])
def test_module_cli_imports_from_an_uninstalled_checkout(isolated_checkout, stage):
    checkout, dependencies = isolated_checkout
    env = os.environ | {'PYTHONPATH': str(dependencies), 'PYTHONNOUSERSITE': '1'}
    result = subprocess.run([sys.executable, '-S', '-m', 'crest', stage, '--help'],
                            cwd=checkout, env=env, text=True,
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert '--config' in result.stdout
    assert '--run' in result.stdout


def test_redundant_stage_wrappers_are_preserved_only_in_the_archive():
    for filename in ('stage1_generate.py', 'stage2_judge.py', 'stage3_analyze.py'):
        assert not (ROOT / 'crest' / filename).exists()
        assert (ROOT / 'crest/_archive/entrypoints' / filename).is_file()
