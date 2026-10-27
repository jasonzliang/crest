"""Isolated Caesar API worker. Importing this module never imports Rome or credentials."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import copy
import hashlib
import inspect
import json
import logging
import math
import os
from pathlib import Path
import random
import signal
import socket
import sys
import tempfile
import threading
import time
from email.utils import parsedate_to_datetime
from uuid import uuid4

PROTOCOL_VERSION = "caesar-worker-v1"
SOL = "gpt-6.1-sol"
# Standard prices: https://developers.openai.com/api/docs/models/gpt-6.1-sol
PRICES = {SOL: {"input": 2., "output": 10., "cache_read": .1, "cache_write": 2.5},
          "text-embedding-3-small": {"input": .02, "output": 0.},
          "text-embedding-3-large": {"input": .13, "output": 0.},
          "text-embedding-ada-002": {"input": .10, "output": 0.}}


def atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_config(prompt: str, settings: dict, output_dir: Path, worker_id: str) -> dict:
    """Translate the documented preset into Rome's actual API configuration."""
    output_dir = Path(output_dir).resolve()
    model = settings.get("model", SOL)
    collection = "crest_" + hashlib.sha256(worker_id.encode()).hexdigest()[:40]
    return {
        "Agent": {"repository": str(output_dir), "agent_api": False, "draw_fsm": False},
        "AgentMemory": {"enabled": False},
        "Logger": {"base_dir": str(output_dir / "logs"), "level": "INFO", "console": False},
        "LLMHandler": {
            "provider": "openai", "model": model, "reasoning_effort": settings.get("reasoning_effort", "medium"),
            "cost_limit": settings.get("handler_budget_usd", settings.get("handler_cost_limit", 4.)),
            "max_completion_tokens": settings.get("max_completion_tokens", 6000),
            "max_input_tokens": settings.get("max_input_tokens", 64000),
            "timeout": settings.get("call_timeout_seconds", 120), "max_retries": 0,
        },
        "CaesarAgent": {
            "mode": "web", "starting_query": prompt, "allowed_domains": ["*"],
            "max_iterations": settings.get("max_iterations", 30), "max_depth": settings.get("max_depth", 6),
            "additional_starting_queries": settings.get("additional_starting_queries", 3),
            "max_web_searches": settings.get("max_web_searches", 5),
            "draw_graph": False, "adapt_role": False, "use_quick_explore": False,
            "exploration_llm_config": {
                "model": settings.get("exploration_model", model),
                "reasoning_effort": settings.get("exploration_reasoning_effort", "low"),
                "max_completion_tokens": settings.get("exploration_max_completion_tokens", 2000),
                "timeout": settings.get("call_timeout_seconds", 120),
            },
        },
        "ArtifactSynthesizer": {
            "synthesis_classic_mode": False, "synthesis_drafts": settings.get("synthesis_drafts", 2),
            "synthesis_iterations": settings.get("synthesis_iterations", 5),
            "synthesis_reasoning_effort": settings.get("synthesis_reasoning_effort", "medium"),
            "synthesis_top_k": settings.get("retrieval_chunks", 8),
            "synthesis_top_n": settings.get("retrieval_chunks", 8),
            "synthesis_merge_artifacts": False, "synthesis_merge_clarify": False,
            "synthesis_eli5": False, "synthesis_human_eval": False, "synthesis_generate_images": 0,
        },
        "BraveSearch": {"use_ddgs": True},
        "ChromaClientManager": {
            "collection_name": collection, "enable_reranking": False, "use_shared_server": False,
            "model": settings.get("kb_model", model), "reasoning_effort": settings.get("kb_reasoning_effort", "low"),
            "embedding_model": settings.get("embedding_model", "text-embedding-3-small"),
            "top_k": settings.get("retrieval_chunks", 8),
        },
        "ChromaServerManager": {"host": "127.0.0.1", "port": settings.get("chroma_port", 8000),
                                "persist_path": str(output_dir / "chroma"),
                                "startup_timeout": 15, "shutdown_timeout": 2},
    }


def extract_result(artifact: dict, model: str, usage: dict, *, expected_drafts=2, expected_iterations=5) -> dict:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("artifact"), str) or not artifact["artifact"].strip():
        raise ValueError("Caesar did not return a nonempty final artifact")
    if artifact.get("num_drafts") != expected_drafts:
        raise ValueError("Caesar synthesis ended before all requested drafts completed")
    metadata = artifact.get("metadata") or {}
    if metadata.get("synthesis_queries", 0) < expected_iterations:
        raise ValueError("Caesar synthesis ended before all requested Q&A rounds completed")
    sources = artifact.get("sources") or {}
    if not isinstance(sources, dict):
        raise ValueError("Caesar returned an invalid source map")
    citations = [{"url": url, "title": f"[{index}]"}
                 for url, index in sorted(sources.items(), key=lambda item: int(item[1]))]
    sections = []
    if artifact.get("abstract"):
        sections.append("Abstract\n" + artifact["abstract"])
    sections.append(artifact["artifact"])
    if citations:
        sections.append("Sources\n" + "\n".join(f"{item['title']} {item['url']}" for item in citations))
    unknown = usage.get("unknown_cost", True) or not usage.get("successful_calls")
    warnings = ["Budget is a target: SDK audit estimates successful-call costs; unobserved timeout billing cannot be capped."]
    if unknown:
        warnings.append("Some usage or prices are unavailable; total cost is unknown.")
    return {"text": "\n\n".join(sections), "citations": citations, "model": model,
            "usage": usage, "cost_usd": None if unknown else usage.get("cost_usd"),
            "cost_estimated": True, "warnings": warnings, "raw": {"artifact": artifact, "usage_audit": usage}}


@contextmanager
def compatibility(handler, default_config, litellm_module, llama_utils, kb_limit, *, tokenizer_registry=None):
    """Scoped registrations; Rome and installed package files remain untouched."""
    saved = {name: copy.deepcopy(getattr(handler, name)) for name in
             ("MODEL_PRICING", "MODEL_CONTEXT_SIZE", "REASONING_MODELS", "_known_models_registered")}
    registries = {name: copy.deepcopy(getattr(llama_utils, name)) for name in
                  ("O1_MODELS", "CHAT_MODELS", "ALL_AVAILABLE_MODELS")}
    tokenizer_saved = dict(tokenizer_registry) if tokenizer_registry is not None else None
    default_limit = default_config["LLMHandler"]["max_completion_tokens"]
    old_litellm = copy.deepcopy(getattr(litellm_module, "model_cost", {}).get(SOL))
    try:
        if tokenizer_registry is not None:
            tokenizer_registry[SOL] = "o200k_base"
        handler.MODEL_PRICING[SOL] = {"input": 2, "output": 10}
        handler.MODEL_CONTEXT_SIZE[SOL] = 1_050_000
        handler.REASONING_MODELS.add(SOL)
        handler._known_models_registered = False
        for name in registries:
            getattr(llama_utils, name)[SOL] = 1_050_000
        default_config["LLMHandler"]["max_completion_tokens"] = kb_limit
        litellm_module.register_model({SOL: {"litellm_provider": "openai", "mode": "chat",
            "input_cost_per_token": .000002, "output_cost_per_token": .00001,
            "max_input_tokens": 1_050_000, "max_tokens": 1_050_000,
            "supports_reasoning": True, "cache_read_input_token_cost": .0000001,
            "cache_creation_input_token_cost": .0000025}})
        yield
    finally:
        for name, value in saved.items():
            setattr(handler, name, value)
        for name, value in registries.items():
            registry = getattr(llama_utils, name)
            registry.clear()
            registry.update(value)
        if tokenizer_registry is not None:
            tokenizer_registry.clear()
            tokenizer_registry.update(tokenizer_saved)
        default_config["LLMHandler"]["max_completion_tokens"] = default_limit
        if hasattr(litellm_module, "model_cost"):
            if old_litellm is None:
                litellm_module.model_cost.pop(SOL, None)
            else:
                litellm_module.model_cost[SOL] = old_litellm


class WorkerDeadlineExceeded(BaseException):
    """Fatal wall-clock cutoff that Rome's broad Exception handlers cannot swallow."""


class SDKRequestFailed(BaseException):
    """Stop Rome retry ladders after permanent, exhausted, or ambiguous SDK failure."""


class IncompleteSDKOutput(ValueError):
    """Known billed output was truncated; a budgeted rewrite can be attempted."""


def _retry_after_seconds(error):
    headers = getattr(getattr(error, "response", None), "headers", {})
    value = headers.get("retry-after", headers.get("Retry-After"))
    try:
        advised = float(value)
    except (TypeError, ValueError):
        try:
            advised = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            advised = 0.
    return max(0., advised) if math.isfinite(advised) else 0.


class BudgetExceeded(RuntimeError):
    """A projected request cannot fit the observable remaining target budget."""


class UsageAudit:
    """Audit at the OpenAI SDK boundary, including direct KB and embedding calls.

    Reservations use a conservative UTF-8 byte bound for input and the requested
    output limit. Ambiguous failures retain reservations and stop Rome retry ladders.
    Confirmed 429 rejections release reservations and retry here with bounded backoff;
    SDK-internal retries are disabled so every attempt remains visible.
    """
    def __init__(self, budget: float, path: Path, prices=None, *, retry_attempts=4):
        self.budget = float(budget)
        self.retry_attempts = max(1, int(retry_attempts))
        self.path = Path(path)
        self.prices = {**PRICES, **(prices or {})}
        self.events = []
        self.pending = {}
        self.lock = threading.RLock()
        self.persist()

    def snapshot(self) -> dict:
        with self.lock:
            completed = [event for event in self.events if event["status"] == "completed"]
            unknown = any(event.get("unknown_cost") for event in self.events) or bool(self.pending)
            known = sum(event.get("cost_usd") or 0 for event in completed)
            inputs = sum(event.get("input_tokens") or 0 for event in completed)
            outputs = sum(event.get("output_tokens") or 0 for event in completed)
            by_model = {}
            for event in completed:
                item = by_model.setdefault(event["model"], {"input_tokens": 0, "output_tokens": 0, "known_cost_usd": 0.})
                item["input_tokens"] += event.get("input_tokens") or 0
                item["output_tokens"] += event.get("output_tokens") or 0
                item["known_cost_usd"] += event.get("cost_usd") or 0
            return {"input_tokens": inputs, "output_tokens": outputs, "total_tokens": inputs + outputs,
                    "successful_calls": len(completed), "failed_calls": sum(e["status"] == "failed" for e in self.events),
                    "rate_limit_events": sum(e.get("status_code") == 429 for e in self.events),
                    "known_cost_usd": known, "cost_usd": None if unknown or not self.events else known,
                    "unknown_cost": unknown or not self.events, "budget_target_usd": self.budget,
                    "budget_exceeded": known > self.budget, "by_model": by_model,
                    "events": copy.deepcopy(self.events), "in_flight": copy.deepcopy(list(self.pending.values()))}

    def persist(self):
        atomic_json(self.path, self.snapshot())

    def before(self, options) -> str:
        data = getattr(options, "json_data", {}) or {}
        if not isinstance(data, dict):
            data = {}
        model = str(data.get("model", "unknown")).removeprefix("openai/")
        rates = self.prices.get(model)
        # Byte count bounds ordinary BPE token counts; overhead covers message wrappers.
        content = data.get("messages", data.get("input", ""))
        input_bound = len(json.dumps(content, ensure_ascii=False).encode("utf-8")) + 128
        output_bound = data.get("max_completion_tokens", data.get("max_tokens", 0))
        bounded = model.startswith("text-embedding-") or isinstance(output_bound, int) and output_bound > 0
        input_multiplier = 2 if model == SOL and input_bound > 272_000 else 1
        output_multiplier = 1.5 if input_multiplier == 2 else 1
        input_rate = max(rates.get("input", 0), rates.get("cache_write", 0)) if rates else 0
        reserve = (input_bound * input_rate * input_multiplier + (output_bound or 0) * rates["output"] * output_multiplier) / 1e6 if rates and bounded else 0.
        with self.lock:
            known = sum(event.get("cost_usd") or 0 for event in self.events)
            reserved = sum(event["reserved_usd"] for event in self.pending.values())
            reserved += sum(event.get("reserved_usd", 0) for event in self.events if event["status"] == "failed")
            if rates and bounded and known + reserved + reserve > self.budget:
                raise BudgetExceeded("Projected SDK request exceeds the remaining Caesar budget target")
            token = uuid4().hex
            self.pending[token] = {"model": model, "reserved_usd": reserve,
                                   "unknown_cost": not bool(rates and bounded)}
            self.persist()
            return token

    def after(self, token, response=None, error=None):
        with self.lock:
            event = self.pending[token]
            if error is not None:
                status = getattr(error, "status_code", None)
                rejected = status in (401, 403, 429)
                event.update(status="failed", status_code=status, error_type=type(error).__name__,
                             error_message=_redact(str(error)), unknown_cost=not rejected,
                             cost_usd=0. if rejected else None)
                if status == 429:
                    event["retry_after_seconds"] = _retry_after_seconds(error)
                if rejected:
                    event["reserved_usd"] = 0.
            else:
                # litellm uses SDK with_raw_response; parse() returns the cached typed body.
                if not hasattr(response, "usage") and callable(getattr(response, "parse", None)):
                    response = response.parse()
                usage = getattr(response, "usage", None)
                if isinstance(usage, dict):
                    get = usage.get
                else:
                    get = lambda key, default=None: getattr(usage, key, default)
                inputs = get("prompt_tokens", get("input_tokens"))
                embedding = event["model"].startswith("text-embedding-")
                outputs = get("completion_tokens", get("output_tokens", 0 if embedding else None))
                rates = self.prices.get(event["model"])
                valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (inputs, outputs))
                details = get("prompt_tokens_details", get("input_tokens_details")) or {}
                detail = details.get if isinstance(details, dict) else lambda key, default=None: getattr(details, key, default)
                cached = detail("cached_tokens") or 0
                written = detail("cache_write_tokens") or 0
                valid_cache = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (cached, written))
                valid = valid and valid_cache and cached + written <= inputs
                priced_cache = rates is not None and (not cached or "cache_read" in rates) and (not written or "cache_write" in rates)
                cost = None
                if valid and rates and priced_cache:
                    # Read/write tokens partition reported input; they are never added again.
                    input_cost = (inputs - cached - written) * rates["input"] + cached * rates.get("cache_read", 0) + written * rates.get("cache_write", 0)
                    input_multiplier = 2 if event["model"] == SOL and inputs > 272_000 else 1
                    output_multiplier = 1.5 if input_multiplier == 2 else 1
                    cost = (input_cost * input_multiplier + outputs * rates["output"] * output_multiplier) / 1e6
                raw_usage = (usage.model_dump(mode="json") if callable(getattr(usage, "model_dump", None))
                             else copy.deepcopy(usage) if isinstance(usage, dict)
                             else vars(usage).copy() if usage is not None else None)
                event.update(status="completed", input_tokens=inputs, output_tokens=outputs,
                             raw_usage=raw_usage, response_model=getattr(response, "model", None),
                             cost_usd=cost, unknown_cost=cost is None)
            self.pending.pop(token)
            self.events.append(event)
            self.persist()
            if error is None:
                choices = getattr(response, "choices", [])
                if any(getattr(choice, "finish_reason", None) not in (None, "stop") for choice in choices):
                    raise IncompleteSDKOutput("SDK returned incomplete or unexpected chat output")

    def retry_delay(self, error, attempt):
        if not isinstance(error, Exception):
            raise error
        status = getattr(error, "status_code", None)
        if status != 429 or getattr(error, "code", None) == "insufficient_quota" or attempt + 1 >= self.retry_attempts:
            outcome = "rejected" if status in (401, 403, 429) else "billing outcome unknown"
            raise SDKRequestFailed(f"{type(error).__name__}: {outcome}; stopped after {attempt + 1} attempt(s)") from error
        return max(min(30., 2. ** attempt) + random.uniform(0., 1.), _retry_after_seconds(error))

    def completed(self, token, response):
        try:
            self.after(token, response=response)
        except IncompleteSDKOutput:
            raise
        except Exception as error:
            # Accepted but undecodable output can already be billed. Keep the
            # pending reservation and prevent Rome from submitting a second call.
            raise SDKRequestFailed(f"Accepted SDK response accounting failed: {type(error).__name__}; billing outcome unknown") from error

    async def acompleted(self, token, response):
        try:
            if not hasattr(response, "usage") and inspect.iscoroutinefunction(getattr(response, "parse", None)):
                response = await response.parse()
            self.completed(token, response)
        except IncompleteSDKOutput:
            raise
        except Exception as error:
            raise SDKRequestFailed(f"Accepted SDK response accounting failed: {type(error).__name__}; billing outcome unknown") from error

    @contextmanager
    def installed(self, sync_class, async_class=None):
        sync_request = sync_class.request
        audit = self
        def request(instance, cast_to, options, **kwargs):
            for attempt in range(audit.retry_attempts):
                token = audit.before(options)
                try:
                    result = sync_request(instance, cast_to, options, **kwargs)
                except BaseException as error:
                    audit.after(token, error=error)
                    time.sleep(audit.retry_delay(error, attempt))
                    continue
                audit.completed(token, result)
                return result
        async_request = async_class.request if async_class else None
        async def arequest(instance, cast_to, options, **kwargs):
            for attempt in range(audit.retry_attempts):
                token = audit.before(options)
                try:
                    result = await async_request(instance, cast_to, options, **kwargs)
                except BaseException as error:
                    audit.after(token, error=error)
                    await asyncio.sleep(audit.retry_delay(error, attempt))
                    continue
                await audit.acompleted(token, result)
                return result
        sync_class.request = request
        if async_class:
            async_class.request = arequest
        try:
            yield
        finally:
            sync_class.request = sync_request
            if async_class:
                async_class.request = async_request


@contextmanager
def _runtime(settings: dict, audit: UsageAudit):
    """Import and patch only inside the dedicated worker, without any dotenv loader."""
    root = Path(settings.get("rome_path", Path(__file__).resolve().parents[2] / "rome")).resolve()
    sys.path.insert(0, str(root))
    # All SDK clients (including Chroma and LlamaIndex clients) must expose retries
    # as separate calls to this audit rather than silently repeat timed-out charges.
    import openai
    from openai._base_client import SyncAPIClient, AsyncAPIClient
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm
    import tiktoken.model
    from llama_index.llms.openai import utils as llama_utils
    from rome.config import DEFAULT_CONFIG
    from rome.llm_handler import LLMHandler
    original_init = openai.OpenAI.__init__
    original_async_init = openai.AsyncOpenAI.__init__
    def init(instance, *args, **kwargs):
        kwargs["max_retries"] = 0
        kwargs.setdefault("timeout", settings.get("call_timeout_seconds", 120))
        original_init(instance, *args, **kwargs)
    def async_init(instance, *args, **kwargs):
        kwargs["max_retries"] = 0
        kwargs.setdefault("timeout", settings.get("call_timeout_seconds", 120))
        original_async_init(instance, *args, **kwargs)
    openai.OpenAI.__init__ = init
    openai.AsyncOpenAI.__init__ = async_init
    try:
        with compatibility(LLMHandler, DEFAULT_CONFIG, litellm, llama_utils, settings.get("kb_max_completion_tokens", 2000), tokenizer_registry=tiktoken.model.MODEL_TO_ENCODING), audit.installed(SyncAPIClient, AsyncAPIClient):
            from caesar.caesar_agent import CaesarAgent
            yield CaesarAgent
    finally:
        openai.OpenAI.__init__ = original_init
        openai.AsyncOpenAI.__init__ = original_async_init
        sys.path.remove(str(root))


def _redact(text: str) -> str:
    for key, value in os.environ.items():
        if len(value) >= 8 and any(part in key.upper() for part in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
            text = text.replace(value, "[REDACTED]")
    return text


@contextmanager
def _safe_logging():
    factory = logging.getLogRecordFactory()
    def redacted_record(*args, **kwargs):
        record = factory(*args, **kwargs)
        record.msg = _redact(record.getMessage())
        record.args = ()
        return record
    class Stream:
        def __init__(self, original): self.original = original
        def write(self, value): return self.original.write(_redact(value))
        def flush(self): return self.original.flush()
        def __getattr__(self, name): return getattr(self.original, name)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    logging.setLogRecordFactory(redacted_record)
    sys.stdout, sys.stderr = Stream(old_stdout), Stream(old_stderr)
    try:
        yield
    finally:
        logging.setLogRecordFactory(factory)
        sys.stdout, sys.stderr = old_stdout, old_stderr


@contextmanager
def _deadline(seconds):
    # The worker owns a wall-clock limit even while the parent is absent.
    def timeout(signum, frame):
        raise WorkerDeadlineExceeded("Caesar worker exceeded its wall-clock limit")
    previous = signal.signal(signal.SIGALRM, timeout)
    old_timer = signal.setitimer(signal.ITIMER_REAL, max(float(seconds), .001))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
        signal.signal(signal.SIGALRM, previous)


class ExplorationBudgetReserved(BaseException):
    """Leave the exploration loop before spending its synthesis allowance."""


def _explore_with_synthesis_reserve(agent, settings, audit):
    original_perceive = agent.perceive
    reserve = float(settings.get("synthesis_reserve_usd", 1.5))
    # The handler's separate guard also needs enough room for final writing.
    ceiling = min(audit.budget, float(settings.get("handler_budget_usd", settings.get("handler_cost_limit", 4.))))
    stop = None
    def perceive(*args, **kwargs):
        usage = audit.snapshot()
        committed = usage["known_cost_usd"] + sum(item["reserved_usd"] for item in usage["in_flight"])
        committed += sum(item.get("reserved_usd", 0) for item in usage["events"] if item["status"] == "failed")
        if committed >= max(0., ceiling - reserve):
            raise ExplorationBudgetReserved({"iterations_completed": max(0, agent.current_iteration - 1),
                "committed_usd": committed, "synthesis_reserve_usd": reserve,
                "exploration_limit_usd": max(0., ceiling - reserve)})
        return original_perceive(*args, **kwargs)
    agent.perceive = perceive
    try:
        try:
            artifact = agent.explore()
        except ExplorationBudgetReserved as error:
            stop = error.args[0]
            agent.current_iteration = stop["iterations_completed"]
            agent._crest_exploration_budget_stop = stop
            atomic_json(audit.path.with_name("exploration-budget-stop.json"), stop)
    finally:
        agent.perceive = original_perceive
    if stop is not None:
        artifact = agent.synthesizer.synthesize_artifact()
    return artifact, stop


def run_worker(request: dict, result_path: Path) -> int:
    settings = request.get("settings", {})
    output_dir = Path(request["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = UsageAudit(settings.get("budget_usd", 5.), output_dir / "usage.json", settings.get("model_pricing"), retry_attempts=settings.get("retry_attempts", 4))
    agent = None
    record = None
    artifact = None
    exploration_stop = None
    try:
        with _deadline(settings.get("timeout_seconds", 1800)), _safe_logging(), _runtime(settings, audit) as agent_class:
            config = build_config(request["prompt"], settings, output_dir, request.get("worker_id", request["job_key"]))
            if "chroma_port" not in settings:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    config["ChromaServerManager"]["port"] = sock.getsockname()[1]
            agent = agent_class(name="crest" + request["job_key"][:20], repository=str(output_dir), config=config)
            artifact, exploration_stop = _explore_with_synthesis_reserve(agent, settings, audit)
            if getattr(agent, "shutdown_called", False):
                raise RuntimeError("Caesar was interrupted before completing synthesis")
            result = extract_result(artifact, settings.get("model", SOL), audit.snapshot(),
                                    expected_drafts=settings.get("synthesis_drafts", 2),
                                    expected_iterations=settings.get("synthesis_iterations", 5))
            if exploration_stop is not None:
                result["raw"]["exploration_budget_stop"] = exploration_stop
                result["warnings"].append(f"Exploration stopped after {exploration_stop['iterations_completed']} iterations to reserve ${exploration_stop['synthesis_reserve_usd']:g} for synthesis.")
            result["raw"]["config"] = config
            result["raw"]["protocol_version"] = PROTOCOL_VERSION
            record = {"status": "completed", "result": result}
    except BaseException as error:
        exploration_stop = exploration_stop or getattr(agent, "_crest_exploration_budget_stop", None)
        record = {"status": "failed", "error": _redact(f"{type(error).__name__}: {error}"),
                  "usage": audit.snapshot(), "raw": {"artifact": artifact, "exploration_budget_stop": exploration_stop}, "protocol_version": PROTOCOL_VERSION}
    finally:
        if agent is not None:
            try:
                with _safe_logging():
                    agent.shutdown()
            except BaseException as error:
                if record and record.get("status") == "completed":
                    record["result"]["warnings"].append(f"Caesar cleanup failed: {type(error).__name__}")
        if record is not None:
            atomic_json(result_path, record)
    return 0 if record and record.get("status") == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if request.get("protocol_version") != PROTOCOL_VERSION:
        atomic_json(args.result, {"status": "failed", "error": "Unsupported Caesar worker protocol"})
        return 1
    return run_worker(request, args.result)


if __name__ == "__main__":
    raise SystemExit(main())
