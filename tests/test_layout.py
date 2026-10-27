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
    assert Path(config['questions']) == ROOT / 'crest/data/queries_n50.jsonl'
    assert len(load_questions(config['questions'])) == 50
    assert Path(config['rubric']) == ROOT / 'crest/prompts/nus_pairwise.txt'
    assert Path(config['output_dir']) == ROOT / 'crest/results'
    assert Path(config['cache_dir']) == ROOT / 'crest/results/.cache/generation'
    assert Path(config['research']['caesar']['rome_path']) == ROOT.parent / 'rome'


def test_mbp_profile_inherits_the_same_data_and_storage_paths():
    profile = ROOT / 'crest/configs/crest.mbp.yaml'
    assert profile.is_file()
    base, mbp = load_config(), load_config(profile)
    for name in ('questions', 'rubric', 'output_dir', 'cache_dir'):
        assert mbp[name] == base[name]
    assert mbp['research']['caesar']['rome_path'] == base['research']['caesar']['rome_path']


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
