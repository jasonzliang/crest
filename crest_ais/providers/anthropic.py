"""Claude Fable judge for the frozen released-paper comparison.

The paper comparison reuses the shared CREST Messages adapter, so both pipelines
send the same structured A/B verdict request: one user turn holding the frozen
prompt, a JSON schema for ``reason`` and ``winner``, streaming with in-place
retry of interrupted streams, and no tools.
"""
from __future__ import annotations

from crest.cache import Job
from crest.providers import anthropic as _shared

ADAPTER_VERSION = _shared.ADAPTER_VERSION
JUDGE_MODEL = _shared.JUDGE_MODEL


async def judge(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _shared.judge(prompt, settings, job, client=client)


def account_state(state: dict) -> tuple[dict, float | None] | None:
    """Recompute usage and cost from a saved checkpoint, including billed retries.

    Returns None when the checkpoint holds no billed Anthropic output.
    """
    raw = state.get("raw")
    turns = raw.get("turns") if isinstance(raw, dict) else None
    attempts = state.get("interrupted_attempts") or []
    if not turns:
        receipt = state.get("provider_result")
        if isinstance(receipt, dict) and isinstance(receipt.get("raw"), dict):
            turns = receipt["raw"].get("turns")
    if not turns and not attempts:
        return None
    return _shared._account(turns or [], attempts)
