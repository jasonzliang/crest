"""Caesar has one wall-clock deadline; phases are bounded by iterations and budget, never by time."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from types import SimpleNamespace
import threading

from crest import caesar_worker as worker


class Clock:
    def __init__(self, now=0): self.now = now
    def monotonic(self): return self.now
    def advance(self, seconds): self.now += seconds


def test_quick_exploration_runs_past_old_time_limits_until_the_budget_reserve(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    accepted = threading.Barrier(2)
    calls, ingested = [], []
    class Agent:
        _crest_worker_started = 0
        current_iteration = 0
        visited_urls = {}
        shutdown_called = False
        def __init__(self):
            self.kb_manager = SimpleNamespace(add_texts=lambda values: ingested.extend(values))
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Complete draft'})
        def _quick_perceive_and_think(self, url, iteration):
            calls.append(url)
            accepted.wait(timeout=5)
            clock.now = 7000  # Far past any per-phase time share; only the budget may stop pages.
            return {'url': url, 'insights': 'Collected', 'iteration': iteration}
        def explore(self):
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(lambda i: self._quick_perceive_and_think(str(i), i), range(4)))
            values = [value for value in values if value]
            self.visited_urls = {value['url']: 1 for value in values}
            self.current_iteration = max(value['iteration'] for value in values)
            self.kb_manager.add_texts(values)
            return self.synthesizer.synthesize_artifact()
    agent = Agent()
    artifact, stop = worker._quick_explore_with_synthesis_reserve(agent, {}, audit)
    assert artifact['artifact'] == 'Complete draft'
    assert len(calls) == len(ingested) == 4 and stop is None
    assert audit.exploration_limit is None


def test_ordinary_exploration_stops_only_on_the_budget_reserve(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    audit.events.append({'status': 'completed', 'cost_usd': 2.5, 'model': 'gpt-6-luna'})  # Reserve is $3 of $5.
    calls = []
    class Agent:
        _crest_worker_started = 0
        current_iteration = 0
        def __init__(self):
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Complete draft'})
        def perceive(self):
            calls.append(self.current_iteration)
            clock.advance(9000)  # Hours pass; time alone never ends exploration.
        def explore(self):
            for iteration in range(1, 251):
                self.current_iteration = iteration
                self.perceive()
    agent = Agent()
    artifact, stop = worker._explore_with_synthesis_reserve(agent, {}, audit)
    assert calls == []  # Stopped before the first page: $2.50 committed exceeds the $2 exploration limit.
    assert stop['reason'] == 'budget_reserve' and 'time_limited' not in stop
    assert stop['iterations_completed'] == 0
    assert artifact['artifact'] == 'Complete draft'


def test_synthesis_allowance_is_money_only(tmp_path, monkeypatch):
    clock = Clock(7100)  # Would have been past every old time allowance.
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    calls = []
    class Synthesizer:
        synthesis_drafts = 3
        synthesis_iterations = 15
        synthesis_merge_artifacts = True
        _current_draft = 1
        def _generate_qa_pairs(self):
            calls.append('genuine query')
            clock.advance(5000)
            return [('Question', 'Answer', [])]
    agent = SimpleNamespace(synthesizer=Synthesizer())
    with worker.adaptive_synthesis_budget(agent, {'budget_usd': 5}, audit) as records:
        assert agent.synthesizer._generate_qa_pairs() == [('Question', 'Answer', [])]
        assert audit.request_limit is None  # Restored after the draft's allowance.
    assert calls == ['genuine query']
    row = records['drafts'][0]
    assert row['completed_qa_rounds'] == 1 and row['budget_limited'] is False and row['qa_allowance_usd'] > 0
    assert 'time_policy' not in records and 'time_limited' not in row


def test_worker_initialization_uses_one_monotonic_overall_deadline(tmp_path, monkeypatch):
    clock = Clock(100)
    monkeypatch.setattr(worker, 'time', clock)
    seen = {}
    @contextmanager
    def deadline(seconds):
        seen['deadline_allowance'] = seconds
        yield
    class Agent:
        shutdown_called = False
        def __init__(self, **kwargs): clock.advance(3000)
        def perceive(self): clock.advance(4000)  # Exploration outlives the old 37.5% time share.
        def explore(self):
            self.current_iteration = 1
            self.perceive()
            return self.synthesizer.synthesize_artifact()
        @property
        def synthesizer(self):
            def synthesize():
                seen['start'] = self._crest_worker_started
                return {'artifact': 'A complete final answer', 'num_drafts': 3,
                        'metadata': {'synthesis_queries': 1}}
            return SimpleNamespace(synthesize_artifact=synthesize)
        def shutdown(self): pass
    @contextmanager
    def runtime(settings, audit): yield Agent
    monkeypatch.setattr(worker, '_runtime', runtime)
    monkeypatch.setattr(worker, '_deadline', deadline)
    path = tmp_path / 'result.json'
    assert worker.run_worker({'prompt': 'Q', 'settings': {}, 'output_dir': str(tmp_path / 'output'),
                              'job_key': 'a' * 64}, path) == 0
    assert seen['start'] == 100
    assert seen['deadline_allowance'] == 7200  # The whole default timeout, armed once before the agent starts.
    result = json.loads(path.read_text())['result']
    assert 'exploration_budget_stop' not in result['raw']
