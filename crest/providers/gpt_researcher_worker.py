"""Isolated GPT Researcher worker; imports are credential-free until execution.

The SDK boundary, not upstream cost callbacks, owns the cumulative ledger. Only
native OpenAI text chat requests at the pinned model's standard tariff are allowed.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import copy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

# Direct script execution must also resolve the uninstalled Crest package.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROTOCOL_VERSION = 'gpt-researcher-worker-v1'
PINNED_COMMIT = 'ddd4db36208d9c8e49f3b2436efda97baecb5433'
MODEL = 'gpt-6.1-sol'
DEFAULTS = {
    'model': MODEL, 'reasoning_effort': 'high', 'answer_word_limit': None,
    'budget_usd': 4., 'budget_target_usd': 3.4, 'budget_cap': 'hard',
    'synthesis_reserve_usd': .5, 'deep_research_breadth': 4,
    'deep_research_depth': 3, 'deep_research_concurrency': 2,
    'max_iterations': 3, 'max_search_results_per_query': 5, 'max_research_rounds': 3,
    'max_completion_tokens': 32000, 'synthesis_max_completion_tokens': 32000,
    'max_input_tokens': 64000, 'retry_attempts': 1,
    'call_timeout_seconds': 600., 'timeout_seconds': 5400.,
    'poll_interval_seconds': .5,
}
# Standard USD / million tokens, checked 2026-11-21. No paid tools are enabled.
PRICES = {'input': 2., 'cache_read': .1, 'cache_write': 2.5, 'output': 10.}


def normalize_settings(settings: dict) -> dict:
    aliases = {'max_output_tokens': 'max_completion_tokens',
               'synthesis_max_output_tokens': 'synthesis_max_completion_tokens',
               'breadth': 'deep_research_breadth', 'depth': 'deep_research_depth',
               'max_search_results': 'max_search_results_per_query'}
    settings = {aliases.get(k, k): v for k, v in settings.items()}
    values = {**DEFAULTS, **{k: v for k, v in settings.items() if k in DEFAULTS}}
    if values['model'] != MODEL or values['reasoning_effort'] not in ('high', 'xhigh'):
        raise ValueError('GPT Researcher requires gpt-6.1-sol with high or xhigh reasoning')
    if values['budget_cap'] not in ('hard', 'auto', 'soft'):
        raise ValueError('GPT Researcher budget_cap must be hard, auto, or soft')
    for key in ('budget_usd', 'budget_target_usd', 'synthesis_reserve_usd',
                'call_timeout_seconds', 'timeout_seconds', 'poll_interval_seconds'):
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be positive and finite')
    if not values['synthesis_reserve_usd'] < values['budget_target_usd']:
        raise ValueError('Require synthesis reserve < target')
    if values['budget_cap'] != 'soft' and not values['budget_target_usd'] <= values['budget_usd'] <= 4:
        raise ValueError('Require target <= ceiling <= $4 for hard/auto budgets')
    word_limit = values['answer_word_limit']
    if word_limit is not None and (type(word_limit) is not int or word_limit <= 0):
        raise ValueError('answer_word_limit must be None or a positive integer')
    limits = {'deep_research_breadth': (1, 8),
              'deep_research_depth': (1, 4), 'deep_research_concurrency': (1, 4),
              'max_iterations': (1, 6), 'max_search_results_per_query': (1, 10),
              'max_research_rounds': (1, 3), 'max_completion_tokens': (1, 32000),
              'synthesis_max_completion_tokens': (1, 32000), 'max_input_tokens': (1000, 64000),
              'retry_attempts': (0, 1)}
    for key, (low, high) in limits.items():
        value = values[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be an integer in [{low}, {high}]')
    write_bound = (values['max_input_tokens'] * PRICES['cache_write'] +
                   values['synthesis_max_completion_tokens'] * PRICES['output']) / 1e6
    if values['budget_cap'] != 'soft' and values['synthesis_reserve_usd'] < write_bound:
        raise ValueError('Synthesis reserve cannot cover the bounded final request')
    return values


def atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request_digest(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def build_config(settings: dict) -> dict:
    s = normalize_settings(settings)
    return {
        **{key: f'openai:{MODEL}' for key in ('FAST_LLM', 'SMART_LLM', 'STRATEGIC_LLM')},
        'REASONING_EFFORT': s['reasoning_effort'],
        'LLM_KWARGS': {'reasoning_effort': s['reasoning_effort'], 'temperature': None,
                       'max_tokens': s['max_completion_tokens'], 'max_retries': 0,
                       'timeout': s['call_timeout_seconds'], 'llm_timeout': s['call_timeout_seconds'],
                       'use_responses_api': False},
        'FAST_TOKEN_LIMIT': s['max_completion_tokens'], 'SMART_TOKEN_LIMIT': s['max_completion_tokens'],
        'STRATEGIC_TOKEN_LIMIT': s['max_completion_tokens'],
        'RETRIEVER': 'duckduckgo', 'CONTEXT_FILTER': 'keyword', 'SCRAPER': 'bs',
        'CURATE_SOURCES': False,
        **({'TOTAL_WORDS': s['answer_word_limit']} if s['answer_word_limit'] is not None else {}),
        'MAX_ITERATIONS': s['max_iterations'], 'MAX_SEARCH_RESULTS_PER_QUERY': s['max_search_results_per_query'],
        'DEEP_RESEARCH_BREADTH': s['deep_research_breadth'], 'DEEP_RESEARCH_DEPTH': s['deep_research_depth'],
        'DEEP_RESEARCH_CONCURRENCY': s['deep_research_concurrency'],
        'MAX_SCRAPER_WORKERS': 4, 'IMAGE_GENERATION_ENABLED': False,
        'MCP_STRATEGY': 'disabled', 'MCP_SERVERS': [], 'VERBOSE': False,
    }


class BudgetStop(BaseException):
    """Predispatch stop that bypasses upstream's catch-and-retry ladders."""


class SDKStopped(BaseException):
    """Uncertain or invalid request outcome; never allow an upstream retry."""


class _SDKBoundaryStopped(SDKStopped, Exception):
    """Ordinary Exception while crossing LangChain's gather/callback machinery."""


class _BudgetBoundaryStop(BudgetStop, Exception):
    """Ordinary Exception until outside LangChain; then restore BudgetStop."""


def _input_bound(messages):
    """One definition for both the final writer fit and SDK admission."""
    return len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 256 + 64 * len(messages)


def _fit_prefix(text, fits):
    """Monotone prefix fit, preserving UTF-8/codepoint boundaries and JSON escaping."""
    if not fits(''):
        raise ValueError('Fixed prompt exceeds the bounded request size')
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(text[:middle]):
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _research_context(query, context, limit):
    """Fit evidence only against the pinned learning-extraction messages."""
    prefix = (f"Given the following research results for the query '{query}', extract key learnings and suggest "
              "follow-up questions. For each learning, include a citation to the source URL if available.\n\n"
              "Return ONLY a JSON object using this exact schema:\n"
              '{"learnings": [{"insight": "<insight>", "sourceUrl": "<url or empty string>"}], '
              '"followUpQuestions": ["<question 1>", "<question 2>"]}\n\n'
              "Research results:\n")
    def fits(value):
        return _input_bound([
            {'role': 'system', 'content': 'You are an expert researcher analyzing search results. Return valid JSON only.'},
            {'role': 'user', 'content': prefix + str(value)},
        ]) <= limit
    if fits(context) or not fits(''):
        # Fixed query/instructions are never shortened: native admission remains
        # the backstop when even an empty evidence section cannot fit.
        return context
    text = '\n'.join(str(item) for item in context) if isinstance(context, list) else str(context)
    fitted = _fit_prefix(text, fits)
    if len(fitted) < len(text):
        # Deep run() emits "learning [Source: URL]" lines: keep each learning
        # and citation together. Otherwise retain only whole whitespace tokens,
        # never a newly cut word or URL, even within a long single Content line.
        start = text.rfind('\n', 0, len(fitted)) + 1
        end = text.find('\n', len(fitted))
        line = text[start:end if end >= 0 else len(text)]
        if '[Source:' in line and (end < 0 or len(fitted) < end):
            fitted = fitted[:start]
        elif fitted and not text[len(fitted)].isspace():
            cut = len(fitted)
            while cut and not fitted[cut - 1].isspace():
                cut -= 1
            fitted = fitted[:cut]
        # Source boundaries do not depend on titles being single-line. After
        # either backtrack, drop incomplete headers and newly empty Content
        # blocks, retaining earlier complete source/evidence pairs unchanged.
        end = len(text)
        for source in reversed(list(re.finditer(r'(?m)^Source: ', text))):
            if source.start() < len(fitted):
                content = re.search(r'(?m)^Content: ', text[source.end():end])
                body_start = source.end() + content.end() if content else len(text)
                if fitted[body_start:].strip():
                    break
                fitted = fitted[:source.start()]
            end = source.start()
    if not fitted.strip():
        raise ValueError('No source-associated research evidence fits the request')
    return fitted


def _writer_context(context, prompt, role, limit):
    # Exact custom-prompt messages used by pinned actions/report_generation.py.
    return _fit_prefix(context, lambda value: _input_bound([
        {'role': 'system', 'content': role},
        {'role': 'user', 'content': prompt + '\n\nContext: ' + value},
    ]) <= limit)


def _writer_evidence(captures, prompt, role, limit):
    """Select bounded evidence and its permitted sources together, newest first."""
    def header(items):
        return ('Verified retrieved source URLs (only these may be cited):\n' +
                json.dumps([source['url'] for source in items], ensure_ascii=False) +
                '\n\nResearch evidence (quoted URLs are not retrieval proof):\n')
    def bound(value):
        return _input_bound([{'role': 'system', 'content': role},
            {'role': 'user', 'content': prompt + '\n\nContext: ' + value}])
    base = bound(header([]))
    manifest_bound = base + max(0, limit - base) // 3
    allowed, sections, seen = [], [], set()
    for capture in reversed(captures):
        value = capture['context']
        value = '\n'.join(str(x) for x in value) if isinstance(value, list) else str(value or '')
        sources = _sources(capture['sources'])
        if not value.strip() or value in seen or not sources:
            continue
        candidates = _sources(allowed + sources)
        low, high = len(allowed), len(candidates)
        while low < high:
            middle = (low + high + 1) // 2
            if bound(header(candidates[:middle])) <= manifest_bound:
                low = middle
            else:
                high = middle - 1
        proposed = candidates[:low]
        keys = {_source_key(source['url']) for source in proposed}
        associated = [source['url'] for source in sources if _source_key(source['url']) in keys]
        if not associated:
            continue  # Never include evidence whose entire source set was cut.
        label = 'Evidence capture source URLs: ' + json.dumps(associated, ensure_ascii=False) + '\n'
        prefix = header(proposed) + '\n\n'.join(sections) + ('\n\n' if sections else '') + label
        # Adding a manifest entry must not push earlier evidence out of view or
        # leave this capture's label without a meaningful portion of its text.
        if bound(prefix + value[:min(256, len(value))]) > limit:
            continue
        fitted = _fit_prefix(value, lambda text: bound(prefix + text) <= limit)
        allowed = proposed
        sections.append(label + fitted)
        seen.add(value)
        if len(fitted) < len(value):
            break
    if not sections:
        raise ValueError('No source/evidence pair fits the bounded writer request')
    return header(allowed) + '\n\n'.join(sections), allowed


class ReportValidationError(ValueError):
    """Static reason codes only; never copy arbitrary exception/URL text to logs."""
    def __init__(self, code, *, citation_index=None, url=None):
        messages = {
            'empty_report': 'Empty report',
            'word_limit': 'Answer exceeds the word limit',
            'missing_sources': 'GPT Researcher produced no verifiable source URLs',
            'missing_citations': 'Answer has no linked citations to retrieved sources',
            'unretrieved_citation': 'Answer cites a URL that was not a retrieved source',
            'unsupported_citation': 'Answer contains unsupported HTML or image citation markup',
        }
        super().__init__(messages[code])
        self.diagnostic = {'code': code}
        if citation_index is not None:
            self.diagnostic['citation_index'] = citation_index
        if url is not None:
            self.diagnostic['url_sha256'] = hashlib.sha256(url.encode()).hexdigest()


def _record_answer(text, sources, allowed, usage, request, settings, path):
    # This is an audit artifact, never a completed result or authorization to
    # replay synthesis. Preserve exact returned text before any local validation.
    receipt = {key: request.get(key) for key in
               ('protocol_version', 'job_key', 'worker_id', 'source_identity')}
    receipt.update(request_sha256=request_digest(request), status='unvalidated',
        text=text if isinstance(text, str) else None,
        text_sha256=hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None,
        retrieved_sources=_sources(sources), allowed_sources=allowed,
        settings=normalize_settings(settings), usage=usage)
    atomic_json(path, receipt)
    try:
        result = extract_result(text, allowed, usage, request['source_identity'], settings)
    except ReportValidationError as exc:
        receipt.update(status='rejected', validation=exc.diagnostic)
        atomic_json(path, receipt)
        raise
    receipt.update(status='validated', validation={'code': 'passed'})
    atomic_json(path, receipt)
    result['raw']['retrieved_sources'] = receipt['retrieved_sources']
    return result


def _mapping(value):
    if isinstance(value, dict):
        return value
    if callable(getattr(value, 'model_dump', None)):
        return value.model_dump(mode='json')
    return vars(value) if value is not None and hasattr(value, '__dict__') else {}


class UsageAudit:
    """Persist-before-dispatch accounting shared by every nested SDK client.

    For text-only chat, UTF-8 bytes plus framing allowance conservatively bound
    ordinary BPE input tokens. Unknown outcomes retain their *entire* reservation.
    A ledger amount is a list-price usage estimate, not an invoice or fabricated
    observed spend. No client internal retries or provider fallback is permitted.
    """
    def __init__(self, path: Path, settings: dict):
        self.path = Path(path)
        self.settings = normalize_settings(settings)
        self.phase = 'research'
        self.deadline = time.monotonic() + self.settings['timeout_seconds']
        self.settlement_grace = min(5., .1 * self.settings['call_timeout_seconds'])
        self.phase_headroom = self.settings['call_timeout_seconds'] + self.settlement_grace
        self.research_deadline = self.deadline - 2 * self.phase_headroom
        self.active_calls = {}  # Strong references to shielded SDK settlement tasks; never serialized.
        self.events = []
        self.pending = {}
        self.lock = threading.RLock()
        self.research_stopped = False
        self.terminal_failure = None
        self.quarantined = False
        self.phase_stops = {}
        self.search_calls = 0
        self.persist()

    def snapshot(self):
        with self.lock:
            known = math.fsum(e.get('cost_usd') or 0. for e in self.events)
            reserved = math.fsum(e['reserved_usd'] for e in self.events if e.get('unknown_cost'))
            reserved += math.fsum(e['reserved_usd'] for e in self.pending.values())
            unknown = bool(self.pending) or any(e.get('unknown_cost') for e in self.events)
            inputs = sum(e['input_tokens'] for e in self.events if e['status'] == 'completed')
            outputs = sum(e['output_tokens'] for e in self.events if e['status'] == 'completed')
            return {'cost_usd': None if unknown else known, 'known_cost_usd': known,
                    'reserved_usd': reserved, 'upper_bound_usd': known + reserved,
                    'unknown_cost': unknown, 'input_tokens': inputs, 'output_tokens': outputs,
                    'total_tokens': inputs + outputs,
                    'successful_calls': sum(e['status'] == 'completed' for e in self.events),
                    'failed_calls': sum(e['status'] != 'completed' for e in self.events),
                    'retry_calls': sum(e.get('attempt', 0) > 0 for e in self.events),
                    'rate_limit_events': sum(e.get('status_code') == 429 for e in self.events),
                    'search_calls': self.search_calls, 'paid_tool_cost_usd': 0.,
                    'budget_cap': self.settings['budget_cap'],
                    'budget_usd': self.settings['budget_usd'],
                    'budget_overrun_usd': max(0., known - self.settings['budget_usd']),
                    'projected_budget_overrun_usd': max(0., known + reserved - self.settings['budget_usd']),
                    'budget_target_usd': self.settings['budget_target_usd'],
                    'synthesis_reserve_usd': self.settings['synthesis_reserve_usd'],
                    'research_stopped': self.research_stopped,
                    'terminal_failure': self.terminal_failure, 'phase_stops': self.phase_stops.copy(),
                    'quarantined': self.quarantined,
                    'reasoning_effort': self.settings['reasoning_effort'],
                    'prices_per_million': PRICES.copy(), 'cost_basis': 'sdk_usage_priced_estimate',
                    'events': copy.deepcopy(self.events), 'in_flight': copy.deepcopy(list(self.pending.values()))}

    def persist(self):
        atomic_json(self.path, self.snapshot())

    def latch(self, error):
        """A terminal circuit never reopens; a research stop still permits synthesis."""
        with self.lock:
            if isinstance(error, BudgetStop):
                self.phase_stops.setdefault(self.phase, 'request_bound')
                self.research_stopped = self.research_stopped or self.phase == 'research'
            else:
                self.terminal_failure = self.terminal_failure or type(error).__name__
            try:
                self.persist()
            except Exception:
                # The previous durable reservation remains authoritative if the disk fails.
                pass

    def raise_if_stopped(self, *, allow_phase_stop=False):
        with self.lock:
            if self.terminal_failure:
                raise SDKStopped('Audit circuit is permanently open after a terminal outcome')
            if not allow_phase_stop and self.phase in self.phase_stops:
                raise BudgetStop('This research phase has reached a request bound')

    def quarantine(self):
        # A single-use worker with surviving work must never restore unaudited SDK
        # methods. Keep the permanent terminal guard until this process exits.
        self.quarantined = True
        self.latch(SDKStopped('Unsafe task teardown; worker quarantined'))

    def close_research(self, reason='completed'):
        """Admission closes before draining; it cannot reopen under synthesis's budget."""
        with self.lock:
            self.phase_stops.setdefault('research', reason)
            if reason != 'completed':
                self.research_stopped = True
            self.persist()

    def stop(self, error):
        self.latch(error)
        raise error

    def before(self, options, *, attempt=0):
        self.raise_if_stopped()
        if self.phase == 'research' and time.monotonic() >= self.research_deadline:
            self.close_research('time_headroom')
            raise BudgetStop('Research admission closed to preserve drain and synthesis time')
        if self.phase == 'synthesis' and time.monotonic() + self.settings['call_timeout_seconds'] > self.deadline:
            self.stop(SDKStopped('Insufficient synthesis request time remains'))
        # The SDK merges extra_json AFTER this hook. Do not allow a deferred
        # body to replace any model, budget, tool, or effort field we audit.
        extra = getattr(options, 'extra_json', None)
        if extra is not None and (not isinstance(extra, dict) or extra):
            self.stop(SDKStopped('Deferred SDK body overrides are not allowed'))
        data = getattr(options, 'json_data', None)
        if not isinstance(data, dict) or getattr(options, 'url', '') != '/chat/completions':
            self.stop(SDKStopped('Only audited native text chat requests are allowed'))
        if str(getattr(options, 'method', 'post')).lower() != 'post':
            self.stop(SDKStopped('Unexpected SDK request method'))
        allowed = {'model', 'messages', 'max_tokens', 'max_completion_tokens', 'reasoning_effort',
                   'temperature', 'stream', 'stream_options', 'response_format', 'stop', 'n',
                   'service_tier', 'seed', 'user', 'store', 'logprobs', 'top_logprobs'}
        if set(data) - allowed or data.get('model') != MODEL or data.get('stream') or data.get('n', 1) != 1:
            self.stop(SDKStopped('Unpriced model, tool, streaming or request option refused'))
        if data.get('service_tier', 'default') not in ('default', None):
            self.stop(SDKStopped('Only standard service-tier pricing is allowed'))
        messages = data.get('messages')
        if not isinstance(messages, list) or any(not isinstance(m, dict) or not isinstance(m.get('content'), str)
                                               or m.get('role') not in ('system', 'developer', 'user', 'assistant')
                                               or set(m) - {'role', 'content', 'name'} for m in messages):
            self.stop(SDKStopped('Only bounded plain-text chat messages are allowed'))
        input_bound = _input_bound(messages)
        limit = self.settings['synthesis_max_completion_tokens' if self.phase == 'synthesis' else 'max_completion_tokens']
        supplied = data.get('max_completion_tokens', data.get('max_tokens'))
        output_bound = min(supplied, limit) if type(supplied) is int and supplied > 0 else limit
        if input_bound > self.settings['max_input_tokens']:
            self.stop(BudgetStop('Input exceeds the conservative text-token bound'))
        data.pop('max_tokens', None)
        data.pop('temperature', None)
        data.pop('stream_options', None)
        data.update(max_completion_tokens=output_bound, reasoning_effort=self.settings['reasoning_effort'],
                    service_tier='default')
        reserve = (input_bound * PRICES['cache_write'] + output_bound * PRICES['output']) / 1e6
        with self.lock:
            self.raise_if_stopped()
            ceiling = self.settings['budget_usd']
            if self.phase == 'research':
                ceiling = min(ceiling, self.settings['budget_target_usd']) - self.settings['synthesis_reserve_usd']
            # Soft references are advisory: even an already exceeded reference
            # cannot reject an otherwise valid paid request. Reservations remain
            # visible; research still hands off at the next outer-round boundary.
            if (self.settings['budget_cap'] != 'soft' and
                    self.snapshot()['upper_bound_usd'] + reserve > ceiling + 1e-12):
                self.research_stopped = self.phase == 'research'
                self.persist()
                self.stop(BudgetStop('Request cannot fit while preserving the synthesis reserve'))
            token = uuid4().hex
            self.pending[token] = {'request_id': token, 'model': MODEL, 'phase': self.phase,
                                   'reasoning_effort': self.settings['reasoning_effort'],
                                   'attempt': attempt, 'input_bound': input_bound,
                                   'output_bound': output_bound, 'reserved_usd': reserve, 'unknown_cost': True}
            self.persist()
            return token

    def after(self, token, response=None, error=None):
        try:
            event = self._settle(token, response=response, error=error)
        except BaseException as exc:
            self.latch(exc)
            raise
        if event.get('unknown_cost'):
            self.latch(SDKStopped('Uncertain request outcome'))
        return event

    def _settle(self, token, response=None, error=None):
        with self.lock:
            # An interrupted rollback can leave both the charge and reservation.
            # Reconcile by admitted request ID rather than charging a redelivery.
            existing = next((item for item in self.events if item.get('request_id') == token), None)
            had_reservation = token in self.pending
            reserved_event = self.pending.get(token, existing)
            if reserved_event is None:
                raise SDKStopped('Cannot settle a request without an admission record')
            event = copy.deepcopy(reserved_event)
            if error is not None:
                status = getattr(error, 'status_code', None)
                rejected = status in (401, 403, 429)
                event.update(status='failed', status_code=status, error_type=type(error).__name__,
                             unknown_cost=not rejected, cost_usd=0. if rejected else None)
                if rejected:
                    event['reserved_usd'] = 0.
            else:
                usage = _mapping(getattr(response, 'usage', None))
                inputs, outputs = usage.get('prompt_tokens'), usage.get('completion_tokens')
                details = _mapping(usage.get('prompt_tokens_details'))
                cached, written = details.get('cached_tokens', 0) or 0, details.get('cache_write_tokens', 0) or 0
                valid = all(type(v) is int and v >= 0 for v in (inputs, outputs, cached, written))
                valid = valid and cached + written <= inputs
                model = getattr(response, 'model', MODEL)
                valid = valid and (model == MODEL or str(model).startswith(MODEL + '-'))
                cost = ((inputs - cached - written) * PRICES['input'] + cached * PRICES['cache_read'] +
                        written * PRICES['cache_write'] + outputs * PRICES['output']) / 1e6 if valid else None
                event.update(status='completed' if valid else 'unknown', input_tokens=inputs, output_tokens=outputs,
                             raw_usage=usage, response_model=model, provider_request_id=getattr(response, '_request_id', None),
                             unknown_cost=not valid, cost_usd=cost)
                if valid:
                    event['reserved_usd'] = 0.
            if existing is not None and event != existing:
                raise SDKStopped('Conflicting receipt for an already recorded request')
            try:
                # Record the charge BEFORE releasing its reservation. Repeated
                # receipts release only a shadow reservation, never append again.
                if existing is None:
                    self.events.append(event)
                if had_reservation:
                    self.pending.pop(token)
                self.persist()
            except BaseException:
                # Restore conservative exposure before removing a NEW charge.
                # Never remove the existing charge when reconciling a duplicate.
                if had_reservation:
                    self.pending[token] = reserved_event
                if existing is None and self.events and self.events[-1] is event:
                    self.events.pop()
                raise SDKStopped('Cannot persist settlement; exposure retained') from None
            if error is None:
                if event['unknown_cost']:
                    raise SDKStopped('Accepted response has no valid usage; reservation retained')
                if inputs > event['input_bound'] or outputs > event['output_bound']:
                    raise SDKStopped('Provider usage exceeded the request bound; review the audit')
                choices = getattr(response, 'choices', [])
                if not choices or any(getattr(c, 'finish_reason', None) != 'stop' or
                                      not getattr(getattr(c, 'message', None), 'content', '') for c in choices):
                    raise SDKStopped('Billed response was empty or incomplete; no automatic paid replay')
            return event

    @contextmanager
    def installed(self, sync_class, async_class=None):
        original_sync = sync_class.request
        original_async = async_class.request if async_class else None
        audit = self

        def prepare(instance, options):
            if str(instance.base_url).rstrip('/') != 'https://api.openai.com/v1':
                raise SDKStopped('Only the native OpenAI endpoint is allowed')
            instance.max_retries = 0
            if hasattr(options, 'max_retries'):
                options.max_retries = 0

        def can_retry(error, attempt):
            return getattr(error, 'status_code', None) == 429 and attempt < audit.settings['retry_attempts']

        def dispatch(instance, cast_to, options, **kwargs):
            prepare(instance, options)
            for attempt in range(audit.settings['retry_attempts'] + 1):
                try:
                    token = audit.before(options, attempt=attempt)
                except Exception:
                    raise SDKStopped('Cannot persist request reservation; no request sent') from None
                try:
                    result = original_sync(instance, cast_to, options, **kwargs)
                    if not hasattr(result, 'usage') and callable(getattr(result, 'parse', None)):
                        parsed = result.parse()
                    else:
                        parsed = result
                except BaseException as error:
                    audit.after(token, error=error)
                    if can_retry(error, attempt):
                        time.sleep(1.)
                        continue
                    raise SDKStopped(f'SDK {type(error).__name__}; stopped without upstream retry') from None
                audit.after(token, response=parsed)
                return result

        async def settle_request(instance, cast_to, options, token, kwargs):
            # The task that owns the accepted HTTP request also owns settlement.
            # Caller cancellation never settles it speculatively as zero/unknown.
            try:
                remaining = max(0., audit.deadline - time.monotonic())
                async with asyncio.timeout(min(audit.settings['call_timeout_seconds'], remaining)):
                    result = await original_async(instance, cast_to, options, **kwargs)
                    if not hasattr(result, 'usage') and callable(getattr(result, 'parse', None)):
                        parsed = result.parse()
                        if inspect.isawaitable(parsed):
                            parsed = await parsed
                    else:
                        parsed = result
            except BaseException as error:
                audit.after(token, error=error)
                raise
            audit.after(token, response=parsed)
            return result

        def finished(token, task):
            audit.active_calls.pop(token, None)
            if not task.cancelled():
                task.exception()  # A cancelled caller may no longer retrieve the exception.

        async def adispatch(instance, cast_to, options, **kwargs):
            prepare(instance, options)
            for attempt in range(audit.settings['retry_attempts'] + 1):
                try:
                    token = audit.before(options, attempt=attempt)
                except Exception:
                    raise SDKStopped('Cannot persist request reservation; no request sent') from None
                task = asyncio.create_task(settle_request(instance, cast_to, options, token, kwargs))
                audit.active_calls[token] = task
                task.add_done_callback(lambda done, key=token: finished(key, done))
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    if (task.done() and token not in audit.pending and not audit.terminal_failure
                            and audit.phase in audit.phase_stops):
                        raise BudgetStop('Settled request tail cancelled after research closed') from None
                    # Settlement continues in the tracked task. The caller may fail,
                    # but the worker's drain still gets the actual usage receipt.
                    raise SDKStopped('Caller cancelled while an admitted request is settling') from None
                except BaseException as error:
                    if can_retry(error, attempt):
                        await asyncio.sleep(1.)
                        continue
                    raise SDKStopped(f'SDK {type(error).__name__}; stopped without upstream retry') from None
        def boundary(error):
            if (isinstance(error, asyncio.CancelledError) and not audit.pending
                    and not audit.terminal_failure and audit.phase in audit.phase_stops):
                error = BudgetStop('Unpaid retry/backoff cancelled after research closed')
            audit.latch(error)
            if isinstance(error, BudgetStop):
                return _BudgetBoundaryStop('Request bound reached; synthesis reserve preserved')
            return _SDKBoundaryStopped('Terminal SDK outcome; audit circuit permanently open')

        def request(instance, cast_to, options, **kwargs):
            try:
                return dispatch(instance, cast_to, options, **kwargs)
            except BaseException as exc:
                raise boundary(exc) from None

        async def arequest(instance, cast_to, options, **kwargs):
            try:
                return await adispatch(instance, cast_to, options, **kwargs)
            except BaseException as exc:
                raise boundary(exc) from None

        sync_class.request = request
        if async_class:
            async_class.request = arequest
        try:
            yield
        finally:
            if audit.pending or any(not task.done() for task in audit.active_calls.values()):
                audit.quarantine()
            if not audit.quarantined:
                sync_class.request = original_sync
                if async_class:
                    async_class.request = original_async


def _source_key(url):
    """Match the retrieved resource, allowing fragments but not invented paths."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
            return None
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', parts.query, ''))
    except ValueError:
        return None


def _sources(sources):
    result = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get('url') or source.get('href')
        key = _source_key(url)
        if key:
            result.setdefault(key, {'url': url, 'title': source.get('title') or url})
    return list(result.values())


def _citation_urls(text):
    """Parse rendered Markdown destinations, never source labels or code blocks."""
    from markdown_it import MarkdownIt
    parser = MarkdownIt('commonmark')
    # CommonMark decoding happens once inside the parser. Do not additionally
    # URL-normalize/HTML-decode an already-decoded resource identifier.
    parser.normalizeLink = lambda url: url
    # Parse otherwise-disallowed schemes too, so they cannot hide a URL label
    # as plain text. Our exact retrieved-resource check rejects the destination.
    parser.validateLink = lambda url: True
    bare = re.compile(r"https?://[^\s<>\"\]“”]+", re.IGNORECASE)
    for block in parser.parse(text):
        if block.type == 'html_block':
            raise ReportValidationError('unsupported_citation')
        if block.type != 'inline':
            continue  # Fenced/indented code is never citation evidence.
        link_depth = 0
        for token in block.children or []:
            if token.type in ('html_inline', 'image'):
                raise ReportValidationError('unsupported_citation')
            if token.type == 'link_open':
                link_depth += 1
                url = token.attrGet('href') or ''
                if not url.startswith('#'):
                    yield url, True
            elif token.type == 'link_close':
                link_depth -= 1
            elif token.type == 'text' and not link_depth:
                # Text tokens have already undergone Markdown's single decode.
                for match in bare.finditer(token.content):
                    yield match.group(), False


def _cited_sources(text, sources):
    retrieved = {_source_key(source['url']): source for source in sources}
    cited = {}
    # Bare URLs, inline Markdown links, autolinks and reference definitions all
    # expose their target URL. Every external URL must identify a retrieved page.
    for index, (candidate, delimited) in enumerate(_citation_urls(text)):
        url = candidate
        if not delimited:
            # Only bare URLs may carry prose punctuation. In a Markdown or
            # angle-delimited destination, terminal !/. etc. belong to the URL.
            url = url.rstrip('.,;:!?')
            while url.endswith(')') and url.count(')') > url.count('('):
                url = url[:-1]
        key = _source_key(url)
        if key not in retrieved:
            raise ReportValidationError('unretrieved_citation', citation_index=index, url=url)
        cited.setdefault(key, retrieved[key])
    if not cited:
        raise ReportValidationError('missing_citations')
    return list(cited.values())


def extract_result(text, sources, usage, identity, settings):
    s = normalize_settings(settings)
    retrieved = _sources(sources)
    if not isinstance(text, str) or not text.strip():
        raise ReportValidationError('empty_report')
    if s['answer_word_limit'] is not None and len(text.split()) > s['answer_word_limit']:
        raise ReportValidationError('word_limit')
    if not retrieved:
        raise ReportValidationError('missing_sources')
    citations = _cited_sources(text, retrieved)
    warnings = ['Uncertain billed usage; inspect retained reservations.'] if usage.get('unknown_cost') else []
    if s['budget_cap'] == 'soft':
        if usage.get('known_cost_usd', 0.) > s['budget_usd'] + 1e-12:
            warnings.append('Soft budget reference exceeded by known metered usage; no dollar cutoff was applied.')
        elif usage.get('upper_bound_usd', 0.) > s['budget_usd'] + 1e-12:
            warnings.append('Projected exposure exceeds the soft budget reference; reservations are not known spend.')
    return {'text': text.strip(), 'model': MODEL, 'citations': citations, 'usage': usage,
            'cost_usd': None if usage.get('unknown_cost') else usage.get('cost_usd'),
            'cost_estimated': True, 'warnings': warnings,
            'raw': {'gpt_researcher_audit': usage, 'accounting': usage, 'source_identity': identity, 'sources': citations,
                    'retrieved_sources': retrieved, 'protocol_version': PROTOCOL_VERSION, 'word_count': len(text.split())}}


@contextmanager
def _runtime(settings, audit, captures):
    """Patch only this isolated process, never tracked upstream source files."""
    import openai
    from gpt_researcher import GPTResearcher
    from gpt_researcher.skills.deep_research import DeepResearchSkill
    from gpt_researcher.config.config import Config
    from gpt_researcher.llm_provider.generic.base import GenericLLMProvider
    from gpt_researcher.retrievers.duckduckgo.duckduckgo import Duckduckgo
    original_response = GenericLLMProvider.get_chat_response
    original_conduct = GPTResearcher.conduct_research
    original_results = DeepResearchSkill.process_research_results
    original_search = Duckduckgo.search
    original_parser = inspect.getattr_static(Config, 'parse_reasoning_effort')

    def parse_effort(value):
        # The pinned upstream enum predates xhigh. Extend only this one value;
        # delegate every existing value/error and preserve staticmethod binding.
        return 'xhigh' if value == 'xhigh' else original_parser.__func__(value)

    async def nonstream(self, messages, stream=False, websocket=None, **kwargs):
        # Upstream writers request a stream. Force the provider's documented
        # nonstream path so SDK usage is complete before the request is settled.
        audit.raise_if_stopped()
        try:
            result = await original_response(self, messages, False, None, **kwargs)
        except BaseException:
            # LangChain may wrap an SDK exception. Restore the terminal signal
            # *outside* LangChain so upstream's Exception retry ladder cannot eat it.
            audit.raise_if_stopped()
            audit.latch(SDKStopped('Provider processing failed'))
            audit.raise_if_stopped()
            raise
        # A phase-only stop blocks NEW requests, not the useful result of a
        # previously admitted, now-settled request. Terminal failures still stop.
        audit.raise_if_stopped(allow_phase_stop=True)
        return result

    async def conduct(self, *args, **kwargs):
        context = await original_conduct(self, *args, **kwargs)
        if context and _sources(self.get_research_sources()):
            captures.append({'context': context, 'sources': self.get_research_sources()})
            atomic_json(audit.path.with_name('evidence.json'), {'captures': captures})
        return context

    async def bounded_results(self, query, context, num_learnings=3):
        fitted = _research_context(query, context, audit.settings['max_input_tokens'])
        return await original_results(self, query, fitted, num_learnings)

    def search(self, *args, **kwargs):
        with audit.lock:
            audit.search_calls += 1
            audit.persist()
        return original_search(self, *args, **kwargs)

    Config.parse_reasoning_effort = staticmethod(parse_effort)
    GenericLLMProvider.get_chat_response = nonstream
    GPTResearcher.conduct_research = conduct
    DeepResearchSkill.process_research_results = bounded_results
    Duckduckgo.search = search
    try:
        with audit.installed(openai.OpenAI, openai.AsyncOpenAI):
            yield GPTResearcher
    finally:
        if not audit.quarantined:
            Config.parse_reasoning_effort = original_parser
            GenericLLMProvider.get_chat_response = original_response
            GPTResearcher.conduct_research = original_conduct
            DeepResearchSkill.process_research_results = original_results
            Duckduckgo.search = original_search


def _context(captures, byte_limit):
    parts = []
    seen = set()
    for capture in reversed(captures):
        value = capture['context']
        value = '\n'.join(str(x) for x in value) if isinstance(value, list) else str(value)
        if value not in seen:
            seen.add(value)
            parts.append(value)
    return _fit_prefix('\n\n'.join(parts),
        lambda text: len(json.dumps(text, ensure_ascii=False).encode('utf-8')) <= max(2, byte_limit))


async def _finish_research(audit, baseline):
    """Drain accepted requests before cancelling unpaid tails, within reserved time."""
    audit.close_research()
    drain_deadline = min(time.monotonic() + audit.phase_headroom,
                         audit.deadline - audit.phase_headroom)
    expired = False
    while audit.snapshot()['in_flight']:
        remaining = drain_deadline - time.monotonic()
        if remaining <= 0:
            expired = True
            audit.latch(SDKStopped('Accepted-request drain deadline expired'))
            break
        active = {task for task in audit.active_calls.values() if not task.done()}
        if active:
            await asyncio.wait(active, timeout=min(.05, remaining))
        else:
            # A synchronous SDK call can settle from another thread.
            await asyncio.sleep(min(.01, remaining))

    # Give settled responses a bounded chance to finish parsing/capture evidence.
    # The research circuit is closed, so these tails cannot admit another call.
    pending = {task for task in asyncio.all_tasks() - baseline if not task.done()}
    if pending and not expired:
        await asyncio.wait(pending, timeout=max(0., min(audit.settlement_grace,
                                                       drain_deadline - time.monotonic())))
    pending = {task for task in asyncio.all_tasks() - baseline if not task.done()}
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=max(0., min(audit.settlement_grace,
                                                       audit.deadline - time.monotonic())))
    # Retrieve child exceptions (including intentional phase-boundary stops).
    for task in (asyncio.all_tasks() - baseline) | pending:
        if task.done() and not task.cancelled():
            task.exception()
    if any(not task.done() for task in asyncio.all_tasks() - baseline):
        audit.quarantine()
        raise SDKStopped('Research tasks remain alive; refusing a synthesis phase switch')
    if expired or audit.snapshot()['unknown_cost']:
        if audit.pending:
            audit.quarantine()
        audit.latch(SDKStopped('Research requests did not settle to known usage'))
        raise SDKStopped('Unresolved research requests require review before synthesis')
    audit.raise_if_stopped(allow_phase_stop=True)


async def research(request, audit, researcher_class, captures):
    s = audit.settings
    config_path = audit.path.with_name('config.json')
    atomic_json(config_path, build_config(s))
    original_prompt = request['prompt']
    context_limit = s['max_input_tokens'] - len(original_prompt.encode()) - 6000
    if context_limit < 1000:
        raise ValueError('Prompt leaves insufficient bounded evidence context')
    rounds = 0
    warnings = []

    async def conduct_rounds():
        nonlocal rounds
        researcher = researcher_class(query=original_prompt, report_type='deep', report_source='web',
                                     config_path=str(config_path), verbose=False, mcp_strategy='disabled')
        followups_seen, previous_urls = set(), set()
        while rounds < s['max_research_rounds']:
            rounds += 1
            await researcher.conduct_research()
            urls = {item['url'] for c in captures for item in _sources(c['sources'])}
            if not urls:
                raise ValueError('No sources retrieved; refusing a model-only answer')
            if urls == previous_urls or rounds >= s['max_research_rounds']:
                break
            previous_urls = urls
            if audit.snapshot()['upper_bound_usd'] >= s['budget_target_usd'] - s['synthesis_reserve_usd']:
                break
            findings = await researcher.deep_researcher.process_research_results(
                original_prompt, _context(captures, context_limit))
            followups = [q.strip() for q in findings.get('followUpQuestions', [])
                         if isinstance(q, str) and q.strip() and q.strip() not in followups_seen]
            if not followups:
                break
            followups_seen.update(followups)
            next_query = original_prompt + '\n\nResearch these evidence-driven follow-up questions, avoiding repeated findings:\n' + '\n'.join(followups[:3])
            researcher = researcher_class(query=next_query, report_type='deep', report_source='web',
                config_path=str(config_path), verbose=False, mcp_strategy='disabled', visited_urls=set(urls))

    baseline = asyncio.all_tasks()
    stage = asyncio.create_task(conduct_rounds())
    try:
        # Unlike wait_for/timeout, wait does NOT cancel an admitted request when
        # the research allowance ends. Admission closes, then the drain owns it.
        done, _ = await asyncio.wait({stage}, timeout=max(0., audit.research_deadline - time.monotonic()))
        if not done:
            audit.close_research('time_headroom')
            warnings.append('Research time allowance ended; drained accepted requests before synthesis.')
        else:
            try:
                stage.result()
            except BudgetStop:
                audit.close_research('request_bound')
                warnings.append('Research stopped at a request bound; synthesized saved evidence within reserve.')
    finally:
        try:
            await _finish_research(audit, baseline)
        finally:
            if stage.done() and not stage.cancelled():
                stage.exception()

    sources = [source for capture in captures for source in capture['sources']]
    context = _context(captures, context_limit)
    if not context.strip() or not _sources(sources):
        raise ValueError('No source-backed context survived research; refusing synthesis')
    audit.phase = 'synthesis'
    writer_role = 'You are a research writer. Cite only the supplied source-backed evidence.'
    writer = researcher_class(query=original_prompt, report_type='deep', report_source='web',
                             config_path=str(config_path), verbose=False, mcp_strategy='disabled', role=writer_role)
    writer.cfg.llm_kwargs['max_tokens'] = s['synthesis_max_completion_tokens']
    writer.cfg.smart_token_limit = s['synthesis_max_completion_tokens']
    length_instruction = (f' At most {s["answer_word_limit"]} words; aim below the limit.'
                          if s['answer_word_limit'] is not None else '')
    # Always use the pinned writer's custom-prompt branch. It bypasses upstream's
    # default TOTAL_WORDS minimum (1200); no None/implicit word target reaches the model.
    custom_prompt = (original_prompt + '\n\nReturn only the final answer.' + length_instruction +
        ' Use inline Markdown links to the supplied source URLs; no separate reference list. '
        'Do not invent sources. Preserve the original task and clearly qualify uncertainties. '
        'Cite only exact URLs in the verified retrieved source manifest; quoted or bibliographic URLs '
        'not in the manifest are unverified and cannot be cited. The manifest authorizes URLs, '
        'not claims: cite a listed source only when the supplied evidence supports the claim.')
    context, allowed = _writer_evidence(captures, custom_prompt, writer_role, s['max_input_tokens'])
    text = await writer.write_report(ext_context=context, custom_prompt=custom_prompt)
    result = _record_answer(text, sources, allowed, audit.snapshot(), request, s,
                            audit.path.with_name('final-answer.json'))
    result['warnings'].extend(warnings)
    result['raw']['research_rounds'] = rounds
    result['raw']['upstream_estimated_cost_usd'] = writer.get_costs()
    return result


def _validate_request(request, result_path):
    if request.get('protocol_version') != PROTOCOL_VERSION:
        raise ValueError('Unsupported worker protocol')
    if not isinstance(request.get('job_key'), str) or not re.fullmatch(r'[a-f0-9]{64}', request['job_key']):
        raise ValueError('Invalid job key')
    if not isinstance(request.get('worker_id'), str) or not re.fullmatch(r'[a-f0-9]{32}', request['worker_id']):
        raise ValueError('Invalid worker identity')
    if not isinstance(request.get('prompt'), str) or not request['prompt'].strip():
        raise ValueError('Missing research prompt')
    if Path(request['output_dir']).resolve() != result_path.parent / 'gpt-researcher-output':
        raise ValueError('Unexpected worker output directory')


def run(request_path: Path, result_path: Path):
    request_path, result_path = request_path.resolve(), result_path.resolve()
    request = json.loads(request_path.read_text())
    _validate_request(request, result_path)
    if result_path.exists():
        raise ValueError('Existing result must not be overwritten')
    output = Path(request['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    # Exclusive durable claim: even direct duplicate worker invocations cannot pay twice.
    fd = os.open(output / 'started.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump({'job_key': request['job_key'], 'worker_id': request['worker_id']}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    envelope = {k: request[k] for k in ('protocol_version', 'job_key', 'worker_id', 'source_identity')}
    envelope['request_sha256'] = request_digest(request)
    audit = None
    try:
        settings = normalize_settings(request['settings'])
        from crest.providers.gpt_researcher import identity_metadata
        if identity_metadata(request['settings']) != request['source_identity']:
            raise ValueError('Source identity changed before worker execution')
        if not os.environ.get('OPENAI_API_KEY'):
            raise ValueError('OPENAI_API_KEY is required')
        root = Path(request['settings']['source_path'])
        sys.path.insert(0, str(root))
        for key in set(build_config(settings)) | {'CONFIG_PATH', 'LLM_TIMEOUT', 'OPENAI_BASE_URL',
                    'TYPESAFE_API_KEY', 'TAVILY_API_KEY', 'MONOCLE_TRACING', 'LANGSMITH_TRACING'}:
            os.environ.pop(key, None)
        os.environ['PYTHON_DOTENV_DISABLED'] = '1'
        os.environ['LLM_TIMEOUT'] = str(settings['call_timeout_seconds'])
        audit = UsageAudit(output / 'usage.json', settings)
        captures = []
        with _runtime(settings, audit, captures) as cls:
            async def timed():
                async with asyncio.timeout(max(0., audit.deadline - time.monotonic())):
                    return await research(request, audit, cls, captures)
            result = asyncio.run(timed())
        envelope.update(status='completed', result=result)
    except BaseException as exc:
        # Do not persist SDK exception messages: these can echo credentials or inputs.
        envelope.update(status='failed', error=f'GPT Researcher stopped: {type(exc).__name__}; inspect usage/evidence receipts',
                        usage=audit.snapshot() if audit else {'cost_usd': 0., 'known_cost_usd': 0., 'unknown_cost': False})
        if isinstance(exc, ReportValidationError):
            envelope['validation_error'] = exc.diagnostic
            envelope['error'] = ('GPT Researcher final validation failed: ' + exc.diagnostic['code'] +
                                 '; inspect final-answer.json and usage receipts; no automatic replay')
    atomic_json(result_path, envelope)
    return envelope


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args(argv)
    def stopped(signum, frame):
        raise SDKStopped('Worker terminated')
    signal.signal(signal.SIGTERM, stopped)
    run(args.request, args.result)


if __name__ == '__main__':
    main()
