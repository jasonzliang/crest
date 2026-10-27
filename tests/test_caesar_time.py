"""Offline time reservations preserve room for completed Caesar writing."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import threading

from crest import caesar_worker as worker


class Clock:
    def __init__(self, now=0): self.now = now
    def monotonic(self): return self.now
    def advance(self, seconds): self.now += seconds


def test_quick_time_cutoff_skips_queued_pages_but_drains_and_ingests_accepted_pages(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    accepted = threading.Barrier(2)
    calls, ingested = [], []
    class Agent:
        _crest_worker_started = 0
        _crest_worker_deadline = 7200
        current_iteration = 0
        visited_urls = {}
        shutdown_called = False
        def __init__(self):
            self.kb_manager = SimpleNamespace(add_texts=lambda values: ingested.extend(values))
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Complete draft'})
        def _quick_perceive_and_think(self, url, iteration):
            calls.append(url)
            accepted.wait(timeout=5)
            clock.now = 2800
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
    original = agent._quick_perceive_and_think
    artifact, stop = worker._quick_explore_with_synthesis_reserve(agent, {}, audit)
    assert artifact['artifact'] == 'Complete draft'
    assert len(calls) == len(ingested) == 2
    assert stop['reason'] == 'time_reserve'
    assert stop['time_limited'] is True
    assert stop['exploration_time_limit_seconds'] == 2700
    assert stop['iterations_completed'] == 2
    assert audit.exploration_limit is None
    assert agent._quick_perceive_and_think == original
    assert agent.shutdown_called is False


def test_ordinary_exploration_time_cutoff_starts_real_synthesis(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    calls = []
    class Agent:
        _crest_worker_started = 0
        _crest_worker_deadline = 7200
        current_iteration = 0
        def __init__(self):
            self.synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Complete draft'})
        def perceive(self):
            calls.append(self.current_iteration)
            clock.advance(2700)
        def explore(self):
            for iteration in range(1, 251):
                self.current_iteration = iteration
                self.perceive()
    agent = Agent()
    artifact, stop = worker._explore_with_synthesis_reserve(agent, {}, audit)
    assert calls == [1]
    assert stop['reason'] == 'time_reserve'
    assert stop['iterations_completed'] == 1
    assert artifact['artifact'] == 'Complete draft'


def test_qa_time_allowance_preserves_genuine_rounds_three_writes_and_merge(tmp_path, monkeypatch):
    # Exercise Rome's real QA loop rather than a duplicate of its stop behavior.
    from caesar.artifact_synthesis import ArtifactSynthesizer
    clock = Clock(3000)
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    class Synthesizer(ArtifactSynthesizer):
        _num_drafts = 3
        synthesis_drafts = 3
        synthesis_iterations = 15
        synthesis_merge_artifacts = True
        synthesis_top_k = synthesis_top_n = 8
        filters = None
        def __init__(self):
            self.logger = SimpleNamespace(info=lambda *args: None, error=lambda *args: None)
            self.kb_manager = SimpleNamespace(query=self.query)
        def query(self, *args, **kwargs):
            clock.advance(250)
            return 'Genuine knowledge-base answer', []
        def _generate_next_query(self, *args, **kwargs):
            clock.advance(50)
            return 'Next question'
        def _merge_artifacts(self, drafts):
            clock.advance(100)
            return {'artifact': 'Complete merged artifact'}
    agent = SimpleNamespace(_crest_worker_started=0, _crest_worker_deadline=7200,
                            shutdown_called=False, synthesizer=Synthesizer())
    agent.synthesizer.agent = agent
    original_shutdown = agent.synthesizer._shutdown_requested
    drafts = []
    with worker.adaptive_synthesis_budget(agent, {}, audit) as records:
        for draft in range(1, 4):
            agent.synthesizer._current_draft = draft
            pairs = agent.synthesizer._generate_qa_pairs('iterative', 'Question')
            assert pairs and all(pair[1] == 'Genuine knowledge-base answer' for pair in pairs)
            assert agent.synthesizer._shutdown_requested() is False
            drafts.append(pairs)
            clock.advance(100)  # Actual completed draft write.
            if draft < 3: clock.advance(100)  # Inter-draft query refinement.
        artifact = agent.synthesizer._merge_artifacts(drafts)
    assert artifact['artifact'] == 'Complete merged artifact'
    assert clock.now < 7200
    assert len(records['drafts']) == 3
    assert all(1 <= row['completed_qa_rounds'] < 15 for row in records['drafts'])
    assert all(row['time_limited'] for row in records['drafts'])
    assert records['time_policy']['write_allowance_per_call_seconds'] == 300
    assert records['time_policy']['best_effort'] is True
    assert records['merge_completed'] is True
    assert agent.synthesizer._shutdown_requested == original_shutdown
    assert agent.shutdown_called is False


def test_worker_initialization_uses_the_same_monotonic_overall_deadline(tmp_path, monkeypatch):
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
        def perceive(self): raise AssertionError('must not restart exploration after its cutoff')
        def explore(self):
            self.current_iteration = 1
            self.perceive()
        @property
        def synthesizer(self):
            def synthesize():
                seen['start'] = self._crest_worker_started
                seen['deadline'] = self._crest_worker_deadline
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
    assert seen['deadline'] == 7300
    assert seen['deadline_allowance'] <= 7200
    result = json.loads(path.read_text())['result']
    assert result['raw']['exploration_budget_stop']['reason'] == 'time_reserve'


def test_exhausted_qa_time_does_not_fabricate_a_completed_round(tmp_path, monkeypatch):
    clock = Clock(7100)
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    calls = []
    class Synthesizer:
        synthesis_drafts = 3
        synthesis_iterations = 15
        synthesis_merge_artifacts = True
        _current_draft = 1
        def _shutdown_requested(self): return False
        def _generate_qa_pairs(self):
            if self._shutdown_requested(): return []
            calls.append('genuine query')
            return [('Question', 'Answer', [])]
    agent = SimpleNamespace(_crest_worker_deadline=7200, synthesizer=Synthesizer())
    with worker.adaptive_synthesis_budget(agent, {}, audit) as records:
        assert agent.synthesizer._generate_qa_pairs() == []
        assert agent.synthesizer._shutdown_requested() is False
    assert calls == []
    assert records['drafts'][0]['completed_qa_rounds'] == 0
    assert records['drafts'][0]['time_limited'] is True


def test_zero_qa_allowance_still_attempts_one_genuine_round_when_writing_time_remains(tmp_path, monkeypatch):
    clock = Clock(5700)
    monkeypatch.setattr(worker, 'time', clock)
    audit = worker.UsageAudit(5, tmp_path / 'usage.json')
    calls = []
    class Synthesizer:
        synthesis_drafts = 3
        synthesis_iterations = 15
        synthesis_merge_artifacts = True
        _current_draft = 1
        def _shutdown_requested(self): return False
        def _generate_next_query(self):
            calls.append('unnecessary next question')
            return 'Next'
        def _generate_qa_pairs(self):
            pairs = []
            for _ in range(self.synthesis_iterations):
                if self._shutdown_requested(): break
                calls.append('genuine knowledge-base query')
                clock.advance(100)
                pairs.append(('Question', 'Genuine answer', []))
                if self._generate_next_query() is None: break
            return pairs
    agent = SimpleNamespace(_crest_worker_deadline=7200, synthesizer=Synthesizer())
    with worker.adaptive_synthesis_budget(agent, {}, audit) as records:
        pairs = agent.synthesizer._generate_qa_pairs()
    assert calls == ['genuine knowledge-base query']
    assert pairs == [('Question', 'Genuine answer', [])]
    assert records['drafts'][0]['qa_time_allowance_seconds'] == 0
    assert records['drafts'][0]['completed_qa_rounds'] == 1
    assert records['drafts'][0]['time_limited'] is True
    assert clock.now < 7200 - 300
