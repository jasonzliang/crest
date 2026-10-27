"""Small, explicit configuration and exact-text JSONL question loading."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .cache import digest
from .artifacts import DEFAULT_RESULTS_TIMEZONE

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'crest/configs/crest.yaml'
DEFAULTS = {
    'questions': '../data/queries_n50.jsonl',
    'rubric': '../prompts/nus_pairwise_v2.txt',
    'cache_dir': '../results/.cache/generation', 'output_dir': '../results',
    'results_timezone': DEFAULT_RESULTS_TIMEZONE,
    'research_prompt': (
        'Answer the question below, producing the requested artifact rather than a research plan. '
        'Follow its explicit requirements, format and length. Research relevant evidence and '
        'cite sources for factual claims when appropriate. Clearly distinguish proposals and '
        'invented examples from established facts. Do not identify your model or provider.\n\n'
        'QUESTION:\n{question}'
    ),
    'research': {
        'caesar': {
            'rome_path': '../../../rome', 'python_executable': sys.executable,
            'recovery_from': None, 'budget_history_from': None,
            'model': 'gpt-6.1-sol', 'exploration_model': 'gpt-6-luna',
            'kb_model': 'gpt-6-luna', 'budget_usd': 5.0, 'handler_budget_usd': 5.0,
            'reasoning_effort': 'medium', 'synthesis_reasoning_effort': 'medium',
            'exploration_reasoning_effort': 'low', 'kb_reasoning_effort': 'low',
            'max_iterations': 250, 'synthesis_drafts': 3, 'synthesis_iterations': 15,
            'synthesis_top_k': 15, 'synthesis_top_n': 10,
            'additional_starting_queries': 11, 'use_quick_explore': False,
            'quick_explore_insights': True, 'quick_explore_workers': 2,
            'adapt_role': True, 'synthesis_merge_artifacts': True,
            'max_completion_tokens': 25000, 'query_max_completion_tokens': 6000,
            'exploration_max_completion_tokens': 2000, 'kb_max_completion_tokens': 2000,
            'synthesis_reserve_usd': 3.0,
            'call_timeout_seconds': 600,
            'timeout_seconds': 7200, 'initial_concurrency': 1, 'concurrency': 4, 'revision': 1,
        },
        'openai': {
            'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
            'max_output_tokens': 40000, 'max_tool_calls': 25,
            'budget_usd': 5.0, 'timeout_seconds': 1800, 'poll_interval_seconds': 5,
            'initial_concurrency': 3, 'concurrency': 12, 'revision': 1,
        },
        'gemini': {
            'agent': 'deep-research-preview-04-2026',
            'billing_model': 'gemini-3.1-pro-preview', 'budget_usd': 5.0,
            'timeout_seconds': 1800, 'poll_interval_seconds': 5,
            'initial_concurrency': 2, 'concurrency': 8, 'revision': 1,
        },
    },
    'judges': {
        'openai': {'model': 'gpt-6-astra', 'reasoning_effort': 'high',
                   'max_output_tokens': 32768, 'timeout_seconds': 900,
                   'poll_interval_seconds': 3, 'initial_concurrency': 4, 'concurrency': 16, 'revision': 1},
        'gemini': {'model': 'gemini-4-argon', 'thinking_level': 'high',
                   'max_output_tokens': 32768, 'timeout_seconds': 900,
                   'poll_interval_seconds': 3, 'initial_concurrency': 4, 'concurrency': 16, 'revision': 1},
    },
    'analysis': {'bootstrap_samples': 1000, 'seed': 2026, 'workers': 0},
}
for _section in ('research', 'judges'):
    for _settings in DEFAULTS[_section].values():
        _settings.update(retry_attempts=4, retry_backoff_base_seconds=1,
                         retry_backoff_max_seconds=30)


def _merge(base, updates):
    for key, value in updates.items():
        if key not in base:
            raise ValueError(f'Unknown configuration field: {key}')
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f'{key} must be a mapping')
            _merge(base[key], value)
        else:
            base[key] = value


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict:
    path = Path(path).expanduser().resolve()
    supplied = yaml.safe_load(path.read_text()) or {}
    if not isinstance(supplied, dict):
        raise ValueError('Configuration must be a YAML mapping')
    config = copy.deepcopy(DEFAULTS)
    _merge(config, supplied)
    try:
        if not isinstance(config['results_timezone'], str) or not config['results_timezone']:
            raise ValueError
        ZoneInfo(config['results_timezone'])
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError('results_timezone must be a valid IANA timezone, such as America/Chicago') from exc
    for key in ('questions', 'rubric', 'cache_dir', 'output_dir'):
        p = Path(config[key]).expanduser()
        config[key] = str((path.parent / p).resolve())
    p = Path(config['research']['caesar']['rome_path']).expanduser()
    config['research']['caesar']['rome_path'] = str((path.parent / p).resolve())
    caesar = config['research']['caesar']
    for field in ('recovery_from', 'budget_history_from'):
        source = caesar[field]
        if source is not None:
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f'research.caesar.{field} must be a nonempty path or null')
            caesar[field] = str((path.parent / Path(source).expanduser()).resolve())
    if caesar['recovery_from'] and caesar['budget_history_from']:
        raise ValueError('Choose recovery_from or budget_history_from, not both')
    if '{question}' not in config['research_prompt']:
        raise ValueError('research_prompt must contain {question}')
    for section in ('research', 'judges'):
        for name, settings in config[section].items():
            for key in ('concurrency', 'initial_concurrency', 'retry_attempts', 'max_output_tokens', 'max_tool_calls', 'max_iterations',
                        'synthesis_drafts', 'synthesis_iterations', 'max_completion_tokens',
                        'query_max_completion_tokens', 'synthesis_top_k', 'synthesis_top_n',
                        'exploration_max_completion_tokens', 'kb_max_completion_tokens', 'quick_explore_workers'):
                if key in settings and (isinstance(settings[key], bool) or
                                        not isinstance(settings[key], int) or settings[key] < 1):
                    raise ValueError(f'{section}.{name}.{key} must be a positive integer')
            if 'additional_starting_queries' in settings and (
                    type(settings['additional_starting_queries']) is not int or
                    settings['additional_starting_queries'] < 0):
                raise ValueError(f'{section}.{name}.additional_starting_queries must be a nonnegative integer')
            for key in ('use_quick_explore', 'quick_explore_insights', 'adapt_role',
                        'synthesis_merge_artifacts'):
                if key in settings and not isinstance(settings[key], bool):
                    raise ValueError(f'{section}.{name}.{key} must be a boolean')
            if settings['initial_concurrency'] > settings['concurrency']:
                settings['initial_concurrency'] = settings['concurrency']
            for key in ('budget_usd', 'handler_budget_usd', 'timeout_seconds', 'call_timeout_seconds', 'poll_interval_seconds',
                        'retry_backoff_base_seconds', 'retry_backoff_max_seconds', 'synthesis_reserve_usd'):
                if key in settings and (not isinstance(settings[key], (int, float)) or
                                        isinstance(settings[key], bool) or not math.isfinite(settings[key]) or settings[key] <= 0):
                    raise ValueError(f'{section}.{name}.{key} must be positive and finite')
    for key in ('workers', 'bootstrap_samples'):
        if type(config['analysis'][key]) is not int or config['analysis'][key] < 0:
            raise ValueError(f'analysis.{key} must be a nonnegative integer')
    if type(config['analysis']['seed']) is not int:
        raise ValueError('analysis.seed must be an integer')
    config['_config_path'] = str(path)
    return config


def load_questions(path: Path | str) -> list[dict]:
    questions, ids, texts = [], set(), set()
    for line_no, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f'Invalid question JSON at line {line_no}') from exc
        text = next((row[k] for k in ('query', 'question', 'text', 'prompt') if k in row), None) if isinstance(row, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'Question line {line_no} needs a nonempty query string')
        identity = str(row.get('id') or ('q-' + digest(text)[:12]))
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', identity) or identity in {'.', '..'}:
            raise ValueError(f'Unsafe question ID at line {line_no}')
        if identity in ids or text in texts:
            raise ValueError(f'Duplicate question at line {line_no}')
        ids.add(identity)
        texts.add(text)
        question = {'id': identity, 'text': text}
        if 'category' in row:
            question['category'] = row['category']
        questions.append(question)
    if not questions:
        raise ValueError('Question file is empty')
    return questions
