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
import shutil
import socket
import sys
import tempfile
import threading
import time
from email.utils import parsedate_to_datetime
from uuid import uuid4

from crest.caesar_metrics import iteration_metrics

PROTOCOL_VERSION = "caesar-worker-v1"
SOL = "gpt-6.1-sol"
LUNA = "gpt-6-luna"
# Standard prices: https://developers.openai.com/api/docs/models/gpt-6.1-sol
# Luna: https://developers.openai.com/api/docs/models/gpt-6-luna
PRICES = {LUNA: {"input": .1, "output": .5, "cache_read": .01, "cache_write": .125}, SOL: {"input": 2., "output": 10., "cache_read": .1, "cache_write": 2.5},
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
            "cost_limit": settings.get("handler_budget_usd", settings.get("handler_cost_limit", 5.)),
            "max_completion_tokens": settings.get("max_completion_tokens", 25000),
            "max_input_tokens": settings.get("max_input_tokens", 64000),
            "timeout": settings.get("call_timeout_seconds", 600), "max_retries": 0,
        },
        "CaesarAgent": {
            "mode": "web", "starting_query": prompt, "allowed_domains": ["*"],
            "max_iterations": settings.get("max_iterations", 250), "max_depth": settings.get("max_depth", 6),
            "additional_starting_queries": settings.get("additional_starting_queries", 11),
            "max_web_searches": settings.get("max_web_searches", 5),
            "draw_graph": False, "adapt_role": settings.get("adapt_role", True),
            "use_quick_explore": settings.get("use_quick_explore", False),
            "quick_explore_insights": settings.get("quick_explore_insights", True),
            "quick_explore_workers": settings.get("quick_explore_workers", 2),
            "save_graph_interval": settings.get("save_graph_interval", 50),
            "exploration_llm_config": {
                "model": settings.get("exploration_model", LUNA),
                "reasoning_effort": settings.get("exploration_reasoning_effort", "low"),
                "max_completion_tokens": settings.get("exploration_max_completion_tokens", 2000),
                "timeout": settings.get("call_timeout_seconds", 600),
            },
        },
        "ArtifactSynthesizer": {
            "synthesis_classic_mode": False, "synthesis_drafts": settings.get("synthesis_drafts", 3),
            "synthesis_iterations": settings.get("synthesis_iterations", 15),
            "synthesis_reasoning_effort": settings.get("synthesis_reasoning_effort", "medium"),
            "synthesis_top_k": settings.get("synthesis_top_k", settings.get("retrieval_chunks", 15)),
            "synthesis_top_n": settings.get("synthesis_top_n", settings.get("retrieval_chunks", 10)),
            "synthesis_merge_artifacts": settings.get("synthesis_merge_artifacts", True), "synthesis_merge_clarify": False,
            "synthesis_eli5": False, "synthesis_human_eval": False, "synthesis_generate_images": 0,
        },
        "BraveSearch": {"use_ddgs": True},
        "ChromaClientManager": {
            "collection_name": collection, "enable_reranking": False, "use_shared_server": False,
            "model": settings.get("kb_model", LUNA), "reasoning_effort": settings.get("kb_reasoning_effort", "low"),
            "embedding_model": settings.get("embedding_model", "text-embedding-3-small"),
            "top_k": settings.get("synthesis_top_k", settings.get("retrieval_chunks", 15)),
        },
        "ChromaServerManager": {"host": "127.0.0.1", "port": settings.get("chroma_port", 8000),
                                "persist_path": str(output_dir / "chroma"),
                                "startup_timeout": 15, "shutdown_timeout": 2},
    }


def extract_result(artifact: dict, model: str, usage: dict, *, expected_drafts=3, expected_iterations=15) -> dict:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("artifact"), str) or not artifact["artifact"].strip():
        raise ValueError("Caesar did not return a nonempty final artifact")
    if artifact.get("num_drafts") != expected_drafts:
        raise ValueError("Caesar synthesis ended before all requested drafts completed")
    metadata = artifact.get("metadata") or {}
    completed_rounds = metadata.get("synthesis_queries", 0)
    if not isinstance(completed_rounds, int) or completed_rounds < 1:
        raise ValueError("Caesar synthesis did not complete any Q&A rounds")
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
    if completed_rounds < expected_iterations:
        warnings.append(f"Final draft completed {completed_rounds} of up to {expected_iterations} requested Q&A rounds.")
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
    old_litellm = {model: copy.deepcopy(getattr(litellm_module, "model_cost", {}).get(model)) for model in (SOL, LUNA)}
    try:
        entries = {}
        for model in (SOL, LUNA):
            rates = PRICES[model]
            if tokenizer_registry is not None:
                tokenizer_registry[model] = "o200k_base"
            handler.MODEL_PRICING[model] = {"input": rates["input"], "output": rates["output"]}
            handler.MODEL_CONTEXT_SIZE[model] = 1_050_000
            handler.REASONING_MODELS.add(model)
            for name in registries:
                getattr(llama_utils, name)[model] = 1_050_000
            entries[model] = {"litellm_provider": "openai", "mode": "chat",
                "input_cost_per_token": rates["input"] / 1e6, "output_cost_per_token": rates["output"] / 1e6,
                "max_input_tokens": 1_050_000, "max_tokens": 1_050_000, "supports_reasoning": True,
                "cache_read_input_token_cost": rates["cache_read"] / 1e6,
                "cache_creation_input_token_cost": rates["cache_write"] / 1e6}
        handler._known_models_registered = False
        default_config["LLMHandler"]["max_completion_tokens"] = kb_limit
        litellm_module.register_model(entries)
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
            for model, previous in old_litellm.items():
                if previous is None:
                    litellm_module.model_cost.pop(model, None)
                else:
                    litellm_module.model_cost[model] = previous


class WorkerDeadlineExceeded(BaseException):
    """Fatal wall-clock cutoff that Rome's broad Exception handlers cannot swallow."""


class SDKRequestFailed(BaseException):
    """Stop Rome retry ladders after permanent, exhausted, or ambiguous SDK failure."""


class IncompleteSDKOutput(ValueError):
    """Known billed output was truncated; a budgeted rewrite can be attempted."""


def _error_body(error):
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return {}
    return body["error"] if isinstance(body.get("error"), dict) else body


def _retry_after_seconds(error):
    headers = getattr(getattr(error, "response", None), "headers", {})
    body = _error_body(error)
    values = [headers.get("retry-after", headers.get("Retry-After")), body.get("retry_after"), body.get("retry_after_seconds")]
    delay = 0.
    for value in values:
        try:
            advised = float(value)
        except (TypeError, ValueError):
            try:
                advised = parsedate_to_datetime(value).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                continue
        if math.isfinite(advised):
            delay = max(delay, advised)
    return delay


class BudgetExceeded(RuntimeError):
    """A projected request cannot fit the observable remaining target budget."""


class UsageAudit:
    """Audit at the OpenAI SDK boundary, including direct KB and embedding calls.

    Reservations use a conservative UTF-8 byte bound for input and the requested
    output limit. Ambiguous failures retain reservations and stop Rome retry ladders.
    Confirmed 429 rejections release reservations; transient 5xx retries retain theirs.
    Both retry here with bounded attempts/backoff and a new budget check each time;
    SDK-internal retries are disabled so every attempt remains visible.
    """
    def __init__(self, budget: float, path: Path, prices=None, *, retry_attempts=4,
                 retry_backoff_base_seconds=1, retry_backoff_max_seconds=30):
        self.budget = float(budget)
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff_base_seconds = max(0., float(retry_backoff_base_seconds))
        self.retry_backoff_max_seconds = max(0., float(retry_backoff_max_seconds))
        self.path = Path(path)
        self.prices = {**PRICES, **(prices or {})}
        self.events = []
        self.pending = {}
        self.exploration_limit = None
        self.request_limit = None
        self.request_limited = False
        self.exploration_limited = False
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
        input_multiplier = 2 if model in (SOL, LUNA) and input_bound > 272_000 else 1
        output_multiplier = 1.5 if input_multiplier == 2 else 1
        input_rate = max(rates.get("input", 0), rates.get("cache_write", 0)) if rates else 0
        reserve = (input_bound * input_rate * input_multiplier + (output_bound or 0) * rates["output"] * output_multiplier) / 1e6 if rates and bounded else 0.
        with self.lock:
            known = sum(event.get("cost_usd") or 0 for event in self.events)
            reserved = sum(event["reserved_usd"] for event in self.pending.values())
            reserved += sum(event.get("reserved_usd", 0) for event in self.events if event["status"] == "failed")
            ceiling = self.budget if self.exploration_limit is None else min(self.budget, self.exploration_limit)
            if self.request_limit is not None:
                ceiling = min(ceiling, self.request_limit)
            if rates and bounded and known + reserved + reserve > ceiling:
                if self.request_limit is not None and known + reserved + reserve > self.request_limit:
                    self.request_limited = True
                if self.exploration_limit is not None and known + reserved + reserve > self.exploration_limit:
                    self.exploration_limited = True
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
                if status == 429 or isinstance(status, int) and 500 <= status < 600:
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
                    input_multiplier = 2 if event["model"] in (SOL, LUNA) and inputs > 272_000 else 1
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
            return event

    def retry_delay(self, error, attempt, failed_event=None):
        if not isinstance(error, Exception):
            raise error
        status = getattr(error, "status_code", None)
        reserved = bool(failed_event and failed_event.get("reserved_usd", 0) > 0)
        transient = status == 429 or reserved and isinstance(status, int) and 500 <= status < 600
        if not transient or _error_body(error).get("retryable") is False or getattr(error, "code", None) == "insufficient_quota" or attempt + 1 >= self.retry_attempts:
            outcome = "rejected" if status in (401, 403, 429) else "billing outcome unknown"
            raise SDKRequestFailed(f"{type(error).__name__}: {outcome}; stopped after {attempt + 1} attempt(s)") from error
        backoff = min(self.retry_backoff_max_seconds, self.retry_backoff_base_seconds * 2. ** attempt)
        return max(backoff + random.uniform(0., 1.), _retry_after_seconds(error))

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
                    failed = audit.after(token, error=error)
                    time.sleep(audit.retry_delay(error, attempt, failed))
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
                    failed = audit.after(token, error=error)
                    await asyncio.sleep(audit.retry_delay(error, attempt, failed))
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
def chroma_python_cli(manager_class):
    """Run Chroma with the worker's packages even when its CLI is absent from PATH."""
    original = manager_class._try_start_command
    def launch(manager, command):
        if command and command[0] == "chroma":
            command = [sys.executable, "-c",
                "import sys; from chromadb.cli.cli import app; sys.argv[0] = 'chroma'; app()", *command[1:]]
        return original(manager, command)
    manager_class._try_start_command = launch
    try:
        yield
    finally:
        manager_class._try_start_command = original


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
    from rome.kb_server import ChromaServerManager
    original_init = openai.OpenAI.__init__
    original_async_init = openai.AsyncOpenAI.__init__
    def init(instance, *args, **kwargs):
        kwargs["max_retries"] = 0
        kwargs["timeout"] = settings.get("call_timeout_seconds", 600)
        original_init(instance, *args, **kwargs)
    def async_init(instance, *args, **kwargs):
        kwargs["max_retries"] = 0
        kwargs["timeout"] = settings.get("call_timeout_seconds", 600)
        original_async_init(instance, *args, **kwargs)
    openai.OpenAI.__init__ = init
    openai.AsyncOpenAI.__init__ = async_init
    try:
        with compatibility(LLMHandler, DEFAULT_CONFIG, litellm, llama_utils, settings.get("kb_max_completion_tokens", 2000), tokenizer_registry=tiktoken.model.MODEL_TO_ENCODING), audit.installed(SyncAPIClient, AsyncAPIClient), chroma_python_cli(ChromaServerManager):
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



def _committed_spend(audit):
    usage = audit.snapshot()
    return (usage["known_cost_usd"] + sum(item["reserved_usd"] for item in usage["in_flight"])
            + sum(item.get("reserved_usd", 0) for item in usage["events"] if item["status"] == "failed"))



@contextmanager
def synthesis_query_completion_limits(agent, settings):
    """Keep query/refinement requests short without limiting draft/merge output."""
    synthesizer = getattr(agent, "synthesizer", None)
    original = getattr(synthesizer, "_llm_call", None)
    if original is None:
        yield
        return
    def call(*args, **kwargs):
        label = kwargs.get("label", args[4] if len(args) > 4 else "LLM")
        if label not in {"NEXT_QUERY", "REFINE"}:
            return original(*args, **kwargs)
        chat = agent.chat_completion
        handler = getattr(agent, "llm_handler", None)
        previous = getattr(handler, "max_completion_tokens", None)
        limit = min(int(settings.get("query_max_completion_tokens", 6000)), previous or int(settings.get("max_completion_tokens", 25000)))
        def short_chat(*chat_args, **chat_kwargs):
            overrides = dict(chat_kwargs.get("override_config") or {})
            overrides["max_completion_tokens"] = limit
            chat_kwargs["override_config"] = overrides
            return chat(*chat_args, **chat_kwargs)
        agent.chat_completion = short_chat
        if previous is not None:
            handler.max_completion_tokens = limit
        try:
            return original(*args, **kwargs)
        finally:
            agent.chat_completion = chat
            if previous is not None:
                handler.max_completion_tokens = previous
    synthesizer._llm_call = call
    try:
        yield
    finally:
        synthesizer._llm_call = original


@contextmanager
def adaptive_synthesis_budget(agent, settings, audit):
    """Allocate QA money and elapsed time while retaining later writes and merging."""
    synthesizer = getattr(agent, "synthesizer", None)
    original_qa = getattr(synthesizer, "_generate_qa_pairs", None)
    original_merge = getattr(synthesizer, "_merge_artifacts", None)
    timeout = float(settings.get("timeout_seconds", 7200))
    deadline = getattr(agent, "_crest_worker_deadline", time.monotonic() + timeout)
    write_seconds = min(300., timeout / 24)
    records = {"requested_qa_rounds_per_draft": settings.get("synthesis_iterations", 15),
               "drafts": [], "merge_requested": settings.get("synthesis_merge_artifacts", True),
               "merge_completed": False, "write_allowance_per_call_usd": .35,
               "time_policy": {"timeout_seconds": timeout, "exploration_time_limit_seconds": timeout * .375,
                    "write_allowance_per_call_seconds": write_seconds, "best_effort": True}}
    agent._crest_synthesis_budget = records
    if original_qa is None:
        yield records
        return
    def qa(*args, **kwargs):
        draft = getattr(synthesizer, "_current_draft", 1)
        remaining_drafts = max(1, synthesizer.synthesis_drafts - draft + 1)
        writes = remaining_drafts + remaining_drafts - 1 + int(synthesizer.synthesis_merge_artifacts)
        committed = _committed_spend(audit)
        ceiling = min(audit.budget, float(settings.get("handler_budget_usd", 5.)))
        write_allowance = min(writes * .35, max(0., ceiling - committed) * .7)
        allowance = max(0., (ceiling - committed - write_allowance) / remaining_drafts)
        qa_started = time.monotonic()
        time_allowance = max(0., (deadline - qa_started - writes * write_seconds) / remaining_drafts)
        qa_deadline = qa_started + time_allowance
        time_limited = False
        first_check = True
        original_shutdown = getattr(synthesizer, "_shutdown_requested", None)
        original_next = getattr(synthesizer, "_generate_next_query", None)
        def should_stop():
            nonlocal time_limited, first_check
            initial = first_check
            first_check = False
            if original_shutdown is not None and original_shutdown():
                return True
            now = time.monotonic()
            if now >= qa_deadline:
                time_limited = True
                return not (initial and deadline - now > write_seconds)
            return False
        def next_query(*args, **kwargs):
            return None if should_stop() else original_next(*args, **kwargs)
        previous_limit, previous_limited = audit.request_limit, audit.request_limited
        audit.request_limit, audit.request_limited = committed + allowance, False
        synthesizer._shutdown_requested = should_stop
        if original_next is not None:
            synthesizer._generate_next_query = next_query
        try:
            pairs = original_qa(*args, **kwargs)
        finally:
            limited = audit.request_limited
            audit.request_limit, audit.request_limited = previous_limit, previous_limited
            if original_shutdown is None:
                del synthesizer._shutdown_requested
            else:
                synthesizer._shutdown_requested = original_shutdown
            if original_next is not None:
                synthesizer._generate_next_query = original_next
        records["drafts"].append({"draft": draft, "requested_qa_rounds": synthesizer.synthesis_iterations,
            "completed_qa_rounds": len(pairs), "budget_limited": limited, "qa_allowance_usd": allowance,
            "remaining_write_allowance_usd": write_allowance, "time_limited": time_limited,
            "qa_time_allowance_seconds": time_allowance, "qa_elapsed_seconds": time.monotonic() - qa_started,
            "remaining_write_allowance_seconds": writes * write_seconds})
        atomic_json(audit.path.with_name("synthesis-budget.json"), records)
        return pairs
    def merge(*args, **kwargs):
        result = original_merge(*args, **kwargs)
        records["merge_completed"] = bool(result and result.get("artifact"))
        atomic_json(audit.path.with_name("synthesis-budget.json"), records)
        return result
    synthesizer._generate_qa_pairs = qa
    if original_merge is not None:
        synthesizer._merge_artifacts = merge
    try:
        yield records
    finally:
        synthesizer._generate_qa_pairs = original_qa
        if original_merge is not None:
            synthesizer._merge_artifacts = original_merge


def _quick_explore_with_synthesis_reserve(agent, settings, audit):
    """Drain accepted quick tasks and ingest their results before releasing the reserve."""
    reserve = float(settings.get("synthesis_reserve_usd", 3.))
    ceiling = min(audit.budget, float(settings.get("handler_budget_usd", settings.get("handler_cost_limit", 5.))))
    limit = max(0., ceiling - reserve)
    previous_limit, previous_limited = audit.exploration_limit, audit.exploration_limited
    original_page = agent._quick_perceive_and_think
    original_ingest = agent.kb_manager.add_texts
    original_synthesize = agent.synthesizer.synthesize_artifact
    started = getattr(agent, "_crest_worker_started", time.monotonic())
    deadline = getattr(agent, "_crest_worker_deadline", started + float(settings.get("timeout_seconds", 7200)))
    exploration_seconds = (deadline - started) * .375
    exploration_deadline = started + exploration_seconds
    time_limited = False
    stop = None
    audit.exploration_limit, audit.exploration_limited = limit, False
    def page(*args, **kwargs):
        nonlocal time_limited
        if time.monotonic() >= exploration_deadline:
            time_limited = True
            return None
        if audit.exploration_limited or _committed_spend(audit) >= limit:
            audit.exploration_limited = True
            return None
        return original_page(*args, **kwargs)
    def finish_exploration():
        nonlocal stop
        if (audit.exploration_limited or time_limited) and stop is None:
            stop = {"mode": "quick", "iterations_completed": len(agent.visited_urls),
                "max_submission_iteration": agent.current_iteration,
                "committed_usd": _committed_spend(audit), "synthesis_reserve_usd": reserve,
                "exploration_limit_usd": limit, "reason": "time_reserve" if time_limited else "budget_reserve",
                "time_limited": time_limited, "exploration_time_limit_seconds": exploration_seconds,
                "elapsed_seconds": time.monotonic() - started}
            agent._crest_exploration_budget_stop = stop
            atomic_json(audit.path.with_name("exploration-budget-stop.json"), stop)
        audit.exploration_limit = previous_limit
    def ingest(*args, **kwargs):
        finish_exploration()
        return original_ingest(*args, **kwargs)
    def synthesize(*args, **kwargs):
        finish_exploration()
        return original_synthesize(*args, **kwargs)
    agent._quick_perceive_and_think = page
    agent.kb_manager.add_texts = ingest
    agent.synthesizer.synthesize_artifact = synthesize
    try:
        artifact = agent.explore()
    finally:
        finish_exploration()
        agent._quick_perceive_and_think = original_page
        agent.kb_manager.add_texts = original_ingest
        agent.synthesizer.synthesize_artifact = original_synthesize
        audit.exploration_limit, audit.exploration_limited = previous_limit, previous_limited
    return artifact, stop


def _explore_with_synthesis_reserve(agent, settings, audit):
    if getattr(agent, "use_quick_explore", False):
        return _quick_explore_with_synthesis_reserve(agent, settings, audit)
    original_perceive = agent.perceive
    reserve = float(settings.get("synthesis_reserve_usd", 3.))
    # The handler's separate guard also needs enough room for final writing.
    ceiling = min(audit.budget, float(settings.get("handler_budget_usd", settings.get("handler_cost_limit", 5.))))
    started = getattr(agent, "_crest_worker_started", time.monotonic())
    deadline = getattr(agent, "_crest_worker_deadline", started + float(settings.get("timeout_seconds", 7200)))
    exploration_seconds = (deadline - started) * .375
    stop = None
    def perceive(*args, **kwargs):
        committed = _committed_spend(audit)
        time_limited = time.monotonic() >= started + exploration_seconds
        if time_limited or committed >= max(0., ceiling - reserve):
            raise ExplorationBudgetReserved({"iterations_completed": max(0, agent.current_iteration - 1),
                "committed_usd": committed, "synthesis_reserve_usd": reserve,
                "exploration_limit_usd": max(0., ceiling - reserve),
                "reason": "time_reserve" if time_limited else "budget_reserve", "time_limited": time_limited,
                "exploration_time_limit_seconds": exploration_seconds, "elapsed_seconds": time.monotonic() - started})
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


def _agent_name(key):
    return "".join(char for char in ("crest" + key[:20]) if char.isalnum()).ljust(8, "0")[:32]



def _assert_history_worker_stopped(source):
    state_path = source / "state.json"
    if not state_path.exists():
        return
    import psutil
    state = json.loads(state_path.read_text())
    pid = state.get("worker_pid")
    try:
        processes = [psutil.Process(int(pid))] if pid else psutil.process_iter()
        for process in processes:
            try:
                if process.status() == psutil.STATUS_ZOMBIE:
                    continue
                command = process.cmdline()
                if "crest.caesar_worker" in command and any(str(source) in str(arg) for arg in command):
                    raise ValueError("Source worker is still running; final usage is not stable")
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as error:
                if pid:
                    raise ValueError("Cannot verify source worker has stopped") from error
    except psutil.NoSuchProcess:
        return


def recovery_history(source, prompt):
    """Verify each preserved attempt once; never double-count embedded summaries."""
    history, seen = [], set()
    cursor = Path(source).resolve()
    while True:
        if cursor in seen:
            raise ValueError("Recovery ancestry contains a cycle")
        seen.add(cursor)
        _assert_history_worker_stopped(cursor)
        request = json.loads((cursor / "caesar-request.json").read_text())
        record = json.loads((cursor / "caesar-result.json").read_text())
        if request.get("prompt") != prompt:
            raise ValueError("Recovery ancestry contains a different prompt")
        if record.get("status") not in {"failed", "completed"}:
            raise ValueError("Budget ancestry requires a terminal failed/completed attempt")
        result = record.get("result") or {}
        raw = record.get("raw") or result.get("raw") or {}
        usage_path = cursor / "caesar-output" / "usage.json"
        usage = json.loads(usage_path.read_text()) if usage_path.is_file() else raw.get("new_attempt_usage_audit") or record.get("usage") or result.get("usage") or {}
        if raw.get("recovery") and raw.get("budget_history"):
            raise ValueError("Ambiguous budget ancestry modes")
        prior = raw.get("recovery") or raw.get("budget_history") or {}
        known = float(usage["known_cost_usd"])
        unknown = [event for event in usage.get("events", []) if event.get("unknown_cost")]
        unknown += usage.get("in_flight", [])
        if usage.get("unknown_cost") and not unknown:
            raise ValueError("Previous unknown usage has no bounded request entries")
        reserved = [float(event.get("reserved_usd", 0)) for event in unknown]
        if not math.isfinite(known) or known < 0 or any(not math.isfinite(value) or value <= 0 for value in reserved):
            raise ValueError("Previous usage lacks a conservative cost bound")
        worker_id = request.get("worker_id") or request.get("job_key") or cursor.name
        history.append({"source_job": str(cursor), "known_cost_usd": known,
            "usage_source": str(usage_path) if usage_path.is_file() else "terminal_per_attempt_snapshot",
            "unknown_reserved_usd": sum(reserved), "cost_unknown": bool(usage.get("unknown_cost") or unknown),
            "collection_name": "crest_" + hashlib.sha256(worker_id.encode()).hexdigest()[:40]})
        previous_settings = request.get("settings") or {}
        if previous_settings.get("recovery_from") and previous_settings.get("budget_history_from"):
            raise ValueError("Recovery and budget-history modes are mutually exclusive")
        parent = prior.get("source_job") or previous_settings.get("recovery_from") or previous_settings.get("budget_history_from")
        if not parent:
            original_budget = float(usage.get("budget_target_usd", (request.get("settings") or {}).get("budget_usd", 5)))
            if not math.isfinite(original_budget) or original_budget <= 0:
                raise ValueError("Original budget must be positive and finite")
            return list(reversed(history)), original_budget
        cursor = Path(parent).resolve()



def prepare_budget_history(prompt, settings):
    """Reserve lifetime spend while starting completely fresh research state."""
    source = Path(settings["budget_history_from"]).resolve()
    ancestry, original_budget = recovery_history(source, prompt)
    original_budget = min(original_budget, float(settings.get("budget_usd", 5.)))
    known = sum(item["known_cost_usd"] for item in ancestry)
    reserved = sum(item["unknown_reserved_usd"] for item in ancestry)
    remaining = original_budget - known - reserved
    if not math.isfinite(remaining) or remaining <= 0:
        raise ValueError("No budget remains after prior known charges and unknown reservations")
    configured_reserve = float(settings.get("synthesis_reserve_usd", 3.))
    return {"mode": "fresh_restart", "source_job": str(source), "ancestry": ancestry,
        "original_budget_usd": original_budget, "previous_known_cost_usd": known,
        "previous_unknown_reserved_usd": reserved, "previous_cost_unknown": any(item["cost_unknown"] for item in ancestry),
        "new_attempt_budget_usd": remaining, "budgeted_total_exposure_usd": known + reserved + remaining,
        "configured_synthesis_reserve_usd": configured_reserve,
        "effective_synthesis_reserve_usd": configured_reserve * remaining / original_budget}


def prepare_synthesis_recovery(prompt, settings, output_dir, job_key, config):
    """Copy a reviewed failed attempt's local knowledge; never mutate its ledger."""
    source, output_dir = Path(settings["recovery_from"]).resolve(), Path(output_dir).resolve()
    if source == output_dir or source in output_dir.parents:
        raise ValueError("Recovery output must be in a separate new job")
    request = json.loads((source / "caesar-request.json").read_text())
    record = json.loads((source / "caesar-result.json").read_text())
    if record.get("status") != "failed" or request.get("prompt") != prompt:
        raise ValueError("Recovery requires a failed attempt for the exact same prompt")
    prior = (record.get("raw") or {}).get("recovery") or {}
    ancestry, original_budget = recovery_history(source, prompt)
    known = sum(item["known_cost_usd"] for item in ancestry)
    reserved = sum(item["unknown_reserved_usd"] for item in ancestry)
    budget = float(settings.get("budget_usd", 5))
    if not 0 < budget <= min(4.3, original_budget - known - reserved):
        raise ValueError("Recovery needs an explicit budget at most $4.30 and within the prior residual")
    source_output = source / "caesar-output"
    paths = list((source_output / "__rome__").glob("*.checkpoint.json"))
    if len(paths) != 1 or not (source_output / "chroma" / "chroma.sqlite3").is_file():
        raise ValueError("Recovery requires one checkpoint and a persisted Chroma database")
    checkpoint = json.loads(paths[0].read_text())
    if checkpoint.get("config", {}).get("starting_query") != prompt or not checkpoint.get("visited_urls"):
        raise ValueError("Recovery checkpoint has no matching explored knowledge")
    collection = prior.get("collection_name") or ancestry[0]["collection_name"]
    shutil.copytree(source_output / "chroma", output_dir / "chroma")
    checkpoint["cost"] = {"accumulated_cost": 0., "call_count": 0, "sessions": []}
    atomic_json(output_dir / "__rome__" / f"agent_{_agent_name(job_key)}.checkpoint.json", checkpoint)
    config["CaesarAgent"].update(max_iterations=0, adapt_role=False, starting_url=checkpoint["config"]["starting_url"])
    config["ChromaClientManager"]["collection_name"] = collection
    config["LLMHandler"]["cost_limit"] = min(config["LLMHandler"]["cost_limit"], budget)
    recovery = {"source_job": str(source), "source_checkpoint_sha256": hashlib.sha256(paths[0].read_bytes()).hexdigest(),
        "collection_name": collection, "iteration": checkpoint["iteration"], "visited_urls": len(checkpoint["visited_urls"]),
        "previous_known_cost_usd": known, "previous_unknown_reserved_usd": reserved,
        "previous_cost_unknown": any(item["cost_unknown"] for item in ancestry), "ancestry": ancestry,
        "original_budget_usd": original_budget, "new_attempt_budget_usd": budget,
        "budgeted_total_exposure_usd": known + reserved + budget}
    atomic_json(output_dir / "recovery.json", recovery)
    return recovery


def run_worker(request: dict, result_path: Path) -> int:
    worker_started = time.monotonic()
    settings = request.get("settings", {})
    worker_deadline = worker_started + float(settings.get("timeout_seconds", 7200))
    output_dir = Path(request["output_dir"])
    if settings.get("recovery_from") and settings.get("budget_history_from"):
        raise ValueError("Recovery and fresh budget-history modes are mutually exclusive")
    history_source = settings.get("recovery_from") or settings.get("budget_history_from")
    if history_source:
        source = Path(history_source).resolve()
        if source == output_dir.resolve() or source in output_dir.resolve().parents or source in Path(result_path).resolve().parents:
            raise ValueError("Recovery must not write into its original failed job")
    output_dir.mkdir(parents=True, exist_ok=True)
    budget_history = None
    attempt_settings = dict(settings)
    if settings.get("budget_history_from"):
        try:
            budget_history = prepare_budget_history(request["prompt"], settings)
        except Exception as error:
            atomic_json(result_path, {"status": "failed", "error": f"{type(error).__name__}: {error}",
                "usage": {"known_cost_usd": 0., "cost_usd": 0., "unknown_cost": False,
                          "successful_calls": 0, "failed_calls": 0, "events": [], "in_flight": []}})
            return 1
        attempt_settings.update(budget_usd=budget_history["new_attempt_budget_usd"],
            handler_budget_usd=min(float(settings.get("handler_budget_usd", 5.)), budget_history["new_attempt_budget_usd"]),
            synthesis_reserve_usd=budget_history["effective_synthesis_reserve_usd"])
        atomic_json(output_dir / "budget-history.json", budget_history)
    audit = UsageAudit(attempt_settings.get("budget_usd", 5.), output_dir / "usage.json", settings.get("model_pricing"),
                       retry_attempts=settings.get("retry_attempts", 4),
                       retry_backoff_base_seconds=settings.get("retry_backoff_base_seconds", 1),
                       retry_backoff_max_seconds=settings.get("retry_backoff_max_seconds", 30))
    agent = None
    record = None
    artifact = None
    exploration_stop = None
    recovery = None
    metrics = None
    try:
        with _deadline(max(.001, worker_deadline - time.monotonic())), _safe_logging(), _runtime(attempt_settings, audit) as agent_class:
            config = build_config(request["prompt"], attempt_settings, output_dir, request.get("worker_id", request["job_key"]))
            if settings.get("recovery_from"):
                recovery = prepare_synthesis_recovery(request["prompt"], settings, output_dir, request["job_key"], config)
            if "chroma_port" not in settings:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    config["ChromaServerManager"]["port"] = sock.getsockname()[1]
            agent = agent_class(name=_agent_name(request["job_key"]), repository=str(output_dir), config=config)
            agent._crest_worker_started, agent._crest_worker_deadline = worker_started, worker_deadline
            with iteration_metrics(agent, audit, Path(result_path).parent) as metrics, synthesis_query_completion_limits(agent, attempt_settings), adaptive_synthesis_budget(agent, attempt_settings, audit) as synthesis_budget:
                if recovery is not None:
                    if agent.current_iteration != recovery["iteration"] or not agent.visited_urls or agent.kb_manager.size() < 1:
                        raise ValueError("Native recovery did not load the copied checkpoint and knowledge")
                    artifact = agent.synthesizer.synthesize_artifact()
                else:
                    artifact, exploration_stop = _explore_with_synthesis_reserve(agent, attempt_settings, audit)
            if getattr(agent, "shutdown_called", False):
                raise RuntimeError("Caesar was interrupted before completing synthesis")
            result = extract_result(artifact, settings.get("model", SOL), audit.snapshot(),
                                    expected_drafts=settings.get("synthesis_drafts", 3),
                                    expected_iterations=settings.get("synthesis_iterations", 15))
            if exploration_stop is not None:
                result["raw"]["exploration_budget_stop"] = exploration_stop
                time_note = (f" at its {exploration_stop['exploration_time_limit_seconds'] / 60:g}-minute new-page limit, preserving time and"
                             if exploration_stop.get("time_limited") else " to reserve")
                result["warnings"].append(f"Exploration stopped after {exploration_stop['iterations_completed']} iterations{time_note} ${exploration_stop['synthesis_reserve_usd']:g} for synthesis.")
            accounting = recovery or budget_history
            if accounting is not None:
                mode = "recovery" if recovery is not None else "budget_history"
                result["raw"][mode] = accounting
                result["raw"]["new_attempt_usage_audit"] = copy.deepcopy(result["usage"])
                result["usage"]["new_attempt_cost_usd"] = result["cost_usd"]
                result["usage"]["new_attempt_budget_target_usd"] = audit.budget
                result["usage"]["budget_target_usd"] = accounting["original_budget_usd"]
                result["usage"][mode + "_previous_known_cost_usd"] = accounting["previous_known_cost_usd"]
                result["usage"][mode + "_previous_unknown_reserved_usd"] = accounting["previous_unknown_reserved_usd"]
                cumulative_known = accounting["previous_known_cost_usd"] + result["usage"]["known_cost_usd"]
                result["usage"]["known_cost_usd"] = result["usage"]["cumulative_known_cost_usd"] = cumulative_known
                if accounting["previous_cost_unknown"] or result["usage"]["unknown_cost"]:
                    result["cost_usd"] = result["usage"]["cost_usd"] = None
                    result["usage"]["unknown_cost"] = True
                else:
                    result["cost_usd"] = result["usage"]["cost_usd"] = cumulative_known
                result["warnings"].append("Explicit synthesis-only recovery reused copied knowledge; prior attempt billing remains separately recorded." if recovery is not None else "Fresh research inherited prior charges and unknown reservations without reusing old knowledge.")
            result["raw"]["synthesis_budget"] = synthesis_budget
            result["raw"]["iteration_metrics"] = {"records": metrics.records, "summary": metrics.summary(), "trace_path": str(metrics.path)}
            reduced = [row for row in synthesis_budget["drafts"] if row["completed_qa_rounds"] < row["requested_qa_rounds"]]
            if reduced:
                result["warnings"].append("Some requested Q&A rounds did not complete; actual counts and budget limits are recorded for each draft.")
            if synthesis_budget["drafts"] and synthesis_budget["merge_requested"] and not synthesis_budget["merge_completed"]:
                result["warnings"].append("The merge did not complete; the final complete draft was preserved.")
            result["raw"]["config"] = config
            result["raw"]["protocol_version"] = PROTOCOL_VERSION
            record = {"status": "completed", "result": result}
    except BaseException as error:
        exploration_stop = exploration_stop or getattr(agent, "_crest_exploration_budget_stop", None)
        record = {"status": "failed", "error": _redact(f"{type(error).__name__}: {error}"),
                  "usage": audit.snapshot(), "raw": {"artifact": artifact, "exploration_budget_stop": exploration_stop, "synthesis_budget": getattr(agent, "_crest_synthesis_budget", None), "recovery": recovery, "budget_history": budget_history,
                  "iteration_metrics": {"records": metrics.records, "summary": metrics.summary(), "trace_path": str(metrics.path)} if metrics is not None else None}, "protocol_version": PROTOCOL_VERSION}
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
