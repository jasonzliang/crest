"""Durable, local subprocess adapter for the sibling Rome Caesar implementation."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

from crest.caesar_worker import PROTOCOL_VERSION, atomic_json

ADAPTER_VERSION = "caesar-subprocess-v1"
# Only public execution settings cross the worker boundary. Credentials are inherited.
SETTINGS = frozenset({
    "rome_path", "model", "exploration_model", "kb_model", "embedding_model",
    "reasoning_effort", "exploration_reasoning_effort", "kb_reasoning_effort",
    "synthesis_reasoning_effort", "max_iterations", "max_depth",
    "additional_starting_queries", "max_web_searches", "synthesis_drafts",
    "synthesis_iterations", "retrieval_chunks", "max_completion_tokens",
    "exploration_max_completion_tokens", "kb_max_completion_tokens", "max_input_tokens",
    "budget_usd", "handler_budget_usd", "handler_cost_limit", "timeout_seconds",
    "call_timeout_seconds", "model_pricing", "chroma_port", "synthesis_reserve_usd", "retry_attempts",
})


def identity_metadata(settings: dict) -> dict:
    """Include relevant application and adapter source contents in the cache identity."""
    root = Path(settings.get("rome_path", Path(__file__).resolve().parents[3] / "rome")).resolve()
    files = sorted(root.glob("caesar/*.py")) + sorted(root.glob("rome/*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    # Adapter/worker edits invalidate even when the manually maintained version is unchanged.
    own_digest = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).parents[1].joinpath("caesar_worker.py").read_bytes()).hexdigest()
    return {"adapter_version": ADAPTER_VERSION, "protocol_version": PROTOCOL_VERSION,
            "rome_source_sha256": digest.hexdigest(), "adapter_source_sha256": own_digest,
            "rome_source_available": bool(files)}


async def _notify_rate_limits(job, usage: dict) -> None:
    controller = getattr(job, "rate_controller", None)
    if controller is None:
        return
    count = int(usage.get("rate_limit_events", 0) or 0)
    seen = int(job.state.get("caesar_rate_limit_events_seen", 0))
    events = [event for event in usage.get("events", []) if event.get("status_code") == 429]
    for index in range(seen, count):
        delay = float(events[index].get("retry_after_seconds", 0)) if index < len(events) else 0.
        reported = controller.rate_limited(max(0., delay) if math.isfinite(delay) else 0.)
        if inspect.isawaitable(reported):
            await reported
        job.save(caesar_rate_limit_events_seen=index + 1)


async def _read_record(path: Path, job) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    await _notify_rate_limits(job, (record.get("result") or {}).get("usage", record.get("usage") or {}))
    job.save(raw=record, remote_status=record.get("status", "unknown"))
    if record.get("status") != "completed":
        raise RuntimeError(record.get("error") or "Caesar worker did not complete")
    result = record.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("text"), str) or not result["text"].strip():
        raise RuntimeError("Caesar worker returned an empty answer")
    return result


def _worker_alive(state: dict) -> bool:
    """Verify both PID and command to avoid attaching to a recycled PID."""
    import psutil
    try:
        process = psutil.Process(int(state["worker_pid"]))
        if process.status() == psutil.STATUS_ZOMBIE:
            return False
        result = str(state.get("result_path", ""))
        command = process.cmdline()
        return bool(result and "crest.caesar_worker" in command and result in command)
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, ValueError):
        return False


async def _terminate_worker(state: dict) -> None:
    """Stop owned process groups, including Chroma's independently started session."""
    import psutil
    if not _worker_alive(state):
        return
    pid = int(state["worker_pid"])
    try:
        owned = psutil.Process(pid).children(recursive=True)
    except psutil.NoSuchProcess:
        owned = []
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    # Rome's signal handler shuts down its dedicated Chroma server on SIGTERM.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _worker_alive(state):
        await asyncio.sleep(.2)
    for process in owned:
        try:
            # psutil verifies creation time before signalling, avoiding PID reuse.
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    await asyncio.sleep(.2)
    for process in owned:
        try:
            if process.is_running():
                process.kill()
        except psutil.NoSuchProcess:
            pass
    if _worker_alive(state):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def generate(prompt: str, settings: dict, job, *, client=None) -> dict:
    """Resume a local result or worker; uncertain execution never submits twice."""
    directory = Path(job.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result_path = Path(job.state.get("result_path", directory / "caesar-result.json"))
    usage_path = directory / "caesar-output" / "usage.json"
    if result_path.exists():
        return await _read_record(result_path, job)
    if job.state.get("remote_status") in {"timed_out", "interrupted", "failed"}:
        raise RuntimeError("Caesar worker was interrupted or failed; review the saved audit before retrying")
    child = None
    timeout = float(settings.get("timeout_seconds", 1800))
    started = job.state.get("worker_started_at", time.time())
    if job.state.get("worker_pid"):
        if not _worker_alive(job.state):
            job.save(remote_status="interrupted", submission_unknown=True)
            raise RuntimeError("Caesar worker was interrupted without a final result; review required")
    elif job.state.get("submission_unknown"):
        raise RuntimeError("Caesar worker submission is unknown; review required before retrying")
    else:
        from uuid import uuid4
        request_path = directory / "caesar-request.json"
        request = {"protocol_version": PROTOCOL_VERSION, "prompt": prompt,
                   "settings": {key: value for key, value in settings.items() if key in SETTINGS},
                   "output_dir": str(directory / "caesar-output"), "job_key": job.key,
                   "worker_id": uuid4().hex}
        atomic_json(request_path, request)
        job.save(result_path=str(result_path), submission_unknown=True,
                 worker_started_at=started, remote_status="starting")
        # No shell or credentials in argv/config. A process crash in this launch window
        # remains unknown rather than silently launching another paid run.
        with (directory / "caesar-worker.log").open("ab") as log:
            child = await asyncio.create_subprocess_exec(
                settings.get("python_executable", sys.executable), "-m", "crest.caesar_worker",
                "--request", str(request_path), "--result", str(result_path),
                stdout=log, stderr=log, start_new_session=True,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        job.save(worker_pid=child.pid, submission_unknown=False, remote_status="running")
    deadline = time.monotonic() + max(0, timeout - (time.time() - started))
    try:
        while not result_path.exists():
            if usage_path.exists():
                await _notify_rate_limits(job, json.loads(usage_path.read_text()))
            if time.monotonic() >= deadline:
                await _terminate_worker(job.state)
                usage = json.loads(usage_path.read_text()) if usage_path.exists() else {}
                await _notify_rate_limits(job, usage)
                # A terminated request may still be billed; never report a hard cap.
                usage.update(unknown_cost=True, cost_usd=None)
                job.save(remote_status="timed_out", raw={"status": "timed_out", "usage": usage})
                raise TimeoutError(f"Caesar worker exceeded {timeout:g} seconds; cost may be unknown")
            if child is not None:
                if child.returncode is not None:
                    # Atomic result publication happens before normal worker exit.
                    if result_path.exists():
                        break
                    job.save(remote_status="interrupted", submission_unknown=True)
                    raise RuntimeError(f"Caesar worker exited ({child.returncode}) without a result; review required")
            elif not _worker_alive(job.state):
                if result_path.exists():
                    break
                job.save(remote_status="interrupted", submission_unknown=True)
                raise RuntimeError("Caesar worker exited without a result; review required")
            await asyncio.sleep(min(float(settings.get("poll_interval_seconds", .5)), 5))
        if child is not None:
            try:
                await asyncio.wait_for(child.wait(), timeout=min(5., max(.001, deadline - time.monotonic())))
            except TimeoutError:
                await _terminate_worker(job.state)
        return await _read_record(result_path, job)
    except asyncio.CancelledError:
        # Leave the worker running so another invocation can retrieve its result.
        # Its own deadline still stops research if the parent never returns.
        job.save(remote_status="running", submission_unknown=False)
        raise
