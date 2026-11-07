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
from .budget import HOSTED as HOSTED_AGENTS, plan as budget_plan
from .caesar_budget import DERIVED as CAESAR_DERIVED

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'crest/configs/crest.yaml'
DEFAULTS = {
    'questions': '../data/queries_n50_v2.jsonl',
    'rubric': '../prompts/nus_pairwise_v2.txt',
    'cache_dir': '../results/.cache/generation', 'output_dir': '../results',
    'results_timezone': DEFAULT_RESULTS_TIMEZONE,
    # Rendered for every research agent whose use_research_prompt flag is true.
    # {question} is the exact question text; {max_words} is the agent's answer_word_limit.
    'research_prompt': (
        '### QUERY\n\n{question}\n\n'
        '### YOUR TASK\n\n'
        'Use deep research to create a novel, exciting, and thought-provoking response that creatively '
        'answers the query above. Focus on the following:\n'
        '- Emergent patterns not visible in individual sources\n'
        '- Novel discoveries, connections, or applications\n'
        '- Surprising new directions or perspectives\n'
        '- Interesting tensions, contradictions, or open questions\n\n'
        'IMPORTANT: Avoid excessive jargon, ensure artifact text is well-organized (logical, clear, focused), '
        'and convincing to a skeptical reader\n'
        'IMPORTANT: The final response must be at most {max_words} words'
    ),
    # Global answer length limit in words; each research agent inherits it unless it sets its own.
    'answer_word_limit': 600,
    # Sent to a hosted single-call agent (OpenAI, Anthropic) whose finished answer cost less than its
    # budget_floor_usd: the agent researches further and rewrites the answer, up to max_research_rounds.
    'research_continuation_prompt': (
        'Your research so far cost ${spent} of a ${floor} to ${ceiling} research budget. Continue the research: '
        'run further web searches on the aspects of the query that are weakest, least evidenced or most '
        'conventional, read the most promising sources, and then rewrite the complete response so that it '
        'stands alone and incorporates the new findings. Keep every requirement of the original task, '
        'including the limit of {max_words} words.'
    ),
    'research': {
        'caesar': {
            'budget_cap': 'soft',  # hard: budget_usd is enforced; auto: enforced and depth is overridden from it; soft: overruns are only flagged.
            # Caesar receives the bare question: Rome owns its own research prompting.
            'use_research_prompt': False, 'answer_word_limit': None,
            'rome_path': '../../../rome', 'python_executable': sys.executable,
            'recovery_from': None, 'budget_history_from': None,
            'model': 'gpt-6.1-sol', 'exploration_model': 'gpt-6-luna',
            'kb_model': 'gpt-6-luna', 'budget_usd': 4.0,
            'reasoning_effort': 'medium', 'synthesis_reasoning_effort': 'medium',
            'exploration_reasoning_effort': 'low', 'kb_reasoning_effort': 'low',
            # Chosen depth; with budget_cap auto crest.budget overrides them from budget_usd.
            'max_iterations': 300, 'synthesis_drafts': 3, 'synthesis_iterations': 20,
            'synthesis_top_k': 50, 'synthesis_top_n': 10, 'enable_reranking': True,
            'max_depth': 6, 'max_web_searches': 5,
            'additional_starting_queries': 11, 'use_quick_explore': False,
            'quick_explore_insights': True, 'quick_explore_workers': 2,
            'adapt_role': True, 'synthesis_merge_artifacts': True,
            'max_completion_tokens': 10000, 'query_max_completion_tokens': 6000,
            'exploration_max_completion_tokens': 2000, 'kb_max_completion_tokens': 2000,
            'synthesis_reserve_usd': None,
            'call_timeout_seconds': 600,
            'timeout_seconds': None, 'initial_concurrency': 1, 'concurrency': 4, 'revision': 1,
        },
        'openai': {
            'budget_cap': 'soft',  # hard: budget_usd is enforced; auto: enforced and depth is overridden from it; soft: overruns are only flagged.
            'use_research_prompt': True, 'answer_word_limit': None,
            'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh', 'search_context_size': 'high',
            'max_output_tokens': 100000, 'max_tool_calls': 150,
            'budget_usd': 4.0, 'budget_floor_usd': 3.0, 'max_research_rounds': 6, 'continuation_prompt': None,
            'timeout_seconds': 3600, 'poll_interval_seconds': 5,
            'initial_concurrency': 3, 'concurrency': 12, 'revision': 1,
        },
        'gemini': {
            'budget_cap': 'soft',  # hard: budget_usd is enforced; auto: enforced and depth is overridden from it; soft: overruns are only flagged.
            'use_research_prompt': True, 'answer_word_limit': None,
            'agent': 'deep-research-preview-04-2026',
            'billing_model': 'gemini-3.1-pro-preview', 'budget_usd': 4.0,
            'timeout_seconds': 1800, 'poll_interval_seconds': 5,
            'initial_concurrency': 2, 'concurrency': 8, 'revision': 1,
        },
        'anthropic': {
            'budget_cap': 'soft',  # hard: budget_usd is enforced; auto: enforced and depth is overridden from it; soft: overruns are only flagged.
            'use_research_prompt': True, 'answer_word_limit': None,
            'model': 'claude-sonnet-5-5', 'effort': 'high',
            'max_output_tokens': 64000, 'max_web_searches': 30, 'max_web_fetches': 10,
            'web_fetch': True, 'max_continuations': 10, 'refusal_fallback': False,
            'budget_usd': 4.0, 'budget_floor_usd': 3.0, 'max_research_rounds': 14, 'continuation_prompt': None,
            'timeout_seconds': 5400,
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
        'anthropic': {'model': 'claude-fable-5-1', 'effort': 'high',
                      'max_output_tokens': 32768, 'refusal_fallback': False, 'timeout_seconds': 900,
                      'initial_concurrency': 4, 'concurrency': 16, 'revision': 1},
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


BUDGET_CAPS = ('hard', 'soft', 'auto')


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _apply_auto_budget(name, settings, keys, probe, overrides):
    """Set ``keys`` from the master budget calculator and record and print each value that changed."""
    derived = budget_plan(name, float(settings['budget_usd']), probe)['settings']
    for key in keys:
        if settings.get(key) != derived[key]:
            overrides.append({'agent': name, 'setting': key, 'from': settings.get(key), 'to': derived[key]})
            print(f"budget_cap auto: research.{name}.{key} {settings.get(key)!r} -> {derived[key]!r} "
                  f"(derived from budget_usd {settings['budget_usd']} by crest/budget.py)", file=sys.stderr)
        settings[key] = derived[key]


def _budget_cap(name, settings):
    cap = settings.get('budget_cap', 'hard')
    if cap not in BUDGET_CAPS:
        raise ValueError(f'research.{name}.budget_cap must be hard, soft or auto')
    if name == 'gemini' and cap != 'soft':
        raise ValueError('research.gemini.budget_cap must be soft: the managed agent exposes no depth control, so budget_usd can only be flagged')
    return cap


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
    overrides = []  # budget_cap auto: what the calculator overrode, printed and kept for `crest plan`.
    caesar = config['research']['caesar']
    for field in ('recovery_from', 'budget_history_from'):
        source = caesar[field]
        if source is not None:
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f'research.caesar.{field} must be a nonempty path or null')
            caesar[field] = str((path.parent / Path(source).expanduser()).resolve())
    if caesar['recovery_from'] and caesar['budget_history_from']:
        raise ValueError('Choose recovery_from or budget_history_from, not both')
    if type(caesar['budget_usd']) is bool or not isinstance(caesar['budget_usd'], (int, float)):
        raise ValueError('research.caesar.budget_usd must be a number')
    for key in ('max_iterations', 'synthesis_drafts', 'synthesis_iterations', 'max_completion_tokens', 'query_max_completion_tokens'):
        if caesar.get(key) is not None and (isinstance(caesar[key], bool) or not isinstance(caesar[key], int) or caesar[key] < 1):
            raise ValueError(f'research.caesar.{key} must be a positive integer')
    cap = _budget_cap('caesar', caesar)
    if cap == 'auto':
        # The calculator owns every depth key: derive from a probe with them cleared, then override.
        probe = {**caesar, **{key: None for key in CAESAR_DERIVED}}
        _apply_auto_budget('caesar', caesar, CAESAR_DERIVED, probe, overrides)
    else:
        missing = [key for key in ('max_iterations', 'synthesis_drafts', 'synthesis_iterations') if caesar[key] is None]
        if missing:
            raise ValueError(f'research.caesar.{missing[0]} must be set when budget_cap is {cap}; use budget_cap: auto to derive it')
        plan = budget_plan('caesar', float(caesar['budget_usd']), caesar)
        if cap == 'hard' and plan['estimate']['total_usd'] > caesar['budget_usd']:
            raise ValueError(f"research.caesar depth is estimated at ${plan['estimate']['total_usd']:.2f}, above budget_usd "
                             f"{caesar['budget_usd']}: lower the depth, raise the budget, or set budget_cap to soft or auto")
        caesar.update({key: plan['settings'][key] for key in CAESAR_DERIVED if caesar[key] is None})
    if not isinstance(config['research_prompt'], str) or '{question}' not in config['research_prompt']:
        raise ValueError('research_prompt must contain {question}')
    limit = config['answer_word_limit']
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('answer_word_limit must be a positive integer or null')
    for name, settings in config['research'].items():
        if 'use_research_prompt' in settings and not isinstance(settings['use_research_prompt'], bool):
            raise ValueError(f'research.{name}.use_research_prompt must be a boolean')
        if _budget_cap(name, settings) == 'auto' and name in HOSTED_AGENTS and _is_number(settings.get('budget_usd')):
            _apply_auto_budget(name, settings, ('budget_floor_usd', 'max_research_rounds'), settings, overrides)
        own = settings.get('answer_word_limit')
        if own is not None and (type(own) is not int or own < 1):
            raise ValueError(f'research.{name}.answer_word_limit must be a positive integer or null')
        if own is None:
            settings['answer_word_limit'] = limit
        if settings.get('use_research_prompt', True) and (
                (settings['answer_word_limit'] is None) == ('{max_words}' in config['research_prompt'])):
            raise ValueError('research_prompt must contain {max_words} exactly when an answer_word_limit applies')
        floor = settings.get('budget_floor_usd')
        if floor is not None:
            ceiling = settings.get('budget_usd')
            if any(type(v) is bool or not isinstance(v, (int, float)) for v in (floor, ceiling)) or not 0 < floor <= ceiling:
                raise ValueError(f'research.{name}.budget_floor_usd must be positive and at most budget_usd')
            if settings.get('continuation_prompt') is None:
                settings['continuation_prompt'] = config['research_continuation_prompt']
            prompt = settings['continuation_prompt']
            if (not isinstance(prompt, str) or any(tag not in prompt for tag in ('{spent}', '{floor}', '{ceiling}'))
                    or ('{max_words}' in prompt) != (settings['answer_word_limit'] is not None)):
                raise ValueError(f'research.{name}.continuation_prompt must contain {{spent}}, {{floor}} and {{ceiling}}, '
                                 'and {max_words} exactly when an answer_word_limit applies')
    for section in ('research', 'judges'):
        for name, settings in config[section].items():
            if 'effort' in settings and settings['effort'] not in ('low', 'medium', 'high', 'xhigh', 'max'):
                raise ValueError(f'{section}.{name}.effort must be low, medium, high, xhigh or max')
            if 'search_context_size' in settings and settings['search_context_size'] not in ('low', 'medium', 'high'):
                raise ValueError(f'{section}.{name}.search_context_size must be low, medium or high')
            for key in ('web_fetch', 'refusal_fallback'):
                if key in settings and not isinstance(settings[key], bool):
                    raise ValueError(f'{section}.{name}.{key} must be a boolean')
            for key in ('concurrency', 'initial_concurrency', 'retry_attempts', 'max_output_tokens', 'max_tool_calls', 'max_iterations', 'max_depth', 'max_web_searches',
                        'synthesis_drafts', 'synthesis_iterations', 'max_completion_tokens',
                        'query_max_completion_tokens', 'synthesis_top_k', 'synthesis_top_n',
                        'exploration_max_completion_tokens', 'kb_max_completion_tokens', 'quick_explore_workers',
                        'max_web_searches', 'max_web_fetches', 'max_continuations', 'max_research_rounds'):
                if key in settings and (isinstance(settings[key], bool) or
                                        not isinstance(settings[key], int) or settings[key] < 1):
                    raise ValueError(f'{section}.{name}.{key} must be a positive integer')
            if 'additional_starting_queries' in settings and (
                    type(settings['additional_starting_queries']) is not int or
                    settings['additional_starting_queries'] < 0):
                raise ValueError(f'{section}.{name}.additional_starting_queries must be a nonnegative integer')
            for key in ('use_quick_explore', 'quick_explore_insights', 'adapt_role',
                        'synthesis_merge_artifacts', 'enable_reranking'):
                if key in settings and not isinstance(settings[key], bool):
                    raise ValueError(f'{section}.{name}.{key} must be a boolean')
            if settings['initial_concurrency'] > settings['concurrency']:
                settings['initial_concurrency'] = settings['concurrency']
            for key in ('budget_usd', 'timeout_seconds', 'call_timeout_seconds', 'poll_interval_seconds',
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
    config['budget_overrides'] = overrides
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
        for key in ('category', 'generated_by'):
            if key in row:
                question[key] = row[key]
        questions.append(question)
    if not questions:
        raise ValueError('Question file is empty')
    return questions
