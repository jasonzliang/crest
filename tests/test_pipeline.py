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
    rubric = tmp_path / 'rubric.txt'
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


def test_analysis_script_accepts_result_dir_and_does_not_need_api_keys(tmp_path):
    import os
    import subprocess
    import sys
    config = fixture_config(tmp_path, n=1)
    providers = {name: FakeProvider(name) for name in ('caesar', 'openai', 'gemini')}
    pipeline = Pipeline(config, providers=providers)
    asyncio.run(pipeline.run())
    env = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY'}}
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'crest/stage3_analyze.py'),
                             str(pipeline.run_dir), '--config', config['_config_path']],
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
    assert sum(e['cost_usd'] for e in errors) == pytest.approx(2.52)
    assert all(e['usage']['output_tokens'] == 123 for e in errors)
    state = pipeline._stage_cache('judge').job(errors[0]['key']).state
    assert state['status'] == 'failed'
    assert state['provider_result']['cost_usd'] == .42
    report = pipeline.analyze()['report']
    assert report['costs']['failures']['known_usd'] == pytest.approx(2.52)
    assert report['costs']['total']['known_usd'] == pytest.approx(3.18)


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
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'crest/stage1_generate.py'),
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
    completed = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'crest/stage2_judge.py'),
                                str(pipeline.run_dir), '--config', config['_config_path']],
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
