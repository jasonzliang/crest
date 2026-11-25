"""Offline request-boundary accounting and GPT Researcher worker checks."""
import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest

# Tests marked @gpt_runtime drive the pinned upstream package, which is installed
# only in the worker venv. The main interpreter does not collect them; it runs them
# all at once through test_runtime_tests_pass_under_worker_venv (end of this file).
RUNTIME_AVAILABLE = all(importlib.util.find_spec(name) for name in ('gpt_researcher', 'langchain_openai'))
RUNTIME_TESTS = []


def gpt_runtime(test):
    RUNTIME_TESTS.append(test.__name__)
    if not RUNTIME_AVAILABLE:
        test.__test__ = False  # Not collected here, so the main run does not list 77 skips.
    return test


@pytest.fixture(autouse=True)
def _worker_tests_no_network(monkeypatch):
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('Worker tests must use in-memory transports, never external networking')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'getaddrinfo', denied)


@pytest.fixture(autouse=True)
def _no_fsync(monkeypatch):
    # Durability is not under test; atomic_json's per-write fsyncs dominated the
    # runtime tests (each ledger update persists). Write/replace order is unchanged.
    monkeypatch.setattr(os, 'fsync', lambda fd: None)


@pytest.fixture(autouse=True)
def _cached_entry_points(monkeypatch):
    # Every upstream Config scans installed plugin metadata (~40 ms); it cannot change inside one test.
    import functools
    import importlib.metadata
    monkeypatch.setattr(importlib.metadata, 'entry_points', functools.cache(importlib.metadata.entry_points))


@pytest.fixture
def isolated_process_state(monkeypatch):
    """worker.run() is a one-shot process entry: it prepends the GPT Researcher checkout to sys.path and
    rewrites os.environ. Restore both so later tests in this xdist worker see the original interpreter."""
    monkeypatch.setattr(sys, 'path', list(sys.path))
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def instant_backoff(monkeypatch):
    """Record the worker's fixed 1 s rate-limit backoff instead of waiting for it."""
    delays, real_sleep = [], asyncio.sleep
    async def sleep(delay, *args, **kwargs):
        if delay == 1.:
            delays.append(delay)
            delay = 0
        return await real_sleep(delay, *args, **kwargs)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    monkeypatch.setattr(time, 'sleep', delays.append)
    return delays


def worker():
    assert importlib.util.find_spec('crest.providers.gpt_researcher_worker'), 'worker not implemented'
    return importlib.import_module('crest.providers.gpt_researcher_worker')


MODEL = 'gpt-6.1-sol'
EVIDENCE_URL = 'https://example.test/evidence'


def evidence():
    return [{'context': f'Evidence {EVIDENCE_URL}', 'sources': [{'url': EVIDENCE_URL}]}]


def chat_response(content, *, completion_tokens=20, finish_reason='stop', reasoning_tokens=None,
                  missing_usage=False):
    """An in-memory OpenAI chat completion; 100 prompt tokens unless usage is missing."""
    usage = {'prompt_tokens': 100, 'completion_tokens': completion_tokens, 'total_tokens': 100 + completion_tokens}
    if reasoning_tokens is not None:
        usage['completion_tokens_details'] = {'reasoning_tokens': reasoning_tokens}
    return httpx.Response(200, json={'id': 'offline-id', 'object': 'chat.completion', 'created': 1, 'model': MODEL,
        'choices': [{'index': 0, 'finish_reason': finish_reason, 'message': {'role': 'assistant', 'content': content}}],
        'usage': None if missing_usage else usage})


def offline_kwargs(client, **extra):
    return {'api_key': 'offline-test-placeholder', 'http_async_client': client, 'use_responses_api': False, **extra}


async def chat(client, content, max_tokens=8000):
    """One real upstream create_chat_completion call through the in-memory client."""
    from gpt_researcher.utils.llm import create_chat_completion
    return await create_chat_completion(messages=[{'role': 'user', 'content': content}], model=MODEL,
        llm_provider='openai', max_tokens=max_tokens, llm_kwargs=offline_kwargs(client, reasoning_effort='high'))


def route_providers(monkeypatch, client):
    """Send every upstream GenericLLMProvider through the in-memory client."""
    from gpt_researcher.llm_provider.generic.base import GenericLLMProvider
    original = GenericLLMProvider.from_provider.__func__
    def factory(cls, *args, **kwargs):
        kwargs.update(api_key='offline-test-placeholder', http_async_client=client)
        return original(cls, *args, **kwargs)
    monkeypatch.setattr(GenericLLMProvider, 'from_provider', classmethod(factory))


def learning_skill(client):
    """A pinned DeepResearchSkill whose STRATEGIC calls use the in-memory client."""
    import gpt_researcher.skills.deep_research as deep
    skill = object.__new__(deep.DeepResearchSkill)
    skill.researcher = SimpleNamespace(cfg=SimpleNamespace(strategic_llm_provider='openai',
        strategic_llm_model=MODEL, strategic_token_limit=32000, llm_kwargs=offline_kwargs(client)),
        add_costs=lambda value: None)
    return skill


def options(**changes):
    return SimpleNamespace(url='/chat/completions', method='post', json_data={
        'model': 'gpt-6.1-sol', 'messages': [{'role': 'user', 'content': 'question'}],
        'max_completion_tokens': 100, 'reasoning_effort': 'high', **changes})


def response(**changes):
    return SimpleNamespace(model='gpt-6.1-sol', usage={
        'prompt_tokens': 100, 'completion_tokens': 20, **changes},
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='answer'))])


def audit(tmp_path, **settings):
    return worker().UsageAudit(tmp_path / 'usage.json', settings)


@pytest.mark.parametrize('settings', [
    {'budget_usd': 4.01}, {'budget_target_usd': 4.1}, {'budget_usd': float('nan')},
    {'max_input_tokens': 300000}, {'max_completion_tokens': 0},
    {'reasoning_effort': 'low'}, {'model': 'other'}, {'answer_word_limit': -1},
    {'deep_research_depth': 0}, {'synthesis_reserve_usd': 4},
])
def test_invalid_or_unbounded_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        worker().normalize_settings(settings)


def test_persisted_reservation_precedes_billing_and_reconciles_cache(tmp_path):
    a = audit(tmp_path)
    token = a.before(options(messages=[{'role': 'user', 'content': 'x' * 1000}]))
    disk = json.loads(a.path.read_text())
    assert disk['unknown_cost'] is True
    assert disk['reserved_usd'] > 0
    a.after(token, response=response(prompt_tokens=1000, completion_tokens=100,
        prompt_tokens_details={'cached_tokens': 300, 'cache_write_tokens': 200}))
    state = a.snapshot()
    assert state['cost_usd'] == pytest.approx((500 * 2 + 300 * .1 + 200 * 2.5 + 100 * 10) / 1e6)
    assert state['reserved_usd'] == 0
    assert state['unknown_cost'] is False
    assert state['successful_calls'] == 1
    assert 'question' not in a.path.read_text()


def test_concurrent_reservations_preserve_synthesis_headroom(tmp_path):
    w = worker()
    a = audit(tmp_path, budget_usd=.4, budget_target_usd=.3, synthesis_reserve_usd=.1,
              max_completion_tokens=8000, synthesis_max_completion_tokens=1000, max_input_tokens=1000)
    for _ in range(2):
        a.before(options(max_completion_tokens=8000))
    with pytest.raises(w.BudgetStop):
        a.before(options(max_completion_tokens=8000))
    assert a.snapshot()['upper_bound_usd'] <= .2
    a.phase = 'synthesis'
    a.before(options(max_completion_tokens=1000))
    assert a.snapshot()['upper_bound_usd'] <= .4


@pytest.mark.parametrize('error', [TimeoutError(), RuntimeError(), asyncio.CancelledError()])
def test_uncertain_failures_keep_full_reservation(tmp_path, error):
    a = audit(tmp_path)
    token = a.before(options())
    reserved = a.snapshot()['reserved_usd']
    a.after(token, error=error)
    state = a.snapshot()
    assert state['cost_usd'] is None
    assert state['unknown_cost']
    assert state['reserved_usd'] == reserved
    assert state['upper_bound_usd'] == reserved


def test_confirmed_rejection_releases_reservation(tmp_path):
    a = audit(tmp_path)
    token = a.before(options())
    a.after(token, error=SimpleNamespace(status_code=429))
    assert a.snapshot()['reserved_usd'] == 0
    assert a.snapshot()['rate_limit_events'] == 1
    assert a.snapshot()['known_cost_usd'] == 0


@pytest.mark.parametrize('usage', [None, {}, {'prompt_tokens': 100, 'completion_tokens': -1},
    {'prompt_tokens': 100, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 101}},
    {'prompt_tokens': 'invalid', 'completion_tokens': 20}])
def test_missing_or_invalid_usage_never_becomes_zero(tmp_path, usage):
    a = audit(tmp_path)
    token = a.before(options())
    result = response()
    result.usage = usage
    with pytest.raises(worker().SDKStopped):
        a.after(token, response=result)
    assert a.snapshot()['cost_usd'] is None
    assert a.snapshot()['unknown_cost'] is True
    assert a.snapshot()['reserved_usd'] > 0


@pytest.mark.parametrize('change', [
    {'model': 'other'}, {'tools': [{'type': 'web_search'}]}, {'stream': True},
    {'service_tier': 'priority'}, {'n': 2}, {'prompt_cache_retention': '24h'},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'x'}}]}]},
])
def test_unpriced_requests_are_refused_before_dispatch(tmp_path, change):
    a = audit(tmp_path)
    with pytest.raises(worker().SDKStopped):
        a.before(options(**change))
    assert a.snapshot()['events'] == []


def test_input_bound_and_phase_output_limit(tmp_path):
    a = audit(tmp_path)
    opt = options(max_completion_tokens=100000)
    token = a.before(opt)
    assert opt.json_data['max_completion_tokens'] == 32000
    a.after(token, response=response())
    with pytest.raises(worker().BudgetStop):
        a.before(options(messages=[{'role': 'user', 'content': 'x' * 64000}]))


def test_sdk_hook_covers_sync_async_disables_internal_retries_and_stops_fallback(tmp_path):
    w = worker()
    a = audit(tmp_path)
    observed = []
    class Sync:
        base_url = 'https://api.openai.com/v1/'
        max_retries = 2
        def request(self, cast_to, opts, **kwargs):
            observed.append(('sync', self.max_retries))
            return response()
    class Async(Sync):
        async def request(self, cast_to, opts, **kwargs):
            observed.append(('async', self.max_retries))
            raise TimeoutError('potentially billed')
    original = Sync.request
    with a.installed(Sync, Async):
        Sync().request(object, options())
        with pytest.raises(w.SDKStopped):
            asyncio.run(Async().request(object, options()))
    assert Sync.request is original
    assert observed == [('sync', 0), ('async', 0)]
    assert a.snapshot()['successful_calls'] == 1
    assert a.snapshot()['cost_usd'] is None


def test_one_explicit_retry_is_individually_metered(tmp_path, instant_backoff):
    a = audit(tmp_path, retry_attempts=1)
    class RateLimit(Exception):
        status_code = 429
    class SDK:
        base_url = 'https://api.openai.com/v1/'
        calls = 0
        max_retries = 2
        def request(self, cast_to, opts, **kwargs):
            self.calls += 1
            if self.calls == 1: raise RateLimit()
            return response()
    client = SDK()
    with a.installed(SDK):
        client.request(object, options())
    assert client.calls == 2
    assert instant_backoff == [1.]
    assert len(a.snapshot()['events']) == 2
    assert a.snapshot()['retry_calls'] == 1


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """Record every retry backoff the worker requests, without waiting."""
    delays, real_sleep = [], asyncio.sleep
    async def sleep(delay, *args, **kwargs):
        delays.append(delay)
        return await real_sleep(0, *args, **kwargs)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    monkeypatch.setattr(time, 'sleep', delays.append)
    return delays


class ServerError(Exception):
    """Offline stand-in for openai.InternalServerError (e.g. a Cloudflare 520)."""
    def __init__(self, status_code=520, headers=None):
        super().__init__('offline server error')
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


def flaky_clients(failures, error=lambda: ServerError()):
    """Sync and async SDK stand-ins that raise ``failures`` errors, then succeed."""
    def outcome():
        Sync.calls += 1
        if Sync.calls <= failures:
            raise error()
        return response()
    class Sync:
        base_url = 'https://api.openai.com/v1/'
        max_retries = 2
        calls = 0
        def request(self, cast_to, opts, **kwargs):
            return outcome()
    class Async(Sync):
        async def request(self, cast_to, opts, **kwargs):
            return outcome()
    return Sync, Async


def send(a, asynchronous, failures, error=lambda: ServerError()):
    Sync, Async = flaky_clients(failures, error)
    with a.installed(Sync, Async):
        if asynchronous:
            asyncio.run(Async().request(object, options()))
        else:
            Sync().request(object, options())
    return Sync


@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
def test_transient_5xx_retries_and_keeps_failed_reservation_unknown(tmp_path, recorded_sleeps, asynchronous):
    a = audit(tmp_path)
    client = send(a, asynchronous, failures=1)
    state = a.snapshot()
    assert client.calls == 2
    assert recorded_sleeps == [2.]
    failed, completed = state['events']
    assert failed['status'] == 'failed' and failed['status_code'] == 520
    assert failed['unknown_cost'] is True and failed['cost_usd'] is None
    assert failed['retry_scheduled'] is True and failed['reserved_usd'] > 0
    assert completed['status'] == 'completed' and completed['attempt'] == 1
    # The possibly billed 520 attempt is never reset: it stays reserved and unknown.
    assert state['unknown_cost'] is True and state['cost_usd'] is None
    assert state['reserved_usd'] == failed['reserved_usd']
    assert state['upper_bound_usd'] == pytest.approx(state['known_cost_usd'] + failed['reserved_usd'])
    assert state['terminal_failure'] is None and not state['in_flight']
    assert not a.unresolved()
    assert json.loads((tmp_path / 'usage.json').read_text())['events'][0]['retry_scheduled'] is True


@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
def test_persistent_5xx_stops_after_bounded_retries_with_all_reservations_held(
        tmp_path, recorded_sleeps, asynchronous):
    w = worker()
    a = audit(tmp_path)
    with pytest.raises(w.SDKStopped):
        send(a, asynchronous, failures=10 ** 6)
    state = a.snapshot()
    retries = w.SERVER_ERROR_RETRIES
    assert len(state['events']) == retries + 1
    assert recorded_sleeps == [min(w.SERVER_RETRY_MAX_SECONDS, w.SERVER_RETRY_BASE_SECONDS * 2 ** n)
                               for n in range(retries)]
    assert [e.get('retry_scheduled', False) for e in state['events']] == [True] * retries + [False]
    assert all(e['unknown_cost'] and e['reserved_usd'] > 0 for e in state['events'])
    assert state['reserved_usd'] == pytest.approx(sum(e['reserved_usd'] for e in state['events']))
    assert state['terminal_failure'] == 'SDKStopped' and a.unresolved()
    with pytest.raises(w.SDKStopped):
        a.before(options())


@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
@pytest.mark.parametrize('status', [400, 404, None])
def test_4xx_or_unknown_errors_are_never_retried(tmp_path, recorded_sleeps, asynchronous, status):
    w = worker()
    a = audit(tmp_path)
    with pytest.raises(w.SDKStopped):
        send(a, asynchronous, failures=1, error=lambda: ServerError(status))
    state = a.snapshot()
    assert recorded_sleeps == [] and len(state['events']) == 1
    assert not state['events'][0].get('retry_scheduled')
    assert state['terminal_failure'] == 'SDKStopped' and state['reserved_usd'] > 0


@pytest.mark.parametrize('header,expected', [('7', 7.), ('9999', 'cap'), ('soon', 2.), ('0.5', 2.)])
def test_5xx_backoff_honors_capped_retry_after(tmp_path, recorded_sleeps, header, expected):
    w = worker()
    a = audit(tmp_path)
    send(a, False, failures=1, error=lambda: ServerError(503, {'retry-after': header}))
    assert recorded_sleeps == [w.RETRY_AFTER_CAP_SECONDS if expected == 'cap' else expected]


def test_5xx_backoff_never_sleeps_past_the_worker_deadline(tmp_path, recorded_sleeps):
    a = audit(tmp_path)
    a.deadline = time.monotonic() + .5
    send(a, False, failures=1, error=lambda: ServerError(502, {'retry-after': '30'}))
    assert len(recorded_sleeps) == 1 and 0 <= recorded_sleeps[0] <= .5


def test_retried_5xx_does_not_block_synthesis_but_unscheduled_unknown_does(tmp_path, recorded_sleeps):
    w = worker()
    a = audit(tmp_path)
    send(a, True, failures=1)
    async def finish(audit_):
        await w._finish_research(audit_, asyncio.all_tasks())
    asyncio.run(finish(a))
    assert a.snapshot()['phase_stops'] == {'research': 'completed'}
    assert a.snapshot()['terminal_failure'] is None
    # Any other unresolved charge (here without a latched circuit) still blocks synthesis.
    b = audit(tmp_path / 'b')
    b.events.append({'request_id': 'x', 'status': 'failed', 'status_code': 500, 'unknown_cost': True,
                     'cost_usd': None, 'reserved_usd': .1, 'input_tokens': 0, 'output_tokens': 0})
    assert b.unresolved()
    with pytest.raises(w.SDKStopped):
        asyncio.run(finish(b))


@pytest.mark.parametrize('url,same', [
    ('https://example.test/a/', 'https://example.test/a'),
    ('https://Example.test/a/b/', 'https://example.test/a/b'),
    ('https://example.test/a/?q=1', 'https://example.test/a?q=1'),
    ('https://example.test/a/#part', 'https://example.test/a'),
    ('https://example.test/', 'https://example.test'),
])
def test_source_key_treats_trailing_path_slash_as_the_same_resource(url, same):
    w = worker()
    assert w._source_key(url) == w._source_key(same)
    for text, retrieved in [(url, same), (same, url)]:
        result = w.extract_result(f'Claim [source]({text}).', [{'url': retrieved}], {'cost_usd': .1}, {}, {})
        assert result['citations'] == [{'url': retrieved, 'title': retrieved}]


def test_source_key_keeps_root_and_other_distinctions():
    w = worker()
    assert w._source_key('https://example.test') == 'https://example.test/'
    assert w._source_key('https://example.test/') == 'https://example.test/'
    assert w._source_key('https://example.test/a') != w._source_key('https://example.test/b')
    assert w._source_key('https://example.test/a') != w._source_key('https://example.test/a/b')
    assert w._source_key('https://example.test/a?q=1/') != w._source_key('https://example.test/a?q=1')
    assert w._source_key('http://example.test/a/') != w._source_key('https://example.test/a')
    assert w._source_key('ftp://example.test/a/') is None
    with pytest.raises(ValueError, match='not a retrieved source'):
        w.extract_result('Claim [x](https://example.test/a/b/).', [{'url': 'https://example.test/a'}],
                         {'cost_usd': .1}, {}, {})


def test_result_requires_text_and_sources_and_keeps_unknown_cost():
    w = worker()
    # Word limits and missing citations have their own tests below.
    for text, sources in [('answer', []), ('', [{'url': 'https://example.test'}])]:
        with pytest.raises(ValueError):
            w.extract_result(text, sources, {}, {}, {})
    result = w.extract_result('Finding [evidence](https://example.test).', [{'url': 'https://example.test', 'title': 'Evidence'}],
                              {'cost_usd': None, 'known_cost_usd': .2, 'unknown_cost': True}, {}, {})
    assert result['cost_usd'] is None
    assert result['raw']['accounting']['known_cost_usd'] == .2
    assert result['citations'][0]['url'] == 'https://example.test'


def test_atomic_json_roundtrip_and_nonfinite_rejection(tmp_path):
    w = worker()
    path = tmp_path / 'receipt.json'
    w.atomic_json(path, {'status': 'ok'})
    with pytest.raises(ValueError):
        w.atomic_json(path, {'cost': float('nan')})
    assert json.loads(path.read_text()) == {'status': 'ok'}
    assert list(tmp_path.glob('*.tmp')) == []


@gpt_runtime
def test_actual_sdk_and_langchain_stream_override_use_complete_usage(tmp_path):
    """Real installed clients, but an in-memory transport: no network/inference."""
    w = worker()
    a = audit(tmp_path)
    sent = []
    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        assert request.url.path == '/v1/chat/completions'
        assert body['model'] == w.MODEL
        assert body['reasoning_effort'] == 'high'
        assert not body.get('stream')
        return chat_response('Offline answer.')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with w._runtime({}, a, []):
                from gpt_researcher.llm_provider.generic.base import GenericLLMProvider
                provider = GenericLLMProvider.from_provider('openai', model=w.MODEL,
                    api_key='offline-test-placeholder', http_async_client=client,
                    reasoning_effort='high', temperature=None, max_tokens=512,
                    max_retries=0, use_responses_api=False)
                return await provider.get_chat_response([{'role': 'user', 'content': 'Q'}], True)
    assert asyncio.run(go()) == 'Offline answer.'
    assert len(sent) == 1
    assert a.snapshot()['cost_usd'] == pytest.approx(.0004)
    assert a.snapshot()['unknown_cost'] is False


def test_no_source_research_fails_before_synthesis(tmp_path):
    w = worker()
    a = audit(tmp_path)
    class Researcher:
        def __init__(self, **kwargs): pass
        async def conduct_research(self): return 'model-only unsupported text'
        async def write_report(self, **kwargs): pytest.fail('must not synthesize without evidence')
    request = {'prompt': 'Q', 'source_identity': {}}
    with pytest.raises(ValueError, match='No sources'):
        asyncio.run(w.research(request, a, Researcher, []))


def test_budget_stop_salvages_completed_evidence_for_final_answer(tmp_path):
    w = worker()
    a = audit(tmp_path, answer_word_limit=600)
    captures = []
    class Researcher:
        def __init__(self, **kwargs):
            self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=100)
            self.query = kwargs['query']
        async def conduct_research(self):
            captures.append({'context': 'Source-backed findings https://example.test/evidence',
                             'sources': [{'url': 'https://example.test/evidence'}]})
            raise w.BudgetStop('research allowance exhausted')
        async def write_report(self, **kwargs):
            assert a.phase == 'synthesis'
            assert self.query == 'Exact original question'
            assert 'Source-backed' in kwargs['ext_context']
            assert '600 words' in kwargs['custom_prompt']
            assert self.cfg.llm_kwargs['max_tokens'] == 32000
            return 'Finding [evidence](https://example.test/evidence).'
        def get_costs(self): return 9999.0
    result = asyncio.run(w.research({'prompt': 'Exact original question', 'source_identity': {'source_commit': 'test'}},
                                   a, Researcher, captures))
    assert result['text'] == 'Finding [evidence](https://example.test/evidence).'
    assert result['raw']['research_rounds'] == 1
    assert result['raw']['gpt_researcher_audit']['research_stopped'] is True
    assert result['cost_usd'] == 0
    assert result['cost_usd'] != result['raw']['upstream_estimated_cost_usd']


def test_continuation_requires_new_questions_and_stops_on_duplicate_sources(tmp_path):
    w = worker()
    a = audit(tmp_path)
    captures, queries = [], []
    class Researcher:
        def __init__(self, **kwargs):
            self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=100)
            self.deep_researcher = self
            self.query = kwargs['query']
        async def conduct_research(self):
            queries.append(self.query)
            captures.append({'context': 'Observed evidence.', 'sources': [{'url': 'https://example.test'}]})
        async def process_research_results(self, *args):
            return {'followUpQuestions': ['What evidence contradicts this result?']}
        async def write_report(self, **kwargs): return 'Finding [evidence](https://example.test).'
        def get_costs(self): return 0.
    result = asyncio.run(w.research({'prompt': 'Original', 'source_identity': {}}, a, Researcher, captures))
    assert len(queries) == 2
    assert 'contradicts' in queries[1]
    assert result['raw']['research_rounds'] == 2


def test_worker_duplicate_claim_refuses_to_overwrite_existing_usage(tmp_path):
    w = worker()
    from crest.providers.gpt_researcher import public_settings
    output = tmp_path / 'gpt-researcher-output'
    output.mkdir()
    (output / 'started.json').write_text('{}')
    (output / 'usage.json').write_text('{"known_cost_usd":2.5}')
    request = {'protocol_version': w.PROTOCOL_VERSION, 'job_key': 'a' * 64, 'worker_id': 'b' * 32,
               'prompt': 'Q', 'settings': public_settings({}), 'source_identity': {}, 'output_dir': str(output)}
    path = tmp_path / 'gpt-researcher-request.json'
    path.write_text(json.dumps(request))
    with pytest.raises(FileExistsError): w.run(path, tmp_path / 'gpt-researcher-result.json')
    assert json.loads((output / 'usage.json').read_text())['known_cost_usd'] == 2.5


def test_accounting_write_failure_retains_reservation_and_stops_retry(tmp_path, monkeypatch):
    w = worker()
    a = audit(tmp_path)
    token = a.before(options())
    def disk_full(*args, **kwargs): raise OSError('disk full')
    monkeypatch.setattr(w, 'atomic_json', disk_full)
    with pytest.raises(w.SDKStopped):
        a.after(token, response=response())
    assert a.snapshot()['unknown_cost']
    assert a.snapshot()['reserved_usd'] > 0
    assert a.snapshot()['cost_usd'] is None


@gpt_runtime
@pytest.mark.parametrize('outcome', ['length', 'empty', 'timeout', 'missing_usage'])
def test_real_upstream_completion_terminal_failure_sends_at_most_one_request(tmp_path, monkeypatch, outcome):
    """Exercise SDK -> LangChain -> GenericLLMProvider -> upstream retry loop."""
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    a = audit(tmp_path, max_completion_tokens=8000)
    sent = []
    async def no_sleep(*args): pass
    monkeypatch.setattr(asyncio, 'sleep', no_sleep)
    def handler(request):
        sent.append(json.loads(request.content))
        if outcome == 'timeout':
            raise httpx.ReadTimeout('offline timeout', request=request)
        return chat_response('' if outcome in ('length', 'empty') else 'Answer', completion_tokens=8000, reasoning_tokens=8000,
            finish_reason='length' if outcome == 'length' else 'stop', missing_usage=outcome == 'missing_usage')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with w._runtime({}, a, []):
                for _ in range(2):
                    with pytest.raises(w.SDKStopped):
                        await create_chat_completion(messages=[{'role': 'user', 'content': 'Q'}],
                            model=w.MODEL, llm_provider='openai', max_tokens=8000,
                            llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
    asyncio.run(go())
    assert len(sent) == 1, 'terminal outcome must permanently prevent any further dispatch'
    assert a.snapshot()['terminal_failure']
    assert len(a.snapshot()['events']) == 1
    if outcome in ('timeout', 'missing_usage'):
        assert a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] > 0
    else:
        assert a.snapshot()['cost_usd'] == pytest.approx(.0802)


@gpt_runtime
def test_real_upstream_budget_stop_reaches_synthesis_with_retained_evidence(tmp_path, monkeypatch):
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    a = audit(tmp_path)
    spent = a.settings['budget_target_usd'] - a.settings['synthesis_reserve_usd'] - .05
    a.events.append({'status': 'completed', 'cost_usd': spent, 'input_tokens': 0,
                     'output_tokens': 0, 'unknown_cost': False, 'reserved_usd': 0.})
    captures = [{'context': 'Retained evidence at https://example.test/real-source',
                 'sources': [{'url': 'https://example.test/real-source'}]}]
    sent = []
    async def no_sleep(*args): pass
    monkeypatch.setattr(asyncio, 'sleep', no_sleep)
    def handler(request):
        sent.append(json.loads(request.content))
        assert a.phase == 'synthesis', 'no research request fits the remaining research allowance'
        return chat_response('Finding [source](https://example.test/real-source).')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def completion(text, tokens):
                return await create_chat_completion(messages=[{'role': 'user', 'content': text}],
                    model=w.MODEL, llm_provider='openai', max_tokens=tokens,
                    llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
            class Researcher:
                def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
                async def conduct_research(self): return await completion('Research', 8000)
                async def write_report(self, **kwargs): return await completion(kwargs['ext_context'], 16000)
                def get_costs(self): return 0.
            with w._runtime({}, a, captures):
                return await w.research({'prompt': 'Original query', 'source_identity': {}}, a, Researcher, captures)
    result = asyncio.run(go())
    assert len(sent) == 1
    assert result['cost_usd'] == pytest.approx(spent + .0004)
    assert result['raw']['accounting']['research_stopped']


@pytest.mark.parametrize('payload', ['{"x":"v"}\n' * 6000, '\\"\t\n' * 18000, '漢字😀\\"' * 9000], ids=['json', 'controls', 'unicode'])
def test_synthesis_fits_fully_serialized_messages_not_raw_context_bytes(tmp_path, payload):
    w = worker()
    a = audit(tmp_path, max_research_rounds=1)
    captures = []
    class Researcher:
        def __init__(self, **kwargs):
            self.role = kwargs.get('role')
            self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
        async def conduct_research(self):
            captures.append({'context': 'Source: https://example.test/data\n' + payload,
                             'sources': [{'url': 'https://example.test/data'}]})
        async def write_report(self, ext_context, custom_prompt):
            messages = [{'role': 'system', 'content': str(self.role)},
                        {'role': 'user', 'content': custom_prompt + '\n\nContext: ' + ext_context}]
            bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 256 + 64 * len(messages)
            assert bound <= 64000, 'full serialized request must fit before synthesis starts'
            assert 'Source: https://example.test/data' in ext_context
            token = a.before(options(messages=messages, max_completion_tokens=16000))
            a.after(token, response=response())
            return 'Finding [data](https://example.test/data).'
        def get_costs(self): return 0.
    result = asyncio.run(w.research({'prompt': 'Original query with "quotes" and \\slashes', 'source_identity': {}},
                                   a, Researcher, captures))
    assert result['text'] == 'Finding [data](https://example.test/data).'


REAL = 'https://example.test/real-source'
A = 'https://example.test/a'


@pytest.mark.parametrize(('text', 'retrieved', 'match'), [
    # Missing or fabricated provenance.
    *[(text, REAL, 'citat|retrieved|source') for text in (
        'Unsupported answer with no citations.',
        'Unsupported answer [1].',
        'Claim [proof](https://fabricated.invalid/article).',
        'Claim [proof](https://example.test/not-the-retrieved-page).',
        'One [real](https://example.test/real-source), one [invented](https://fabricated.invalid/article).',
    )],
    # Markdown tokenization never hides fabricated neighbors.
    *[(text, retrieved, 'not a retrieved source') for text, retrieved in (
        ('Claim [A](https://example.test/a),[bad](https://fabricated.invalid/a).', A),
        ('Claim **[A](https://example.test/a)**,https://fabricated.invalid/a', A),
        ('Claim [A](https://example.test/a)[bad](https://example.test/invented).', A),
        ('Claim [A](https://example.test/a)[bad](https://example.test/a?invented=1).', A),
        ('Claim **[bad](https://fabricated.invalid/a)**[A](https://example.test/a).', A),
        # Delimited terminal punctuation is part of the URL, so it cannot alias the shorter retrieved resource.
        ('Claim [source](https://example.test/a!).', A),
        ('Claim [source](https://example.test/a.).', A),
        ('Claim [source](https://example.test/a?q=Wow!).', 'https://example.test/a?q=Wow'),
    )],
    # Rendered destinations, not labels or code, own citation provenance.
    *[(text, A, None) for text in (
        '[good](https://example.test/a) [bad](HTTPS://fabricated.invalid/b)',
        '[good](https://example.test/a) [bad](https&#58;//fabricated.invalid/b)',
        '[https://example.test/a](//fabricated.invalid/b)',
        'Claim [source][s].\n\n[s]: https://example.test/a!',
        '```markdown\n[source](https://example.test/a)\n```',
        '`https://example.test/a`',
        '[https://example.test/a](#section)',
        '[https://example.test/a](javascript:alert(1))',
        '<a href="https://fabricated.invalid/b">https://example.test/a</a>',
        '![https://example.test/a](//fabricated.invalid/b)',
    )],
])
def test_result_rejects_missing_fabricated_or_unrendered_citation_provenance(text, retrieved, match):
    with pytest.raises(ValueError, match=match):
        worker().extract_result(text, [{'url': retrieved}], {'cost_usd': .2, 'unknown_cost': False}, {}, {})


def test_result_citations_include_only_actually_cited_retrieved_sources():
    result = worker().extract_result(
        'Claim [evidence](https://example.test/real-source#results).',
        [{'url': 'https://example.test/unused', 'title': 'Unused'},
         {'url': 'https://example.test/real-source', 'title': 'Evidence'}],
        {'cost_usd': .2, 'unknown_cost': False}, {}, {})
    assert result['citations'] == [{'url': 'https://example.test/real-source', 'title': 'Evidence'}]
    assert len(result['raw']['retrieved_sources']) == 2


def test_default_answers_have_no_word_limit_but_explicit_limit_is_preserved():
    w = worker()
    assert w.DEFAULTS['answer_word_limit'] is None
    assert w.normalize_settings({'answer_word_limit': None})['answer_word_limit'] is None
    assert w.normalize_settings({'answer_word_limit': 1200})['answer_word_limit'] == 1200
    assert 'TOTAL_WORDS' not in w.build_config({})
    assert w.build_config({'answer_word_limit': 600})['TOTAL_WORDS'] == 600
    text = 'word ' * 700 + '[source](https://example.test/evidence)'
    args = (text, [{'url': 'https://example.test/evidence'}], {'cost_usd': .1}, {})
    assert w.extract_result(*args, {})['raw']['word_count'] == 701
    with pytest.raises(ValueError, match='word limit'):
        w.extract_result(*args, {'answer_word_limit': 600})


@gpt_runtime
def test_real_upstream_writer_has_no_hidden_word_target_in_uncapped_mode(tmp_path, monkeypatch):
    from gpt_researcher import GPTResearcher
    w = worker()
    a = audit(tmp_path, max_research_rounds=1, answer_word_limit=None)
    captures, sent = [], []
    answer = 'word ' * 700 + '[source](https://example.test/evidence)'
    async def offline_conduct(self, **kwargs):
        self.research_sources = [{'url': 'https://example.test/evidence'}]
        return 'Evidence at https://example.test/evidence'
    monkeypatch.setattr(GPTResearcher, 'conduct_research', offline_conduct)
    def handler(request):
        data = json.loads(request.content)
        sent.append(data)
        prompt = '\n'.join(m['content'] for m in data['messages'])
        assert 'None words' not in prompt
        assert '600 words' not in prompt
        assert '1200 words' not in prompt
        assert 'at most' not in prompt
        return chat_response(answer, completion_tokens=1000)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            route_providers(monkeypatch, client)
            with w._runtime({}, a, captures) as cls:
                return await w.research({'prompt': 'Original task', 'source_identity': {}}, a, cls, captures)
    result = asyncio.run(go())
    assert result['text'] == answer
    assert len(sent) == 1
    assert a.snapshot()['unknown_cost'] is False


@gpt_runtime
@pytest.mark.parametrize('outcome', ['success', 'timeout', 'hung'])
def test_real_langchain_drains_admitted_request_before_synthesis(tmp_path, outcome):
    """A sibling hits the ceiling while the first real SDK call is still accepted."""
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    # Settled replies take .05 s; the .5 s call timeout leaves room for scheduler stalls under load.
    a = audit(tmp_path, call_timeout_seconds=.5, timeout_seconds=3)
    spent = a.settings['budget_target_usd'] - a.settings['synthesis_reserve_usd'] - .16
    a.events.append({'status': 'completed', 'cost_usd': spent, 'input_tokens': 0,
                     'output_tokens': 0, 'unknown_cost': False, 'reserved_usd': 0.})
    captures = [{'context': 'Evidence https://example.test/evidence',
                 'sources': [{'url': 'https://example.test/evidence'}]}]
    sent, cancelled, received = [], [], []
    async def go():
        accepted = asyncio.Event()
        async def handler(request):
            data = json.loads(request.content)
            name = data['messages'][0]['content']
            sent.append(name)
            if name == 'accepted':
                accepted.set()
                try:
                    await asyncio.sleep(2 if outcome == 'hung' else .05)
                except asyncio.CancelledError:
                    cancelled.append(name)
                    raise
                if outcome == 'timeout':
                    raise httpx.ReadTimeout('offline genuine timeout', request=request)
            else:
                assert name == 'synthesis' and a.phase == 'synthesis'
                snapshot = a.snapshot()
                assert all(e['phase'] == 'synthesis' for e in snapshot['in_flight'])
                assert not any(e.get('unknown_cost') for e in snapshot['events'])
            return chat_response('Finding [source](https://example.test/evidence).')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def completion(name):
                result = await create_chat_completion(messages=[{'role': 'user', 'content': name}],
                    model=w.MODEL, llm_provider='openai', max_tokens=8000,
                    llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
                received.append(name)
                return result
            class Researcher:
                def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
                async def conduct_research(self):
                    async def denied():
                        await accepted.wait()
                        return await completion('must-not-send')
                    return await asyncio.gather(completion('accepted'), denied())
                async def write_report(self, **kwargs): return await completion('synthesis')
                def get_costs(self): return 0.
            with w._runtime({}, a, captures):
                return await w.research({'prompt': 'Original', 'source_identity': {}}, a, Researcher, captures)
    import time
    started = time.monotonic()
    if outcome == 'success':
        result = asyncio.run(go())
        assert result['cost_usd'] == pytest.approx(spent + .0008)
        assert cancelled == []
        assert sent == ['accepted', 'synthesis']
        assert 'accepted' in received, 'settled accepted content must survive a phase-only stop'
        assert not a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] == 0
    else:
        with pytest.raises(w.SDKStopped): asyncio.run(go())
        assert sent == ['accepted']
        assert a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] > 0
        if outcome == 'timeout':
            assert cancelled == [], 'genuine SDK failure should settle, not be preemptively cancelled'
        else:
            assert time.monotonic() - started >= .45, 'do not cancel before the bounded request timeout'
    assert time.monotonic() - started < 3


@gpt_runtime
def test_research_time_cutoff_drains_late_admitted_call_with_synthesis_headroom(tmp_path):
    from gpt_researcher.utils.llm import create_chat_completion
    import time
    w = worker()
    a = audit(tmp_path, call_timeout_seconds=1, timeout_seconds=4)
    a.research_deadline = time.monotonic() + .3
    captures = [{'context': 'Evidence https://example.test/evidence',
                 'sources': [{'url': 'https://example.test/evidence'}]}]
    sent, cancelled = [], []
    async def go():
        async def handler(request):
            name = json.loads(request.content)['messages'][0]['content']
            sent.append(name)
            if name == 'accepted':
                try:
                    # Stay in flight until just past the research cutoff, however late admission ran.
                    await asyncio.sleep(max(0., a.research_deadline - time.monotonic()) + .05)
                except asyncio.CancelledError:
                    cancelled.append(name)
                    raise
            assert time.monotonic() < a.deadline
            return chat_response('Finding [source](https://example.test/evidence).')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def completion(name):
                return await create_chat_completion(messages=[{'role': 'user', 'content': name}],
                    model=w.MODEL, llm_provider='openai', max_tokens=8000,
                    llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
            class Researcher:
                def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
                async def conduct_research(self):
                    await completion('accepted')
                    return await completion('must-not-send-after-time-cutoff')
                async def write_report(self, **kwargs): return await completion('synthesis')
                def get_costs(self): return 0.
            with w._runtime({}, a, captures):
                return await w.research({'prompt': 'Original', 'source_identity': {}}, a, Researcher, captures)
    result = asyncio.run(go())
    assert sent == ['accepted', 'synthesis']
    assert cancelled == []
    assert result['cost_usd'] == pytest.approx(.0008)
    assert a.snapshot()['research_stopped'] and not a.snapshot()['unknown_cost']


@gpt_runtime
def test_shielded_sdk_settles_even_when_langchain_caller_is_cancelled(tmp_path):
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    a = audit(tmp_path, call_timeout_seconds=.6, timeout_seconds=2)
    sent, cancelled = [], []
    async def go():
        accepted = asyncio.Event()
        baseline = asyncio.all_tasks()
        async def handler(request):
            sent.append(1)
            accepted.set()
            try:
                await asyncio.sleep(.05)
            except asyncio.CancelledError:
                cancelled.append(1)
                raise
            return chat_response('Settled answer.')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with w._runtime({}, a, []):
                caller = asyncio.create_task(create_chat_completion(
                    messages=[{'role': 'user', 'content': 'Q'}], model=w.MODEL, llm_provider='openai', max_tokens=8000,
                    llm_kwargs=offline_kwargs(client, reasoning_effort='high')))
                await accepted.wait()
                caller.cancel()
                try:
                    await caller
                except BaseException:
                    pass
                with pytest.raises(w.SDKStopped):
                    await w._finish_research(a, baseline)
                with pytest.raises(w.SDKStopped): a.before(options())
    asyncio.run(go())
    assert sent == [1] and cancelled == []
    assert a.snapshot()['terminal_failure'], 'external cancellation must not reopen admission'
    assert a.snapshot()['cost_usd'] == pytest.approx(.0004)
    assert not a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] == 0


def test_nonbillable_tail_must_finish_before_global_phase_switch(tmp_path):
    w = worker()
    a = audit(tmp_path, call_timeout_seconds=.1, timeout_seconds=2)
    captures = [{'context': 'Evidence https://example.test/evidence',
                 'sources': [{'url': 'https://example.test/evidence'}]}]
    writes = []
    class Researcher:
        def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
        async def conduct_research(self):
            started = asyncio.Event()
            async def unpaid_tail():
                started.set()
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    await asyncio.sleep(.05)  # Deliberately outlast the bounded cleanup grace.
            asyncio.create_task(unpaid_tail())
            await started.wait()
            raise w.BudgetStop('Research finished')
        async def write_report(self, **kwargs):
            writes.append(1)
            return 'Finding [source](https://example.test/evidence).'
        def get_costs(self): return 0.
    with pytest.raises(w.SDKStopped):
        asyncio.run(w.research({'prompt': 'Q', 'source_identity': {}}, a, Researcher, captures))
    assert not writes
    assert a.phase == 'research'
    assert a.snapshot()['terminal_failure']


@gpt_runtime
def test_confirmed_429_backoff_is_nonbillable_cleanup_not_unknown_failure(tmp_path):
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    a = audit(tmp_path, call_timeout_seconds=.5, timeout_seconds=2)
    spent = a.settings['budget_target_usd'] - a.settings['synthesis_reserve_usd'] - .16
    a.events.append({'status': 'completed', 'cost_usd': spent, 'input_tokens': 0,
                     'output_tokens': 0, 'unknown_cost': False, 'reserved_usd': 0.})
    captures = [{'context': 'Evidence https://example.test/evidence',
                 'sources': [{'url': 'https://example.test/evidence'}]}]
    sent = []
    async def go():
        rejected = asyncio.Event()
        async def handler(request):
            name = json.loads(request.content)['messages'][0]['content']
            sent.append(name)
            if name == 'rejected':
                rejected.set()
                return httpx.Response(429, json={'error': {'type': 'rate_limit_error', 'message': 'offline rejection'}})
            assert name == 'synthesis'
            return chat_response('Finding [source](https://example.test/evidence).')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def completion(name):
                return await create_chat_completion(messages=[{'role': 'user', 'content': name}],
                    model=w.MODEL, llm_provider='openai', max_tokens=8000,
                    llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
            class Researcher:
                def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
                async def conduct_research(self):
                    async def too_large():
                        await rejected.wait()
                        return await completion('x' * 60000)
                    return await asyncio.gather(completion('rejected'), too_large())
                async def write_report(self, **kwargs): return await completion('synthesis')
                def get_costs(self): return 0.
            with w._runtime({}, a, captures):
                return await w.research({'prompt': 'Original', 'source_identity': {}}, a, Researcher, captures)
    result = asyncio.run(go())
    assert sent == ['rejected', 'synthesis']
    assert result['cost_usd'] == pytest.approx(spent + .0004)
    assert not a.snapshot()['unknown_cost'] and not a.snapshot()['terminal_failure']


@gpt_runtime
def test_real_sdk_520_in_research_and_writer_retries_to_an_answer_with_held_reservations(
        tmp_path, recorded_sleeps):
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    a = audit(tmp_path, max_research_rounds=1)
    captures = [{'context': 'Evidence https://example.test/evidence',
                 'sources': [{'url': 'https://example.test/evidence'}]}]
    sent = []
    async def go():
        async def handler(request):
            name = json.loads(request.content)['messages'][0]['content']
            sent.append(name)
            if sent.count(name) == 1:  # One Cloudflare edge failure per role.
                return httpx.Response(520, text='<html>origin error</html>')
            return chat_response('Finding [source](https://example.test/evidence/).')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def completion(name):
                return await create_chat_completion(messages=[{'role': 'user', 'content': name}],
                    model=w.MODEL, llm_provider='openai', max_tokens=8000,
                    llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
            class Researcher:
                def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
                async def conduct_research(self): return await completion('research')
                async def write_report(self, **kwargs): return await completion('synthesis')
                def get_costs(self): return 0.
            with w._runtime({}, a, captures):
                return await w.research({'prompt': 'Original', 'source_identity': {}}, a, Researcher, captures)
    result = asyncio.run(go())
    state = a.snapshot()
    assert sent == ['research', 'research', 'synthesis', 'synthesis']
    assert recorded_sleeps.count(w.SERVER_RETRY_BASE_SECONDS) == 2
    failed = [e for e in state['events'] if e['status'] == 'failed']
    assert [(e['status_code'], e['error_type'], e['phase']) for e in failed] == [
        (520, 'InternalServerError', 'research'), (520, 'InternalServerError', 'synthesis')]
    assert all(e['retry_scheduled'] and e['unknown_cost'] and e['reserved_usd'] > 0 for e in failed)
    assert state['reserved_usd'] == pytest.approx(sum(e['reserved_usd'] for e in failed))
    assert state['known_cost_usd'] == pytest.approx(.0008)
    assert state['terminal_failure'] is None and not state['in_flight']
    assert result['cost_usd'] is None and result['usage']['unknown_cost'] is True
    assert result['citations'] == [{'url': 'https://example.test/evidence', 'title': 'https://example.test/evidence'}]
    assert any('Uncertain billed usage' in warning for warning in result['warnings'])


@gpt_runtime
def test_unsafe_tail_cannot_make_unaudited_call_after_runtime_teardown(tmp_path, monkeypatch):
    import openai
    from gpt_researcher import GPTResearcher
    from gpt_researcher.skills.deep_research import DeepResearchSkill
    from gpt_researcher.llm_provider.generic.base import GenericLLMProvider
    from gpt_researcher.retrievers.duckduckgo.duckduckgo import Duckduckgo
    from gpt_researcher.utils.llm import create_chat_completion
    # A quarantined production worker is single-use and exits. This test process
    # restores its classes only AFTER asyncio.run has terminated all test tasks.
    import inspect
    from gpt_researcher.config.config import Config
    for cls, name in ((openai.OpenAI, 'request'), (openai.AsyncOpenAI, 'request'),
                      (GenericLLMProvider, 'get_chat_response'), (GPTResearcher, 'conduct_research'),
                      (Duckduckgo, 'search'), (Config, 'parse_reasoning_effort'),
                      (DeepResearchSkill, 'process_research_results')):
        monkeypatch.setattr(cls, name, inspect.getattr_static(cls, name))
    w = worker()
    a = audit(tmp_path, call_timeout_seconds=.1, timeout_seconds=2)
    captures = [{'context': 'Evidence https://example.test/evidence',
                 'sources': [{'url': 'https://example.test/evidence'}]}]
    sent, attempted, denied = [], [], []
    async def go():
        finished = asyncio.Event()
        def handler(request):
            sent.append(1)
            return chat_response('Unaudited answer.')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            class Researcher:
                def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
                async def conduct_research(self):
                    started = asyncio.Event()
                    async def survivor():
                        started.set()
                        try:
                            await asyncio.sleep(1)
                        except asyncio.CancelledError:
                            await asyncio.sleep(.05)
                        attempted.append(1)
                        try:
                            await create_chat_completion(messages=[{'role': 'user', 'content': 'late'}],
                                model=w.MODEL, llm_provider='openai', max_tokens=8000,
                                llm_kwargs=offline_kwargs(client, reasoning_effort='high'))
                        except w.SDKStopped:
                            denied.append(1)
                        finally:
                            finished.set()
                    asyncio.create_task(survivor())
                    await started.wait()
                    raise w.BudgetStop('Research allowance closed')
                async def write_report(self, **kwargs): pytest.fail('unsafe cleanup must not synthesize')
            with w._runtime({}, a, captures):
                with pytest.raises(w.SDKStopped):
                    await w.research({'prompt': 'Q', 'source_identity': {}}, a, Researcher, captures)
            # Deliberately let the late task run AFTER the runtime context exits.
            await asyncio.wait_for(finished.wait(), 5)
    asyncio.run(go())
    assert attempted == [1] and denied == [1]
    assert sent == [], 'no original/unpatched SDK dispatch is allowed after unsafe cleanup'
    assert a.snapshot()['quarantined']


@gpt_runtime
@pytest.mark.parametrize(('answer', 'reason'), [
    ('word ' * 701 + '[source](https://example.test/retrieved)', None),
    ('Claim [proof](https://fabricated.invalid/article).', 'unretrieved_citation'),
    ('Unsupported answer without links.', 'missing_citations'),
], ids=['uncapped-valid', 'fabricated-url', 'no-citations'])
def test_real_writer_preserves_paid_answer_before_validation_and_lists_allowed_sources(tmp_path, monkeypatch, answer, reason):
    """Actual upstream writer/LangChain/mock HTTP; no paid requests or URL repair."""
    import hashlib
    from gpt_researcher import GPTResearcher
    w = worker()
    a = audit(tmp_path, max_research_rounds=1)
    captures, sent = [], []
    request = {'protocol_version': w.PROTOCOL_VERSION, 'job_key': 'a' * 64,
               'worker_id': 'b' * 32, 'prompt': 'Original question',
               'source_identity': {'source_commit': 'offline-pinned'}, 'settings': a.settings}
    async def offline_conduct(self, **kwargs):
        self.research_sources = [{'url': 'https://example.test/retrieved'}]
        # This quoted bibliography URL is NOT a retrieved resource. The exact
        # retrieved URL is absent from the summary, as upstream can produce.
        return 'Summary quotes a bibliography: https://doi.org/10.1234/unretrieved'
    monkeypatch.setattr(GPTResearcher, 'conduct_research', offline_conduct)
    def handler(http_request):
        data = json.loads(http_request.content)
        sent.append(data)
        prompt = data['messages'][-1]['content']
        assert 'Verified retrieved source URLs (only these may be cited):' in prompt
        inventory = prompt.split('Verified retrieved source URLs (only these may be cited):\n', 1)[1].split('\n\nResearch evidence', 1)[0]
        assert json.loads(inventory) == ['https://example.test/retrieved']
        assert 'https://doi.org/10.1234/unretrieved' not in inventory
        assert 'quoted or bibliographic URLs not in the manifest are unverified' in prompt
        assert 'None words' not in prompt and '600 words' not in prompt and '1200 words' not in prompt
        assert w._input_bound(data['messages']) <= a.settings['max_input_tokens']
        return chat_response(answer, completion_tokens=1000)
    original_extract = w.extract_result
    def checked_extract(*args, **kwargs):
        receipt = json.loads((tmp_path / 'final-answer.json').read_text())
        assert receipt['text'] == answer
        assert receipt['status'] == 'unvalidated'
        assert receipt['request_sha256'] == w.request_digest(request)
        assert receipt['source_identity'] == request['source_identity']
        assert receipt['usage']['successful_calls'] == 1
        return original_extract(*args, **kwargs)
    monkeypatch.setattr(w, 'extract_result', checked_extract)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            route_providers(monkeypatch, client)
            with w._runtime({}, a, captures) as cls:
                return await w.research(request, a, cls, captures)
    if reason:
        with pytest.raises(ValueError) as exc:
            asyncio.run(go())
        assert exc.value.diagnostic['code'] == reason
        assert 'fabricated.invalid' not in str(exc.value)
    else:
        assert asyncio.run(go())['text'] == answer
    receipt = json.loads((tmp_path / 'final-answer.json').read_text())
    assert receipt['text'] == answer
    assert receipt['text_sha256'] == hashlib.sha256(answer.encode()).hexdigest()
    assert receipt['job_key'] == request['job_key'] and receipt['worker_id'] == request['worker_id']
    assert receipt['protocol_version'] == w.PROTOCOL_VERSION
    assert receipt['usage']['known_cost_usd'] == pytest.approx(.0102)
    assert receipt['usage']['unknown_cost'] is False
    assert receipt['status'] == ('rejected' if reason else 'validated')
    assert receipt['validation']['code'] == (reason or 'passed')
    assert len(sent) == 1, 'validation must never request a paid repair or fallback'


def test_large_source_manifest_keeps_whole_urls_and_bounded_evidence(tmp_path):
    w = worker()
    a = audit(tmp_path, max_research_rounds=1)
    sources = [{'url': f'https://example.test/item/{i}?q=' + 'x' * 400} for i in range(500)]
    captures, observed = [], {}
    class Researcher:
        def __init__(self, **kwargs):
            self.role = kwargs.get('role')
            self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
        async def conduct_research(self):
            captures.append({'context': 'Actual evidence. ' + '{"x":"v"}\n' * 6000, 'sources': sources})
        async def write_report(self, ext_context, custom_prompt):
            messages = [{'role': 'system', 'content': self.role},
                        {'role': 'user', 'content': custom_prompt + '\n\nContext: ' + ext_context}]
            full = messages[-1]['content']
            inventory = full.split('Verified retrieved source URLs (only these may be cited):\n', 1)[1].split('\n\nResearch evidence', 1)[0]
            urls = json.loads(inventory)
            assert 0 < len(urls) < len(sources)
            assert all(url in [s['url'] for s in sources] for url in urls)
            assert 'Actual evidence.' in full
            assert w._input_bound(messages) <= 64000
            observed['urls'] = urls
            return f"Finding [source]({urls[0]})."
        def get_costs(self): return 0.
    result = asyncio.run(w.research({'prompt': 'Q', 'source_identity': {}}, a, Researcher, captures))
    assert result['citations'][0]['url'] == observed['urls'][0]
    assert len(result['raw']['retrieved_sources']) == len(sources)


def test_worker_validation_failure_is_diagnostic_preserved_and_terminal(tmp_path, monkeypatch, isolated_process_state):
    from contextlib import contextmanager
    from crest.providers import gpt_researcher as p
    w = worker()
    output = tmp_path / 'gpt-researcher-output'
    request = {'protocol_version': w.PROTOCOL_VERSION, 'job_key': 'a' * 64, 'worker_id': 'b' * 32,
               'prompt': 'Q', 'settings': p.public_settings({'max_research_rounds': 1}),
               'source_identity': {}, 'output_dir': str(output)}
    path, result_path = tmp_path / 'gpt-researcher-request.json', tmp_path / 'gpt-researcher-result.json'
    path.write_text(json.dumps(request))
    monkeypatch.setattr(p, 'identity_metadata', lambda settings: {})
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-placeholder')
    calls = []
    @contextmanager
    def runtime(settings, a, captures):
        class Researcher:
            def __init__(self, **kwargs): self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
            async def conduct_research(self):
                captures.append({'context': 'Evidence.', 'sources': [{'url': 'https://example.test/real'}]})
            async def write_report(self, **kwargs):
                calls.append('synthesis')
                token = a.before(options())
                a.after(token, response=response())
                return 'Claim [proof](https://fabricated.invalid/article).'
            def get_costs(self): return 0.
        yield Researcher
    monkeypatch.setattr(w, '_runtime', runtime)
    envelope = w.run(path, result_path)
    assert envelope['status'] == 'failed'
    assert envelope['validation_error']['code'] == 'unretrieved_citation'
    assert 'fabricated.invalid' not in envelope['error']
    assert envelope['usage']['known_cost_usd'] == pytest.approx(.0004)
    assert json.loads((output / 'final-answer.json').read_text())['status'] == 'rejected'
    with pytest.raises(ValueError, match='Existing result'):
        w.run(path, result_path)
    assert calls == ['synthesis']


@pytest.mark.parametrize('text', [
    'Claim **[source](https://example.test/a)**.',
    'Claim *[source](https://example.test/a)*.',
    'Claim ~~[source](https://example.test/a)~~.',
    'Claim [A](https://example.test/a),[B](https://example.test/b).',
    'Claim [A](https://example.test/a)[B](https://example.test/b).',
    'Claim **[A](https://example.test/a)**;*[B](https://example.test/b)*.',
])
def test_markdown_destination_boundaries_do_not_swallow_valid_citations(text):
    sources = [{'url': 'https://example.test/a'}, {'url': 'https://example.test/b'}]
    result = worker().extract_result(text, sources, {'cost_usd': .1}, {}, {})
    expected = sources if 'https://example.test/b' in text else sources[:1]
    assert [s['url'] for s in result['citations']] == [s['url'] for s in expected]


@pytest.mark.parametrize('url', [
    'https://en.wikipedia.org/wiki/Jeopardy!',
    'https://example.test/article.',
    'https://example.test/search?q=Wow!',
])
@pytest.mark.parametrize('render', ['[source]({url})', '**[source]({url})**', '<{url}>'])
def test_delimited_citation_keeps_real_terminal_url_punctuation(url, render):
    text = 'Claim ' + render.format(url=url) + '.'
    result = worker().extract_result(text, [{'url': url}], {'cost_usd': .1}, {}, {})
    assert result['citations'][0]['url'] == url
    for neighbor in ['https://fabricated.invalid/no', url + '?fabricated=1']:
        with pytest.raises(ValueError, match='not a retrieved source'):
            worker().extract_result(text + f'[bad]({neighbor})', [{'url': url}], {'cost_usd': .1}, {}, {})


@gpt_runtime
@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
@pytest.mark.parametrize('override', [
    {'model': 'unpriced-model'},
    {'messages': [{'role': 'user', 'content': 'x' * 100000}]},
    {'max_completion_tokens': 100000},
    {'reasoning_effort': 'low'},
    {'service_tier': 'priority'},
    {'tools': [{'type': 'function', 'function': {'name': 'unpriced'}}]},
], ids=['model', 'messages', 'tokens', 'effort', 'tier', 'tools'])
def test_sdk_extra_body_cannot_override_audited_request(tmp_path, asynchronous, override):
    import openai
    w, a, sent = worker(), audit(tmp_path), []
    def handler(request):
        sent.append(json.loads(request.content))
        return chat_response('Offline.')
    params = dict(model=w.MODEL, messages=[{'role': 'user', 'content': 'Q'}],
                  max_completion_tokens=100, extra_body=override)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with openai.AsyncOpenAI(api_key='offline-test-placeholder', http_client=http) as client:
                with w._runtime({}, a, []):
                    with pytest.raises(w.SDKStopped): await client.chat.completions.create(**params)
    if asynchronous:
        asyncio.run(go())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with openai.OpenAI(api_key='offline-test-placeholder', http_client=http) as client:
                with w._runtime({}, a, []):
                    with pytest.raises(w.SDKStopped): client.chat.completions.create(**params)
    assert sent == [], 'extra_json must be rejected BEFORE transport and reservation'
    assert not a.snapshot()['events'] and not a.snapshot()['in_flight']
    with pytest.raises(w.SDKStopped): a.before(options())


@pytest.mark.parametrize(('boundary', 'disk_failure'), [
    ('self.events.append(event)', False),
    ('self.pending.pop(token)', False),
    ('self.persist()', False),
    ('self.pending[token] = reserved_event', True),
    ('self.events.pop()', True),
], ids=['record-charge', 'release-reservation', 'persist-charge', 'restore-reservation', 'remove-rolled-back-charge'])
def test_sigterm_during_settlement_never_erases_paid_exposure(tmp_path, monkeypatch, boundary, disk_failure):
    import inspect
    import signal
    w, a = worker(), audit(tmp_path)
    token = a.before(options())
    original_reserved = a.snapshot()['reserved_usd']
    # Trace injection names the financial transition operation, not a fixed line
    # number. The actual worker-style raising SIGTERM handler interrupts it.
    lines, first = inspect.getsourcelines(w.UsageAudit._settle)
    target = next(first + i for i, line in enumerate(lines) if line.strip() == boundary)
    if disk_failure:
        persist, attempts = a.persist, []
        def failing_once():
            attempts.append(1)
            if len(attempts) == 1: raise OSError('offline disk failure')
            return persist()
        monkeypatch.setattr(a, 'persist', failing_once)
    fired = []
    def terminated(signum, frame): raise w.SDKStopped('Worker terminated')
    def trace(frame, event, arg):
        if (not fired and event == 'line' and frame.f_code is w.UsageAudit._settle.__code__
                and frame.f_lineno == target):
            fired.append(1)
            os.kill(os.getpid(), signal.SIGTERM)
        return trace
    previous_signal, previous_trace = signal.getsignal(signal.SIGTERM), sys.gettrace()
    try:
        signal.signal(signal.SIGTERM, terminated)
        sys.settrace(trace)
        with pytest.raises(w.SDKStopped): a.after(token, response=response())
    finally:
        sys.settrace(previous_trace)
        signal.signal(signal.SIGTERM, previous_signal)
    assert fired == [1]
    for state in [a.snapshot(), json.loads(a.path.read_text())]:
        assert state['terminal_failure']
        if state['unknown_cost']:
            assert state['reserved_usd'] >= original_reserved
        else:
            assert state['known_cost_usd'] == pytest.approx(.0004)
        assert state['upper_bound_usd'] >= .0004, 'must never persist apparently known zero'
    with pytest.raises(w.SDKStopped): a.before(options())


@pytest.mark.parametrize(('text', 'url'), [
    ('Claim [source][s].\n\n[s]: https://example.test/a!', 'https://example.test/a!'),
    (r'Claim [source](https://example.test/paper_\(a\)).', 'https://example.test/paper_(a)'),
    ('Claim [source](HTTPS://EXAMPLE.TEST/a).', 'https://example.test/a'),
    ('Claim [source](https&#58;//example.test/a).', 'https://example.test/a'),
    ('Claim [evidence](https://example.test/paper_(a)?x=1&amp;y=2).', 'https://example.test/paper_(a)?x=1&y=2'),
    ("Finding [source](https://en.wikipedia.org/wiki/McDonald's).", "https://en.wikipedia.org/wiki/McDonald's"),
    ("Finding [source](https://en.wikipedia.org/wiki/O'Reilly_Media).", "https://en.wikipedia.org/wiki/O'Reilly_Media"),
    ('Claim: https://example.test/evidence.', 'https://example.test/evidence'),  # bare URL trims prose period
])
def test_commonmark_destinations_match_exact_retrieved_resources(text, url):
    assert worker().extract_result(text, [{'url': url}], {'cost_usd': .1}, {}, {})['citations'][0]['url'] == url


@pytest.mark.parametrize(('destination', 'matched_resource'), [
    ('&y=2', 0), ('&amp;y=2', 0), ('&amp;amp;y=2', 1), ('&amp;amp;amp;y=2', 2),
])
@pytest.mark.parametrize('resource', [0, 1, 2])
def test_entity_decoding_occurs_once_at_markdown_boundary(destination, matched_resource, resource):
    url = 'https://example.test/a?x=1' + ['&y=2', '&amp;y=2', '&amp;amp;y=2'][resource]
    text = f'[source](https://example.test/a?x=1{destination})'
    if resource == matched_resource:
        assert worker().extract_result(text, [{'url': url}], {'cost_usd': .1}, {}, {})['citations'][0]['url'] == url
    else:
        with pytest.raises(ValueError, match='not a retrieved source'):
            worker().extract_result(text, [{'url': url}], {'cost_usd': .1}, {}, {})


@pytest.mark.parametrize('mode', ['newest-fills-context', 'many-short-captures', 'newest-url-too-large'])
def test_writer_manifest_and_visible_evidence_select_same_captures(tmp_path, mode):
    import re
    w = worker()
    a = audit(tmp_path, max_research_rounds=1)
    captures = []
    sources = [{'url': f'https://example.test/source/{i}?q=' + 'x' * 400} for i in range(100)]
    if mode == 'newest-url-too-large': sources[-1]['url'] += 'z' * 100000
    class Researcher:
        def __init__(self, **kwargs):
            self.role = kwargs.get('role')
            self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=8000)
        async def conduct_research(self):
            for i, source in enumerate(sources):
                tail = 'Source-specific findings. ' * (6000 if i == 99 and mode == 'newest-fills-context' else 5)
                captures.append({'context': f'EVIDENCE_ID_{i}\n' + tail, 'sources': [source]})
        async def write_report(self, ext_context, custom_prompt):
            inventory, evidence = ext_context.split('Verified retrieved source URLs (only these may be cited):\n', 1)[1].split('\n\nResearch evidence', 1)
            urls = json.loads(inventory)
            allowed_ids = {int(re.search(r'/source/(\d+)', url).group(1)) for url in urls}
            visible_ids = {int(i) for i in re.findall(r'EVIDENCE_ID_(\d+)', evidence)}
            assert visible_ids, 'do not synthesize an inventory without evidence'
            assert visible_ids <= allowed_ids, 'every visible capture must retain its authorized source'
            assert allowed_ids <= visible_ids, 'do not authorize unrelated sources without their evidence'
            expected_first = 98 if mode == 'newest-url-too-large' else 99
            assert expected_first in visible_ids
            assert w._input_bound([{'role': 'system', 'content': self.role},
                {'role': 'user', 'content': custom_prompt + '\n\nContext: ' + ext_context}]) <= 64000
            return f"Finding [source]({sources[expected_first]['url']})."
        def get_costs(self): return 0.
    result = asyncio.run(w.research({'prompt': 'Q', 'source_identity': {}}, a, Researcher, captures))
    assert result['citations'][0]['url'] == sources[98 if mode == 'newest-url-too-large' else 99]['url']


@pytest.mark.parametrize(('settings', 'effort'), [({}, 'high'), ({'reasoning_effort': 'high'}, 'high'),
                                                   ({'reasoning_effort': 'xhigh'}, 'xhigh')])
def test_selected_effort_controls_all_roles_and_audit_with_explicit_free_tools(tmp_path, settings, effort):
    w, a = worker(), audit(tmp_path, **settings)
    config = w.build_config(settings)
    assert config['REASONING_EFFORT'] == config['LLM_KWARGS']['reasoning_effort'] == effort
    assert all(config[k] == 'openai:gpt-6.1-sol' for k in ('FAST_LLM', 'SMART_LLM', 'STRATEGIC_LLM'))
    assert config['RETRIEVER'] == 'duckduckgo'
    assert config['CONTEXT_FILTER'] == 'keyword'
    assert 'TOTAL_WORDS' not in config
    assert config['LLM_KWARGS']['max_retries'] == 0
    assert config['IMAGE_GENERATION_ENABLED'] is False
    assert config['MCP_STRATEGY'] == 'disabled'
    opt = options(reasoning_effort='high')
    token = a.before(opt)
    assert opt.json_data['reasoning_effort'] == effort
    assert json.loads(a.path.read_text())['in_flight'][0]['reasoning_effort'] == effort
    a.after(token, response=response())
    assert a.snapshot()['events'][0]['reasoning_effort'] == effort
    assert a.snapshot()['reasoning_effort'] == effort


@gpt_runtime
@pytest.mark.parametrize('outcome', ['normal', 'exception', 'baseexception', 'quarantine'])
def test_xhigh_parser_extension_restores_exact_staticmethod_descriptor(tmp_path, monkeypatch, outcome):
    import inspect
    import openai
    from gpt_researcher import GPTResearcher
    from gpt_researcher.skills.deep_research import DeepResearchSkill
    from gpt_researcher.config.config import Config
    from gpt_researcher.llm_provider.generic.base import GenericLLMProvider
    from gpt_researcher.retrievers.duckduckgo.duckduckgo import Duckduckgo
    w, a = worker(), audit(tmp_path)
    original = inspect.getattr_static(Config, 'parse_reasoning_effort')
    original_learning = DeepResearchSkill.process_research_results
    for cls, name in [(Config, 'parse_reasoning_effort'), (openai.OpenAI, 'request'),
                      (openai.AsyncOpenAI, 'request'), (GenericLLMProvider, 'get_chat_response'),
                      (GPTResearcher, 'conduct_research'), (Duckduckgo, 'search'),
                      (DeepResearchSkill, 'process_research_results')]:
        monkeypatch.setattr(cls, name, inspect.getattr_static(cls, name))
    try:
        with w._runtime({}, a, []):
            patched = inspect.getattr_static(Config, 'parse_reasoning_effort')
            assert isinstance(patched, staticmethod)
            assert DeepResearchSkill.process_research_results is not original_learning
            assert Config.parse_reasoning_effort('xhigh') == 'xhigh'
            assert object.__new__(Config).parse_reasoning_effort('xhigh') == 'xhigh'
            for value in (None, 'low', 'medium', 'high'):
                assert Config.parse_reasoning_effort(value) == original.__func__(value)
            with pytest.raises(ValueError): Config.parse_reasoning_effort('unsupported')
            if outcome == 'exception': raise RuntimeError('offline context exit')
            if outcome == 'baseexception': raise w.SDKStopped('offline context exit')
            if outcome == 'quarantine': a.quarantine()
    except (RuntimeError, w.SDKStopped):
        if outcome not in ('exception', 'baseexception'): raise
    if outcome == 'quarantine':
        assert inspect.getattr_static(Config, 'parse_reasoning_effort') is patched
        assert DeepResearchSkill.process_research_results is not original_learning
        assert a.snapshot()['terminal_failure']
    else:
        assert inspect.getattr_static(Config, 'parse_reasoning_effort') is original
        assert DeepResearchSkill.process_research_results is original_learning
        with pytest.raises(ValueError): object.__new__(Config).parse_reasoning_effort('xhigh')


@gpt_runtime
@pytest.mark.parametrize('effort', ['xhigh', 'high'])
@pytest.mark.parametrize('outputs,reasoning', [(20, 0), (13000, 12000)], ids=['short', 'reasoning-over-8k'])
def test_real_upstream_roles_nested_followup_and_writer_send_selected_effort(
        tmp_path, monkeypatch, instant_backoff, effort, outputs, reasoning):
    from gpt_researcher import GPTResearcher
    from gpt_researcher.actions.agent_creator import choose_agent
    from gpt_researcher.utils.llm import create_chat_completion
    w = worker()
    a = audit(tmp_path, reasoning_effort=effort, max_research_rounds=2)
    captures, sent, rounds = [], [], []
    agent = json.dumps({'server': 'Research Agent', 'agent_role_prompt': 'Research evidence'})
    plan = json.dumps([{'query': 'offline nested question', 'researchGoal': 'Check evidence'}])
    answers = ['Fast evidence', agent, plan,
               json.dumps({'learnings': ['Observed'], 'followUpQuestions': ['Check conflicting evidence?']}),
               'Fast evidence', agent, plan, 'Finding [source](https://example.test/round/2).']
    async def offline_conduct(self, **kwargs):
        rounds.append(self.query)
        self.research_sources = [{'url': f'https://example.test/round/{len(rounds)}'}]
        cfg = self.cfg
        fast = asyncio.create_task(create_chat_completion(
            messages=[{'role': 'user', 'content': 'FAST nested evidence'}], model=cfg.fast_llm_model,
            llm_provider=cfg.fast_llm_provider, max_tokens=cfg.fast_token_limit, llm_kwargs=cfg.llm_kwargs))
        assert await fast == 'Fast evidence'
        nested = GPTResearcher(query='Nested SMART agent', config_path=str(a.path.with_name('config.json')), verbose=False)
        assert (await choose_agent('Nested SMART evidence', nested.cfg))[0] == 'Research Agent'
        assert (await self.deep_researcher.generate_search_queries('STRATEGIC plan', 1))[0]['query'] == 'offline nested question'
        return 'Evidence-backed finding for this capture.'
    monkeypatch.setattr(GPTResearcher, 'conduct_research', offline_conduct)
    def handler(request):
        data = json.loads(request.content)
        sent.append(data)
        assert data['model'] == 'gpt-6.1-sol' and data['reasoning_effort'] == effort
        if len(sent) == 1:
            return httpx.Response(429, json={'error': {'message': 'offline rate limit', 'type': 'rate_limit'}})
        return chat_response(answers.pop(0), completion_tokens=outputs, reasoning_tokens=reasoning)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            route_providers(monkeypatch, client)
            with w._runtime({}, a, captures) as cls:
                return await w.research({'prompt': 'Original task', 'source_identity': {}}, a, cls, captures)
    result = asyncio.run(go())
    assert not answers and len(sent) == 9 and len(rounds) == 2
    assert instant_backoff == [1.]  # the one 429 waits the worker's fixed backoff
    assert result['raw']['research_rounds'] == 2 and result['citations'][0]['url'].endswith('/round/2')
    assert a.snapshot()['successful_calls'] == 8 and a.snapshot()['retry_calls'] == 1
    assert all(e['reasoning_effort'] == effort for e in a.snapshot()['events'])
    assert all(data['max_completion_tokens'] == 32000 for data in sent)
    completed = [e for e in a.snapshot()['events'] if e['status'] == 'completed']
    assert all(e['output_bound'] == 32000 for e in completed)
    assert all(e['raw_usage']['completion_tokens_details']['reasoning_tokens'] == reasoning for e in completed)
    assert result['cost_usd'] == pytest.approx(1.0416 if outputs == 13000 else .0032)
    assert not a.snapshot()['unknown_cost'] and not a.snapshot()['terminal_failure']
    assert {e['phase'] for e in a.snapshot()['events']} == {'research', 'synthesis'}


@gpt_runtime
def test_default_writer_timeout_preserves_longer_research_and_drain_headroom(tmp_path, monkeypatch):
    from gpt_researcher.llm_provider.generic.base import GenericLLMProvider
    w, a = worker(), audit(tmp_path)
    config = w.build_config({})
    monkeypatch.setenv('LLM_TIMEOUT', '180')  # A stale upstream fallback must not shorten this job.
    provider = GenericLLMProvider.from_provider('openai', model=w.MODEL,
        api_key='offline-test-placeholder', **config['LLM_KWARGS'])
    assert provider.llm_timeout == 600
    assert provider.llm.request_timeout == 600
    assert a.phase_headroom == 605
    assert a.deadline - a.research_deadline == pytest.approx(1210)
    assert a.settings['timeout_seconds'] - 2 * a.phase_headroom == 4190
    assert a.settings['budget_usd'] == 4 and a.settings['synthesis_reserve_usd'] == .5


@gpt_runtime
@pytest.mark.parametrize(('call_timeout', 'outcome'), [(.18, 'timeout'), (1.2, 'success'), (1.2, 'thinking-only')])
def test_real_writer_slow_response_and_thinking_only_fail_closed(tmp_path, monkeypatch, call_timeout, outcome):
    from gpt_researcher import GPTResearcher
    w = worker()
    a = audit(tmp_path, call_timeout_seconds=call_timeout, timeout_seconds=5.4, max_research_rounds=1,
              synthesis_max_completion_tokens=16000)  # Preserve the historical writer-limit regression.
    captures, sent = [], []
    monkeypatch.setenv('LLM_TIMEOUT', '.18')
    async def offline_conduct(self, **kwargs):
        self.research_sources = [{'url': 'https://example.test/evidence'}]
        return 'Evidence-backed content.'
    monkeypatch.setattr(GPTResearcher, 'conduct_research', offline_conduct)
    async def handler(request):
        data = json.loads(request.content)
        sent.append(data)
        assert data['reasoning_effort'] == 'high' and data['max_completion_tokens'] == 16000
        await asyncio.sleep(.22)  # Scaled beyond the old .18 deadline, well inside 1.2.
        thinking_only = outcome == 'thinking-only'
        outputs = 16000 if thinking_only else 1000
        return chat_response('' if thinking_only else 'Finding [source](https://example.test/evidence).',
            completion_tokens=outputs, finish_reason='length' if thinking_only else 'stop',
            reasoning_tokens=16000 if thinking_only else 500)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            route_providers(monkeypatch, client)
            return await w.research({'prompt': 'Q', 'source_identity': {}}, a, cls, captures)
    # Match production: runtime guards surround asyncio.run and its shutdown of
    # any shielded settlement task, not just the parent coroutine's lifetime.
    with w._runtime({}, a, captures) as cls:
        if outcome == 'success':
            assert asyncio.run(go())['cost_usd'] == pytest.approx(.0102)
            assert not a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] == 0
        else:
            with pytest.raises(w.SDKStopped): asyncio.run(go())
            assert a.snapshot()['terminal_failure']
            if outcome == 'timeout':
                assert a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] > 0
                assert a.snapshot()['cost_usd'] is None
            else:
                assert a.snapshot()['cost_usd'] == pytest.approx(.1602)
                assert not a.snapshot()['unknown_cost'] and a.snapshot()['reserved_usd'] == 0
    assert len(sent) == 1, 'neither timeout nor reasoning exhaustion authorizes another paid writer call'


def test_settlement_uses_same_price_constants_as_reservations(tmp_path, monkeypatch):
    w = worker()
    monkeypatch.setattr(w, 'PRICES', {'input': 4., 'cache_read': .25, 'cache_write': 3., 'output': 12.})
    a = audit(tmp_path, max_input_tokens=1000, max_completion_tokens=100, synthesis_max_completion_tokens=100)
    token = a.before(options())
    a.after(token, response=response(prompt_tokens=100, completion_tokens=20,
            prompt_tokens_details={'cached_tokens': 30, 'cache_write_tokens': 20}))
    # 50 regular input*4 + 30 cached*.25 + 20 written*3 + 20 output*12, per million.
    assert a.snapshot()['known_cost_usd'] == pytest.approx(.0005075)
    assert a.snapshot()['reserved_usd'] == 0


@pytest.mark.parametrize('boundary', ['self.pending[token] = reserved_event', 'self.events.pop()'])
@pytest.mark.parametrize('interruption', ['sigterm', 'baseexception'])
def test_interrupted_rollback_redelivery_reconciles_one_charge_and_other_admitted_calls(
        tmp_path, monkeypatch, boundary, interruption):
    import inspect
    import signal
    w, a = worker(), audit(tmp_path)
    token, other = a.before(options()), a.before(options())
    receipt = response()
    persist, writes = a.persist, []
    def fail_once():
        writes.append(1)
        if len(writes) == 1: raise OSError('offline interrupted settlement write')
        persist()
    monkeypatch.setattr(a, 'persist', fail_once)
    lines, first = inspect.getsourcelines(w.UsageAudit._settle)
    target = next(first + i for i, line in enumerate(lines) if line.strip() == boundary)
    fired = []
    def terminated(signum, frame): raise w.SDKStopped('Worker terminated')
    def trace(frame, event, arg):
        if (not fired and event == 'line' and frame.f_code is w.UsageAudit._settle.__code__
                and frame.f_lineno == target):
            fired.append(1)
            if interruption == 'sigterm': os.kill(os.getpid(), signal.SIGTERM)
            else: raise BaseException('offline rollback interruption')
        return trace
    previous_signal, previous_trace = signal.getsignal(signal.SIGTERM), sys.gettrace()
    try:
        signal.signal(signal.SIGTERM, terminated)
        sys.settrace(trace)
        with pytest.raises(BaseException): a.after(token, response=receipt)
    finally:
        sys.settrace(previous_trace)
        signal.signal(signal.SIGTERM, previous_signal)
    assert fired == [1] and a.snapshot()['terminal_failure']
    assert other in a.pending
    # Admission remains terminal, but already-admitted requests MUST settle.
    with pytest.raises(w.SDKStopped): a.before(options())
    a.after(other, response=response())
    a.after(token, response=receipt)  # Same receipt, no new SDK request.
    assert a.snapshot()['known_cost_usd'] == pytest.approx(.0008), 'redelivery must not append a third charge'
    a.after(token, response=receipt)  # A normal duplicate must also be idempotent.
    a.after(other, response=response())
    for state in [a.snapshot(), json.loads(a.path.read_text())]:
        assert state['known_cost_usd'] == pytest.approx(.0008)
        assert state['successful_calls'] == 2
        assert len(state['events']) == len({e['request_id'] for e in state['events']}) == 2
        assert not state['unknown_cost'] and state['reserved_usd'] == 0
        assert state['terminal_failure'], 'reconciling usage never reopens paid admission'


def test_completed_settlement_repeat_is_idempotent_without_closing_admission(tmp_path):
    a = audit(tmp_path)
    token = a.before(options())
    first = a.after(token, response=response())
    assert a.after(token, response=response()) == first
    assert a.snapshot()['known_cost_usd'] == pytest.approx(.0004)
    assert a.snapshot()['successful_calls'] == 1 and not a.snapshot()['terminal_failure']
    other = a.before(options())
    a.after(other, response=response())
    assert a.snapshot()['known_cost_usd'] == pytest.approx(.0008)


@pytest.mark.parametrize('conflict', ['usage', 'outcome'])
def test_conflicting_same_request_receipt_cannot_reprice_known_charge(tmp_path, conflict):
    w, a = worker(), audit(tmp_path)
    token, other = a.before(options()), a.before(options())
    a.after(token, response=response())
    with pytest.raises(w.SDKStopped):
        if conflict == 'usage': a.after(token, response=response(completion_tokens=40))
        else: a.after(token, error=TimeoutError())
    a.after(other, response=response())
    state = json.loads(a.path.read_text())
    assert state['known_cost_usd'] == pytest.approx(.0008)
    assert len(state['events']) == 2 and not state['unknown_cost']
    with pytest.raises(w.SDKStopped): a.before(options())


def test_unknown_settlement_repeat_retains_one_unresolved_reservation(tmp_path):
    w, a = worker(), audit(tmp_path)
    token, other = a.before(options()), a.before(options())
    reserved = a.pending[token]['reserved_usd']
    a.after(token, error=TimeoutError())
    a.after(token, error=TimeoutError())
    a.after(other, response=response())
    state = json.loads(a.path.read_text())
    assert state['known_cost_usd'] == pytest.approx(.0004)
    assert state['cost_usd'] is None and state['reserved_usd'] == reserved
    assert state['failed_calls'] == state['successful_calls'] == 1
    assert len(state['events']) == 2 and state['unknown_cost']
    with pytest.raises(w.SDKStopped): a.before(options())


def test_incomplete_paid_response_repeat_stays_terminal_and_is_charged_once(tmp_path):
    w, a = worker(), audit(tmp_path)
    token = a.before(options())
    receipt = response()
    receipt.choices[0].finish_reason = 'length'
    receipt.choices[0].message.content = ''
    for _ in range(2):
        with pytest.raises(w.SDKStopped): a.after(token, response=receipt)
    state = json.loads(a.path.read_text())
    assert state['known_cost_usd'] == pytest.approx(.0004)
    assert state['successful_calls'] == 1 and len(state['events']) == 1
    assert not state['unknown_cost'] and state['terminal_failure']


@pytest.mark.parametrize('reference,target', [(4., 3.2), (10., 3.2), (.1, 3.2)])
def test_soft_budget_reference_does_not_impose_hard_configuration_ceiling(reference, target):
    settings = worker().normalize_settings({'budget_cap': 'soft', 'budget_usd': reference,
                                             'budget_target_usd': target})
    assert settings['budget_cap'] == 'soft' and settings['budget_usd'] == reference
    assert worker().normalize_settings({})['budget_cap'] == 'hard'


@pytest.mark.parametrize('phase', ['research', 'synthesis'])
@pytest.mark.parametrize('spent', [3.99, 4.25])
def test_soft_admission_tracks_projected_and_known_overruns_without_stopping(tmp_path, phase, spent):
    a = audit(tmp_path, budget_cap='soft')
    a.events.append({'status': 'completed', 'cost_usd': spent, 'input_tokens': 0, 'output_tokens': 0})
    a.phase = phase
    token = a.before(options(max_completion_tokens=8000))
    projected = a.snapshot()
    assert projected['upper_bound_usd'] > 4 and projected['budget_cap'] == 'soft'
    assert projected['projected_budget_overrun_usd'] == pytest.approx(projected['upper_bound_usd'] - 4)
    assert projected['budget_overrun_usd'] == pytest.approx(max(0., spent - 4))
    assert projected['in_flight'] and not projected['research_stopped'] and not projected['terminal_failure']
    a.after(token, response=response())
    final = json.loads(a.path.read_text())
    assert final['known_cost_usd'] == pytest.approx(spent + .0004)
    assert not final['unknown_cost'] and final['reserved_usd'] == 0


@pytest.mark.parametrize('cap', ['hard', 'auto'])
def test_hard_and_auto_still_refuse_projected_overrun(tmp_path, cap):
    a = audit(tmp_path, budget_cap=cap)
    a.phase = 'synthesis'
    a.events.append({'status': 'completed', 'cost_usd': 3.99, 'input_tokens': 0, 'output_tokens': 0})
    with pytest.raises(worker().BudgetStop):
        a.before(options(max_completion_tokens=8000))
    assert not a.snapshot()['in_flight']
    with pytest.raises(ValueError): worker().normalize_settings({'budget_cap': cap, 'budget_usd': 4.1})


@pytest.mark.parametrize('cap,guard', [('default', 'time'), ('soft', 'time'), ('soft', 'input'), ('soft', 'model')])
def test_admission_refuses_after_time_cutoff_and_soft_budget_keeps_non_dollar_guards(tmp_path, cap, guard):
    import time
    w = worker()
    a = audit(tmp_path) if cap == 'default' else audit(tmp_path, budget_cap=cap)
    opts = options()
    if guard == 'time': a.research_deadline = time.monotonic() - 1 if cap == 'default' else 0
    if guard == 'input': opts.json_data['messages'][0]['content'] = 'x' * 64000
    if guard == 'model': opts.json_data['model'] = 'unpriced-model'
    with pytest.raises(w.BudgetStop if cap == 'default' else (w.BudgetStop, w.SDKStopped)): a.before(opts)
    assert a.snapshot()['in_flight'] == []
    if cap == 'default':
        assert a.snapshot()['events'] == []


@gpt_runtime
@pytest.mark.parametrize('outcome', ['success', 'empty', 'missing_usage', 'timeout'])
def test_real_soft_upstream_overrun_preserves_settlement_and_terminal_circuit(tmp_path, monkeypatch, outcome):
    from gpt_researcher.utils.llm import create_chat_completion
    w, a = worker(), audit(tmp_path, budget_cap='soft')
    a.events.append({'status': 'completed', 'cost_usd': 4.25, 'input_tokens': 0, 'output_tokens': 0})
    sent = []
    async def no_sleep(*args): pass
    monkeypatch.setattr(asyncio, 'sleep', no_sleep)
    def handler(request):
        data = json.loads(request.content)
        assert data['reasoning_effort'] == 'high'
        sent.append(data)
        if outcome == 'timeout': raise httpx.ReadTimeout('offline timeout', request=request)
        return chat_response('' if outcome == 'empty' else 'Answer', missing_usage=outcome == 'missing_usage')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with w._runtime({}, a, []):
                for phase in ('research', 'synthesis'):
                    a.phase = phase
                    async def call():
                        return await create_chat_completion(messages=[{'role': 'user', 'content': 'Q'}],
                            model=w.MODEL, llm_provider='openai', max_tokens=8000,
                            reasoning_effort='xhigh', llm_kwargs=offline_kwargs(client))
                    if outcome == 'success': assert await call() == 'Answer'
                    else:
                        with pytest.raises(w.SDKStopped): await call()
    asyncio.run(go())
    s = a.snapshot()
    assert len(sent) == (2 if outcome == 'success' else 1)
    assert s['budget_cap'] == 'soft' and s['budget_overrun_usd'] >= .25
    if outcome in ('timeout', 'missing_usage'):
        assert s['unknown_cost'] and s['reserved_usd'] > 0 and s['terminal_failure']
    else:
        assert s['known_cost_usd'] == pytest.approx(4.2508 if outcome == 'success' else 4.2504)
        assert not s['unknown_cost'] and s['reserved_usd'] == 0
        assert bool(s['terminal_failure']) == (outcome == 'empty')


@gpt_runtime
@pytest.mark.parametrize('settings,spent,writer_tokens,expected_cost', [
    pytest.param({}, 4.25, 20, 4.2508, id='standard-reserve'),
    pytest.param({'budget_usd': .10, 'budget_target_usd': .10, 'synthesis_reserve_usd': .05},
                 .06, 12000, .1806, id='low-writer-reserve'),
])
def test_real_soft_writer_overrun_keeps_target_round_handoff_and_source_validation(
        tmp_path, monkeypatch, settings, spent, writer_tokens, expected_cost):
    from gpt_researcher import GPTResearcher
    from gpt_researcher.utils.llm import create_chat_completion
    w, a = worker(), audit(tmp_path, budget_cap='soft', **settings)
    a.events.append({'status': 'completed', 'cost_usd': spent, 'input_tokens': 0, 'output_tokens': 0})
    captures, rounds, sent = [], [], []
    async def conduct(self, **kwargs):
        rounds.append(self.query)
        await create_chat_completion(messages=[{'role': 'user', 'content': 'Q'}],
            model=w.MODEL, llm_provider='openai', max_tokens=8000, reasoning_effort='xhigh')
        self.research_sources = [{'url': 'https://example.test/evidence'}]
        return 'A source-backed finding.'
    monkeypatch.setattr(GPTResearcher, 'conduct_research', conduct)
    def handler(request):
        sent.append(json.loads(request.content))
        outputs = writer_tokens if a.phase == 'synthesis' else 20
        if a.phase == 'synthesis':
            assert a.snapshot()['reserved_usd'] >= .32
            assert a.snapshot()['projected_budget_overrun_usd'] > 0
        return chat_response('Finding [source](https://example.test/evidence).', completion_tokens=outputs)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            route_providers(monkeypatch, client)
            with w._runtime({}, a, captures) as cls:
                return await w.research({'prompt': 'Q', 'source_identity': {}}, a, cls, captures)
    out = asyncio.run(go())
    assert rounds == ['Q'] and out['raw']['research_rounds'] == 1
    assert len(sent) == 2 and sent[-1]['max_completion_tokens'] == 32000
    assert out['cost_usd'] == pytest.approx(expected_cost) and out['citations'][0]['url'].endswith('/evidence')
    assert out['usage']['budget_cap'] == 'soft' and not out['usage']['unknown_cost']
    assert any('soft' in warning.lower() and 'exceed' in warning.lower() for warning in out['warnings'])
    draft = json.loads((tmp_path / 'final-answer.json').read_text())
    assert draft['status'] == 'validated' and draft['settings']['budget_cap'] == 'soft'
    assert draft['usage']['budget_cap'] == 'soft'


@pytest.mark.parametrize('cap', ['soft', 'hard', 'auto'])
def test_low_writer_reserve_is_advisory_only_for_soft(cap):
    settings = {'budget_cap': cap, 'budget_usd': .10, 'budget_target_usd': .10,
                'synthesis_reserve_usd': .05}
    if cap == 'soft':
        normalized = worker().normalize_settings(settings)
        assert normalized['synthesis_reserve_usd'] == .05
        assert normalized['synthesis_max_completion_tokens'] == 32000
        assert normalized['max_input_tokens'] == 64000
    else:
        with pytest.raises(ValueError, match='reserve cannot cover'):
            worker().normalize_settings(settings)


def test_default_headroom_keeps_legacy_hard_and_reserves_bounded_32k_writer(tmp_path):
    w, a = worker(), audit(tmp_path)
    assert a.settings['budget_cap'] == 'hard'
    assert a.settings['budget_target_usd'] == 3.4 and a.settings['synthesis_reserve_usd'] == .5
    a.events.append({'status': 'completed', 'cost_usd': 2.89, 'input_tokens': 0, 'output_tokens': 0})
    # A small research request still fits below the new $2.90 research allowance.
    token = a.before(options())
    a.after(token, response=response())
    a.phase = 'synthesis'
    messages = [{'role': 'user', 'content': ''}]
    messages[0]['content'] = 'x' * (64000 - w._input_bound(messages))
    opts = options(messages=messages, max_completion_tokens=100000)
    a.before(opts)
    assert opts.json_data['max_completion_tokens'] == 32000
    assert a.snapshot()['reserved_usd'] == pytest.approx(.48)
    assert a.snapshot()['upper_bound_usd'] == pytest.approx(3.3704)


@gpt_runtime
@pytest.mark.parametrize('shape', ['short', 'text', 'list', 'cut-source-header', 'cut-learning-citation'])
def test_real_pinned_learning_prompt_fits_only_evidence_and_preserves_sources(tmp_path, monkeypatch, shape):
    import copy
    import gpt_researcher.skills.deep_research as deep
    w, a = worker(), audit(tmp_path, budget_cap='soft')
    source = 'https://example.test/source'
    first = f'Source: {source}\nTitle: Unicode evidence\nContent: Supported finding.\n'
    text = first + ('é漢😀 {"x":"v"}\\\t\n' * 7000)
    if shape == 'short': context = first
    elif shape == 'list': context = [first, text]
    elif shape == 'cut-source-header':
        context = first + '\nSource: https://example.test/cut-' + 'x' * 70000 + '\nTitle: too long\nContent: not included'
    elif shape == 'cut-learning-citation':
        context = first + '\n' + 'long finding ' * 7000 + ' [Source: https://example.test/cut-learning]\n'
    else: context = text
    before = copy.deepcopy(context)
    query = "Exact original 'query' 漢😀 with \\ and \"quotes\""
    pinned, sent = [], []
    async def record_prompt(**kwargs):
        pinned.extend(copy.deepcopy(kwargs['messages']))
        return '{}'
    def handler(request):
        data = json.loads(request.content)
        sent.append(data)
        assert data['model'] == w.MODEL and data['reasoning_effort'] == 'high'
        assert data['max_completion_tokens'] == 32000
        assert data['messages'][0] == pinned[0]
        assert data['messages'][1]['content'].startswith(pinned[1]['content'])
        retained = data['messages'][1]['content'][len(pinned[1]['content']):]
        assert first in retained and 'https://example.test/cut-' not in retained
        assert w._input_bound(data['messages']) <= 64000
        if shape == 'short': assert retained == first
        else: assert len(retained) < len(str(context))
        if shape == 'cut-learning-citation': assert 'long finding' not in retained
        return chat_response(json.dumps({'learnings': [{'insight': 'Supported finding.', 'sourceUrl': source}],
                                   'followUpQuestions': ['Check contrast?']}))
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            skill = object.__new__(deep.DeepResearchSkill)
            skill.researcher = SimpleNamespace(cfg=SimpleNamespace(strategic_llm_provider='openai',
                strategic_llm_model=w.MODEL, strategic_token_limit=32000, llm_kwargs=offline_kwargs(client)),
                add_costs=lambda value: None)
            with monkeypatch.context() as recording:
                recording.setattr(deep, 'create_chat_completion', record_prompt)
                await skill.process_research_results(query, '')
            with w._runtime({}, a, []):
                return await skill.process_research_results(query, context)
    out = asyncio.run(go())
    assert context == before and len(sent) == 1
    assert out['citations']['Supported finding.'] == source
    assert out['followUpQuestions'] == ['Check contrast?']
    assert not a.snapshot()['phase_stops'] and not a.snapshot()['terminal_failure']
    assert a.snapshot()['known_cost_usd'] == pytest.approx(.0004)


@gpt_runtime
@pytest.mark.parametrize('operation', ['fixed-learning-query', 'unrelated-sdk-call'])
def test_learning_fit_does_not_shorten_fixed_prompts_or_unrelated_calls(tmp_path, operation):
    from gpt_researcher.skills.deep_research import DeepResearchSkill
    from gpt_researcher.utils.llm import create_chat_completion
    w, a = worker(), audit(tmp_path, budget_cap='soft')
    sent = []
    def handler(request):
        sent.append(1)
        pytest.fail('Oversized fixed instructions must never dispatch')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            kwargs=offline_kwargs(client)
            skill=object.__new__(DeepResearchSkill)
            skill.researcher=SimpleNamespace(cfg=SimpleNamespace(strategic_llm_provider='openai',
                strategic_llm_model=w.MODEL,strategic_token_limit=32000,llm_kwargs=kwargs),add_costs=lambda value:None)
            with w._runtime({},a,[]):
                with pytest.raises(w.BudgetStop):
                    if operation == 'fixed-learning-query':
                        await skill.process_research_results('Q'*64000,'Source: https://example.test\nContent: evidence')
                    else:
                        await create_chat_completion(messages=[{'role':'user','content':'Q'*64000}],
                            model=w.MODEL,llm_provider='openai',llm_kwargs=kwargs,max_tokens=32000)
    asyncio.run(go())
    assert not sent and not a.snapshot()['events'] and not a.snapshot()['in_flight']
    assert a.snapshot()['phase_stops']['research'] == 'request_bound'


@gpt_runtime
@pytest.mark.parametrize('mode', ['continue', 'no-followups', 'same-sources', 'zero-queries'])
def test_real_deep_recursion_and_outer_followups_survive_large_branch_context(tmp_path, monkeypatch, mode):
    import re
    from gpt_researcher import GPTResearcher
    import gpt_researcher.skills.deep_research as deep
    w, a = worker(), audit(tmp_path, budget_cap='soft')
    captures, rounds, depths, leaves, extractions, outer_extractions, sent = [], [], [], [], [], [], []
    query_sets = []
    original_conduct = GPTResearcher.conduct_research
    original_deep = deep.DeepResearchSkill.deep_research
    async def local_search(*args, **kwargs): return []
    monkeypatch.setattr(deep, 'get_search_results', local_search)
    async def leaf_or_real(self, *args, **kwargs):
        if self.report_type == 'deep':
            rounds.append(self.query)
            return await original_conduct(self, *args, **kwargs)
        leaves.append(self.query)
        n = 1 if mode == 'same-sources' else len(leaves)
        url = f'https://example.test/source/{n}'
        self.research_sources = [{'url': url, 'title': 'Observed evidence'}]
        self.visited_urls = {url}
        self.context = f'Source: {url}\nTitle: Observed evidence\nContent: ' + ('é漢😀 {"x":"v"}\\\n' * 7000)
        return self.context
    async def trace_depth(self, *args, **kwargs):
        depths.append(kwargs['depth'])
        return await original_deep(self, *args, **kwargs)
    monkeypatch.setattr(GPTResearcher, 'conduct_research', leaf_or_real)
    monkeypatch.setattr(deep.DeepResearchSkill, 'deep_research', trace_depth)
    def handler(request):
        data = json.loads(request.content)
        sent.append(data)
        assert w._input_bound(data['messages']) <= 64000
        assert data['max_completion_tokens'] == 32000 and data['reasoning_effort'] == 'high'
        system = data['messages'][0]['content']
        user = data['messages'][-1]['content']
        if 'analyze the original query and search results' in system:
            answer = {'questions': []}
        elif 'generating search queries' in system:
            query_sets.append(user)
            answer = [] if mode == 'zero-queries' else [
                {'query': f'branch-{len(query_sets)}-{i}', 'researchGoal': f'Goal {len(query_sets)}-{i}'}
                for i in (1, 2)]
        elif 'analyzing search results' in system:
            fixed, evidence = user.split('Research results:\n', 1)
            sources = re.findall(r'https://example.test/source/\d+', evidence)
            assert sources, 'Every fitted branch/aggregate retains source linkage'
            extractions.append(fixed)
            outer = "query 'Original task" in fixed
            if outer: outer_extractions.append(fixed)
            followups = ['Resolve conflicting evidence?']
            if outer and (mode == 'no-followups' or len(outer_extractions) > 1): followups = []
            answer = {'learnings': [{'insight': 'Observed finding.', 'sourceUrl': sources[0]}],
                      'followUpQuestions': followups}
        else:
            assert system == 'You are a research writer. Cite only the supplied source-backed evidence.'
            n = 1 if mode == 'same-sources' else len(leaves)
            answer = f'Finding [source](https://example.test/source/{n}).'
        return chat_response(answer if isinstance(answer, str) else json.dumps(answer))
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            route_providers(monkeypatch, client)
            with w._runtime({}, a, captures) as cls:
                return await w.research({'prompt': 'Original task', 'source_identity': {}}, a, cls, captures)
    if mode == 'zero-queries':
        with pytest.raises(ValueError, match='No sources'): asyncio.run(go())
        assert depths == [3] and not leaves and not extractions
        assert all(event['phase'] == 'research' for event in a.snapshot()['events'])
    else:
        result = asyncio.run(go())
        expected_rounds = 1 if mode == 'no-followups' else 2
        assert result['raw']['research_rounds'] == len(rounds) == expected_rounds
        assert depths == [3, 2, 1, 1, 2, 1, 1] * expected_rounds
        assert len(leaves) == 14 * expected_rounds
        assert len(query_sets) == 7 * expected_rounds
        assert len(outer_extractions) == (2 if mode == 'continue' else 1)
        assert len(extractions) == len(leaves) + len(outer_extractions)
        assert result['citations'] and result['cost_usd'] == pytest.approx(.0004 * len(sent))
    state = a.snapshot()
    assert state['phase_stops'] == {'research': 'completed'}
    assert not state['terminal_failure'] and not state['unknown_cost'] and not state['in_flight']
    assert state['reserved_usd'] == 0 and state['failed_calls'] == 0


@gpt_runtime
@pytest.mark.parametrize('previous_source', [False, True], ids=['sole-source', 'last-source'])
@pytest.mark.parametrize('boundary', ['header-end', 'citation-line', 'first-word',
                                      'multiline-title-url', 'multiline-title', 'content-marker'])
def test_learning_fit_drops_newly_partial_or_empty_source_blocks(
        tmp_path, monkeypatch, previous_source, boundary):
    import copy
    from langchain_core.documents import Document
    from gpt_researcher.prompts import PromptFamily
    import gpt_researcher.skills.deep_research as deep
    w, a = worker(), audit(tmp_path, budget_cap='soft')
    previous = PromptFamily.pretty_print_docs([Document(page_content='Earlier supported evidence.',
        metadata={'source': 'https://example.test/earlier', 'title': 'Earlier'})]) + '\n' if previous_source else ''
    url = 'https://example.test/' + 'b' * 500
    body = 'Substantive finding. ' * 5000
    if boundary == 'citation-line': body += f' [Source: {url}]'
    # Use the actual pinned formatter: title newlines are deliberately unsanitized.
    block = PromptFamily.pretty_print_docs([Document(page_content=body,
        metadata={'source': url, 'title': 'Two\nlines' if boundary.startswith('multiline-title') else 'Single'})])
    context = previous + block
    content_start = context.index('Content: ', len(previous)) + len('Content: ')
    cuts = {'header-end': content_start, 'citation-line': content_start + len('Substantive'),
            'first-word': content_start + 1, 'multiline-title-url': len(previous) + len('Source: ') + 128,
            'multiline-title': context.find('\nlines', len(previous)) + 3,
            'content-marker': content_start - 3}
    raw_prefix = context[:cuts[boundary]]
    pinned, sent = [], []
    async def recorder(**kwargs):
        pinned[:] = copy.deepcopy(kwargs['messages'])
        return '{}'
    def handler(request):
        data = json.loads(request.content)
        sent.append(data)
        return chat_response('{"learnings":[],"followUpQuestions":[]}')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            skill = object.__new__(deep.DeepResearchSkill)
            skill.researcher = SimpleNamespace(cfg=SimpleNamespace(strategic_llm_provider='openai',
                strategic_llm_model=w.MODEL, strategic_token_limit=32000, llm_kwargs=offline_kwargs(client)),
                add_costs=lambda value: None)
            original = deep.DeepResearchSkill.process_research_results
            with monkeypatch.context() as recording:
                recording.setattr(deep, 'create_chat_completion', recorder)
                await original(skill, '', raw_prefix)
                query = 'Q' * (64000 - w._input_bound(pinned))
                await original(skill, query, '')
            # The native guard must still refuse the original oversized request.
            with w._runtime({}, a, []):
                with pytest.raises(w.BudgetStop):
                    await original(skill, query, context)
            assert not sent and not a.snapshot()['events']
            # A fresh audit compares the fitted path without clearing a stopped ledger.
            fitted_audit = audit(tmp_path / 'fitted', budget_cap='soft')
            with w._runtime({}, fitted_audit, []):
                if previous_source:
                    await skill.process_research_results(query, context)
                else:
                    with pytest.raises(ValueError, match='No source-associated research evidence'):
                        await skill.process_research_results(query, context)
            return fitted_audit.snapshot()
    state = asyncio.run(go())
    assert len(sent) == int(previous_source)
    for data in sent:
        assert data['messages'][0] == pinned[0]
        assert data['messages'][1]['content'].startswith(pinned[1]['content'])
        retained = data['messages'][1]['content'][len(pinned[1]['content']):]
        assert retained == previous, 'Do not dispatch newly partial or metadata-only source blocks'
        assert url not in retained and w._input_bound(data['messages']) <= 64000
    assert state['known_cost_usd'] == pytest.approx(.0004 if previous_source else 0)
    assert state['reserved_usd'] == 0 and not state['unknown_cost']
    assert not state['in_flight'] and not state['terminal_failure']
    assert len(state['events']) == int(previous_source)


@pytest.mark.parametrize('as_list', [False, True])
def test_learning_fit_keeps_already_complete_short_source_identity(as_list):
    w = worker()
    text = 'Source: https://example.test/a\nTitle: Two\nlines\nContent: A'
    context = [text] if as_list else text
    assert w._research_context('Q', context, 64000) is context


@gpt_runtime
@pytest.mark.parametrize('previous_line', [False, True], ids=['sole-line', 'last-line'])
@pytest.mark.parametrize('boundary', ['line-end', 'after-newline', 'inside-citation'])
def test_learning_fit_keeps_complete_citation_line_but_drops_cut_citation(
        tmp_path, monkeypatch, previous_line, boundary):
    import copy
    import gpt_researcher.skills.deep_research as deep
    w = worker()
    previous = 'Earlier finding. [Source: https://example.test/earlier]\n' if previous_line else ''
    line = 'A complete supported finding. [Source: https://example.test/a]'
    end = len(line) + (1 if boundary == 'after-newline' else -4 if boundary == 'inside-citation' else 0)
    raw_prefix = previous + (line + '\n')[:end]
    context = previous + line + '\n' + 'Additional evidence. ' * 5000
    expected = previous if boundary == 'inside-citation' else raw_prefix
    template, sent = [], []
    async def recorder(**kwargs):
        template[:] = copy.deepcopy(kwargs['messages'])
        return '{}'
    def handler(request):
        sent.append(json.loads(request.content))
        return chat_response('{"learnings":[],"followUpQuestions":[]}')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            skill = object.__new__(deep.DeepResearchSkill)
            skill.researcher = SimpleNamespace(cfg=SimpleNamespace(strategic_llm_provider='openai',
                strategic_llm_model=w.MODEL, strategic_token_limit=32000, llm_kwargs=offline_kwargs(client)),
                add_costs=lambda value: None)
            original = deep.DeepResearchSkill.process_research_results
            with monkeypatch.context() as recording:
                recording.setattr(deep, 'create_chat_completion', recorder)
                await original(skill, '', raw_prefix)
                query = 'Q' * (64000 - w._input_bound(template))
                await original(skill, query, '')
            if boundary != 'inside-citation':
                # Independent native control proves the intact line actually fits;
                # no stopped audit is reset or reused for the fitted comparison.
                control = audit(tmp_path / 'control', budget_cap='soft')
                with w._runtime({}, control, []):
                    await original(skill, query, expected)
                assert len(sent) == 1 and w._input_bound(sent[0]['messages']) == 64000
                assert control.snapshot()['known_cost_usd'] == pytest.approx(.0004)
            control_calls = len(sent)
            candidate = audit(tmp_path / 'fitted', budget_cap='soft')
            with w._runtime({}, candidate, []):
                if expected:
                    await skill.process_research_results(query, context)
                else:
                    with pytest.raises(ValueError, match='No source-associated research evidence'):
                        await skill.process_research_results(query, context)
            return candidate.snapshot(), sent[control_calls:]
    state, calls = asyncio.run(go())
    assert len(calls) == int(bool(expected))
    for data in calls:
        assert data['messages'][0] == template[0]
        assert data['messages'][1]['content'] == template[1]['content'] + expected
        assert w._input_bound(data['messages']) <= 64000
    assert state['known_cost_usd'] == pytest.approx(.0004 if expected else 0)
    assert state['reserved_usd'] == 0 and not state['unknown_cost'] and not state['in_flight']
    assert not state['terminal_failure'] and not state['phase_stops']


@pytest.mark.skipif(RUNTIME_AVAILABLE, reason='runtime tests already run in this interpreter')
def test_runtime_tests_pass_under_worker_venv():
    """Bridge: the main interpreter lacks GPT Researcher, so run exactly the @gpt_runtime tests under the
    configured worker venv. They must all pass; a skip there means the venv itself is broken."""
    from crest.config import load_config
    python = Path(load_config()['research']['gpt_researcher']['python_executable'])
    if not python.is_file():
        pytest.skip(f'GPT Researcher worker venv missing: {python} (research.gpt_researcher.python_executable)')
    test_file = Path(__file__).resolve()
    assert len(RUNTIME_TESTS) == len(set(RUNTIME_TESTS)) and RUNTIME_TESTS
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTEST_', 'COV_CORE_')) and not key.endswith(('_API_KEY', '_AUTH_TOKEN'))}
    try:
        proc = subprocess.run(
            [str(python), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-o', 'addopts=', '-rfEs',
             *[f'{test_file}::{name}' for name in RUNTIME_TESTS]],
            cwd=test_file.parents[2], env=env, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f'worker-venv runtime tests exceeded 180 s:\n{(exc.stdout or "")[-4000:]}')
    lines = (proc.stdout + proc.stderr).splitlines()
    tail = '\n'.join(lines[-40:])
    summary = next((line for line in reversed(lines) if ' in ' in line and ('passed' in line or 'failed' in line
                    or 'error' in line)), '')
    assert proc.returncode == 0, f'worker-venv runtime tests failed (exit {proc.returncode}):\n{tail}'
    assert 'passed' in summary and not any(word in summary for word in ('skipped', 'failed', 'error', 'deselected')), (
        f'worker-venv runtime tests must all run and pass:\n{tail}')
