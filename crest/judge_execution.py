"""Bounded judge attempts with durable receipts and one parent single-flight lock."""
from __future__ import annotations

from .cache import Cache, digest


_TERMINAL = {'completed', 'failed', 'incomplete', 'cancelled'}


def _refused(state):
    # A returned refusal is a billed, finished response, so another attempt cannot
    # duplicate it. Retrying the same judge keeps the panel's model unchanged.
    return state.get('remote_status') == 'refusal' and not state.get('submission_unknown')


def _terminal(state):
    raw = state.get('raw')
    return (isinstance(raw, dict) and raw.get('status') in _TERMINAL
            or state.get('remote_status') in _TERMINAL)


def _attempt_record(job, index):
    from .pipeline import _job_timing
    state = job.state
    result = state.get('provider_result') or state.get('result') or {}
    if not isinstance(result, dict):
        result = {}
    raw = state.get('raw') if isinstance(state.get('raw'), dict) else {}
    raw_usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else {}
    return {'attempt': index, 'key': job.key, 'cache_record': str(job.path),
            'status': state.get('status', 'pending'), 'remote_id': state.get('remote_id'),
            'submission_unknown': bool(state.get('submission_unknown')),
            'error': state.get('error'), 'result': result,
            'cost_usd': result.get('cost_usd', raw_usage.get('cost_usd')),
            'usage': result.get('usage') or state.get('observed_usage') or raw_usage,
            'substitute_model': state.get('substitute_model'),
            'resent_after_unknown_outcome': bool(state.get('resent_after_unknown_outcome')),
            'observed_cost_usd': state.get('observed_cost_usd'),
            'observed_cost_scope': state.get('observed_cost_scope'),
            'retry_events': state.get('retry_events', []), 'timing': _job_timing(state)}


def _accounting(children):
    attempts = [_attempt_record(child, index) for index, child in enumerate(children, 1)]
    known = sum(a['cost_usd'] for a in attempts if a['cost_usd'] is not None)
    unknown = sum(a['cost_usd'] is None for a in attempts)
    events = [event for attempt in attempts for event in attempt['retry_events']]
    last_result = next((a['result'] for a in reversed(attempts) if a['result']), {})
    return {'attempts': attempts, 'cost_usd': None if unknown else known,
            'known_cost_usd': known, 'unknown_cost_count': unknown,
            'cost_scope': 'all_judgment_attempts', 'retry_events': events,
            'provider_result': last_result}


def _save_accounting(parent, children):
    parent.save(**_accounting(children))


def checkpoint_cost_record(parent):
    """Read paid/uncertain checkpoint receipts without modifying historical state."""
    keys = parent.state.get('attempt_keys')
    children = ([Cache(parent.directory / 'attempts').job(key) for key in keys]
                if keys else [parent])
    children = [child for child in children if any(
        child.state.get(key) is not None for key in
        ('provider_result', 'result', 'raw', 'remote_id', 'submission_unknown'))]
    if not children:
        return None
    return _accounting(children) | {'key': parent.key, 'cache_record': str(parent.path)}


def _substitute_settings(settings, substitute):
    """The same judge call on the stand-in model, priced at its own rates."""
    model = substitute['model']
    return settings | {'model': model, 'model_pricing': {
        **(settings.get('model_pricing') or {}), model: dict(substitute['rates'])}}


def _next_attempt(children, limit, substitute):
    """The stand-in for the next attempt (None for the configured model), or False when none is allowed.

    The stand-in is used only after the configured model has refused on every one of
    its allowed attempts, and it gets the same number of attempts of its own.
    """
    stand_in = [child for child in children if child.state.get('substitute_model')]
    if stand_in:
        return stand_in[-1].state['substitute'] if len(stand_in) < limit else False
    if len(children) < limit:
        return None
    if substitute and children and _refused(children[-1].state):
        return dict(substitute)
    return False


def _row(task, parent, cached):
    from .judging import parse_verdict
    from .pipeline import _job_timing
    result = parent.state.get('result')
    if not isinstance(result, dict):
        raise ValueError('Completed judge checkpoint has no valid response')
    verdict = parse_verdict(result.get('text'), require_reason_quality=True)
    row = {k: task[k] for k in ('key', 'question_id', 'pair', 'order', 'judge',
                                 'answer_keys', 'answer_hashes')}
    row.update({k: task[k] for k in ('protocol_version', 'presentation_version',
                                     'presented_answer_hashes', 'rubric_kind', 'rubric_id') if k in task})
    attempts = parent.state.get('attempts')
    if attempts is None:  # A valid historical single-attempt checkpoint needs no mutation.
        attempts = [_attempt_record(parent, 1)]
    row.update(verdict=verdict, result=result, usage=result.get('usage', {}),
               usage_scope='successful_attempt', cost_scope='all_judgment_attempts',
               cost_usd=parent.state.get('cost_usd', result.get('cost_usd')),
               known_cost_usd=parent.state.get('known_cost_usd', result.get('cost_usd') or 0),
               unknown_cost_count=parent.state.get('unknown_cost_count', int(result.get('cost_usd') is None)),
               attempts=attempts, cache_hit=cached, cache_record=str(parent.path),
               retry_events=parent.state.get('retry_events', []), timing=_job_timing(parent.state))
    return row, cached


async def execute_judgment(pipeline, task, controller=None):
    from .artifacts import TRANSPORT_SETTINGS
    from .judging import parse_verdict
    from .pipeline import _job_timing, _start_checkpoint, timestamp

    async with pipeline._stage_cache('judge').lock(task['key']) as parent:
        if parent.state.get('status') == 'completed':
            try:
                return _row(task, parent, True)
            except ValueError:
                # Preserve this paid result as an attempt before replacing it.
                pass
        had_history = any(k != 'key' for k in parent.state)
        settings = task['settings'] | {
            k: v for k, v in pipeline.config['judges'][task['judge']].items()
            if k in TRANSPORT_SETTINGS}
        limit = max(1, int(settings.get('retry_attempts', 4)))
        substitute = settings.pop('refusal_substitute', None)
        attempt_cache = Cache(parent.directory / 'attempts')
        keys = list(parent.state.get('attempt_keys', []))
        children = [attempt_cache.job(key) for key in keys]
        if not keys and any(k in parent.state for k in (
                'result', 'provider_result', 'remote_id', 'raw', 'submission_unknown')):
            # Legacy checkpoints keep their provider state and original receipt in
            # a child; no old keys or neighboring historical checkpoints change.
            key = digest({'judgment': task['key'], 'attempt': 1})
            child = attempt_cache.job(key)
            child.save(**{k: v for k, v in parent.state.items() if k != 'key'},
                       source_cache_record=str(parent.path))
            keys.append(key)
            children.append(child)
            parent.save(attempt_keys=keys)
        started = timestamp()
        first_started, _ = _start_checkpoint(parent.state)
        parent.save(status='running', stage='judge', started_at=started,
                    first_started_at=first_started if had_history else started, error=None)
        provider = pipeline._provider(task['judge'])
        while True:
            child = children[-1] if children else None
            if child is not None and child.state.get('status') == 'failed' and _refused(child.state):
                child.save(status='rejected', completed_at=child.state.get('failed_at') or timestamp())
            if (child is not None and child.state.get('submission_unknown')
                    and not child.state.get('remote_id') and child.state.get('status') != 'rejected'):
                # Even injected providers must obey the transport's no-resubmit rule.
                # A terminal raw response with an ID can be reconciled by the adapter.
                raw = child.state.get('raw') or {}
                if not (isinstance(raw, dict) and raw.get('id') and _terminal(child.state)):
                    if (getattr(pipeline, 'resend_unknown', False)
                            and not any(c.state.get('resent_after_unknown_outcome') for c in children)):
                        # An explicit, recorded resend: the first try keeps its unknown charge.
                        child.save(status='rejected', resent_after_unknown_outcome=True,
                                   completed_at=child.state.get('failed_at') or timestamp())
                    else:
                        message = 'Judge submission outcome unknown; reconcile before submitting again'
                        child.save(status='failed', error=message, failed_at=timestamp())
                        _save_accounting(parent, children)
                        parent.save(status='failed', error=message, failed_at=timestamp())
                        raise RuntimeError(message)
            if child is None or child.state.get('status') == 'rejected':
                stand_in = _next_attempt(children, limit, substitute)
                if stand_in is False:
                    _save_accounting(parent, children)
                    message = f'Judge response rejected after {len(children)} attempts'
                    parent.save(status='failed', error=message, failed_at=timestamp())
                    raise ValueError(message)
                key = digest({'judgment': task['key'], 'attempt': len(children) + 1})
                child = attempt_cache.job(key)
                if stand_in:
                    child.save(substitute_model=stand_in['model'], substitute=stand_in)
                keys.append(key)
                children.append(child)
                # Link the child before any provider action so a crash can never
                # orphan a paid submission and open a fresh attempt on resume.
                parent.save(attempt_keys=keys)
            child.rate_controller = controller
            attempt_settings = (_substitute_settings(settings, child.state['substitute'])
                                if child.state.get('substitute_model') else settings)
            # A failed legacy checkpoint can contain a placeholder result while
            # its paid remote job is still active. Only a completed checkpoint or
            # a provider receipt establishes that there is a response to validate.
            result = child.state.get('provider_result', child.state.get('result'))
            receipt = child.state.get('provider_result')
            provider_returned = (child.state.get('provider_returned')
                                 or isinstance(receipt, dict) and 'text' in receipt
                                 or child.state.get('status') == 'completed'
                                 and isinstance(result, dict) and 'text' in result)
            received = (provider_returned
                        or child.state.get('status') == 'completed' and 'result' in child.state
                        or _terminal(child.state) and 'provider_result' in child.state)
            raw = child.state.get('raw')
            active = (child.state.get('remote_status') in {'queued', 'in_progress'}
                      or isinstance(raw, dict) and raw.get('status') in {'queued', 'in_progress'})
            reconcile_remote = (child.state.get('remote_id') and not _terminal(child.state)
                                and (active or not provider_returned))
            first, _ = _start_checkpoint(child.state)
            child_started = timestamp()
            had_child_history = any(k != 'key' for k in child.state)
            child.save(status='running', stage='judge', started_at=child_started,
                       first_started_at=first if had_child_history else child_started, error=None)
            provider_error = None
            validation_rejected = False
            if not received or reconcile_remote or child.state.get('submission_unknown'):
                try:
                    result = await provider.judge(task['prompt'], attempt_settings, child)
                except Exception as exc:
                    provider_error = exc
                else:
                    child.save(provider_result=result, provider_returned=True)
            if provider_error is None:
                try:
                    if not isinstance(result, dict):
                        raise ValueError('Judge returned no complete JSON response')
                    verdict = parse_verdict(result.get('text'), require_reason_quality=True)
                except ValueError as exc:
                    provider_error = exc
                    validation_rejected = True
                else:
                    # Checkpoint failures must escape without turning a valid paid
                    # response into a rejected attempt or creating a new submission.
                    result = result | {'verdict': verdict}
                    completed = child.state.get('completed_at') or timestamp()
                    child.save(status='completed', result=result, completed_at=completed, error=None,
                               timing=_job_timing(child.state | {'completed_at': completed}))
                    _save_accounting(parent, children)
                    completed = timestamp()
                    parent.save(status='completed', result=result, completed_at=completed, error=None,
                                timing=_job_timing(parent.state | {'completed_at': completed}))
                    return _row(task, parent, False)
            # Only a returned response or confirmed terminal remote state permits
            # another paid attempt. Poll/transport ambiguity stays on this child.
            rejected = (provider_error is not None
                        and (validation_rejected or _terminal(child.state) or _refused(child.state))
                        and not child.state.get('submission_unknown'))
            finished = timestamp()
            child.save(status='rejected' if rejected else 'failed',
                       error=f'{type(provider_error).__name__}: {provider_error}', failed_at=finished,
                       **({'completed_at': finished} if rejected else {}))
            _save_accounting(parent, children)
            if not rejected:
                parent.save(status='failed', error=f'{type(provider_error).__name__}: {provider_error}',
                            failed_at=finished)
                raise provider_error
