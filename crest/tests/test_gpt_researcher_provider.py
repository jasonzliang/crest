"""Durable subprocess protocol checks; no inference, process or secret required."""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def provider():
    assert importlib.util.find_spec('crest.providers.gpt_researcher'), 'provider not implemented'
    return importlib.import_module('crest.providers.gpt_researcher')


class Job:
    def __init__(self, directory, state=None):
        self.directory = directory
        self.key = 'a' * 64
        self.state = state or {}
    def save(self, **updates): self.state.update(updates)


def result(request):
    p = provider()
    return {'protocol_version': p.PROTOCOL_VERSION, 'job_key': request['job_key'],
            'worker_id': request['worker_id'], 'request_sha256': p.request_digest(request),
            'source_identity': request['source_identity'], 'status': 'completed',
            'result': {'text': 'Evidence [1].', 'model': 'gpt-6.1-sol', 'citations': [{'url': 'https://example.test'}],
                       'cost_usd': .1, 'usage': {'cost_usd': .1}, 'raw': {'accounting': {'cost_usd': .1}}}}


def request(job, settings=None):
    p = provider()
    return {'protocol_version': p.PROTOCOL_VERSION, 'job_key': job.key, 'worker_id': 'b' * 32,
            'prompt': 'Q', 'settings': p.public_settings(settings or {}),
            'source_identity': {'source_commit': 'pinned'}, 'output_dir': str(job.directory / 'gpt-researcher-output')}


def write_receipts(job, req, record):
    job.directory.mkdir(exist_ok=True)
    (job.directory / 'gpt-researcher-request.json').write_text(json.dumps(req))
    (job.directory / 'gpt-researcher-result.json').write_text(json.dumps(record))


def test_completed_result_replays_without_launch(tmp_path, monkeypatch):
    p = provider()
    job = Job(tmp_path)
    req = request(job)
    write_receipts(job, req, result(req))
    async def forbidden(*args, **kwargs): pytest.fail('must not submit twice')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    assert asyncio.run(p.generate('Q', {}, job))['text'] == 'Evidence [1].'


@pytest.fixture
def forbid_existing_request_dispatch(monkeypatch):
    def forbidden_preflight(*args, **kwargs):
        pytest.fail('an existing request must not run preflight')
    async def forbidden_launch(*args, **kwargs):
        pytest.fail('an existing request must not launch another worker')
    monkeypatch.setattr(provider(), 'preflight', forbidden_preflight)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden_launch)


@pytest.mark.parametrize('cap', ['hard', 'soft'])
def test_poll_change_replays_frozen_pipeline_request_without_dispatch(
        tmp_path, monkeypatch, forbid_existing_request_dispatch, cap):
    from copy import deepcopy
    from crest.artifacts import configuration_record
    from crest.config import load_config
    from crest.pipeline import Pipeline

    p = provider()
    monkeypatch.setattr(p, 'identity_metadata', lambda settings: {'source_commit': 'frozen'})
    config = load_config()
    config['research'] = {'gpt_researcher': config['research']['gpt_researcher']}
    config['research']['gpt_researcher'].update(poll_interval_seconds=.5, reasoning_effort='high', budget_cap=cap)
    config.update(cache_dir=str(tmp_path / 'cache'), output_dir=str(tmp_path / 'runs'))
    original = Pipeline(config, limit=1)
    original._ensure_run()
    task = original.generation_jobs()[0]
    job = original.cache.job(task['key'])
    job.save(status='running', result_path=str(job.directory / 'gpt-researcher-result.json'))
    req = request(job, task['settings'])
    req.update(prompt=task['prompt'], source_identity=task['source_identity'])
    write_receipts(job, req, result(req) if cap == 'hard' else budget_record(req, .1))
    paths = [job.directory / name for name in ('gpt-researcher-request.json', 'gpt-researcher-result.json')]
    before = [path.read_bytes() for path in paths]

    changed = deepcopy(config)
    changed['research']['gpt_researcher']['poll_interval_seconds'] = 1.
    changed_task = Pipeline(changed, limit=1).generation_jobs()[0]
    assert changed_task['key'] == task['key']
    assert configuration_record(changed_task) == configuration_record(task)
    resumed = Pipeline(changed, run_dir=original.run_dir)
    row, cached = asyncio.run(resumed._execute(resumed.generation_jobs()[0], 'generate'))

    assert not cached  # Worker completed; the parent had not ingested its receipt.
    assert row['result']['text'].startswith('Evidence [1].')
    assert row['result']['cost_usd'] == .1
    assert original.cache.job(job.key).state['raw']['request_sha256'] == p.request_digest(req)
    assert [path.read_bytes() for path in paths] == before


def test_poll_change_waits_for_accepted_worker_using_new_parent_interval(
        tmp_path, monkeypatch, forbid_existing_request_dispatch):
    p = provider()
    job = Job(tmp_path, {'worker_pid': 43210, 'remote_status': 'running'})
    settings = {'poll_interval_seconds': .5, 'reasoning_effort': 'high'}
    req = request(job, settings)
    request_path = tmp_path / 'gpt-researcher-request.json'
    request_path.write_text(json.dumps(req))
    before = request_path.read_bytes()
    sleeps = []

    async def finish_worker(delay):
        sleeps.append(delay)
        (tmp_path / 'gpt-researcher-result.json').write_text(json.dumps(result(req)))

    monkeypatch.setattr(p, '_worker_alive', lambda state: True)
    monkeypatch.setattr(asyncio, 'sleep', finish_worker)
    out = asyncio.run(p.generate('Q', settings | {'poll_interval_seconds': 1.}, job))
    assert out['cost_usd'] == .1
    assert sleeps == [1.]
    assert request_path.read_bytes() == before
    assert job.state['raw']['request_sha256'] == p.request_digest(req)


@pytest.mark.parametrize('field,value', [
    ('budget_usd', 3.5), ('budget_cap', 'soft'), ('model', 'different-paid-model'), ('source_path', '/different/source'),
])
def test_poll_change_still_rejects_semantic_request_mismatch(
        tmp_path, forbid_existing_request_dispatch, field, value):
    p = provider()
    job = Job(tmp_path)
    settings = {'poll_interval_seconds': .5, 'reasoning_effort': 'high'}
    req = request(job, settings)
    req['settings'][field] = value
    write_receipts(job, req, result(req))  # Even a matching receipt digest cannot override semantics.
    with pytest.raises(RuntimeError, match='request identity does not match'):
        asyncio.run(p.generate('Q', settings | {'poll_interval_seconds': 1.}, job))


@pytest.mark.parametrize('mutation', ['source_identity', 'request_sha256', 'saved_poll'])
def test_poll_change_still_validates_original_request_digest_and_source(
        tmp_path, forbid_existing_request_dispatch, mutation):
    p = provider()
    job = Job(tmp_path)
    settings = {'poll_interval_seconds': .5, 'reasoning_effort': 'high'}
    req = request(job, settings)
    record = result(req)
    if mutation == 'saved_poll':
        req['settings']['poll_interval_seconds'] = 2.  # Receipt still hashes the original .5 request.
    else:
        record[mutation] = 'wrong'
    write_receipts(job, req, record)
    with pytest.raises(RuntimeError, match='receipt identity/protocol mismatch'):
        asyncio.run(p.generate('Q', settings | {'poll_interval_seconds': 1.}, job))


@pytest.mark.parametrize('mutation', ['job_key', 'worker_id', 'protocol_version', 'request_sha256', 'source_identity'])
def test_result_identity_mismatch_never_replays(tmp_path, mutation):
    p = provider()
    job = Job(tmp_path)
    req = request(job)
    record = result(req)
    record[mutation] = 'wrong'
    write_receipts(job, req, record)
    with pytest.raises(RuntimeError, match='identity|protocol|receipt'):
        asyncio.run(p.generate('Q', {}, job))


def test_prompt_or_settings_mismatch_is_refused(tmp_path):
    p = provider()
    job = Job(tmp_path)
    settings = {'deep_research_depth': 1}
    req = request(job, settings)
    write_receipts(job, req, result(req))
    with pytest.raises(RuntimeError): asyncio.run(p.generate('different', settings, job))
    with pytest.raises(RuntimeError): asyncio.run(p.generate('Q', {'deep_research_depth': 2}, job))


@pytest.mark.parametrize('state', [
    {'submission_unknown': True}, {'remote_status': 'failed'}, {'remote_status': 'timed_out'},
    {'worker_pid': 99999999},
])
def test_ambiguous_or_terminal_jobs_are_not_resubmitted(tmp_path, monkeypatch, state):
    p = provider()
    async def forbidden(*args, **kwargs): pytest.fail('must not submit twice')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    monkeypatch.setattr(p, '_worker_alive', lambda state: False)
    with pytest.raises(RuntimeError): asyncio.run(p.generate('Q', {}, Job(tmp_path, state)))


def test_orphan_request_prevents_duplicate_paid_submission(tmp_path):
    p = provider()
    job = Job(tmp_path)
    (tmp_path / 'gpt-researcher-request.json').write_text(json.dumps(request(job)))
    with pytest.raises(RuntimeError): asyncio.run(p.generate('Q', {}, job))


def test_launch_records_unknown_before_spawn_and_strips_credentials(tmp_path, monkeypatch):
    p = provider()
    job = Job(tmp_path)
    monkeypatch.setattr(p, 'preflight', lambda settings: {'source_commit': 'pinned'})
    async def launch(*args, **kwargs):
        assert args[1:3] == ('-m', 'crest.providers.gpt_researcher_worker')
        assert job.state['submission_unknown'] is True
        assert kwargs['start_new_session'] is True
        req = json.loads(Path(args[args.index('--request') + 1]).read_text())
        assert 'api_key' not in json.dumps(req).lower()
        assert 'OPENAI_BASE_URL' not in kwargs['env']
        Path(args[args.index('--result') + 1]).write_text(json.dumps(result(req)))
        class Child:
            pid = 876
            returncode = 0
            async def wait(self): return 0
        return Child()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', launch)
    out = asyncio.run(p.generate('Q', {'api_key': 'never-serialize'}, job))
    assert out['cost_usd'] == .1
    assert job.state['worker_pid'] == 876


@pytest.mark.parametrize('parser_available', [False, True])
def test_preflight_imports_markdown_parser_before_paid_launch(tmp_path, monkeypatch, parser_available):
    import sys

    p = provider()
    source = tmp_path / 'source'
    source.mkdir()
    for name in ('gpt_researcher', 'ddgs', 'langchain_openai'):
        (source / f'{name}.py').write_text('')
    (source / 'openai.py').write_text(
        'class OpenAI: request = staticmethod(lambda: None)\nAsyncOpenAI = OpenAI\n')
    (source / 'markdown_it.py').write_text(
        '' if parser_available else "raise ModuleNotFoundError(\"No module named 'markdown_it'\")\n")
    identity = {'source_commit': p.PINNED_COMMIT, 'source_available': True}
    monkeypatch.setattr(p, 'identity_metadata', lambda settings: identity)
    real_run = p.subprocess.run

    def local_probe(args, **kwargs):
        if args[0] == 'git':
            return SimpleNamespace(returncode=0)
        assert args[:3] == [sys.executable, '-I', '-c']
        assert 'OPENAI_API_KEY' not in kwargs['env']
        return real_run(args, **kwargs)

    async def forbidden_launch(*args, **kwargs):
        pytest.fail('missing parser must stop preflight before launching a worker')

    monkeypatch.setattr(p.subprocess, 'run', local_probe)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden_launch)
    settings = {'source_path': str(source), 'python_executable': sys.executable, 'reasoning_effort': 'high'}
    if parser_available:
        assert p.preflight(settings) == identity
    else:
        with pytest.raises(RuntimeError, match='dependency/import preflight failed'):
            p.preflight(settings)
        job = Job(tmp_path / 'job')
        with pytest.raises(RuntimeError, match='dependency/import preflight failed'):
            asyncio.run(p.generate('Q', settings, job))
        assert not (job.directory / 'gpt-researcher-launch.claim').exists()
        assert not (job.directory / 'gpt-researcher-request.json').exists()
        assert job.state == {}


def test_source_identity_changes_with_code_but_not_dotenv(tmp_path):
    p = provider()
    package = tmp_path / 'gpt_researcher'
    package.mkdir()
    source = package / 'agent.py'
    source.write_text('version = 1\n')
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion="test"\n')
    first = p.identity_metadata({'gpt_researcher_path': str(tmp_path)})
    (tmp_path / '.env').write_text('not-to-be-read')
    assert p.identity_metadata({'gpt_researcher_path': str(tmp_path)}) == first
    source.write_text('version = 2\n')
    assert p.identity_metadata({'gpt_researcher_path': str(tmp_path)}) != first


@pytest.mark.parametrize('draft_status', ['unvalidated', 'rejected', 'validated'])
def test_preserved_answer_never_replays_or_promotes_failed_job(tmp_path, monkeypatch, draft_status):
    p = provider()
    job = Job(tmp_path)
    req = request(job)
    record = result(req)
    record.pop('result')
    record.update(status='failed', error='GPT Researcher final validation failed: unretrieved_citation',
                  validation_error={'code': 'unretrieved_citation'},
                  usage={'known_cost_usd': .1, 'reserved_usd': 0., 'unknown_cost': False})
    write_receipts(job, req, record)
    output = tmp_path / 'gpt-researcher-output'
    output.mkdir()
    (output / 'final-answer.json').write_text(json.dumps({
        'status': draft_status, 'text': 'A paid but unaccepted answer.',
        'source_identity': req['source_identity'], 'request_sha256': p.request_digest(req)}))
    async def forbidden(*args, **kwargs): pytest.fail('a saved answer never authorizes paid replay')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    with pytest.raises(RuntimeError, match='final validation failed'):
        asyncio.run(p.generate('Q', {}, job))
    assert job.state['remote_status'] == 'failed'
    assert job.state['raw']['usage']['known_cost_usd'] == .1



def test_identity_fingerprints_relocated_worker(tmp_path, monkeypatch):
    p = provider()
    package = tmp_path / 'crest/providers'
    package.mkdir(parents=True)
    for name in ('gpt_researcher', 'gpt_researcher_worker'):
        (package / f'{name}.py').write_text('version = 1\n')
    monkeypatch.setattr(p, '__file__', str(package / 'gpt_researcher.py'))
    settings = {'source_path': str(tmp_path / 'upstream')}
    before = p.identity_metadata(settings)
    (package / 'gpt_researcher_worker.py').write_text('version = 2\n')
    assert p.identity_metadata(settings)['adapter_sha256'] != before['adapter_sha256']


@pytest.mark.parametrize('module', ['crest.gpt_researcher_worker', 'crest.providers.gpt_researcher_worker'])
def test_worker_identity_recognizes_legacy_and_relocated_commands(tmp_path, monkeypatch, module):
    import psutil
    p = provider()
    result = str(tmp_path / 'gpt-researcher-result.json')
    command = ['python', '-m', module, '--result', result]
    process = SimpleNamespace(status=lambda: psutil.STATUS_RUNNING, cmdline=lambda: command,
                              create_time=lambda: 12.)
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)
    state = {'worker_pid': 43210, 'result_path': result, 'worker_create_time': 12.}
    assert p._worker_alive(state)
    assert not p._worker_alive(state | {'worker_create_time': 13.})
    assert not p._worker_alive(state | {'result_path': str(tmp_path / 'unrelated.json')})
    command[2] = 'unrelated.worker'
    assert not p._worker_alive(state)


def budget_record(req, cost=4.25):
    from copy import deepcopy
    record = result(req)
    s = req['settings']
    usage = {'budget_cap': s.get('budget_cap', 'hard'), 'budget_usd': s['budget_usd'],
             'budget_target_usd': s['budget_target_usd'], 'synthesis_reserve_usd': s['synthesis_reserve_usd'],
             'cost_usd': cost, 'known_cost_usd': cost, 'reserved_usd': 0., 'upper_bound_usd': cost,
             'unknown_cost': False, 'in_flight': [], 'terminal_failure': None}
    record['result'].update(cost_usd=cost, usage=usage,
                           raw={'accounting': deepcopy(usage), 'gpt_researcher_audit': deepcopy(usage)})
    return record


def test_soft_known_overrun_receipt_replays_without_submission(tmp_path, forbid_existing_request_dispatch):
    p, job = provider(), Job(tmp_path)
    req = request(job, {'budget_cap': 'soft'})
    write_receipts(job, req, budget_record(req))
    before = (tmp_path / 'gpt-researcher-result.json').read_bytes()
    out = asyncio.run(p.generate('Q', {'budget_cap': 'soft'}, job))
    assert out['cost_usd'] == 4.25 and out['usage']['budget_cap'] == 'soft'
    assert (tmp_path / 'gpt-researcher-result.json').read_bytes() == before


@pytest.mark.parametrize('mutation', ['missing_mode', 'hard_mode', 'reference', 'result_cost',
    'usage_cost', 'upper_bound', 'unknown', 'pending', 'accounting_copy', 'audit_copy'])
def test_soft_receipt_overrun_does_not_allow_accounting_or_mode_tampering(
        tmp_path, forbid_existing_request_dispatch, mutation):
    p, job = provider(), Job(tmp_path)
    req = request(job, {'budget_cap': 'soft'})
    record = budget_record(req)
    out, usage = record['result'], record['result']['usage']
    if mutation == 'missing_mode': usage.pop('budget_cap')
    elif mutation == 'hard_mode': usage['budget_cap'] = 'hard'
    elif mutation == 'reference': usage['budget_usd'] = 100.
    elif mutation == 'result_cost': out['cost_usd'] = .01
    elif mutation == 'usage_cost': usage['cost_usd'] = .01
    elif mutation == 'upper_bound': usage['upper_bound_usd'] = .01
    elif mutation == 'unknown': usage['unknown_cost'] = True
    elif mutation == 'pending': usage['in_flight'] = [{'reserved_usd': .1}]
    elif mutation == 'accounting_copy': out['raw']['accounting']['known_cost_usd'] = .01
    elif mutation == 'audit_copy': out['raw']['gpt_researcher_audit']['budget_cap'] = 'hard'
    write_receipts(job, req, record)
    with pytest.raises(RuntimeError, match='budget|accounting'):
        asyncio.run(p.generate('Q', {'budget_cap': 'soft'}, job))


@pytest.mark.parametrize('cap', ['hard', 'auto'])
def test_nonsoft_receipt_cannot_claim_known_overrun(tmp_path, forbid_existing_request_dispatch, cap):
    p, job = provider(), Job(tmp_path)
    req = request(job, {'budget_cap': cap})
    write_receipts(job, req, budget_record(req))
    with pytest.raises(RuntimeError, match='budget'):
        asyncio.run(p.generate('Q', {'budget_cap': cap}, job))


@pytest.mark.parametrize('cap', ['hard', 'auto'])
def test_legacy_receipt_without_mode_keeps_original_nonsoft_semantics(
        tmp_path, forbid_existing_request_dispatch, cap):
    p, job = provider(), Job(tmp_path)
    req = request(job, {'budget_cap': cap})
    if cap == 'hard': req['settings'].pop('budget_cap')
    write_receipts(job, req, result(req))
    assert asyncio.run(p.generate('Q', {'budget_cap': cap}, job))['cost_usd'] == .1
    with pytest.raises(RuntimeError, match='request identity'):
        asyncio.run(p.generate('Q', {'budget_cap': 'soft'}, job))


@pytest.mark.parametrize('cap,reference,target,accepted', [
    ('soft', 10., 3.2, True), ('soft', 2., 3.2, True),
    ('hard', 4.01, 3.2, False), ('hard', 2., 3.2, False),
    ('auto', 4.01, 3.2, False),
])
def test_config_and_provider_agree_on_explicit_budget_policy(tmp_path, cap, reference, target, accepted):
    from crest.config import load_config
    settings = {'budget_cap': cap, 'budget_usd': reference, 'budget_target_usd': target}
    path = tmp_path / 'config.yaml'
    path.write_text(json.dumps({'research': {'gpt_researcher': settings}}))
    if accepted:
        loaded = load_config(path)['research']['gpt_researcher']
        direct, configured = provider().public_settings(settings), provider().public_settings(loaded)
        assert direct['budget_cap'] == configured['budget_cap'] == cap
        assert direct['budget_usd'] == configured['budget_usd'] == reference
        assert direct['budget_target_usd'] == configured['budget_target_usd'] == target
    else:
        with pytest.raises(ValueError): load_config(path)
        with pytest.raises(ValueError): provider().public_settings(settings)


def test_low_writer_reserve_soft_app_provider_and_overrun_receipt_agree(
        tmp_path, forbid_existing_request_dispatch):
    from crest.config import load_config
    settings = {'budget_cap': 'soft', 'budget_usd': .10, 'budget_target_usd': .10,
                'synthesis_reserve_usd': .05}
    path = tmp_path / 'config.yaml'
    path.write_text(json.dumps({'research': {'gpt_researcher': settings}}))
    loaded = load_config(path)['research']['gpt_researcher']
    p = provider()
    normalized = p.public_settings(loaded)
    assert {key: normalized[key] for key in settings} == settings
    job = Job(tmp_path / 'job')
    req = request(job, loaded)
    write_receipts(job, req, budget_record(req, .1806))
    out = asyncio.run(p.generate('Q', loaded, job))
    assert out['cost_usd'] == .1806 and out['usage']['budget_cap'] == 'soft'
