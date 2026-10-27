"""Offline phase allocation against actual Rome exploration and QA loops."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import time
from types import SimpleNamespace

import pytest

from crest import caesar_worker as worker
from crest.caesar_metrics import iteration_metrics


class Clock:
    now = 0.
    def advance(self, seconds): self.now += seconds
    def monotonic(self): return self.now
    def utc(self):
        return (datetime(2026, 10, 27, tzinfo=timezone.utc) + timedelta(seconds=self.now)).isoformat()


def fixture_audit(tmp_path):
    return worker.UsageAudit(5, tmp_path / 'usage.json',
                            {'test-model': {'input': 0, 'output': 1000}})


def pay(audit, clock, *, tokens=100, seconds=1, error=None):
    token = audit.before(SimpleNamespace(json_data={
        'model': 'test-model', 'messages': [], 'max_completion_tokens': tokens}))
    clock.advance(seconds)
    if error:
        audit.after(token, error=error)
        raise error
    audit.after(token, response=SimpleNamespace(usage={'prompt_tokens': 0, 'completion_tokens': tokens}))


def test_regular_iterations_include_perceive_think_act_and_do_not_duplicate_costs(tmp_path):
    from caesar.caesar_agent import CaesarAgent
    clock, audit = Clock(), fixture_audit(tmp_path)
    pay(audit, clock, tokens=50)  # Initialization is intentionally outside iteration records.
    class Agent:
        use_quick_explore = shutdown_called = False
        current_iteration = 0
        max_iterations = 2
        save_graph_interval = checkpoint_interval = 1
        visited_urls = {}
        logger = SimpleNamespace(info=lambda *args: None, error=lambda *args: None)
        checkpoint_manager = SimpleNamespace(save=lambda *args: clock.advance(.25))
        synthesizer = SimpleNamespace(synthesize_artifact=lambda: {'artifact': 'Final answer'})
        def _log_iteration(self, *args): clock.advance(.1)
        def perceive(self):
            pay(audit, clock, seconds=1)
            return 'Content', [('url', 'Page')]
        def think(self, content):
            pay(audit, clock, seconds=2)
            return 'Insight'
        def act(self, links):
            pay(audit, clock, seconds=3)
            return 'url'
        def _draw_graph_visualization(self, *args): clock.advance(.25)
        def explore(self): return CaesarAgent.explore(self)
    agent = Agent()
    original_explore = agent.explore
    with iteration_metrics(agent, audit, tmp_path, utc_now=clock.utc, monotonic=clock.monotonic) as metrics:
        assert agent.explore()['artifact'] == 'Final answer'
        assert len(metrics.records) == 2
    assert agent.explore == original_explore
    first, second = metrics.records
    assert [row['iteration'] for row in metrics.records] == [1, 2]
    assert first['successful_calls'] == 3  # Last exploration iteration skips act in Rome.
    assert second['successful_calls'] == 2
    assert first['known_cost_usd'] == pytest.approx(.3)
    assert second['known_cost_usd'] == pytest.approx(.2)
    assert first['duration_seconds'] == pytest.approx(6.6)
    assert second['duration_seconds'] == pytest.approx(4.1)
    assert all(row['status'] == 'completed' and row['success'] for row in metrics.records)
    assert all(row['started_at'].endswith('+00:00') for row in metrics.records)
    summary = metrics.summary()
    assert summary['allocated_known_cost_usd'] == pytest.approx(.5)
    assert summary['canonical_audit_known_cost_usd'] == pytest.approx(.55)
    assert summary['unattributed_known_cost_usd'] == pytest.approx(.05)
    assert [json.loads(line) for line in metrics.path.read_text().splitlines()] == metrics.records


def test_real_qa_loop_includes_next_question_and_keeps_write_refine_merge_disjoint(tmp_path):
    from caesar.artifact_synthesis import ArtifactSynthesizer
    clock, audit = Clock(), fixture_audit(tmp_path)
    class Synthesizer(ArtifactSynthesizer):
        synthesis_drafts = _num_drafts = 3
        synthesis_iterations = 2
        synthesis_merge_artifacts = True
        synthesis_top_k = synthesis_top_n = 8
        filters = None
        def __init__(self):
            self.logger = SimpleNamespace(info=lambda *args: None, error=lambda *args: None)
            self.kb_manager = SimpleNamespace(query=self.query)
        def query(self, *args, **kwargs):
            pay(audit, clock, seconds=2)
            return 'Genuine KB answer', []
        def _generate_next_query(self, *args):
            pay(audit, clock, seconds=3)
            return 'Next question'
        def _llm_call(self, *args, **kwargs):
            pay(audit, clock, seconds=4)
            return {'artifact': 'Complete draft'}
        def _refine_query(self, *args):
            self._llm_call('Prompt', [], label='REFINE')
            return 'Refined question'
        def _merge_artifacts(self, *args):
            return self._llm_call('Prompt', [], label='MERGE')
        def synthesize_artifact(self):
            drafts = []
            for draft in range(1, 4):
                self._current_draft = draft
                pairs = self._generate_qa_pairs('iterative', 'Question')
                assert len(pairs) == 2
                drafts.append(self._llm_call('Prompt', [], label='SYNTHESIS'))
                if draft < 3: self._refine_query(drafts[-1])
            return self._merge_artifacts(drafts)
    synthesizer = Synthesizer()
    agent = SimpleNamespace(synthesizer=synthesizer, shutdown_called=False,
                            _crest_worker_deadline=time.monotonic() + 7200)
    synthesizer.agent = agent
    original_query = synthesizer.kb_manager.query
    with iteration_metrics(agent, audit, tmp_path, utc_now=clock.utc, monotonic=clock.monotonic) as metrics:
        with worker.adaptive_synthesis_budget(agent, {'synthesis_iterations': 2}, audit):
            assert synthesizer.synthesize_artifact()['artifact'] == 'Complete draft'
    assert synthesizer.kb_manager.query == original_query
    assert Counter(row['phase'] for row in metrics.records) == {
        'synthesis_iteration': 6, 'draft_write': 3, 'draft_refinement': 2, 'merge': 1}
    for draft in range(1, 4):
        rows = [row for row in metrics.records if row['phase'] == 'synthesis_iteration' and row['draft'] == draft]
        assert [row['iteration'] for row in rows] == [1, 2]
        assert [row['duration_seconds'] for row in rows] == [5, 2]
        assert [row['known_cost_usd'] for row in rows] == pytest.approx([.2, .1])
    assert sum(row['successful_calls'] for row in metrics.records) == 15
    assert metrics.summary()['allocated_known_cost_usd'] == pytest.approx(audit.snapshot()['known_cost_usd'])
    assert metrics.summary()['unattributed_known_cost_usd'] == pytest.approx(0)


def test_interrupted_iteration_keeps_known_subtotal_and_unknown_reservation(tmp_path):
    clock, audit = Clock(), fixture_audit(tmp_path)
    class Agent:
        current_iteration = 1
        def _log_iteration(self, *args): pass
        def perceive(self):
            pay(audit, clock, seconds=1)
            return 'Content', []
        def explore(self):
            self._log_iteration(1)
            self.perceive()
            pay(audit, clock, seconds=3, error=worker.WorkerDeadlineExceeded('Time limit'))
    agent = Agent()
    original = dict(vars(agent))
    with pytest.raises(worker.WorkerDeadlineExceeded):
        with iteration_metrics(agent, audit, tmp_path, utc_now=clock.utc, monotonic=clock.monotonic) as metrics:
            agent.explore()
    assert vars(agent) == original
    assert len(metrics.records) == 1
    row = metrics.records[0]
    assert row['status'] == 'stopped' and row['success'] is False
    assert row['duration_seconds'] == 4
    assert row['known_cost_usd'] == pytest.approx(.1)
    assert row['cost_usd'] is None and row['unknown_cost'] is True
    assert row['unknown_reserved_usd_delta'] == pytest.approx(.1)
    assert row['successful_calls'] == row['failed_calls'] == 1
    assert json.loads(metrics.path.read_text()) == row


def test_prior_unknown_bill_does_not_make_a_new_known_iteration_cost_unknown(tmp_path):
    clock, audit = Clock(), fixture_audit(tmp_path)
    try: pay(audit, clock, error=RuntimeError('Earlier billing unknown'))
    except RuntimeError: pass
    class Agent:
        def _log_iteration(self, *args): pass
        def explore(self):
            self._log_iteration(2)
            pay(audit, clock)
    with iteration_metrics(Agent(), audit, tmp_path, utc_now=clock.utc, monotonic=clock.monotonic) as metrics:
        metrics.agent.explore()
    row = metrics.records[0]
    assert audit.snapshot()['unknown_cost'] is True
    assert row['unknown_cost'] is False and row['cost_usd'] == pytest.approx(.1)
    assert row['unknown_reserved_usd_delta'] == 0


def test_trace_write_failure_restores_wrapped_methods(tmp_path):
    clock, audit = Clock(), fixture_audit(tmp_path)
    class Agent:
        def _log_iteration(self, *args): pass
        def explore(self): self._log_iteration(1)
    agent = Agent()
    original = agent.explore
    with pytest.raises(IsADirectoryError):
        with iteration_metrics(agent, audit, tmp_path, utc_now=clock.utc, monotonic=clock.monotonic) as metrics:
            metrics.path.mkdir()
            agent.explore()
    assert agent.explore == original
    assert vars(agent) == {}
