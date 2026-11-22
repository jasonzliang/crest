"""Repository entry points must work without an installed CREST package."""
import json
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
    assert supplied['answer_word_limit'] is None
    assert config['answer_word_limit'] is None
    assert '{max_words}' not in supplied['research_prompt'] and '{question}' in supplied['research_prompt']
    assert '{max_words}' not in supplied['research_continuation_prompt']
    assert supplied['research']['caesar']['use_research_prompt'] is False
    assert all(supplied['research'][name]['use_research_prompt'] is True
               for name in supplied['research'] if name != 'caesar')
    for name, settings in config['research'].items():
        assert settings['answer_word_limit'] is None, name
        assert 'budget_usd' in supplied['research'][name], name


@pytest.fixture
def isolated_checkout(tmp_path):
    checkout = tmp_path / 'checkout'
    package = checkout / 'crest'
    package.mkdir(parents=True)
    for source in (ROOT / 'crest').glob('*.py'):
        shutil.copy2(source, package / source.name)
    shutil.copytree(ROOT / 'crest/providers', package / 'providers',
                    ignore=shutil.ignore_patterns('__pycache__'))
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


@pytest.mark.parametrize('worker', ['caesar_worker', 'gpt_researcher_worker'])
@pytest.mark.parametrize('direct_script', [False, True])
def test_worker_entrypoint_from_uninstalled_checkout(isolated_checkout, tmp_path, direct_script, worker):
    checkout, dependencies = isolated_checkout
    arguments = ([str(checkout / 'crest/providers' / f'{worker}.py')] if direct_script
                 else ['-m', f'crest.providers.{worker}'])
    result = subprocess.run([sys.executable, '-S', *arguments, '--help'],
                            cwd=tmp_path if direct_script else checkout,
                            env={'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert '--request' in result.stdout and '--result' in result.stdout


def test_caesar_budget_cli_from_uninstalled_checkout(isolated_checkout):
    checkout, dependencies = isolated_checkout
    result = subprocess.run([sys.executable, '-S', '-m', 'crest.providers.caesar_budget', '3.5'],
                            cwd=checkout, env={'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert 0 < plan['estimate']['total_usd'] <= 3.5
    assert plan['settings']['max_iterations'] > 0


@pytest.mark.parametrize('modules', [
    ('crest.config', 'crest.providers.caesar'),
    ('crest.providers.caesar', 'crest.config'),
    ('crest.config', 'crest.providers.gpt_researcher'),
    ('crest.providers.gpt_researcher', 'crest.config'),
])
def test_provider_config_import_order_without_upstream(isolated_checkout, modules):
    checkout, dependencies = isolated_checkout
    code = (f'import importlib, sys; [importlib.import_module(name) for name in {modules!r}]; '
            "assert not any(name in sys.modules for name in ('rome', 'caesar', 'openai', 'litellm', 'gpt_researcher'))")
    result = subprocess.run([sys.executable, '-S', '-c', code], cwd=checkout,
                            env={'PYTHONPATH': str(dependencies), 'PYTHONNOUSERSITE': '1',
                                 'PYTHONDONTWRITEBYTECODE': '1'},
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('worker', ['caesar_worker', 'gpt_researcher_worker'])
def test_direct_worker_script_resolves_late_provider_import(isolated_checkout, tmp_path, worker):
    checkout, dependencies = isolated_checkout
    target = checkout / 'crest/providers' / f'{worker}.py'
    adapter = worker.removesuffix('_worker')
    code = (f"import runpy, importlib; runpy.run_path({str(target)!r}, run_name='entrypoint_probe'); "
            f"importlib.import_module('crest.providers.{adapter}')")
    result = subprocess.run([sys.executable, '-S', '-c', code], cwd=tmp_path,
                            env={'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('directory', ['_archive', 'configs', 'data', 'prompts', 'providers', 'results'])
def test_package_directory_guide_exists_and_local_links_resolve(directory):
    import re
    from urllib.parse import unquote, urlsplit

    guide = ROOT / 'crest' / directory / 'readme.md'
    text = guide.read_text()
    assert text.startswith('# '), guide
    for destination in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
        url = urlsplit(destination)
        if url.scheme or url.netloc or not url.path:
            continue
        assert (guide.parent / unquote(url.path)).exists(), (guide, destination)


def test_gitignore_protects_credentials_without_hiding_templates():
    """Probe filenames only; never read or create a credential file."""
    private = {'.env', '.env.local', 'crest/.env', 'credentials.json',
               'service-account.json', 'crest-keys.sh', 'id_rsa', 'id_ed25519'}
    examples = {'.env.example', '.env.sample', 'crest/.env.example', 'credentials.example.json'}
    result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT,
                            input='\n'.join(sorted(private | examples)) + '\n',
                            capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    assert set(result.stdout.splitlines()) == private
