"""Durable bounded judging without generation or automatic paid resubmission."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import importlib
import json
import math
import os
from pathlib import Path
import sys

from crest.cache import Cache, digest, write_json
from .protocol import PROTOCOL_VERSION, add_agent_plan, extend_plan, parse_verdict, requires_reason_quality, validate_verdict, validate_plan_fingerprint

TERMINAL_FAILURES = {"invalid_verdict", "failed", "submission_unknown"}


def save_plan(plan: dict, run_dir: Path) -> None:
    """Create one frozen snapshot; reuse only exactly the same plan."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".plan.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = run_dir / "plan.json"
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != plan:
                raise ValueError("Plan snapshots are immutable; select a different run directory")
        else:
            write_json(path, plan)
            write_json(run_dir / "catalog.json", plan.get("catalog", []))


def _money(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def _safe_error(error: Exception) -> str:
    message = str(error)
    for name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[credential redacted]")
    return f"{type(error).__name__}: {message}"


def _account(state: dict, judge: str, settings: dict) -> dict:
    """Retain the largest known cost observation for this one paid job.

    Cancellation payloads can omit or reduce usage. Neither those payloads nor
    a later result erase a larger durable observation; the estimate remains
    conservative, with usage taken from the observation supplying that cost.
    """
    candidates = [{"cost_usd": _money(state.get("observed_cost_usd")),
                   "usage": state.get("observed_usage") or {},
                   "model": settings.get("model"), "warnings": []}]
    for field in ("pre_cancel_raw", "raw", "cancellation"):
        raw = state.get(field)
        if not isinstance(raw, dict):
            continue
        try:
            if judge == "openai":
                from .providers.openai import _account as account_openai
                usage, cost = account_openai(raw)
            elif judge == "gemini":
                from .providers.gemini import _usage, _cost, _pricing_date
                usage = _usage(raw)
                cost = _cost(usage, raw.get("model", settings.get("model")), research=False,
                             pricing_date=_pricing_date(raw)[0])
            else:
                continue
            candidates.append({"usage": usage, "cost_usd": _money(cost),
                               "model": raw.get("model", settings.get("model")), "warnings": []})
        except (ValueError, TypeError, KeyError):
            continue
    result = state.get("result")
    if isinstance(result, dict):
        candidates.append({"cost_usd": _money(result.get("cost_usd")), "usage": result.get("usage") or {},
                           "model": result.get("model", settings.get("model")), "warnings": result.get("warnings") or []})
    known = [candidate for candidate in candidates if candidate["cost_usd"] is not None]
    accounting = deepcopy(max(known, key=lambda candidate: candidate["cost_usd"]) if known else candidates[-1])
    if not known and state.get("observed_usage"):
        accounting["usage"] = deepcopy(state["observed_usage"])
    if isinstance(result, dict):
        accounting["warnings"] = list(result.get("warnings") or [])
        latest_cost = _money(result.get("cost_usd"))
        if known and (latest_cost is None or accounting["cost_usd"] > latest_cost):
            accounting["warnings"].append("Cost conservatively retains the largest known observation for this job; later output did not establish a higher cost.")
    return accounting


def _completed(task: dict, state: dict, *, require_reason_quality: bool = False) -> dict | None:
    if state.get("status") != "completed":
        return None
    verdict = validate_verdict(state.get("verdict"), require_reason_quality=require_reason_quality)
    if require_reason_quality:
        result = state.get("result")
        if (not isinstance(result, dict)
                or parse_verdict(result.get("text"), require_reason_quality=True) != verdict):
            raise ValueError("Cached provider output differs from its verdict")
    return {"key": task["key"], "verdict": verdict, **_account(state, task["judge"], task["settings"])}


def load_results(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "results.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("results.json must contain a list")
    return value


def create_extension(source_run: Path, run_dir: Path, data_root: Path, *,
                     pairs_per_matchup: int = 10, extension_seed: int = 2026) -> dict:
    """Prepare a larger draw while retaining previously paid judgments."""
    return _prepare_extension(source_run, run_dir, data_root,
        plan_builder=lambda parent, root, source: extend_plan(parent, root,
            pairs_per_matchup=pairs_per_matchup, extension_seed=extension_seed, parent_run_dir=source))


def create_cohort_extension(source_run: Path, run_dir: Path, data_root: Path, *,
                            new_catalog: list[dict], new_agents: dict,
                            pairs_per_matchup: int | None = None, addition_seed: int = 2026) -> dict:
    """Prepare added-scientist matchups with the same guarded import lifecycle."""
    return _prepare_extension(source_run, run_dir, data_root,
        plan_builder=lambda parent, root, source: add_agent_plan(parent, new_catalog, new_agents, root,
            pairs_per_matchup=pairs_per_matchup, addition_seed=addition_seed, parent_run_dir=source))


def _prepare_extension(source_run: Path, run_dir: Path, data_root: Path, *, plan_builder) -> dict:
    """Serialize preparation against other preparation and active judging."""
    source_run, run_dir = Path(source_run).resolve(), Path(run_dir).resolve()
    _reject_superseded(source_run)
    if source_run == run_dir:
        raise ValueError("Extension requires a new immutable run directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".extension.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Extension run is busy with preparation or judging; retry after it finishes") from error
        try:
            return _create_extension(source_run, run_dir, data_root, plan_builder=plan_builder)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _create_extension(source_run: Path, run_dir: Path, data_root: Path, *, plan_builder) -> dict:
    """Freeze an extension and import matching paid work without provider calls.

    Reused costs enter once through imported jobs. Only previously excluded
    costs are copied to the prior ledger. Preparation is safe to repeat.
    """
    from .analysis import analyze

    source_run, run_dir = Path(source_run).resolve(), Path(run_dir).resolve()
    if source_run == run_dir:
        raise ValueError("Extension requires a new immutable run directory")
    parent = json.loads((source_run / "plan.json").read_text(encoding="utf-8"))
    source_results = load_results(source_run)
    if analyze(parent, source_results)["status"] != "complete":
        raise ValueError("Extension requires all parent overall judgments to be complete")
    plan = plan_builder(parent, data_root, str(source_run))
    source_cache = Cache(source_run / ".cache" / "judgments")
    source_rows = {row["key"]: row for row in source_results}
    require_reason_quality = requires_reason_quality(parent)
    states = {}
    for task in parent["jobs"]:
        state = source_cache.job(task["key"]).state
        if _completed(task, state, require_reason_quality=require_reason_quality) != source_rows.get(task["key"]):
            raise ValueError(f"Parent checkpoint differs from result: {task['key']}")
        result = state.get("result")
        if (not isinstance(result, dict)
                or parse_verdict(result.get("text"), require_reason_quality=require_reason_quality) != state["verdict"]):
            raise ValueError("Parent provider output differs from its flat verdict")
        states[task["key"]] = state
    existing_plan = run_dir / "plan.json"
    if existing_plan.exists():
        frozen = json.loads(existing_plan.read_text(encoding="utf-8"))
        validate_plan_fingerprint(frozen)
        if frozen["fingerprint"] != plan["fingerprint"]:
            raise ValueError("Extension run already has a different immutable plan")
        plan = frozen
    _reject_superseded(source_run)
    write_json(run_dir / "extension_preparation.json", {
        "status": "preparing", "plan_fingerprint": plan["fingerprint"],
        "source_run": str(source_run), "source_fingerprint": parent["fingerprint"]})
    destination_cache = Cache(run_dir / ".cache" / "judgments")
    for task in parent["jobs"]:
        job = destination_cache.job(task["key"])
        if job.state:
            if _completed(task, job.state, require_reason_quality=require_reason_quality) != source_rows[task["key"]]:
                raise ValueError("Existing imported checkpoint differs from source")
        else:
            write_json(job.path, deepcopy(states[task["key"]]) | {
                "imported_from_run": str(source_run), "imported_from_fingerprint": parent["fingerprint"]})
    imports_path = run_dir / "imported_results.json"
    if imports_path.exists() and json.loads(imports_path.read_text(encoding="utf-8")) != source_results:
        raise ValueError("Imported result snapshot is immutable")
    write_json(imports_path, source_results)
    prior = source_run / "prior_costs.json"
    if prior.exists():
        ledger = json.loads(prior.read_text(encoding="utf-8"))
        destination = run_dir / "prior_costs.json"
        if destination.exists() and json.loads(destination.read_text(encoding="utf-8")) != ledger:
            raise ValueError("Prior excluded-cost ledger differs from parent")
        write_json(destination, ledger)
    write_json(run_dir / "extension.json", plan["extension"])
    results = [result for task in plan["jobs"]
               if (result := _completed(task, destination_cache.job(task["key"]).state,
                                        require_reason_quality=require_reason_quality)) is not None]
    write_json(run_dir / "results.json", results)
    if not (run_dir / "judging.json").exists():
        known = sum(row["cost_usd"] for row in results if row.get("cost_usd") is not None)
        write_json(run_dir / "failures.json", [])
        write_json(run_dir / "judging.json", {
            "version": "crest-ais-judging-v1", "updated_at": datetime.now(timezone.utc).isoformat(),
            "expected_jobs": len(plan["jobs"]), "completed_jobs": len(results), "failed_jobs": 0,
            "deferred_jobs": len(plan["jobs"]) - len(results), "known_usd": known,
            "unknown_cost_jobs": sum(row.get("cost_usd") is None for row in results),
            "imported_jobs": len(source_results), "newly_completed_jobs": len(results) - len(source_results),
            "imported_known_usd": known, "new_known_usd": 0,
            "effective_worker_counts": {}, "worker_note": "Prepared only; no additional requests dispatched."})
    # Commit imports and ledgers before publishing a dispatchable plan. The
    # durable pending marker survives a crash even during plan publication.
    _reject_superseded(source_run)
    save_plan(plan, run_dir)
    if not (run_dir / "catalog.json").exists():
        write_json(run_dir / "catalog.json", plan["catalog"])
    write_json(run_dir / "extension_preparation.json", {
        "status": "ready", "plan_fingerprint": plan["fingerprint"],
        "source_run": str(source_run), "source_fingerprint": parent["fingerprint"],
        "imported_jobs": len(source_results)})
    return plan


def _preflight(tasks: list[dict], cache: Cache, provided: dict) -> None:
    required = set()
    for task in tasks:
        if task["judge"] in provided:
            continue
        state = cache.job(task["key"]).state
        if state.get("status") in {"completed", *TERMINAL_FAILURES}:
            continue
        if state.get("submission_unknown") and not state.get("remote_id"):
            continue
        if isinstance(state.get("result"), dict):
            continue
        required.add(task["judge"])
    missing = []
    if "openai" in required and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if "gemini" in required and not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        missing.append("GOOGLE_API_KEY or GEMINI_API_KEY")
    if missing:
        raise ValueError("Set " + ", ".join(missing) + " before uncached judging")


def _reject_superseded(run_dir: Path) -> None:
    path = run_dir / "superseded.json"
    if path.exists():
        marker = json.loads(path.read_text(encoding="utf-8"))
        replacement = (marker.get("replacement_run_dir") or marker.get("corrected_run_dir")
                       or marker.get("replacement_run") or "the corrected run recorded in superseded.json")
        raise ValueError(f"This run is superseded and cannot dispatch judging jobs. Use {replacement}. Reason: {marker.get('reason', 'input extraction was corrected')}")


def _check_extension_ready(plan: dict, run_dir: Path) -> None:
    """Fail closed during preparation; verify older prepared runs read-only."""
    marker_path = run_dir / "extension_preparation.json"
    extension = plan.get("extension")
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("status") != "ready" or marker.get("plan_fingerprint") != plan["fingerprint"]:
            raise ValueError("Extension preparation is not ready; resume preparation before judging")
    elif extension:
        # Pre-marker extensions remain usable only when all preparation outputs
        # establish that imports and accounting were fully published.
        required = ("extension.json", "imported_results.json", "results.json", "judging.json")
        if any(not (run_dir / name).is_file() for name in required):
            raise ValueError("Extension preparation is not ready; finish importing paid work before judging")
        metadata = json.loads((run_dir / "extension.json").read_text(encoding="utf-8"))
        imports = json.loads((run_dir / "imported_results.json").read_text(encoding="utf-8"))
        results = {row["key"]: row for row in load_results(run_dir)}
        summary = json.loads((run_dir / "judging.json").read_text(encoding="utf-8"))
        if (metadata != extension or len(imports) != extension["original_pairs"] * 4
                or summary.get("expected_jobs") != len(plan["jobs"])
                or summary.get("completed_jobs", 0) < len(imports)
                or any(results.get(row["key"]) != row for row in imports)):
            raise ValueError("Extension preparation is incomplete; imported paid work is not ready")
    if extension:
        imports_path = run_dir / "imported_results.json"
        if not imports_path.is_file():
            raise ValueError("Extension preparation is not ready; imported results are missing")
        imports = json.loads(imports_path.read_text(encoding="utf-8"))
        if len(imports) != extension["original_pairs"] * 4:
            raise ValueError("Extension preparation is not ready; imported-result count differs")
        source = extension.get("parent_run_dir")
        if source:
            _reject_superseded(Path(source))
            source_prior = Path(source) / "prior_costs.json"
            if source_prior.exists():
                prior = run_dir / "prior_costs.json"
                if not prior.exists() or json.loads(prior.read_text()) != json.loads(source_prior.read_text()):
                    raise ValueError("Extension preparation is not ready; prior-cost ledger differs")


async def run_judging(plan: dict, run_dir: Path, *, providers: dict | None = None,
                      progress: bool = True, max_spend_usd: float = 100,
                      workers_per_judge: int | None = None) -> list[dict]:
    """Hold a shared lifecycle lock so preparation cannot overwrite active work."""
    validate_plan_fingerprint(plan)
    run_dir = Path(run_dir).expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".extension.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Extension preparation is in progress; retry judging after it is ready") from error
        try:
            _check_extension_ready(plan, run_dir)
            return await _run_judging(plan, run_dir, providers=providers, progress=progress,
                                      max_spend_usd=max_spend_usd, workers_per_judge=workers_per_judge)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def _run_judging(plan: dict, run_dir: Path, *, providers: dict | None = None,
                      progress: bool = True, max_spend_usd: float = 100,
                      workers_per_judge: int | None = None) -> list[dict]:
    """Judge or resume a frozen plan; return only strictly valid successful votes.

    By default at most two calls per provider run concurrently; an explicit
    operational worker override may select one through sixteen. It never changes
    frozen prompts, model settings, job keys, or remote submission identities.
    The spend limit guards new
    dispatch from observed costs; in-flight work and unreported usage can exceed
    it. Unknown submissions without a remote id require manual reconciliation.
    Invalid paid outputs and terminal errors are persisted and never resubmitted.
    """
    if workers_per_judge is not None and (isinstance(workers_per_judge, bool)
            or not isinstance(workers_per_judge, int) or not 1 <= workers_per_judge <= 16):
        raise ValueError("workers_per_judge must be an integer from 1 through 16")
    if _money(max_spend_usd) is None:
        raise ValueError("max_spend_usd must be a finite nonnegative number")
    validate_plan_fingerprint(plan)
    tasks = plan.get("jobs", [])
    if len({task["key"] for task in tasks}) != len(tasks):
        raise ValueError("Duplicate planned job keys")
    run_dir = Path(run_dir).expanduser().resolve()
    _reject_superseded(run_dir)
    if plan.get("version") != PROTOCOL_VERSION:
        raise ValueError(f"Plan protocol version must be {PROTOCOL_VERSION}; create a new overall-judgment plan before judging")
    save_plan(plan, run_dir)
    cache = Cache(run_dir / ".cache" / "judgments")
    require_reason_quality = requires_reason_quality(plan)
    # Revalidate completed current-contract checkpoints before snapshots can
    # count them. Invalid paid outputs remain terminal and retain accounting.
    for task in tasks:
        async with cache.lock(task["key"]) as job:
            if job.state.get("status") == "completed":
                try:
                    _completed(task, job.state, require_reason_quality=require_reason_quality)
                except ValueError as error:
                    job.save(status="invalid_verdict", error=_safe_error(error),
                             failed_at=datetime.now(timezone.utc).isoformat())
    provided = providers or {}
    _preflight(tasks, cache, provided)
    resolved_providers = dict(provided)
    deferred, resumed = set(), set()
    finished = 0
    imports_path = run_dir / "imported_results.json"
    imported_rows = json.loads(imports_path.read_text(encoding="utf-8")) if imports_path.exists() else []
    imported_keys = {row["key"] for row in imported_rows}
    tasks_by_key = {task["key"]: task for task in tasks}
    if len(imported_keys) != len(imported_rows) or imported_keys - tasks_by_key.keys():
        raise ValueError("Invalid imported-result identities")
    for row in imported_rows:
        if _completed(tasks_by_key[row["key"]], cache.job(row["key"]).state,
                      require_reason_quality=require_reason_quality) != row:
            raise ValueError("Imported paid result differs from cached checkpoint")
    imported_known = sum(row["cost_usd"] for row in imported_rows if row.get("cost_usd") is not None)
    effective_worker_counts = {}
    for task in tasks:
        name = task["judge"]
        settings = plan.get("judges", {}).get(name, task["settings"])
        effective_worker_counts[name] = (workers_per_judge if workers_per_judge is not None
                                         else max(1, min(2, int(settings.get("concurrency", 2)))))

    def snapshot():
        results, failures = [], []
        known, unknown = 0.0, 0
        for task in tasks:
            state = cache.job(task["key"]).state
            account = _account(state, task["judge"], task["settings"])
            observed = any(field in state for field in ("result", "raw", "remote_id", "submitted_at")) or state.get("submission_unknown")
            if account["cost_usd"] is not None:
                known += account["cost_usd"]
            elif observed:
                unknown += 1
            result = _completed(task, state, require_reason_quality=require_reason_quality)
            if result:
                results.append(result)
            elif state.get("status") in TERMINAL_FAILURES | {"pending_retrieval"}:
                failures.append({"key": task["key"], "judge": task["judge"], "status": state["status"],
                                 "error": state.get("error", ""), "submission_unknown": bool(state.get("submission_unknown")),
                                 "remote_id": state.get("remote_id"), **account})
        summary = {"version": "crest-ais-judging-v1", "updated_at": datetime.now(timezone.utc).isoformat(),
                   "expected_jobs": len(tasks), "completed_jobs": len(results), "failed_jobs": len(failures),
                   "deferred_jobs": len(deferred), "known_usd": known, "unknown_cost_jobs": unknown,
                   "max_spend_usd": max_spend_usd,
                   "effective_worker_counts": effective_worker_counts,
                   "workers_per_judge_override": workers_per_judge,
                   "worker_note": "Worker count is an operational scheduling override only; frozen prompts, model settings, job keys, and submission identities are unchanged.",
                   "budget_note": "Dispatch guard based on observed spend; in-flight or unknown usage can exceed the target.",
                   "resumed_cached_jobs": len(resumed),
                   "imported_jobs": len(imported_keys), "newly_completed_jobs": len(results) - len(imported_keys),
                   "imported_known_usd": imported_known, "new_known_usd": known - imported_known}
        write_json(run_dir / "results.json", results)
        write_json(run_dir / "failures.json", failures)
        write_json(run_dir / "judging.json", summary)
        return results, summary

    async def execute(task):
        nonlocal finished
        async with cache.lock(task["key"]) as job:
            if job.state.get("status") == "completed":
                _completed(task, job.state, require_reason_quality=require_reason_quality)
                resumed.add(task["key"])
                return
            if job.state.get("status") in TERMINAL_FAILURES:
                return
            if job.state.get("submission_unknown") and not job.state.get("remote_id"):
                job.save(status="submission_unknown", error="Submission outcome unknown; reconcile before submitting again")
                snapshot()
                return
            result = job.state.get("result")
            if not isinstance(result, dict):
                _, summary = snapshot()
                if summary["known_usd"] >= max_spend_usd and not job.state.get("remote_id"):
                    deferred.add(task["key"])
                    return
                _reject_superseded(run_dir)
                name = task["judge"]
                if name not in resolved_providers:
                    if name not in {"openai", "gemini"}:
                        raise ValueError(f"Unknown provider: {name}")
                    resolved_providers[name] = importlib.import_module("crest_ais.providers." + name)
                provider = resolved_providers[name]
                method = provider.judge if hasattr(provider, "judge") else provider
                job.save(status="running", started_at=datetime.now(timezone.utc).isoformat(),
                         prompt_sha256=digest(task["prompt"]), settings=deepcopy(task["settings"]))
                try:
                    result = await method(task["prompt"], task["settings"], job)
                    if not isinstance(result, dict):
                        raise ValueError("Provider result must be a dictionary")
                    job.save(result=result, status="received")
                except Exception as error:
                    unknown = bool(job.state.get("submission_unknown") and not job.state.get("remote_id"))
                    remote_status = job.state.get("remote_status")
                    resumable = bool(job.state.get("remote_id") and remote_status in {None, "queued", "in_progress"})
                    failure_status = "submission_unknown" if unknown else "pending_retrieval" if resumable else "failed"
                    job.save(status=failure_status, error=_safe_error(error),
                             failed_at=datetime.now(timezone.utc).isoformat())
                    finished += 1
                    snapshot()
                    if progress:
                        print(f"Judging {finished}/{len(tasks)}: {name} {job.state['status']} ({type(error).__name__})", file=sys.stderr, flush=True)
                    return
            try:
                verdict = parse_verdict(result.get("text"), require_reason_quality=require_reason_quality)
            except ValueError as error:
                job.save(status="invalid_verdict", error=_safe_error(error), failed_at=datetime.now(timezone.utc).isoformat())
            else:
                job.save(status="completed", verdict=verdict, completed_at=datetime.now(timezone.utc).isoformat())
            finished += 1
            snapshot()
            if progress:
                print(f"Judging {finished}/{len(tasks)}: {task['judge']} {job.state['status']}", file=sys.stderr, flush=True)

    by_provider = {}
    for task in tasks:
        by_provider.setdefault(task["judge"], []).append(task)

    async def worker(queue):
        while not queue.empty():
            task = queue.get_nowait()
            try:
                await execute(task)
            finally:
                queue.task_done()

    workers = []
    for name, group in by_provider.items():
        queue = asyncio.Queue()
        for task in group:
            queue.put_nowait(task)
        concurrency = effective_worker_counts[name]
        workers.extend(worker(queue) for _ in range(concurrency))
    worker_tasks = [asyncio.create_task(worker) for worker in workers]
    try:
        await asyncio.gather(*worker_tasks)
    finally:
        # Keep the lifecycle lock through cancellation and provider cleanup if
        # one worker fails; gather alone leaves its sibling tasks running.
        for task in worker_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        results, _ = snapshot()
    return results
