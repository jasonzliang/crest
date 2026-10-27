"""Content-addressed checkpoints with atomic writes and process-safe single flight."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class CacheCorruption(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Job:
    def __init__(self, root: Path, key: str):
        if not re.fullmatch(r'[a-f0-9]{64}', key):
            raise ValueError('Job key must be a SHA-256 digest')
        self.key = key
        self.directory = Path(root) / 'jobs' / key
        self.path = self.directory / 'state.json'
        try:
            self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        except (OSError, ValueError) as exc:
            raise CacheCorruption(f'Cannot trust checkpoint {self.path}; preserve and inspect it') from exc
        if not isinstance(self.state, dict) or self.state.get('key', key) != key:
            raise CacheCorruption(f'Invalid checkpoint identity: {self.path}')

    def save(self, **changes) -> None:
        self.state.update(changes)
        self.state['key'] = self.key
        write_json(self.path, self.state)


class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def job(self, key: str) -> Job:
        return Job(self.root, key)

    @asynccontextmanager
    async def lock(self, key: str):
        self.job(key)
        lock_dir = self.root / 'locks'
        lock_dir.mkdir(parents=True, exist_ok=True)
        with (lock_dir / (key + '.lock')).open('a') as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(.1)
            try:
                yield self.job(key)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
