"""Three independent stages, timestamped snapshots, and a shared paid-work cache."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import uuid

from .cache import Cache, digest, write_json
from .config import load_questions
from .concurrency import AdaptiveLimiter

TRANSPORT_SETTINGS = {'concurrency', 'initial_concurrency', 'poll_interval_seconds',
                      'retry_attempts', 'retry_backoff_base_seconds', 'retry_backoff_max_seconds'}


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')


def _utc(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _start_checkpoint(state):
    if 'first_started_at' in state:
        return state['first_started_at'], 'first_started_at'
    candidates = [(parsed, state[key], key)
                  for key in ('started_at', 'submitted_at', 'worker_started_at')
                  if (parsed := _utc(state.get(key))) is not None]
    return min(candidates, key=lambda item: item[0])[1:] if candidates else (None, None)


def _job_timing(state):
    value, source = _start_checkpoint(state)
    start, finish = _utc(value), _utc(state.get('completed_at'))
    duration = (finish - start).total_seconds() if start and finish and finish >= start else None
    return {'started_at': start.isoformat() if start else None,
            'completed_at': finish.isoformat() if finish else None,
            'duration_seconds': duration,
            'source': f'checkpoint:{source}/completed_at' if start and finish else 'unavailable',
            'definition': 'Client elapsed time until saved completion, including provider queueing, polling, '
                          'retries and interruptions; excludes local scheduling before execution.'}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _append(path: Path, row: dict) -> None:
    import os
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _semantic_settings(settings: dict) -> dict:
    return {k: v for k, v in settings.items() if k not in TRANSPORT_SETTINGS}


class Pipeline:
    def __init__(self, config: dict, *, providers=None, run_dir=None, limit=None):
        self.config = config
        self.providers = providers or {}
        self.cache = Cache(config['cache_dir'])
        self.run_dir = Path(run_dir).expanduser().resolve() if run_dir else None
        self.manifest = None
        if self.run_dir:
            self.manifest = json.loads((self.run_dir / 'run.json').read_text())
            if self.manifest.get('schema') != 'crest-run-v1':
                raise ValueError('Not a current CREST run directory')
            self.questions = self.manifest['questions']
        else:
            self.questions = load_questions(config['questions'])
            if limit is not None:
                if limit < 1:
                    raise ValueError('limit must be positive')
                self.questions = self.questions[:limit]

    def _provider(self, name):
        if name not in self.providers:
            self.providers[name] = importlib.import_module('crest.providers.' + name)
        return self.providers[name]

    def _judge_settings(self):
        return {name: _semantic_settings(settings) | {
                    '_adapter_version': getattr(self._provider(name), 'ADAPTER_VERSION', '1')}
                for name, settings in self.config['judges'].items()}

    def preflight(self, stage: str) -> None:
        """Check all required credentials/dependencies before starting paid work."""
        required = set()
        if stage in {'generate', 'run'}:
            required.update(t['agent'] for t in self.generation_jobs()
                            if self.cache.job(t['key']).state.get('status') != 'completed')
        if stage in {'judge', 'run'}:
            from .judging import make_judgment_jobs
            rubric = Path(self.config['rubric']).read_text()
            if not rubric.strip():
                raise ValueError('Judging rubric is empty')
            agents = self.manifest['agents'] if self.manifest else list(self.config['research'])
            if len(agents) < 2:
                raise ValueError('Judging and ranking require at least two research agents')
            if stage == 'judge':
                self._latest_stage('generate')
            jobs = make_judgment_jobs(self.questions, self.answers(), self._judge_settings(), rubric)
            if stage == 'run' and (required or not self.run_dir):
                required.update(self.config['judges'])
            else:
                required.update(t['judge'] for t in jobs if not t.get('skip_reason')
                                and self._stage_cache('judge').job(t['key']).state.get('status') != 'completed')
        missing = []
        if required & {'openai', 'caesar'} and not os.environ.get('OPENAI_API_KEY'):
            missing.append('OPENAI_API_KEY')
        if 'gemini' in required and not (os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')):
            missing.append('GOOGLE_API_KEY (or GEMINI_API_KEY)')
        if missing:
            raise ValueError('Set ' + ', '.join(missing) + ' before starting uncached API work')
        if 'caesar' in required and stage in {'generate', 'run'}:
            # An attached run executes its original generation settings.
            settings = next(t['settings'] for t in self.generation_jobs() if t['agent'] == 'caesar')
            if not (Path(settings['rome_path']) / 'caesar' / 'caesar_agent.py').is_file():
                raise ValueError('research.caesar.rome_path does not contain Caesar')
            code = ('from importlib.metadata import version,PackageNotFoundError\n'
                    'missing=[]\n'
                    'for name in ["litellm","chromadb","llama-index-core","openai","networkx","mem0ai"]:\n'
                    ' try: version(name)\n'
                    ' except PackageNotFoundError: missing.append(name)\n'
                    'print(", ".join(missing))\n')
            check = subprocess.run([settings['python_executable'], '-c', code],
                                   text=True, capture_output=True, timeout=20)
            if check.returncode or check.stdout.strip():
                raise ValueError('Caesar environment is incomplete; install ../rome dependencies or set '
                                 'research.caesar.python_executable. Missing: ' + check.stdout.strip())

    def generation_jobs(self) -> list[dict]:
        if self.manifest:
            return self.manifest['generation_jobs']
        jobs = []
        for question in self.questions:
            prompt = self.config['research_prompt'].replace('{question}', question['text'])
            for agent, settings in self.config['research'].items():
                provider = self._provider(agent)
                identity = {'stage': 'generate-v1', 'agent': agent,
                            'question': question['text'], 'prompt': prompt,
                            'settings': _semantic_settings(settings),
                            'adapter': getattr(provider, 'ADAPTER_VERSION', '1')}
                if hasattr(provider, 'identity_metadata'):
                    identity['source'] = provider.identity_metadata(settings)
                jobs.append({'key': digest(identity), 'question_id': question['id'],
                             'agent': agent, 'settings': settings, 'prompt': prompt,
                             'adapter_version': identity['adapter'],
                             'source_identity': identity.get('source')})
        return jobs

    def _ensure_run(self):
        if self.run_dir:
            return
        stamp = timestamp()
        root = Path(self.config['output_dir'])
        date = datetime.now(timezone.utc).date().isoformat()
        jobs = self.generation_jobs()
        self.run_dir = root / date / (stamp + '-' + uuid.uuid4().hex[:8])
        self.manifest = {'schema': 'crest-run-v1', 'created_at': stamp,
                         'questions': self.questions, 'agents': list(self.config['research']),
                         'generation_jobs': jobs, 'config': self.config, 'stages': []}
        write_json(self.run_dir / 'run.json', self.manifest)
        write_json(root / 'latest.json', {'run_dir': str(self.run_dir), 'created_at': stamp})

    def _new_stage(self, number: int, name: str) -> Path:
        if not self.run_dir:
            raise ValueError('Select an existing generation run with --run, or generate first')
        path = self.run_dir / f'{number:02d}-{name}-{timestamp()}'
        path.mkdir(parents=True, exist_ok=False)
        stage = {'name': name, 'directory': path.name, 'started_at': timestamp(), 'status': 'running'}
        write_json(path / 'manifest.json', stage)
        with self._manifest_lock():
            self.manifest['stages'].append(stage)
        return path

    @contextmanager
    def _manifest_lock(self):
        with (self.run_dir / '.manifest.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.manifest = json.loads((self.run_dir / 'run.json').read_text())
                yield
                write_json(self.run_dir / 'run.json', self.manifest)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _stage_cache(self, stage: str) -> Cache:
        if stage == 'generate':
            return self.cache
        if not self.run_dir:
            raise ValueError('Select a result directory before using a later-stage cache')
        return Cache(self.run_dir / '.cache' / ('judgments' if stage == 'judge' else 'analysis'))

    def _finish_stage(self, path: Path, summary: dict, **metadata):
        with self._manifest_lock():
            stage = next(s for s in self.manifest['stages'] if s['directory'] == path.name)
            stage.update(metadata, completed_at=timestamp(), summary=summary,
                         status='completed_with_errors' if summary.get('failed', 0) else 'completed')
            write_json(path / 'manifest.json', stage)

    def _latest_stage(self, name: str) -> Path:
        if not self.manifest:
            raise ValueError('No generation run selected')
        self.manifest = json.loads((self.run_dir / 'run.json').read_text())
        stages = [s for s in self.manifest['stages'] if s['name'] == name
                  and s['status'] in {'completed', 'completed_with_errors'}]
        if not stages:
            raise ValueError(f'No completed {name} stage in {self.run_dir}')
        return self.run_dir / stages[-1]['directory']

    def answers(self) -> list[dict]:
        if self.manifest:
            try:
                return _read_jsonl(self._latest_stage('generate') / 'answers.jsonl')
            except ValueError:
                return []
        answers = []
        for task in self.generation_jobs():
            state = self.cache.job(task['key']).state
            result = state.get('result', {})
            if state.get('status') == 'completed' and isinstance(result.get('text'), str) and result['text'].strip():
                answers.append({k: task[k] for k in ('key', 'question_id', 'agent')} |
                               {'result': result, 'timing': _job_timing(state)})
        return answers

    def plan(self) -> dict:
        from .judging import make_judgment_jobs
        jobs = self.generation_jobs()
        agents = self.manifest['agents'] if self.manifest else list(self.config['research'])
        rubric = Path(self.config['rubric']).read_text()
        judges = self._judge_settings()
        judge_jobs = make_judgment_jobs(self.questions, self.answers(), judges, rubric)
        total_judges = len(self.questions) * len(list(itertools.combinations(agents, 2))) * len(judges) * 2
        answer_hits = sum(self.cache.job(t['key']).state.get('status') == 'completed' for t in jobs)
        judge_hits = (sum(self._stage_cache('judge').job(t['key']).state.get('status') == 'completed'
                          for t in judge_jobs) if self.run_dir else 0)
        return {'questions': len(self.questions), 'agents': agents, 'judges': list(judges),
                'generation_calls_total': len(jobs), 'generation_cache_hits': answer_hits,
                'generation_calls_missing': len(jobs) - answer_hits, 'judge_calls_total': total_judges,
                'judge_cache_hits': judge_hits, 'judge_jobs_ready': len(judge_jobs),
                'judge_jobs_waiting_for_answers': total_judges - len(judge_jobs),
                'generation_budget_targets_usd': sum(t['settings']['budget_usd'] for t in jobs),
                'run_dir': str(self.run_dir) if self.run_dir else None,
                'parallelism': {section: {name: {'initial': settings['initial_concurrency'],
                                               'maximum': settings['concurrency']}
                                           for name, settings in self.config[section].items()}
                                for section in ('research', 'judges')},
                'warnings': [
                    '$5 is a per-answer target. Hosted APIs expose no strict per-task USD cap.',
                    'Gemini managed research controls its own backbone; it cannot use the OpenAI model.',
                    'Judge usage is additional to generation budgets. Plan makes no API calls.',
                ]}

    async def _execute(self, task: dict, stage: str, controller=None) -> tuple[dict, bool]:
        from .judging import parse_verdict
        async with self._stage_cache(stage).lock(task['key']) as job:
            job.rate_controller = controller
            cached = job.state.get('status') == 'completed'
            if cached:
                result = job.state['result']
            else:
                started = timestamp()
                first_started, _ = _start_checkpoint(job.state)
                if not any(k != 'key' for k in job.state):
                    first_started = started
                job.save(status='running', stage=stage, started_at=started,
                         first_started_at=first_started, error=None)
                provider = self._provider(task['agent'] if stage == 'generate' else task['judge'])
                call = provider.generate if stage == 'generate' else provider.judge
                try:
                    section, name = ('research', task['agent']) if stage == 'generate' else ('judges', task['judge'])
                    runtime_settings = task['settings'] | {
                        k: v for k, v in self.config[section][name].items() if k in TRANSPORT_SETTINGS}
                    already_started = any(job.state.get(k) for k in (
                        'remote_id', 'worker_pid', 'submission_unknown', 'result_path'))
                    if stage == 'generate' and not already_started:
                        version = getattr(provider, 'ADAPTER_VERSION', '1')
                        if task.get('adapter_version', version) != version:
                            raise ValueError('Generation adapter changed; start a new stage-1 run to apply it')
                        expected = task.get('source_identity')
                        if expected and provider.identity_metadata(runtime_settings) != expected:
                            raise ValueError('Caesar source changed; start a new stage-1 run to apply it')
                    result = await call(task['prompt'], runtime_settings, job)
                    # Preserve charged usage even when the returned text fails validation.
                    job.save(provider_result=result)
                    if not isinstance(result, dict) or not isinstance(result.get('text'), str) or not result['text'].strip():
                        raise ValueError('Provider returned no complete answer text')
                    if stage == 'judge':
                        result['verdict'] = parse_verdict(result['text'])
                    else:
                        missing = [c['url'] for c in result.get('citations', [])
                                   if isinstance(c, dict) and c.get('url') and c['url'] not in result['text']]
                        if missing:
                            result['text'] += '\n\nSources:\n' + '\n'.join(dict.fromkeys(missing))
                    budget, cost = task['settings'].get('budget_usd'), result.get('cost_usd')
                    if budget and cost is not None and cost > budget:
                        result.setdefault('warnings', []).append(f'Estimated cost ${cost:.2f} exceeded ${budget:.2f} target')
                        result['budget_exceeded'] = True
                    completed = timestamp()
                    job.save(status='completed', result=result, completed_at=completed, error=None,
                             timing=_job_timing(job.state | {'completed_at': completed}))
                except Exception as exc:
                    job.save(status='failed', error=f'{type(exc).__name__}: {exc}', failed_at=timestamp())
                    raise
            if stage == 'judge':
                verdict = parse_verdict(result['text'])
                row = {k: task[k] for k in ('key', 'question_id', 'pair', 'order', 'judge', 'answer_keys', 'answer_hashes')}
                row.update(verdict=verdict, cost_usd=result.get('cost_usd'), usage=result.get('usage', {}),
                           result=result, cache_hit=cached)
            else:
                row = {k: task[k] for k in ('key', 'question_id', 'agent')}
                row.update(result=result, cache_hit=cached)
            row['cache_record'] = str(job.path)
            row['retry_events'] = job.state.get('retry_events', [])
            row['timing'] = _job_timing(job.state)
            return row, cached

    async def _run_tasks(self, tasks, stage: str, directory: Path) -> dict:
        settings = self.config['research' if stage == 'generate' else 'judges']
        controllers = {name: AdaptiveLimiter(v['concurrency'], v['initial_concurrency'])
                       for name, v in settings.items()}
        peaks = {name: 0 for name in controllers}
        summary = {'planned': len(tasks), 'completed': 0, 'cached': 0, 'failed': 0, 'skipped': 0}
        output = directory / ('answers.jsonl' if stage == 'generate' else 'judgments.jsonl')
        output.touch()
        async def one(task):
            name = task['agent'] if stage == 'generate' else task['judge']
            if task.get('skip_reason'):
                summary['skipped'] += 1
                _append(directory / 'skipped.jsonl', task)
                return
            async with controllers[name].slot():
                peaks[name] = max(peaks[name], controllers[name].snapshot()['active'])
                try:
                    row, cached = await self._execute(task, stage, controllers[name])
                    _append(output, row)
                    if stage == 'generate':
                        answer_path = directory / 'answers' / task['question_id'] / (name + '.md')
                        answer_path.parent.mkdir(parents=True, exist_ok=True)
                        answer_path.write_text(row['result']['text'], encoding='utf-8')
                    summary['completed'] += 1
                    summary['cached'] += int(cached)
                    if not cached:
                        await controllers[name].succeeded()
                    print(f'{stage}: {task["question_id"]} / {name}: {"cached" if cached else "completed"}', flush=True)
                except Exception as exc:
                    summary['failed'] += 1
                    try:
                        checkpoint = self._stage_cache(stage).job(task['key'])
                        result = checkpoint.state.get('provider_result') or {}
                    except ValueError:
                        checkpoint, result = None, {}
                    if not isinstance(result, dict):
                        result = {}
                    state = checkpoint.state if checkpoint else {}
                    raw = state.get('raw') if isinstance(state.get('raw'), dict) else {}
                    raw_usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else {}
                    _append(directory / 'errors.jsonl', {'key': task['key'], 'question_id': task['question_id'],
                                                       'stage': stage, 'provider': name,
                                                       'error': f'{type(exc).__name__}: {exc}',
                                                       'cost_usd': result.get('cost_usd', raw_usage.get('cost_usd')),
                                                       'observed_cost_usd': state.get('observed_cost_usd'),
                                                       'usage': result.get('usage') or state.get('observed_usage') or raw_usage,
                                                       'budget_exceeded': bool(state.get('budget_exceeded') or
                                                                               state.get('cancel_reason') == 'budget' or
                                                                               result.get('budget_exceeded')),
                                                       'cache_record': str(checkpoint.path) if checkpoint else None})
                    print(f'{stage}: {task["question_id"]} / {name}: FAILED ({type(exc).__name__})', flush=True)
        await asyncio.gather(*(one(task) for task in tasks))
        summary['parallelism'] = {name: controller.snapshot() | {'peak_slots': peaks[name]}
                                  for name, controller in controllers.items()}
        return summary

    async def generate(self) -> dict:
        self._ensure_run()
        directory = self._new_stage(1, 'generate')
        tasks = self.generation_jobs()
        write_json(directory / 'questions.json', self.questions)
        write_json(directory / 'config.json', self.manifest['config'])
        write_json(directory / 'tasks.json', tasks)
        summary = await self._run_tasks(tasks, 'generate', directory)
        self._finish_stage(directory, summary)
        return summary | {'directory': str(directory), 'run_dir': str(self.run_dir)}

    async def judge(self) -> dict:
        from .judging import make_judgment_jobs
        if not self.run_dir:
            raise ValueError('Generate first or select --run PATH')
        generation_source = self._latest_stage('generate')
        answers = _read_jsonl(generation_source / 'answers.jsonl')
        rubric = Path(self.config['rubric']).read_text()
        judges = self._judge_settings()
        tasks = make_judgment_jobs(self.questions, answers, judges, rubric)
        directory = self._new_stage(2, 'judge')
        write_json(directory / 'questions.json', self.questions)
        write_json(directory / 'answers.json', answers)
        write_json(directory / 'judges.json', judges)
        write_json(directory / 'tasks.json', tasks)
        (directory / 'rubric.txt').write_text(rubric)
        summary = await self._run_tasks(tasks, 'judge', directory)
        expected = len(self.questions) * len(list(itertools.combinations(self.manifest['agents'], 2))) * len(judges) * 2
        summary['unavailable'] = expected - len(tasks)
        self._finish_stage(directory, summary, rubric_sha256=digest(rubric),
                           generation_directory=generation_source.name)
        return summary | {'directory': str(directory), 'run_dir': str(self.run_dir)}

    def analyze(self) -> dict:
        from .analysis import ANALYSIS_VERSION, analyze, write_report
        source = self._latest_stage('judge')
        questions = json.loads((source / 'questions.json').read_text())
        answers = json.loads((source / 'answers.json').read_text())
        judges = json.loads((source / 'judges.json').read_text())
        judgments = _read_jsonl(source / 'judgments.jsonl')
        stage_manifest = json.loads((source / 'manifest.json').read_text())
        generation_source = self.run_dir / stage_manifest['generation_directory']
        failures = _read_jsonl(generation_source / 'errors.jsonl') + _read_jsonl(source / 'errors.jsonl')
        def stable(records):
            values = [{k: v for k, v in record.items() if k not in {'cache_hit', 'cache_record'}}
                      for record in records]
            return sorted(values, key=digest)
        cache_key = digest({'analysis_version': ANALYSIS_VERSION, 'questions': questions,
                            'answers': stable(answers), 'judgments': stable(judgments),
                            'failures': stable(failures),
                            'agents': self.manifest['agents'], 'judges': list(judges),
                            'settings': {k: v for k, v in self.config['analysis'].items() if k != 'workers'}})
        job = self._stage_cache('analysis').job(cache_key)
        cached = job.state.get('status') == 'completed'
        if cached:
            report = job.state['result']
        else:
            report = analyze(questions, answers, judgments, agents=self.manifest['agents'],
                             judges=list(judges), failures=failures, **self.config['analysis'])
            job.save(status='completed', result=report, completed_at=timestamp())
        directory = self._new_stage(3, 'analysis')
        write_report(report, directory)
        self._finish_stage(directory, {'failed': 0}, judgment_directory=source.name,
                           analysis_settings=self.config['analysis'], cache_hit=cached,
                           cache_record=str(job.path))
        return {'directory': str(directory), 'run_dir': str(self.run_dir), 'report': report,
                'cache_hit': cached}

    async def run(self):
        generation = await self.generate()
        judgment = await self.judge()
        analysis = self.analyze()
        return {'generation': generation, 'judgment': judgment, 'analysis': analysis,
                'failed': generation['failed'] + judgment['failed']}
