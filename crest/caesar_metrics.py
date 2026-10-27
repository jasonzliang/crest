"""Diagnostic iteration timing and SDK-cost allocation for regular Caesar runs.

These records allocate the canonical usage audit; they are never an extra bill.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


def _pending(snapshot):
    return Counter(json.dumps(item, sort_keys=True) for item in snapshot.get('in_flight', []))


def _uncertain_reserve(snapshot):
    events = [item for item in snapshot.get('events', []) if item.get('unknown_cost')]
    return sum(item.get('reserved_usd', 0) for item in events + snapshot.get('in_flight', []))


class IterationMetrics:
    def __init__(self, agent, audit, directory, *, utc_now=None, monotonic=None):
        self.agent, self.audit = agent, audit
        self.path = Path(directory) / 'iteration-metrics.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records, self.patches = [], []
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc).isoformat())
        self.monotonic = monotonic or time.monotonic
        self.exploration = self.qa = None
        self.in_qa, self.qa_iteration = False, 0

    def begin(self, phase, *, iteration=None, draft=None):
        return {'phase': phase, 'iteration': iteration, 'draft': draft,
                'started_at': self.utc_now(), '_monotonic': self.monotonic(),
                '_audit': self.audit.snapshot()}

    def finish(self, span, error=None, **details):
        if span is None:
            return
        before = span.pop('_audit')
        after = self.audit.snapshot()
        elapsed = max(0., self.monotonic() - span.pop('_monotonic'))
        events = after.get('events', [])[len(before.get('events', [])):]
        pending = _pending(after) - _pending(before)
        successful = after.get('successful_calls', 0) - before.get('successful_calls', 0)
        unknown = bool(pending or any(event.get('unknown_cost') for event in events))
        if successful and not events and after.get('unknown_cost'):
            unknown = True
        known = after.get('known_cost_usd', 0) - before.get('known_cost_usd', 0)
        stopped = error is not None and type(error).__name__ in {
            'ExplorationBudgetReserved', 'BudgetExceeded', 'WorkerDeadlineExceeded',
            'KeyboardInterrupt', 'SystemExit'}
        status = 'stopped' if stopped else 'error' if error is not None else 'completed'
        span.update(completed_at=self.utc_now(), duration_seconds=elapsed, status=status,
                    successful_calls=successful,
                    failed_calls=after.get('failed_calls', 0) - before.get('failed_calls', 0),
                    rate_limit_events=after.get('rate_limit_events', 0) - before.get('rate_limit_events', 0),
                    known_cost_usd=known, cost_usd=None if unknown else known, unknown_cost=unknown,
                    unknown_reserved_usd_delta=_uncertain_reserve(after) - _uncertain_reserve(before),
                    **details)
        span['success'] = (error is None and span.get('knowledge_base_answered', True)
                           and span.get('content_available', True) and span.get('output_available', True))
        if error is not None:
            span['error_type'] = type(error).__name__
            if error.args and isinstance(error.args[0], dict):
                span['stop_reason'] = error.args[0].get('reason', 'budget_or_time_reserve')
        span['sequence'] = len(self.records) + 1
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(span, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        self.records.append(span)

    def finish_exploration(self, error=None):
        span, self.exploration = self.exploration, None
        self.finish(span, error)

    def finish_qa(self, error=None):
        span, self.qa = self.qa, None
        self.finish(span, error)

    def patch(self, owner, name, factory):
        original = getattr(owner, name, None)
        if not callable(original):
            return
        local = vars(owner) if hasattr(owner, '__dict__') else {}
        self.patches.append((owner, name, name in local, local.get(name)))
        setattr(owner, name, factory(original))

    def restore(self):
        for owner, name, local, value in reversed(self.patches):
            if local:
                setattr(owner, name, value)
            else:
                delattr(owner, name)

    def summary(self):
        phases = {}
        for row in self.records:
            item = phases.setdefault(row['phase'], {'iterations': 0, 'duration_seconds': 0.,
                'known_cost_usd': 0., 'unknown_cost_iterations': 0, 'successful_calls': 0, 'failed_calls': 0})
            item['iterations'] += 1
            for field in ('duration_seconds', 'known_cost_usd', 'successful_calls', 'failed_calls'):
                item[field] += row[field]
            item['unknown_cost_iterations'] += row['unknown_cost']
        canonical = self.audit.snapshot()['known_cost_usd']
        allocated = sum(row['known_cost_usd'] for row in self.records)
        return {'records': len(self.records), 'phases': phases, 'allocated_known_cost_usd': allocated,
                'canonical_audit_known_cost_usd': canonical,
                'unattributed_known_cost_usd': max(0., canonical - allocated),
                'definition': 'Nonoverlapping diagnostic allocations of the SDK usage audit; '
                              'never add these costs to the canonical bill. Durations include retries. '
                              'Initialization and work outside these phases remain unattributed.'}

    def install(self):
        agent = self.agent
        synthesizer = getattr(agent, 'synthesizer', None)
        regular = not getattr(agent, 'use_quick_explore', False)
        def log_iteration(original):
            def call(iteration, *args, **kwargs):
                self.finish_exploration()
                self.exploration = self.begin('exploration_iteration', iteration=iteration)
                return original(iteration, *args, **kwargs)
            return call
        def explore(original):
            def call(*args, **kwargs):
                try:
                    return original(*args, **kwargs)
                except BaseException as error:
                    self.finish_exploration(error)
                    raise
                finally:
                    self.finish_exploration()
            return call
        if regular:
            self.patch(agent, '_log_iteration', log_iteration)
            self.patch(agent, 'explore', explore)
        def observe(original):
            def call(*args, **kwargs):
                result = original(*args, **kwargs)
                if self.exploration is not None:
                    content = result[0] if isinstance(result, tuple) and result else result
                    self.exploration['content_available'] = bool(content)
                return result
            return call
        if regular:
            self.patch(agent, 'perceive', observe)
        if synthesizer is None:
            return
        draft = lambda: getattr(synthesizer, '_current_draft', None)
        def synthesize(original):
            def call(*args, **kwargs):
                self.finish_exploration()
                return original(*args, **kwargs)
            return call
        self.patch(synthesizer, 'synthesize_artifact', synthesize)
        def qa_pairs(original):
            def call(*args, **kwargs):
                previous = self.in_qa
                self.in_qa, self.qa_iteration = True, 0
                try:
                    return original(*args, **kwargs)
                except BaseException as error:
                    self.finish_qa(error)
                    raise
                finally:
                    self.finish_qa()
                    self.in_qa = previous
            return call
        self.patch(synthesizer, '_generate_qa_pairs', qa_pairs)
        def query(original):
            def call(*args, **kwargs):
                if not self.in_qa:
                    return original(*args, **kwargs)
                self.finish_qa()
                self.qa_iteration += 1
                self.qa = self.begin('synthesis_iteration', iteration=self.qa_iteration, draft=draft())
                try:
                    result = original(*args, **kwargs)
                    answer = result[0] if isinstance(result, tuple) and result else result
                    self.qa['knowledge_base_answered'] = bool(answer)
                    return result
                except BaseException as error:
                    self.finish_qa(error)
                    raise
            return call
        self.patch(getattr(synthesizer, 'kb_manager', None), 'query', query)
        def next_query(original):
            def call(*args, **kwargs):
                try:
                    result = original(*args, **kwargs)
                    if self.qa is not None:
                        self.qa['next_query_generated'] = bool(result)
                    return result
                except BaseException as error:
                    self.finish_qa(error)
                    raise
                finally:
                    self.finish_qa()
            return call
        self.patch(synthesizer, '_generate_next_query', next_query)
        def measured(phase, *, synthesis_only=False):
            def factory(original):
                def call(*args, **kwargs):
                    if synthesis_only and kwargs.get('label') != 'SYNTHESIS':
                        return original(*args, **kwargs)
                    span = self.begin(phase, draft=draft())
                    try:
                        result = original(*args, **kwargs)
                    except BaseException as error:
                        self.finish(span, error)
                        raise
                    self.finish(span, output_available=bool(result))
                    return result
                return call
            return factory
        self.patch(synthesizer, '_llm_call', measured('draft_write', synthesis_only=True))
        self.patch(synthesizer, '_refine_query', measured('draft_refinement'))
        self.patch(synthesizer, '_merge_artifacts', measured('merge'))


@contextmanager
def iteration_metrics(agent, audit, output_dir, *, utc_now=None, monotonic=None):
    metrics = IterationMetrics(agent, audit, output_dir, utc_now=utc_now, monotonic=monotonic)
    try:
        metrics.install()
        yield metrics
    except BaseException as error:
        metrics.finish_qa(error)
        metrics.finish_exploration(error)
        raise
    finally:
        try:
            metrics.finish_qa()
            metrics.finish_exploration()
        finally:
            metrics.restore()
