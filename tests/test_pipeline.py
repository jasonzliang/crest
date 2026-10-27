import asyncio
import json
from pathlib import Path

import pytest

from crest.cache import Cache, CacheCorruption, digest
from crest.config import load_config, load_questions
from crest.pipeline import Pipeline


def test_checkpoint_survives_restart_and_corruption_is_not_a_miss(tmp_path):
    cache = Cache(tmp_path)
    key = digest({'question': 'A'})
    cache.job(key).save(remote_id='resp_paid', status='running')
    assert Cache(tmp_path).job(key).state['remote_id'] == 'resp_paid'
    cache.job(key).path.write_text('{truncated', encoding='utf-8')
    with pytest.raises(CacheCorruption):
        Cache(tmp_path).job(key)


def test_single_flight_rechecks_cache_after_lock(tmp_path):
    cache = Cache(tmp_path)
    key = digest({'task': 1})
    calls = []
    async def run():
        async def request():
            async with cache.lock(key) as job:
                if job.state.get('status') == 'completed':
                    return job.state['result']
                calls.append(1)
                await asyncio.sleep(.01)
                job.save(status='completed', result={'text': 'paid once'})
                return job.state['result']
        return await asyncio.gather(request(), request(), request())
    assert asyncio.run(run()) == [{'text': 'paid once'}] * 3
    assert len(calls) == 1


def test_questions_preserve_text_and_reject_duplicate_text(tmp_path):
    p = tmp_path / 'questions.jsonl'
    p.write_text(json.dumps({'config': 'mini', 'query': '  exact question?  '}) + '\n')
    assert load_questions(p)[0]['text'] == '  exact question?  '
    p.write_text('{"query":"same"}\n{"query":"same"}\n')
    with pytest.raises(ValueError, match='Duplicate'):
        load_questions(p)


def fixture_config(tmp_path, n=2):
    q = tmp_path / 'questions.jsonl'
    q.write_text(''.join(json.dumps({'query': f'Question {i}'}) + '\n' for i in range(n)))
    rubric = tmp_path / 'rubric_v2.txt'
    rubric.write_text('Compare New, Useful and Surprising. Choose A or B.')
    p = tmp_path / 'crest.yaml'
    p.write_text(f'questions: {q}\nrubric: {rubric}\ncache_dir: {tmp_path / "cache"}\noutput_dir: {tmp_path / "results"}\n')
    return load_config(p)


class FakeProvider:
    ADAPTER_VERSION = 'fixture-v1'
    def __init__(self, name):
        self.name = name
        self.generations = []
        self.judgments = []
    async def generate(self, prompt, settings, job):
        self.generations.append(prompt)
        job.save(remote_id=self.name + '-paid')
        return {'text': self.name + ': ' + prompt, 'model': settings.get('model', 'managed'),
                'citations': [], 'usage': {}, 'cost_usd': .2, 'cost_estimated': True,
                'warnings': [], 'raw': {}}
    async def judge(self, prompt, settings, job):
        self.judgments.append(prompt)
        verdict = {'reason': 'A presents a more creative, useful approach than B.', 'winner': 'A'}
        return {'text': json.dumps(verdict), 'model': settings['model'], 'citations': [],
                'usage': {}, 'cost_usd': .01, 'cost_estimated': True, 'warnings': [], 'raw': {}}


@pytest.mark.parametrize('result', [{}, {'text': ''}, {'text': '  '}, {'text': None}, [], None])
def test_malformed_completed_generation_is_never_accepted_or_resubmitted(tmp_path, result):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'openai': config['research']['openai']}
    provider = FakeProvider('openai')
    pipeline = Pipeline(config, providers={'openai': provider})
    task = pipeline.generation_jobs()[0]
    job = pipeline.cache.job(task['key'])
    job.save(status='completed', result=result)
    original = job.path.read_bytes()
    for _ in range(2):
        summary = asyncio.run(pipeline.generate())
        assert summary['failed'] == 1
        assert summary['completed'] == summary['cached'] == 0
        assert not (Path(summary['directory']) / 'answers.jsonl').read_text()
        error = json.loads((Path(summary['directory']) / 'errors.jsonl').read_text())
        assert 'CacheCorruption' in error['error']
    assert provider.generations == []
    assert job.path.read_bytes() == original


@pytest.mark.parametrize('name,expected_cost', [('openai', .004), ('gemini', .0076)])
def test_terminal_native_failure_reports_computable_estimate(tmp_path, monkeypatch, name, expected_cost):
    import importlib
    from types import SimpleNamespace
    import httpx
    module = importlib.import_module('crest.providers.' + name)
    monkeypatch.setenv('GOOGLE_API_KEY', 'offline-test-key')
    raw = {'id': 'paid-terminal', 'status': 'incomplete', 'model': 'gpt-6.1-sol',
           'service_tier': 'default', 'output': [],
           'usage': {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                     'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 1200}}
    if name == 'gemini':
        raw = {'id': 'paid-terminal', 'status': 'failed', 'steps': [],
               'usage': {'total_input_tokens': 1000, 'total_cached_tokens': 0,
                         'total_output_tokens': 200, 'total_thought_tokens': 0,
                         'total_tool_use_tokens': 0, 'total_tokens': 1200, 'grounding_tool_count': []}}
    async def generate(prompt, settings, job):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=raw))) as client:
            return await module.generate(prompt, settings, job, client=client)
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name]}
    pipeline = Pipeline(config, providers={name: SimpleNamespace(ADAPTER_VERSION=module.ADAPTER_VERSION,
                                                                generate=generate)})
    summary = asyncio.run(pipeline.generate())
    error = json.loads((Path(summary['directory']) / 'errors.jsonl').read_text())
    assert summary['failed'] == 1
    assert summary['completed'] == 0
    assert error['cost_usd'] == pytest.approx(expected_cost)
    assert error['cost_details']['cumulative_known_estimate_usd'] == pytest.approx(expected_cost)
    assert error['usage']['input_tokens'] == 1000
    assert not (Path(summary['directory']) / 'answers.jsonl').read_text()


def test_timeout_failure_keeps_precancel_estimate_separate_from_final_cost(tmp_path):
    from types import SimpleNamespace
    import httpx
    from crest.providers import openai
    raw = {'id': 'paid-timeout', 'status': 'in_progress', 'model': 'gpt-6.1-sol',
           'service_tier': 'default', 'output': [],
           'usage': {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                     'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 1200}}
    def handler(request):
        return httpx.Response(200, json=raw if request.method == 'GET'
                              else {'id': 'paid-timeout', 'status': 'cancelled'})
    async def generate(prompt, settings, job):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openai.generate(prompt, settings, job, client=client)
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'openai': config['research']['openai']}
    pipeline = Pipeline(config, providers={'openai': SimpleNamespace(ADAPTER_VERSION=openai.ADAPTER_VERSION,
                                                                    generate=generate)})
    task = pipeline.generation_jobs()[0]
    pipeline.cache.job(task['key']).save(status='running', remote_id='paid-timeout', submitted_at=0, raw=raw)
    summary = asyncio.run(pipeline.generate())
    error = json.loads((Path(summary['directory']) / 'errors.jsonl').read_text())
    assert error['cost_usd'] is None
    assert error['observed_cost_usd'] == pytest.approx(.004)
    assert error['observed_cost_scope'] == 'partial_pre_cancel'
    assert error['usage']['input_tokens'] == 1000
    assert error['cost_details']['cumulative_known_estimate_usd'] is None


@pytest.mark.parametrize('total, exceeded', [(4.6, False), (5.1, True)])
def test_recovery_cumulative_cost_uses_original_answer_budget(tmp_path, total, exceeded):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'caesar': config['research']['caesar']}
    config['research']['caesar']['budget_usd'] = 4.25
    provider = FakeProvider('caesar')
    async def recovered(prompt, settings, job):
        return {'text': 'Recovered answer', 'cost_usd': total,
                'usage': {'new_attempt_cost_usd': total - .5}, 'warnings': [],
                'raw': {'recovery': {'original_budget_usd': 5.0}}}
    provider.generate = recovered
    pipeline = Pipeline(config, providers={'caesar': provider})
    asyncio.run(pipeline.generate())
    result = pipeline.answers()[0]['result']
    assert bool(result.get('budget_exceeded')) is exceeded


def test_fresh_restart_cannot_raise_frozen_remaining_time(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'caesar': config['research']['caesar']}
    config['research']['caesar'].update(budget_history_from=str(tmp_path / 'prior'), timeout_seconds=3600)
    provider = FakeProvider('caesar')
    received = []
    original = provider.generate
    async def capture(prompt, settings, job):
        received.append(settings['timeout_seconds'])
        return await original(prompt, settings, job)
    provider.generate = capture
    pipeline = Pipeline(config, providers={'caesar': provider})
    pipeline._ensure_run()
    pipeline.config['research']['caesar']['timeout_seconds'] = 7200
    asyncio.run(pipeline.generate())
    assert received == [3600]


def test_budget_history_path_is_resolved_and_cannot_mix_with_recovery(tmp_path):
    p = tmp_path / 'config.yaml'
    p.write_text('research:\n  caesar:\n    budget_history_from: prior-job\n')
    assert load_config(p)['research']['caesar']['budget_history_from'] == str(tmp_path / 'prior-job')
    p.write_text('research:\n  caesar:\n    budget_history_from: prior-job\n    recovery_from: prior-job\n')
    with pytest.raises(ValueError, match='not both'):
        load_config(p)


def test_timestamped_stages_resume_and_rubric_change_never_rebuys_answers(tmp_path):
    config = fixture_config(tmp_path)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    run = pipeline.run_dir
    assert run.parent.name.count('-') == 2
    assert (run / 'run.json').is_file()
    assert len(list(run.glob('01-generate-*'))) == 1
    assert len(list(run.glob('02-judge-*'))) == 1
    assert len(list(run.glob('03-analysis-*/ranking.json'))) == 1
    assert (run / '.cache' / 'judgments').is_dir()
    assert (run / '.cache' / 'analysis').is_dir()
    assert sum(len(p.generations) for p in providers.values()) == 6
    assert sum(len(p.judgments) for p in providers.values()) == 24
    second = Pipeline(config, providers=providers, run_dir=run)
    asyncio.run(second.judge())
    second_analysis = second.analyze()
    assert second_analysis['cache_hit'] is True
    assert len(list(run.glob('02-judge-*'))) == 2
    assert len(list(run.glob('03-analysis-*/ranking.json'))) == 2
    assert sum(len(p.judgments) for p in providers.values()) == 24
    Path(config['rubric']).write_text('Changed rubric; still binary.')
    asyncio.run(second.judge())
    assert sum(len(p.generations) for p in providers.values()) == 6
    assert sum(len(p.judgments) for p in providers.values()) == 48
    third = Pipeline(config, providers=providers)
    asyncio.run(third.generate())
    assert third.run_dir != run
    assert sum(len(p.generations) for p in providers.values()) == 6


def test_analysis_cli_accepts_run_dir_and_does_not_need_api_keys(tmp_path):
    import os
    import subprocess
    import sys
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    env = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY'}}
    env['PYTHONPATH'] = str(Path(__file__).parents[1])
    result = subprocess.run([sys.executable, '-m', 'crest', 'analyze',
                             '--run', str(pipeline.run_dir), '--config', config['_config_path']],
                            cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert len(list(pipeline.run_dir.glob('03-analysis-*'))) == 2


def test_changed_one_provider_invalidates_only_its_generations(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    first = Pipeline(config, providers=providers).generation_jobs()
    config['research']['openai']['reasoning_effort'] = 'medium'
    second = Pipeline(config, providers=providers).generation_jobs()
    before = {j['agent']: j['key'] for j in first}
    after = {j['agent']: j['key'] for j in second}
    assert before['caesar'] == after['caesar']
    assert before['gemini'] == after['gemini']
    assert before['openai'] != after['openai']


def test_generation_failure_does_not_erase_other_paid_answers(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    async def failed(prompt, settings, job):
        job.save(remote_id='still-poll-this')
        raise RuntimeError('temporary poll failure')
    providers['openai'].generate = failed
    pipeline = Pipeline(config, providers=providers)
    summary = asyncio.run(pipeline.generate())
    assert summary['failed'] == 1
    assert len(pipeline.answers()) == 2
    task = next(j for j in pipeline.generation_jobs() if j['agent'] == 'openai')
    assert pipeline.cache.job(task['key']).state['remote_id'] == 'still-poll-this'


def test_default_dataset_plan_has_fifty_questions_and_150_generations():
    config = load_config()
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    assert len(pipeline.questions) == 50
    assert len(pipeline.generation_jobs()) == 150
    assert pipeline.plan()['judge_calls_total'] == 600


def test_judge_adapter_change_invalidates_only_that_judge(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    providers['openai'].ADAPTER_VERSION = 'changed-request-semantics'
    assert pipeline.plan()['judge_cache_hits'] == 6
    asyncio.run(pipeline.judge())
    assert len(providers['openai'].judgments) == 12
    assert len(providers['gemini'].judgments) == 6
    assert sum(len(p.generations) for p in providers.values()) == 3


def test_failed_paid_verdict_keeps_usage_and_cost_but_never_enters_rankings(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    async def invalid(prompt, settings, job):
        return {'text': 'invalid JSON', 'cost_usd': .42, 'usage': {'output_tokens': 123}, 'raw': {}}
    providers['openai'].judge = invalid
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.generate())
    summary = asyncio.run(pipeline.judge())
    errors = [json.loads(line) for line in (Path(summary['directory']) / 'errors.jsonl').read_text().splitlines()]
    assert len(errors) == 6
    charged = 2.52 * config['judges']['openai']['retry_attempts']
    assert sum(e['cost_usd'] for e in errors) == pytest.approx(charged)
    assert all(len(e['attempts']) == config['judges']['openai']['retry_attempts'] for e in errors)
    assert all(e['usage']['output_tokens'] == 123 for e in errors)
    state = pipeline._stage_cache('judge').job(errors[0]['key']).state
    assert state['status'] == 'failed'
    assert state['provider_result']['cost_usd'] == .42
    report = pipeline.analyze()['report']
    assert report['costs']['failures']['known_usd'] == pytest.approx(charged)
    assert report['costs']['total']['known_usd'] == pytest.approx(charged + .66)


def test_analysis_cache_ignores_completion_order(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    source = pipeline._latest_stage('judge') / 'judgments.jsonl'
    rows = source.read_text().splitlines()
    source.write_text('\n'.join(reversed(rows)) + '\n')
    assert pipeline.analyze()['cache_hit'] is True


def test_missing_credentials_stop_before_creating_a_paid_run(tmp_path):
    import os
    import subprocess
    import sys
    config = fixture_config(tmp_path, n=1)
    env = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY'}}
    env['PYTHONPATH'] = str(Path(__file__).parents[1])
    result = subprocess.run([sys.executable, '-m', 'crest', 'generate',
                             '--config', config['_config_path'], '--agents', 'openai'],
                            cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 2
    assert 'OPENAI_API_KEY' in result.stderr
    assert not Path(config['output_dir']).exists()


def test_single_flight_across_processes(tmp_path):
    import subprocess
    import sys
    script = '''
import asyncio,sys
from pathlib import Path
from crest.cache import Cache,digest
async def run():
    async with Cache(sys.argv[1]).lock(digest({'paid':'same'})) as job:
        if job.state.get('status') != 'completed':
            with Path(sys.argv[2]).open('a') as stream: stream.write('request\\n')
            await asyncio.sleep(.1)
            job.save(status='completed',result={'text':'one paid answer'})
asyncio.run(run())
'''
    marker = tmp_path / 'requests.txt'
    children = [subprocess.Popen([sys.executable, '-c', script, str(tmp_path / 'cache'), str(marker)],
                                 cwd=Path(__file__).parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(2)]
    for child in children:
        _, error = child.communicate(timeout=10)
        assert child.returncode == 0, error.decode()
    assert marker.read_text().splitlines() == ['request']


def test_parallelism_ramps_to_ceiling_and_cached_work_does_not_ramp(tmp_path):
    config = fixture_config(tmp_path, n=8)
    config['research'] = {'openai': config['research']['openai']}
    config['research']['openai'].update(initial_concurrency=1, concurrency=3)
    provider = FakeProvider('openai')
    active = peak = 0
    original = provider.generate
    async def delayed(prompt, settings, job):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.01)
            return await original(prompt, settings, job)
        finally:
            active -= 1
    provider.generate = delayed
    summary = asyncio.run(Pipeline(config, providers={'openai': provider}).generate())
    assert peak == 3
    assert summary['parallelism']['openai']['current'] == 3
    cached = asyncio.run(Pipeline(config, providers={'openai': provider}).generate())
    assert cached['cached'] == 8
    assert cached['parallelism']['openai']['current'] == 1


def test_transport_tuning_does_not_invalidate_paid_work(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    before = {t['agent']: t['key'] for t in Pipeline(config, providers=providers).generation_jobs()}
    config['research']['openai'].update(initial_concurrency=1, retry_attempts=6)
    config['judges']['openai'].update(initial_concurrency=1, retry_attempts=6)
    after = {t['agent']: t['key'] for t in Pipeline(config, providers=providers).generation_jobs()}
    assert before == after
    assert pipeline.plan()['judge_cache_hits'] == 12


def test_standalone_judging_reuses_answers_without_keys_or_original_questions(tmp_path):
    import importlib
    import os
    import subprocess
    import sys
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    for name in ('openai', 'gemini'):
        providers[name].ADAPTER_VERSION = importlib.import_module('crest.providers.' + name).ADAPTER_VERSION
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    Path(config['questions']).unlink()
    env = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY'}}
    env['PYTHONPATH'] = str(Path(__file__).parents[1])
    completed = subprocess.run([sys.executable, '-m', 'crest', 'judge',
                                '--run', str(pipeline.run_dir), '--config', config['_config_path']],
                               cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    stage = json.loads((pipeline.run_dir / 'run.json').read_text())['stages'][-1]
    assert stage['name'] == 'judge'
    assert stage['summary']['cached'] == 12
    assert stage['summary']['failed'] == 0


def test_analysis_worker_count_does_not_invalidate_result_cache(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    config['analysis']['workers'] = 2
    assert pipeline.analyze()['cache_hit'] is True


def test_budget_failure_preserves_observed_estimate_usage_and_flag(tmp_path):
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    async def exceeded(prompt, settings, job):
        job.save(observed_cost_usd=5.25, observed_usage={'input_tokens': 300000},
                 budget_exceeded=True, remote_id='paid-over-budget')
        raise RuntimeError('Cancellation attempted; final cost unknown')
    providers['openai'].generate = exceeded
    pipeline = Pipeline(config, providers=providers)
    generated = asyncio.run(pipeline.generate())
    failures = [json.loads(line) for line in (Path(generated['directory']) / 'errors.jsonl').read_text().splitlines()]
    assert failures[0]['cost_usd'] is None
    assert failures[0]['observed_cost_usd'] == 5.25
    assert failures[0]['usage']['input_tokens'] == 300000
    assert failures[0]['budget_exceeded'] is True
    asyncio.run(pipeline.judge())
    analyzed = pipeline.analyze()
    report = json.loads((Path(analyzed['directory']) / 'ranking.json').read_text())
    assert report['costs']['failures']['partial_observed_estimate_usd'] == 5.25
    assert report['costs']['failures']['unknown_count'] == 1


def test_changed_source_blocks_fresh_work_but_recovers_checkpointed_result(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'caesar': config['research']['caesar']}
    provider = FakeProvider('caesar')
    source = {'revision': 'original'}
    provider.identity_metadata = lambda settings: dict(source)
    pipeline = Pipeline(config, providers={'caesar': provider})
    pipeline._ensure_run()
    task = pipeline.generation_jobs()[0]
    source['revision'] = 'updated'
    with pytest.raises(ValueError, match='Caesar source changed'):
        asyncio.run(pipeline._execute(task, 'generate'))
    assert provider.generations == []

    # A parent can die after worker submission but before checkpointing its PID.
    # Recover the already-paid result even if the source changed afterwards.
    from crest.providers import caesar
    result_path = tmp_path / 'caesar-result.json'
    result_path.write_text(json.dumps({'status': 'completed', 'result': {
        'text': 'Previously paid answer', 'model': 'original', 'usage': {},
        'cost_usd': 1.25, 'citations': []}}))
    pipeline.cache.job(task['key']).save(submission_unknown=True, result_path=str(result_path))
    provider.generate = caesar.generate
    recovered, cached = asyncio.run(pipeline._execute(task, 'generate'))
    assert recovered['result']['text'] == 'Previously paid answer'
    assert cached is False


def test_answer_timing_is_saved_and_reused_without_measuring_cache_retrieval(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'openai': config['research']['openai']}
    provider = FakeProvider('openai')
    pipeline = Pipeline(config, providers={'openai': provider})
    first = asyncio.run(pipeline.generate())
    row = json.loads((Path(first['directory']) / 'answers.jsonl').read_text())
    timing = row['timing']
    assert timing['duration_seconds'] >= 0
    assert timing['started_at'].endswith('+00:00')
    assert timing['completed_at'].endswith('+00:00')
    assert timing['source'] == 'checkpoint:first_started_at/completed_at'
    assert 'polling' in timing['definition']
    state = pipeline.cache.job(row['key']).state
    assert state['timing'] == timing
    assert state['first_started_at'] == state['started_at']

    second = asyncio.run(Pipeline(config, providers={'openai': provider}).generate())
    cached = json.loads((Path(second['directory']) / 'answers.jsonl').read_text())
    assert cached['cache_hit'] is True
    assert cached['timing'] == timing
    assert len(provider.generations) == 1


def test_resumed_answer_timing_preserves_the_first_execution(tmp_path, monkeypatch):
    stamps = iter(('20261025T010030.000000Z', '20261025T010100.000000Z'))
    monkeypatch.setattr('crest.pipeline.timestamp', lambda: next(stamps))
    config = fixture_config(tmp_path, n=1)
    provider = FakeProvider('openai')
    pipeline = Pipeline(config, providers={'openai': provider})
    task = next(t for t in pipeline.generation_jobs() if t['agent'] == 'openai')
    job = pipeline.cache.job(task['key'])
    job.save(status='failed', started_at='20261025T010000.000000Z',
             submitted_at=1792890005, remote_id='already-submitted')
    row, cached = asyncio.run(pipeline._execute(task, 'generate'))
    assert not cached
    assert row['timing']['started_at'] == '2026-10-25T01:00:00+00:00'
    assert row['timing']['duration_seconds'] == 60
    state = pipeline.cache.job(task['key']).state
    assert state['first_started_at'] == '20261025T010000.000000Z'
    assert state['started_at'] != state['first_started_at']


@pytest.mark.parametrize('start_fields, expected_start, expected_seconds, expected_source', [
    ({'started_at': '20261025T010000.000000Z'}, '2026-10-25T01:00:00+00:00', 60,
     'checkpoint:started_at/completed_at'),
    ({'started_at': '20261025T010030.000000Z', 'submitted_at': 1792890000},
     '2026-10-25T01:00:00+00:00', 60, 'checkpoint:submitted_at/completed_at'),
    ({'worker_started_at': 1792890000}, '2026-10-25T01:00:00+00:00', 60,
     'checkpoint:worker_started_at/completed_at'),
    ({}, None, None, 'unavailable'),
    ({'started_at': 'not-a-time', 'submitted_at': 'inf'}, None, None, 'unavailable'),
    ({'started_at': '20261025T010200.000000Z'}, '2026-10-25T01:02:00+00:00', None,
     'checkpoint:started_at/completed_at'),
])
def test_legacy_cached_answer_timing_uses_original_checkpoints_or_unknown(
        tmp_path, start_fields, expected_start, expected_seconds, expected_source):
    config = fixture_config(tmp_path, n=1)
    provider = FakeProvider('openai')
    pipeline = Pipeline(config, providers={'openai': provider})
    task = next(t for t in pipeline.generation_jobs() if t['agent'] == 'openai')
    pipeline.cache.job(task['key']).save(status='completed', result={'text': 'Paid answer'},
        completed_at='20261025T010100.000000Z', **start_fields)
    row, cached = asyncio.run(pipeline._execute(task, 'generate'))
    assert cached
    assert row['timing']['started_at'] == expected_start
    assert row['timing']['duration_seconds'] == expected_seconds
    assert row['timing']['source'] == expected_source
    assert provider.generations == []


def test_malformed_cached_completion_time_is_unknown(tmp_path):
    config = fixture_config(tmp_path, n=1)
    pipeline = Pipeline(config, providers={'openai': FakeProvider('openai')})
    task = next(t for t in pipeline.generation_jobs() if t['agent'] == 'openai')
    pipeline.cache.job(task['key']).save(status='completed', result={'text': 'Paid answer'},
        started_at='20261025T010000.000000Z', completed_at='bad timestamp')
    row, _ = asyncio.run(pipeline._execute(task, 'generate'))
    assert row['timing']['completed_at'] is None
    assert row['timing']['duration_seconds'] is None


def test_generation_cost_details_cover_cache_only_overrides_without_mutating_cache(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {'openai': config['research']['openai']}
    provider = FakeProvider('openai')
    class CacheOnlyPipeline(Pipeline):
        async def _execute(self, task, stage, controller):
            assert stage == 'generate'
            result = self.cache.job(task['key']).state['result']
            return {k: task[k] for k in ('key', 'question_id', 'agent')} | {'result': result}, True
    pipeline = CacheOnlyPipeline(config, providers={'openai': provider})
    task = pipeline.generation_jobs()[0]
    result = {'text': 'Exact cached answer', 'model': 'gpt-6.1-sol', 'cost_usd': .25,
              'raw': {'id': 'immutable-receipt'}, 'usage': {'input_tokens': 10}}
    job = pipeline.cache.job(task['key'])
    job.save(status='completed', result=result)
    before = job.path.read_bytes()
    keys = [row['key'] for row in pipeline.generation_jobs()]
    asyncio.run(pipeline.generate())
    answer = pipeline.answers()[0]
    assert answer['cost_details']['cumulative_known_estimate_usd'] == .25
    assert answer['cost_details']['actual_billed_usd'] is None
    assert answer['result'] == result
    assert answer['key'] == task['key']
    assert job.path.read_bytes() == before
    assert [row['key'] for row in pipeline.generation_jobs()] == keys
    assert provider.generations == []


def test_flat_answer_files_link_configuration_registry_without_changing_paid_keys(tmp_path):
    import re
    config = fixture_config(tmp_path, n=2)
    config['research'] = {'openai': config['research']['openai']}
    provider = FakeProvider('openai')
    pipeline = Pipeline(config, providers={'openai': provider})
    keys = [task['key'] for task in pipeline.generation_jobs()]
    generated = asyncio.run(pipeline.generate())
    stage = Path(generated['directory'])
    registry = json.loads((stage / 'configurations.json').read_text())
    assert len(registry) == 1
    number = {question['id']: i + 1 for i, question in enumerate(pipeline.questions)}
    for row in pipeline.answers():
        assert re.fullmatch(r'answers/q\d{2}-openai-[a-f0-9]{12}\.md', row['answer_file'])
        assert row['answer_file'].startswith(f"answers/q{number[row['question_id']]:02d}-")
        assert (stage / row['answer_file']).read_bytes() == row['result']['text'].encode('utf-8')
        record = registry[row['configuration_id']]
        assert row['configuration_sha256'] == record['configuration_sha256']
        assert len(row['configuration_sha256']) == 64
        assert record['settings']['model'] == config['research']['openai']['model']
    assert all(path.is_file() for path in (stage / 'answers').iterdir())
    assert re.fullmatch(r'\d{2}-\d{2}-\d{2}-(?:CDT|CST)-[a-f0-9]{8}', pipeline.run_dir.name)
    assert re.fullmatch(r'01-generate-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-(?:CDT|CST)', stage.name)
    assert [task['key'] for task in pipeline.generation_jobs()] == keys


def test_judging_freezes_configuration_and_prior_cost_ledgers_and_invalidates_only_analysis(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name] for name in ('openai', 'gemini')}
    providers = {name: FakeProvider(name) for name in ('openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    generation = asyncio.run(pipeline.generate())
    prior_path = pipeline.run_dir / 'prior_judgment_costs.jsonl'
    prior = {'key': 'superseded-paid-1', 'stage': 'judge', 'judge': 'openai',
             'cost_usd': .3, 'valid_for_ranking': False, 'replacement_key': 'replacement'}
    prior_path.write_text(json.dumps(prior) + '\n')
    stage = Path(asyncio.run(pipeline.judge())['directory'])
    assert json.loads((stage / 'configurations.json').read_text()) == json.loads(
        (Path(generation['directory']) / 'configurations.json').read_text())
    assert (stage / 'prior_judgment_costs.jsonl').read_text() == prior_path.read_text()
    first = pipeline.analyze()
    assert first['report']['costs']['prior_judgments']['known_usd'] == .3
    assert first['report']['costs']['total']['known_usd'] == pytest.approx(.74)
    assert all(row['choices'] == 4 for row in first['report']['ranking'])
    prior_path.write_text(prior_path.read_text() + json.dumps({**prior, 'key': 'superseded-paid-2', 'cost_usd': .2}) + '\n')
    assert pipeline.analyze()['cache_hit'] is True
    asyncio.run(pipeline.judge())
    second = pipeline.analyze()
    assert second['cache_hit'] is False
    assert second['report']['ranking'] == first['report']['ranking']
    assert second['report']['costs']['prior_judgments']['known_usd'] == .5
    assert second['report']['costs']['total']['known_usd'] == pytest.approx(.94)
    assert sum(len(provider.judgments) for provider in providers.values()) == 4


def test_configuration_ids_follow_frozen_prompt_template_on_resume_and_legacy_registry_fallback(tmp_path):
    import copy
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name] for name in ('openai', 'gemini')}
    providers = {name: FakeProvider(name) for name in ('openai', 'gemini')}
    first = Pipeline(config, providers=providers)
    generation = Path(asyncio.run(first.generate())['directory'])
    expected = json.loads((generation / 'configurations.json').read_text())
    assert all(row['prompt_template'] == config['research_prompt'] for row in expected.values())
    current = copy.deepcopy(config)
    current['research_prompt'] = 'A different current template: {question}'
    resumed = Pipeline(current, providers=providers, run_dir=first.run_dir)
    regenerated = Path(asyncio.run(resumed.generate())['directory'])
    assert json.loads((regenerated / 'configurations.json').read_text()) == expected
    (regenerated / 'configurations.json').unlink()  # Legacy stages lack the sidecar.
    judged = Path(asyncio.run(resumed.judge())['directory'])
    assert json.loads((judged / 'configurations.json').read_text()) == expected
    assert sum(len(provider.generations) for provider in providers.values()) == 2


def judgment_fixture(tmp_path, *, attempts=3):
    config = fixture_config(tmp_path, n=1)
    config['judges'] = {'openai': config['judges']['openai']}
    config['judges']['openai']['retry_attempts'] = attempts
    provider = FakeProvider('openai')
    pipeline = Pipeline(config, providers={'openai': provider})
    pipeline._ensure_run()
    task = {'key': digest({'fixture': 'judge'}), 'question_id': pipeline.questions[0]['id'],
            'pair': ['gemini', 'openai'], 'order': ['gemini', 'openai'], 'judge': 'openai',
            'answer_keys': ['a', 'b'], 'answer_hashes': ['ha', 'hb'], 'prompt': 'Compare.',
            'settings': config['judges']['openai'], 'protocol_version': 'quality-v3',
            'presentation_version': 'anonymous-v1', 'presented_answer_hashes': ['pa', 'pb']}
    return pipeline, provider, task


def verdict_receipt(reason='A offers a more useful concrete plan than B, with clear implementation tradeoffs.', *, cost=.02):
    return {'text': json.dumps({'reason': reason, 'winner': 'A'}), 'cost_usd': cost,
            'usage': {'output_tokens': 100}, 'raw': {'id': f'paid-{cost}'}}


def test_judgment_retries_rejected_reason_in_fresh_checkpoint_and_accounts_for_both(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.path)
        assert 'remote_id' not in job.state
        job.save(remote_id=f'paid-{len(calls)}', retry_events=[{'event': 'transport', 'n': len(calls)}])
        return verdict_receipt('"winner" B', cost=.03) if len(calls) == 1 else verdict_receipt(cost=.02)
    provider.judge = judge
    row, cached = asyncio.run(pipeline._execute(task, 'judge'))
    assert not cached
    assert len(set(calls)) == 2
    assert row['cost_usd'] == pytest.approx(.05)
    assert row['result']['cost_usd'] == .02
    assert row['usage_scope'] == 'successful_attempt'
    assert [a['status'] for a in row['attempts']] == ['rejected', 'completed']
    assert [a['cost_usd'] for a in row['attempts']] == [.03, .02]
    assert all(a['timing']['duration_seconds'] >= 0 for a in row['attempts'])
    assert len(row['retry_events']) == 2
    for key in ('protocol_version', 'presentation_version', 'presented_answer_hashes'):
        assert row[key] == task[key]
    resumed, cached = asyncio.run(pipeline._execute(task, 'judge'))
    assert cached
    assert resumed['cost_usd'] == pytest.approx(.05)
    assert resumed['attempts'] == row['attempts']
    assert len(calls) == 2


def test_judgment_all_invalid_is_bounded_and_resume_keeps_all_charged_receipts(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path, attempts=2)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.path)
        return {**verdict_receipt(cost=.04), 'text': 'invalid JSON'}
    provider.judge = judge
    for _ in range(2):
        with pytest.raises(ValueError, match='valid|invalid|rejected|attempt'):
            asyncio.run(pipeline._execute(task, 'judge'))
    state = pipeline._stage_cache('judge').job(task['key']).state
    assert len(calls) == 2
    assert state['cost_usd'] == pytest.approx(.08)
    assert len(state['attempts']) == 2
    assert all(Path(a['cache_record']).is_file() for a in state['attempts'])


def test_judgment_resume_after_terminal_receipt_checkpoint_does_not_call_provider(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    async def interrupted(prompt, settings, job):
        calls.append(job.path)
        job.save(remote_id='already-paid', provider_result=verdict_receipt(cost=.06))
        raise asyncio.CancelledError()
    provider.judge = interrupted
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._execute(task, 'judge'))
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['cost_usd'] == .06
    assert row['verdict']['winner'] == 'A'
    assert len(calls) == 1
    assert len(row['attempts']) == 1


def test_judgment_terminal_provider_failure_retains_cost_when_next_attempt_succeeds(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.path)
        if len(calls) == 1:
            job.save(remote_id='failed-paid', remote_status='incomplete',
                     raw={'id': 'failed-paid', 'status': 'incomplete'},
                     provider_result={'cost_usd': .07, 'usage': {'output_tokens': 40}})
            raise RuntimeError('terminal incomplete response')
        return verdict_receipt(cost=.02)
    provider.judge = judge
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['cost_usd'] == pytest.approx(.09)
    assert row['attempts'][0]['cost_usd'] == .07
    assert 'terminal incomplete' in row['attempts'][0]['error']
    assert len(calls) == 2


def test_judgment_unknown_submission_never_automatically_resubmits(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.path)
        job.save(submission_unknown=True)
        raise RuntimeError('submission outcome unknown')
    provider.judge = judge
    for _ in range(2):
        with pytest.raises(RuntimeError, match='unknown'):
            asyncio.run(pipeline._execute(task, 'judge'))
    assert len(calls) == 1
    state = pipeline._stage_cache('judge').job(task['key']).state
    assert len(state['attempts']) == 1
    assert state['attempts'][0]['status'] == 'failed'


def test_judgment_retries_are_single_flight_under_concurrent_resume(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.path)
        await asyncio.sleep(.01)
        return {**verdict_receipt(), 'text': 'invalid JSON'} if len(calls) == 1 else verdict_receipt()
    provider.judge = judge
    async def run():
        return await asyncio.gather(*(pipeline._execute(task, 'judge') for _ in range(3)))
    results = asyncio.run(run())
    assert [cached for _, cached in results] == [False, True, True]
    assert all(row['cost_usd'] == pytest.approx(.04) for row, _ in results)
    assert len(set(calls)) == 2


def test_new_judgment_stage_carries_all_previous_paid_keys_once(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name] for name in ('openai', 'gemini')}
    providers = {name: FakeProvider(name) for name in ('openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.generate())
    first = Path(asyncio.run(pipeline.judge())['directory'])
    asyncio.run(pipeline.judge())  # A cached repeat must not charge the same four keys again.
    first_rows = [json.loads(line) for line in (first / 'judgments.jsonl').read_text().splitlines()]
    Path(config['rubric']).write_text('A new rubric version for a distinct comparison.')
    new = Path(asyncio.run(pipeline.judge())['directory'])
    ledger = [json.loads(line) for line in (new / 'prior_judgment_costs.jsonl').read_text().splitlines()]
    assert {r['key'] for r in ledger} == {r['key'] for r in first_rows}
    assert len(ledger) == 4
    assert sum(r['cost_usd'] for r in ledger) == pytest.approx(.04)
    assert all(r['valid_for_ranking'] is False for r in ledger)


def test_completed_cached_judgment_reason_is_revalidated_and_old_receipt_preserved(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    old = verdict_receipt('"winner" B', cost=.08)
    parent = pipeline._stage_cache('judge').job(task['key'])
    parent.save(status='completed', result=old, remote_id='historical-paid',
                started_at='20261026T010000.000000Z', completed_at='20261026T010001.000000Z')
    row, cached = asyncio.run(pipeline._execute(task, 'judge'))
    assert not cached
    assert row['cost_usd'] == pytest.approx(.09)
    assert row['attempts'][0]['result'] == old
    preserved = json.loads(Path(row['attempts'][0]['cache_record']).read_text())
    assert preserved['remote_id'] == 'historical-paid'
    assert preserved['result'] == old
    assert len(provider.judgments) == 1


def test_checkpoint_write_failure_after_valid_verdict_never_creates_another_paid_attempt(tmp_path, monkeypatch):
    from crest.cache import Job
    pipeline, provider, task = judgment_fixture(tmp_path)
    save = Job.save
    failed = False
    def interrupted_save(job, **changes):
        nonlocal failed
        if changes.get('status') == 'completed' and job.key == task['key'] and not failed:
            failed = True
            raise OSError('interrupted parent completion')
        return save(job, **changes)
    monkeypatch.setattr(Job, 'save', interrupted_save)
    with pytest.raises(OSError, match='interrupted'):
        asyncio.run(pipeline._execute(task, 'judge'))
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['cost_usd'] == .01
    assert len(row['attempts']) == 1
    assert len(provider.judgments) == 1


def test_native_terminal_raw_checkpoint_is_recovered_without_rebuying(tmp_path):
    from types import SimpleNamespace
    from crest.providers import openai
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    raw = {'id': 'terminal-paid', 'status': 'completed', 'model': 'gpt-6.1-sol',
           'usage': {'input_tokens': 100, 'output_tokens': 10},
           'output': [{'type': 'message', 'status': 'completed',
                       'content': [{'type': 'output_text', 'text': verdict_receipt()['text']}]}]}
    async def interrupted(prompt, settings, job):
        calls.append(job.path)
        job.save(raw=raw, remote_id=raw['id'], remote_status='completed')
        raise asyncio.CancelledError()
    provider.judge = interrupted
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._execute(task, 'judge'))
    # This adapter can decode the saved terminal response without credentials or network.
    pipeline.providers['openai'] = SimpleNamespace(judge=openai.judge)
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['result']['raw'] == raw
    assert row['cost_usd'] == pytest.approx(.0003)
    assert len(row['attempts']) == 1
    assert len(calls) == 1


@pytest.mark.parametrize('old', [{}, {'text': ''}, {'text': None}, [], None])
def test_malformed_cached_judgment_becomes_preserved_rejected_attempt(tmp_path, old):
    pipeline, provider, task = judgment_fixture(tmp_path)
    parent = pipeline._stage_cache('judge').job(task['key'])
    parent.save(status='completed', result=old)
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert len(row['attempts']) == 2
    assert row['attempts'][0]['status'] == 'rejected'
    assert row['cost_usd'] is None
    assert row['known_cost_usd'] == .01
    assert row['unknown_cost_count'] == 1
    original = json.loads(Path(row['attempts'][0]['cache_record']).read_text())
    assert original['result'] == old
    assert len(provider.judgments) == 1


def test_valid_legacy_cached_judgment_is_strictly_reused_without_checkpoint_mutation(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    parent = pipeline._stage_cache('judge').job(task['key'])
    parent.save(status='completed', result=verdict_receipt(cost=.08))
    before = parent.path.read_bytes()
    row, cached = asyncio.run(pipeline._execute(task, 'judge'))
    assert cached
    assert row['cost_usd'] == .08
    assert parent.path.read_bytes() == before
    assert provider.judgments == []


def test_prior_ledger_carries_failed_attempts_and_imported_costs_once(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name] for name in ('openai', 'gemini')}
    config['judges'] = {'openai': config['judges']['openai']}
    config['judges']['openai']['retry_attempts'] = 2
    providers = {name: FakeProvider(name) for name in ('openai', 'gemini')}
    paid = []
    async def invalid(prompt, settings, job):
        paid.append(job.path)
        return {**verdict_receipt(cost=.04), 'text': 'invalid JSON'}
    providers['openai'].judge = invalid
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.generate())
    imported = {'key': 'imported-superseded', 'stage': 'judge', 'judge': 'openai',
                'cost_usd': .3, 'valid_for_ranking': False}
    (pipeline.run_dir / 'prior_judgment_costs.jsonl').write_text(json.dumps(imported) + '\n')
    failed = asyncio.run(pipeline.judge())
    assert failed['failed'] == 2
    asyncio.run(pipeline.judge())
    assert len(paid) == 4
    Path(config['rubric']).write_text('A different rubric that creates new paid keys.')
    providers['openai'].judge = FakeProvider('openai').judge
    final = Path(asyncio.run(pipeline.judge())['directory'])
    ledger = [json.loads(line) for line in (final / 'prior_judgment_costs.jsonl').read_text().splitlines()]
    assert len(ledger) == 3
    assert sum(row['cost_usd'] for row in ledger) == pytest.approx(.46)
    old = [row for row in ledger if row['key'] != imported['key']]
    assert all(len(row['attempts']) == 2 for row in old)
    assert all(row['valid_for_ranking'] is False for row in ledger)


def test_judgment_unknown_charged_cost_keeps_known_retry_cost_separate(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    paid = []
    async def judge(prompt, settings, job):
        paid.append(job.path)
        if len(paid) == 1:
            return {**verdict_receipt(cost=None), 'text': 'invalid JSON'}
        return verdict_receipt(cost=.02)
    provider.judge = judge
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['cost_usd'] is None
    assert row['known_cost_usd'] == .02
    assert row['unknown_cost_count'] == 1
    assert [attempt['cost_usd'] for attempt in row['attempts']] == [None, .02]
    assert row['result']['cost_usd'] == .02


def test_terminal_raw_id_reconciles_unknown_submission_before_quality_retry(tmp_path):
    from crest.providers import openai
    pipeline, provider, task = judgment_fixture(tmp_path)
    calls = []
    raw = {'id': 'paid-reconcile', 'status': 'completed', 'model': 'gpt-6.1-sol',
           'usage': {'input_tokens': 100, 'output_tokens': 10},
           'output': [{'type': 'message', 'content': [{'type': 'output_text',
                       'text': verdict_receipt('"winner" B')['text']}]}]}
    async def judge(prompt, settings, job):
        calls.append(job.path)
        if len(calls) == 1:
            job.save(raw=raw, submission_unknown=True, provider_result=verdict_receipt('"winner" B', cost=.0003))
            raise asyncio.CancelledError()
        if job.state.get('raw'):
            return await openai.judge(prompt, settings, job)
        return verdict_receipt(cost=.02)
    provider.judge = judge
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline._execute(task, 'judge'))
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['cost_usd'] == pytest.approx(.0203)
    assert row['attempts'][0]['remote_id'] == raw['id']
    assert row['attempts'][0]['submission_unknown'] is False
    assert len(row['attempts']) == 2


def test_legacy_retry_does_not_invent_a_start_time_for_earlier_paid_work(tmp_path):
    pipeline, provider, task = judgment_fixture(tmp_path)
    parent = pipeline._stage_cache('judge').job(task['key'])
    parent.save(status='completed', result=verdict_receipt('"winner" B', cost=.03))
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert row['attempts'][0]['timing']['started_at'] is None
    assert row['attempts'][0]['timing']['duration_seconds'] is None
    assert row['timing']['started_at'] is None
    assert row['timing']['duration_seconds'] is None
    assert row['attempts'][1]['timing']['duration_seconds'] >= 0


@pytest.mark.parametrize('placeholder', [None, {}, {'text': 'invalid JSON'}])
def test_legacy_active_paid_judgment_is_retrieved_before_placeholder_validation(tmp_path, placeholder):
    import httpx
    from crest.providers import openai
    pipeline, provider, task = judgment_fixture(tmp_path)
    parent = pipeline._stage_cache('judge').job(task['key'])
    parent.save(status='failed', result=placeholder, remote_id='active-paid',
                remote_status='in_progress', raw={'id': 'active-paid', 'status': 'in_progress'})
    requests = []
    final = {'id': 'active-paid', 'status': 'completed', 'model': 'gpt-6.1-sol',
             'usage': {'input_tokens': 100, 'output_tokens': 10},
             'output': [{'type': 'message', 'content': [{'type': 'output_text',
                         'text': verdict_receipt()['text']}]}]}
    def handler(request):
        requests.append((request.method, request.url.path))
        assert request.method == 'GET', 'an active paid response must never trigger another POST'
        return httpx.Response(200, json=final)
    async def judge(prompt, settings, job):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openai.judge(prompt, settings, job, client=client)
    provider.judge = judge
    row, _ = asyncio.run(pipeline._execute(task, 'judge'))
    assert requests == [('GET', '/v1/responses/active-paid')]
    assert len(row['attempts']) == 1
    assert row['attempts'][0]['remote_id'] == 'active-paid'
    assert row['cost_usd'] == pytest.approx(.0003)
    assert row['result']['raw'] == final


def test_legacy_active_paid_judgment_poll_failure_never_opens_a_fresh_attempt(tmp_path):
    import httpx
    from crest.providers import openai
    pipeline, provider, task = judgment_fixture(tmp_path)
    parent = pipeline._stage_cache('judge').job(task['key'])
    parent.save(status='failed', result=None, remote_id='active-paid',
                remote_status='in_progress', raw={'id': 'active-paid', 'status': 'in_progress'})
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        assert request.method == 'GET', 'a failed poll must never trigger another POST'
        return httpx.Response(404, json={'error': 'temporary retrieval failure'})
    async def judge(prompt, settings, job):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openai.judge(prompt, settings, job, client=client)
    provider.judge = judge
    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(pipeline._execute(task, 'judge'))
    assert requests == [('GET', '/v1/responses/active-paid')] * 2
    state = pipeline._stage_cache('judge').job(task['key']).state
    assert len(state['attempts']) == 1
    assert state['attempts'][0]['status'] == 'failed'
    assert state['attempts'][0]['remote_id'] == 'active-paid'


def test_corrupt_judgment_cache_keeps_prior_paid_receipt_in_failure_accounting(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name] for name in ('openai', 'gemini')}
    providers = {name: FakeProvider(name) for name in ('openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.generate())
    original = Path(asyncio.run(pipeline.judge())['directory'])
    rows = [json.loads(line) for line in (original / 'judgments.jsonl').read_text().splitlines()]
    job = pipeline._stage_cache('judge').job(rows[0]['key'])
    job.path.write_text('{corrupted checkpoint')
    rerun = Path(asyncio.run(pipeline.judge())['directory'])
    error = json.loads((rerun / 'errors.jsonl').read_text())
    assert error['key'] == rows[0]['key']
    assert error['cost_usd'] == .01
    assert error['historical_cost_receipt']['key'] == rows[0]['key']
    assert not (rerun / 'prior_judgment_costs.jsonl').read_text()
    assert pipeline.analyze()['report']['costs']['total']['known_usd'] == pytest.approx(.44)
    assert sum(len(provider.judgments) for provider in providers.values()) == 4
    assert job.path.read_text() == '{corrupted checkpoint'


def test_prior_tasks_recover_paid_cache_receipts_missing_from_stage_rows(tmp_path):
    config = fixture_config(tmp_path, n=1)
    config['research'] = {name: config['research'][name] for name in ('openai', 'gemini')}
    providers = {name: FakeProvider(name) for name in ('openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.generate())
    old = Path(asyncio.run(pipeline.judge())['directory'])
    original = [json.loads(line) for line in (old / 'judgments.jsonl').read_text().splitlines()]
    (old / 'judgments.jsonl').write_text('')  # Crash between paid checkpoint and row append.
    Path(config['rubric']).write_text('A new rubric produces new judgment keys.')
    current = Path(asyncio.run(pipeline.judge())['directory'])
    ledger = [json.loads(line) for line in (current / 'prior_judgment_costs.jsonl').read_text().splitlines()]
    assert {row['key'] for row in ledger} == {row['key'] for row in original}
    assert sum(row['cost_usd'] for row in ledger) == pytest.approx(.04)
    assert all(row['attempts'] for row in ledger)
    assert pipeline.analyze()['report']['costs']['total']['known_usd'] == pytest.approx(.48)
