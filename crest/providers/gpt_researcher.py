"""Durable GPT Researcher subprocess provider, independent of Caesar and Rome."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
import tomllib
from uuid import uuid4

from crest.providers.gpt_researcher_worker import (
    DEFAULTS, MODEL, PINNED_COMMIT, PROTOCOL_VERSION, atomic_json,
    normalize_settings, request_digest,
)

ADAPTER_VERSION = 'gpt-researcher-subprocess-v1'
_RENAME = {'max_completion_tokens': 'max_output_tokens',
           'synthesis_max_completion_tokens': 'synthesis_max_output_tokens',
           'deep_research_breadth': 'breadth', 'deep_research_depth': 'depth',
           'max_search_results_per_query': 'max_search_results'}
SETTINGS = frozenset({_RENAME.get(k, k) for k in DEFAULTS} | {'source_path', 'python_executable'})


def public_settings(settings: dict) -> dict:
    """Canonical, credential-free execution settings; orchestration stays in Crest."""
    normalized = normalize_settings(settings)
    public = {_RENAME.get(k, k): v for k, v in normalized.items()}
    root = Path(settings.get('source_path', settings.get('gpt_researcher_path',
        Path(__file__).resolve().parents[3] / 'gpt-researcher'))).expanduser().resolve()
    # Do not resolve the executable symlink: invoking the base interpreter loses the venv.
    executable = Path(settings.get('python_executable', root / '.venv/bin/python')).expanduser().absolute()
    public.update(source_path=str(root), python_executable=str(executable))
    return public


def identity_metadata(settings: dict) -> dict:
    s = public_settings(settings)
    root = Path(s['source_path'])
    digest = hashlib.sha256()
    files = sorted((root / 'gpt_researcher').rglob('*.py'))
    for path in files:
        digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
    project = root / 'pyproject.toml'
    if project.is_file():
        digest.update(project.read_bytes())
        version = tomllib.loads(project.read_text()).get('project', {}).get('version')
    else:
        version = None
    try:
        proc = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, timeout=5, check=False)
        commit = proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    lock = root / '.venv/requirements.lock'
    own = Path(__file__).read_bytes() + Path(__file__).with_name('gpt_researcher_worker.py').read_bytes()
    return {'source_commit': commit, 'source_version': version, 'source_sha256': digest.hexdigest(),
            'source_available': bool(files), 'adapter_version': ADAPTER_VERSION,
            'protocol_version': PROTOCOL_VERSION, 'adapter_sha256': hashlib.sha256(own).hexdigest(),
            'dependencies_sha256': hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None}


def _environment(*, credentials=True):
    allowed = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}
    if credentials:
        allowed.add('OPENAI_API_KEY')
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update(PYTHON_DOTENV_DISABLED='1', PYTHONDONTWRITEBYTECODE='1',
               LANGSMITH_TRACING='false', MONOCLE_TRACING='false', HF_HUB_OFFLINE='1')
    return env


def preflight(settings: dict) -> dict:
    """Local-only source, interpreter and import validation; never probes a model."""
    s = public_settings(settings)
    identity = identity_metadata(s)
    if identity['source_commit'] != PINNED_COMMIT or not identity['source_available']:
        raise ValueError('GPT Researcher must use the pinned downloaded checkout')
    if not Path(s['python_executable']).is_file():
        raise ValueError('GPT Researcher isolated Python executable is missing')
    clean = subprocess.run(['git', '-C', s['source_path'], 'diff', '--quiet', 'HEAD', '--',
                            'gpt_researcher', 'pyproject.toml'], capture_output=True, timeout=10)
    if clean.returncode:
        raise ValueError('Tracked GPT Researcher source differs from the pinned revision')
    script = '''import sys, socket
assert sys.version_info >= (3, 12)
def blocked(*args, **kwargs): raise RuntimeError("network forbidden during preflight")
socket.socket.connect = blocked
sys.path.insert(0, sys.argv[1])
import gpt_researcher, ddgs, openai, langchain_openai, markdown_it
assert callable(openai.OpenAI.request) and callable(openai.AsyncOpenAI.request)
'''
    checked = subprocess.run([s['python_executable'], '-I', '-c', script, s['source_path']],
                             env=_environment(credentials=False), capture_output=True, timeout=90)
    if checked.returncode:
        # Import failures are local, but avoid echoing arbitrary dependency diagnostics.
        raise RuntimeError('GPT Researcher dependency/import preflight failed; inspect the isolated environment')
    return identity


def _worker_alive(state):
    import psutil
    try:
        process = psutil.Process(int(state['worker_pid']))
        command = process.cmdline()
        return (process.status() != psutil.STATUS_ZOMBIE
                and any(module in command for module in ('crest.providers.gpt_researcher_worker', 'crest.gpt_researcher_worker'))
                and state.get('result_path') in command
                and (not state.get('worker_create_time') or abs(process.create_time() - state['worker_create_time']) < .1))
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, TypeError, ValueError):
        return False


async def _terminate_worker(state):
    if not _worker_alive(state):
        return
    try:
        os.killpg(int(state['worker_pid']), signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(20):
        if not _worker_alive(state):
            return
        await asyncio.sleep(.1)
    if _worker_alive(state):
        try:
            os.killpg(int(state['worker_pid']), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _audit(directory):
    path = directory / 'gpt-researcher-output/usage.json'
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return {'cost_usd': None, 'unknown_cost': True}


def _interrupted(job, directory, status):
    usage = _audit(directory)
    job.save(remote_status=status, submission_unknown=True,
             raw={'status': status, 'usage': usage, 'raw': {'gpt_researcher_audit': usage}})


def _validate_budget_receipt(result, request):
    """Bind advisory/enforced accounting to the original request, never relabel it."""
    settings = normalize_settings(request.get('settings', {}))
    usage = result.get('usage')
    error = 'GPT Researcher budget/accounting receipt mismatch'
    if not isinstance(usage, dict):
        raise RuntimeError(error)
    mode = usage.get('budget_cap')
    if mode != settings['budget_cap'] and not (mode is None and settings['budget_cap'] != 'soft'):
        raise RuntimeError(error)
    # Old hard/auto receipts did not record the mode. They remain enforced,
    # including when a newer application default explicitly selects soft.
    for value in (result.get('cost_usd'), usage.get('cost_usd'),
                  usage.get('known_cost_usd'), usage.get('upper_bound_usd')):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise RuntimeError(error)
        if value is not None and settings['budget_cap'] != 'soft' and value > settings['budget_usd'] + 1e-12:
            raise RuntimeError(error)
    raw = result.get('raw') or {}
    if not isinstance(raw, dict):
        raise RuntimeError(error)
    for key in ('accounting', 'gpt_researcher_audit'):
        copy = raw.get(key)
        if copy is not None and (not isinstance(copy, dict) or
                (copy.get('budget_cap') is not None and copy['budget_cap'] != settings['budget_cap'])):
            raise RuntimeError(error)
        if mode is not None and copy is not None and copy != usage:
            raise RuntimeError(error)
    if mode is None:
        return  # Preserve the legacy, mode-less hard/auto receipt schema.
    for key in ('budget_usd', 'budget_target_usd', 'synthesis_reserve_usd'):
        if type(usage.get(key)) not in (int, float) or usage[key] != settings[key]:
            raise RuntimeError(error)
    # A completed worker can only publish fully settled, known accounting.
    for key in ('cost_usd', 'known_cost_usd', 'reserved_usd', 'upper_bound_usd'):
        value = usage.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise RuntimeError(error)
    if (usage.get('unknown_cost') is not False or usage['reserved_usd'] != 0 or
            usage.get('in_flight') or usage.get('terminal_failure') or
            result.get('cost_usd') is None or
            any(abs(value - usage['known_cost_usd']) > 1e-12 for value in
                (result['cost_usd'], usage['cost_usd'], usage['upper_bound_usd']))):
        raise RuntimeError(error)


def _read_record(path, request, job):
    record = json.loads(path.read_text())
    expected = {key: request[key] for key in ('protocol_version', 'job_key', 'worker_id', 'source_identity')}
    expected['request_sha256'] = request_digest(request)
    if any(record.get(k) != v for k, v in expected.items()):
        raise RuntimeError('GPT Researcher receipt identity/protocol mismatch')
    if record.get('status') != 'completed':
        job.save(raw=record, remote_status=record.get('status', 'unknown'))
        raise RuntimeError(record.get('error') or 'GPT Researcher worker failed; audit review required')
    result = record.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('text'), str) or not result['text'].strip():
        raise RuntimeError('GPT Researcher receipt has no answer')
    if result.get('model') != MODEL or not result.get('citations'):
        raise RuntimeError('GPT Researcher receipt has no model/source evidence')
    _validate_budget_receipt(result, request)
    job.save(raw=record, remote_status='completed')
    return result


async def generate(prompt: str, settings: dict, job, *, client=None):
    """Resume persisted output or an identified worker; never rerun an unknown job."""
    s = public_settings(settings)
    directory = Path(job.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    request_path = directory / 'gpt-researcher-request.json'
    result_path = directory / 'gpt-researcher-result.json'
    request = None
    if request_path.exists():
        request = json.loads(request_path.read_text())
        request_settings = request.get('settings')
        if isinstance(request_settings, dict) and 'budget_cap' not in request_settings:
            request_settings = request_settings | {'budget_cap': 'hard'}
        # Polling is parent-only transport; keep the frozen request intact for receipt hashing.
        if isinstance(request_settings, dict) and 'poll_interval_seconds' in request_settings:
            request_settings = request_settings | {'poll_interval_seconds': s['poll_interval_seconds']}
        if (request.get('protocol_version') != PROTOCOL_VERSION or request.get('job_key') != job.key
                or request.get('prompt') != prompt or request_settings != s):
            raise RuntimeError('GPT Researcher request identity does not match this job')
    if result_path.exists():
        if request is None:
            raise RuntimeError('GPT Researcher result has no matching request receipt')
        return _read_record(result_path, request, job)
    if job.state.get('remote_status') in ('failed', 'timed_out', 'interrupted') or job.state.get('submission_unknown'):
        raise RuntimeError('GPT Researcher execution is terminal or unknown; review required, no resubmission')
    child = None
    if job.state.get('worker_pid'):
        if request is None or not _worker_alive(job.state):
            _interrupted(job, directory, 'interrupted')
            raise RuntimeError('GPT Researcher worker disappeared without a receipt; no resubmission')
    else:
        if request is not None:
            raise RuntimeError('Orphan GPT Researcher request; cannot rule out previous paid execution')
        import psutil  # Lazy so the provider imports without site-packages; still before any paid launch.
        identity = preflight(s)
        # Cross-process exclusive launch claim also covers the crash-before-job.save window.
        try:
            claim = os.open(directory / 'gpt-researcher-launch.claim', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise RuntimeError('GPT Researcher launch already claimed; review required') from None
        os.close(claim)
        request = {'protocol_version': PROTOCOL_VERSION, 'job_key': job.key, 'worker_id': uuid4().hex,
                   'prompt': prompt, 'settings': s, 'source_identity': identity,
                   'output_dir': str(directory / 'gpt-researcher-output')}
        atomic_json(request_path, request)
        job.save(submission_unknown=True, remote_status='starting', result_path=str(result_path),
                 worker_started_at=time.time())
        with (directory / 'gpt-researcher-worker.log').open('ab') as log:
            child = await asyncio.create_subprocess_exec(s['python_executable'], '-m', 'crest.providers.gpt_researcher_worker',
                '--request', str(request_path), '--result', str(result_path),
                cwd=str(Path(__file__).resolve().parents[2]), env=_environment(),
                stdout=log, stderr=log, start_new_session=True)
        try:
            created = psutil.Process(child.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            created = None
        job.save(worker_pid=child.pid, worker_create_time=created, submission_unknown=False, remote_status='running')
    remaining = s['timeout_seconds'] + 30 - (time.time() - job.state.get('worker_started_at', time.time()))
    deadline = time.monotonic() + max(0., remaining)
    try:
        while not result_path.exists():
            if time.monotonic() >= deadline:
                await _terminate_worker(job.state)
                if result_path.exists():
                    break
                _interrupted(job, directory, 'timed_out')
                raise TimeoutError('GPT Researcher timed out; inspect durable usage before any retry')
            if (child is not None and child.returncode is not None) or (child is None and not _worker_alive(job.state)):
                if result_path.exists():
                    break
                _interrupted(job, directory, 'interrupted')
                raise RuntimeError('GPT Researcher exited without a receipt; no resubmission')
            await asyncio.sleep(min(s['poll_interval_seconds'], 5.))
        if child is not None:
            try:
                await asyncio.wait_for(child.wait(), timeout=5.)
            except TimeoutError:
                await _terminate_worker(job.state)
        return _read_record(result_path, request, job)
    except asyncio.CancelledError:
        # Keep the independent worker alive for durable retrieval, never start a replacement.
        job.save(remote_status='running', submission_unknown=False)
        raise
