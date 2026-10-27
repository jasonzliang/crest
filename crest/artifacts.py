"""Readable artifact names and provenance, independent of paid-work identities."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .cache import digest


DEFAULT_RESULTS_TIMEZONE = 'America/Chicago'


TRANSPORT_SETTINGS = frozenset({
    'concurrency', 'initial_concurrency', 'poll_interval_seconds',
    'retry_attempts', 'retry_backoff_base_seconds', 'retry_backoff_max_seconds',
})


def configuration_record(task: dict, *, prompt_template: str | None = None) -> dict:
    """Describe the frozen entrant configuration; never inspect current settings.

    The shared prompt template belongs to the configuration; rendered questions
    do not. None records an unavailable legacy template. This identifier groups
    readable artifacts only and does not replace paid generation job keys.
    """
    agent = task['agent']
    if not isinstance(agent, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', agent):
        raise ValueError('Agent must be a simple identifier')
    settings = deepcopy({key: value for key, value in task['settings'].items()
                         if key not in TRANSPORT_SETTINGS})
    identity = {'agent': agent, 'settings': settings, 'prompt_template': prompt_template,
                'adapter_version': task.get('adapter_version'),
                'source_identity': deepcopy(task.get('source_identity'))}
    full_hash = digest(identity)
    short_id = full_hash[:12]
    model = settings.get('model') or settings.get('agent')
    label = ' / '.join(str(value) for value in (agent, model, short_id) if value)
    return {'configuration_id': f'{agent}-{short_id}',
            'configuration_sha256': full_hash, 'short_id': short_id,
            'label': label, **identity}


def answer_metadata(task: dict, question_number: int, *, prompt_template: str | None = None) -> dict:
    """Return a flat path relative to the generation stage and its config IDs."""
    if type(question_number) is not int or question_number < 1:
        raise ValueError('Question number must be a positive integer')
    record = configuration_record(task, prompt_template=prompt_template)
    return {'answer_file': f"answers/q{question_number:02d}-{record['agent']}-{record['short_id']}.md",
            'configuration_id': record['configuration_id'],
            'configuration_sha256': record['configuration_sha256']}


def _local(created_at: datetime | str, results_timezone: str) -> datetime:
    value = datetime.fromisoformat(created_at.replace('Z', '+00:00')) if isinstance(created_at, str) else created_at
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Directory timestamps must have a timezone')
    return value.astimezone(ZoneInfo(results_timezone))


def run_date_directory_name(created_at: datetime | str, *,
                            results_timezone: str = DEFAULT_RESULTS_TIMEZONE) -> str:
    """Use the same local date as the run's readable directory timestamp."""
    return _local(created_at, results_timezone).date().isoformat()


def run_directory_name(created_at: datetime | str, nonce: str, *,
                       results_timezone: str = DEFAULT_RESULTS_TIMEZONE) -> str:
    if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{8}', nonce):
        raise ValueError('Run nonce must contain eight lowercase hexadecimal characters')
    return _local(created_at, results_timezone).strftime('%H-%M-%S-%Z') + '-' + nonce


def stage_directory_name(number: int, name: str, created_at: datetime | str, *,
                         results_timezone: str = DEFAULT_RESULTS_TIMEZONE) -> str:
    if type(number) is not int or number < 1 or not re.fullmatch(r'[a-z][a-z0-9-]*', name):
        raise ValueError('Stage needs a positive number and simple name')
    return f'{number:02d}-{name}-' + _local(created_at, results_timezone).strftime('%Y-%m-%d_%H-%M-%S-%Z')


def reserve_directory(parent: Path, name: str) -> Path:
    """Atomically reserve a directory, preserving any existing same-second run."""
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.+-]+', name) or name in {'.', '..'}:
        raise ValueError('Directory name must be one local path component')
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        path = parent / (name if number == 1 else f'{name}-{number}')
        try:
            path.mkdir()
            return path
        except FileExistsError:
            number += 1
