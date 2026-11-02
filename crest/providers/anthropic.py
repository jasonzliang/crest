"""Anthropic Messages adapter: streamed web-search research and structured judging.

Research uses Claude Sonnet with the hosted web_search and web_fetch server tools;
judging uses Claude Fable with a JSON-schema output format and no tools. Both run
through the same durable transport conventions as the other adapters: raw httpx,
checkpoints on the job before any paid request, and no silent resubmission.

Protocol and pricing checked 2026-11-01:
https://platform.claude.com/docs/en/api/versioning
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool
https://platform.claude.com/docs/en/build-with-claude/structured-outputs
https://platform.claude.com/docs/en/build-with-claude/effort
https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback
https://platform.claude.com/docs/en/about-claude/pricing

Messages are synchronous, so a stream that breaks after the server starts
generating has already been billed for an unknown amount. Such attempts are
recorded on the job, retried in place while the conversation is still in memory,
and leave the final cost unknown; a request that never received an HTTP response
is left for review rather than resubmitted.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from typing import TYPE_CHECKING

import httpx

from crest.providers import (DEFAULT_BUDGET_USD, budget_is_hard, budget_warnings, continuation_prompt, count,
                             needs_more_research, sum_usage)
from crest.providers.http import _controller_call, _record, backoff, retry_policy

if TYPE_CHECKING:
    from crest.cache import Job

ADAPTER_VERSION = "anthropic-messages-v2"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
RESEARCH_MODEL = "claude-sonnet-5-5"
JUDGE_MODEL = "claude-fable-5-1"
# USD per million tokens: input, cache read, 5-minute cache write, output.
RATES = {"claude-sonnet-5-5": (2, .10, 2.50, 10), "claude-fable-5-1": (10, .25, 12.50, 50)}
WEB_SEARCH_USD = .01  # $10 per 1,000 searches; web_fetch bills only its tokens.
RETRYABLE = {408, 429, 500, 502, 503, 504, 529}
ENCRYPTED_FIELDS = ("encrypted_content", "encrypted_index")
# Fable's grammar supports the structural subset; nonempty text is checked by parse_verdict.
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "winner": {"type": "string", "enum": ["A", "B"]}},
    "required": ["reason", "winner"],
    "additionalProperties": False,
}


class ProviderError(RuntimeError):
    """A response cannot safely be accepted or submitted automatically."""


class StreamInterrupted(ProviderError):
    """The connection broke after generation started; the attempt was billed."""


class StreamError(ProviderError):
    """The server sent an error event inside the stream."""


async def generate(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _run(prompt, settings, job, client=client, is_judge=False)


async def judge(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _run(prompt, settings, job, client=client, is_judge=True)


def _messages(history):
    """Wire form of the conversation: one cache breakpoint, on the latest user turn.

    Web search then caches each tool result automatically. Echoed assistant content is
    sent back without the server's own cache markers, since at most four are allowed.
    """
    last_user = max(i for i, (role, _) in enumerate(history) if role == "user")
    messages = []
    for index, (role, content) in enumerate(history):
        if role == "user":
            messages.append({"role": "user", "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                             if index == last_user else content})
        else:
            messages.append({"role": "assistant", "content": _without_cache_markers(content)})
    return messages


def _without_cache_markers(value):
    if isinstance(value, dict):
        return {k: _without_cache_markers(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_without_cache_markers(v) for v in value]
    return value


def _payload(messages, settings, is_judge):
    payload = {
        "model": settings.get("model", JUDGE_MODEL if is_judge else RESEARCH_MODEL),
        "max_tokens": settings.get("max_output_tokens", 32768 if is_judge else 64000),
        "messages": messages, "stream": True,
        "output_config": {"effort": settings.get("effort", "high")},
    }
    if is_judge:
        payload["output_config"]["format"] = {"type": "json_schema", "schema": JUDGE_SCHEMA}
    else:
        tools = [{"type": "web_search_20260209", "name": "web_search",
                  "max_uses": settings.get("max_web_searches", 30)}]
        if settings.get("web_fetch", True):
            tools.append({"type": "web_fetch_20260209", "name": "web_fetch",
                          "max_uses": settings.get("max_web_fetches", 10)})
        payload["tools"] = tools
    if settings.get("refusal_fallback"):
        payload["fallbacks"] = "default"
    return payload


def _headers(key, settings):
    headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json",
               "accept": "text/event-stream"}
    if settings.get("refusal_fallback"):
        headers["anthropic-beta"] = FALLBACK_BETA
    return headers


def _raw(turns):
    return {"turns": [_strip(turn) for turn in turns]}


def _strip(value):
    """Drop encrypted search payloads from checkpoints; they are only needed to continue a turn."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in ENCRYPTED_FIELDS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _turn_usage(message):
    usage = message.get("usage") or {}
    tools = usage.get("server_tool_use") or {}
    return {"input_tokens": count(usage.get("input_tokens")),
            "cached_input_tokens": count(usage.get("cache_read_input_tokens") or 0),
            "cache_write_tokens": count(usage.get("cache_creation_input_tokens") or 0),
            # Only a message_delta reports final output; message_start carries a placeholder.
            "output_tokens": count(usage.get("output_tokens")) if message.get("_usage_final") else None,
            "web_search_calls": count(tools.get("web_search_requests", 0)),
            "web_fetch_calls": count(tools.get("web_fetch_requests", 0))}


def _turn_cost(message):
    usage = _turn_usage(message)
    rates = RATES.get(message.get("model"))
    required = [usage[k] for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens",
                                   "output_tokens", "web_search_calls")]
    if rates is None or None in required:
        return usage, None
    inp, cached, writes, output, searches = required
    input_rate, cached_rate, write_rate, output_rate = rates
    # Input tokens exclude cached and cache-written tokens; writes assume the default 5-minute TTL.
    tokens = inp * input_rate + cached * cached_rate + writes * write_rate + output * output_rate
    return usage, tokens / 1_000_000 + searches * WEB_SEARCH_USD


def _account(turns, prior_attempts=()):
    """Sum every billed turn, including interrupted attempts recorded on the job."""
    accounts = [_turn_cost(turn) for turn in turns]
    prior = [attempt.get("cost_usd") for attempt in prior_attempts]
    costs = [cost for _, cost in accounts] + prior
    usage = sum_usage(usage for usage, _ in accounts) | {
        "turns": len(turns), "interrupted_attempts": len(prior_attempts),
        "interrupted_attempt_cost_usd": sum(value for value in prior if isinstance(value, (int, float)))}
    return usage, None if any(value is None or isinstance(value, bool) for value in costs) else sum(costs)


def _text_and_citations(turns):
    """The last research round's text is the answer; citations come from every turn."""
    parts, citations, seen = [], [], set()
    final_round = turns[-1].get("_round", 1)
    for message in turns:
        for block in message.get("content") or []:
            if block.get("type") != "text":
                continue
            if message.get("_round", 1) == final_round:
                parts.append(block.get("text", ""))
            for citation in block.get("citations") or []:
                url = citation.get("url")
                if url and url not in seen:
                    citations.append({"url": url, "title": citation.get("title") or ""})
                    seen.add(url)
    return "\n\n".join(part for part in parts if part), citations


def _finished(turn):
    return turn.get("stop_reason") in ("end_turn", "stop_sequence")


def _result(turns, settings, job, is_judge):
    final = next((turn for turn in reversed(turns) if _finished(turn)), turns[-1])
    stop = final.get("stop_reason")
    text, citations = _text_and_citations(turns[:turns.index(final) + 1])
    usage, cost = _account(turns, job.state.get("interrupted_attempts", []))
    model = final.get("model", settings.get("model", JUDGE_MODEL if is_judge else RESEARCH_MODEL))
    receipt = {"model": model, "usage": usage, "cost_usd": cost, "cost_estimated": cost is not None, "raw": _raw(turns)}
    try:
        if stop == "refusal":
            raise ProviderError(f"Anthropic stop_reason refusal; stop_details={json.dumps(_strip(final.get('stop_details')))}")
        if stop == "max_tokens":
            raise ProviderError("Anthropic response was truncated at max_tokens")
        if stop not in ("end_turn", "stop_sequence"):
            raise ProviderError(f"Anthropic response ended with stop_reason {stop!r}")
        if not text.strip():
            raise ProviderError("Anthropic response contains empty answer text")
    except ProviderError:
        job.save(provider_result=receipt)
        raise
    rounds = final.get("_round", 1)
    warnings = [] if is_judge else [("Budget is a ceiling; " if budget_is_hard(settings) else "Budget is a soft target; ") + "the Messages API exposes no dollar cap and usage is final only at the end of each turn."]
    warnings += budget_warnings(settings, cost, rounds, unknown_reason="usage or pricing for the recorded model is unavailable.")
    if usage["interrupted_attempts"]:
        warnings.append(f"{usage['interrupted_attempts']} earlier attempt(s) were billed before this answer; "
                        + ("their estimate is included." if cost is not None else "their charges are unknown, so the total cost is unknown."))
    if len(turns) > rounds:
        warnings.append(f"The answer took {len(turns)} server turns over {rounds} research round(s); every turn is billed.")
    if turns[-1] is not final:
        warnings.append(f"The final round ended with stop_reason {turns[-1].get('stop_reason')!r}; the previous round's answer is kept.")
    return {"text": text, "citations": citations, **receipt, "warnings": warnings}


class _Assembler:
    """Rebuild a complete message object from server-sent stream events."""

    def __init__(self):
        self.message = None
        self.blocks = {}

    def feed(self, event):
        kind = event.get("type")
        if kind == "message_start":
            self.message = copy.deepcopy(event["message"])
            self.message["content"] = []
        elif kind == "content_block_start":
            block = copy.deepcopy(event["content_block"])
            if block.get("type") in ("server_tool_use", "tool_use"):
                block["_partial_json"] = ""
            self.blocks[event["index"]] = block
            self.message["content"].append(block)
        elif kind == "content_block_delta":
            block, delta = self.blocks.get(event.get("index"), {}), event["delta"]
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                block["text"] = block.get("text", "") + delta.get("text", "")
            elif delta_type == "input_json_delta":
                block["_partial_json"] = block.get("_partial_json", "") + delta.get("partial_json", "")
            elif delta_type == "citations_delta":
                if not isinstance(block.get("citations"), list):
                    block["citations"] = []
                block["citations"].append(delta.get("citation"))
            elif delta_type == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
            elif delta_type == "signature_delta":
                block["signature"] = delta.get("signature")
        elif kind == "content_block_stop":
            block = self.blocks.get(event["index"], {})
            partial = block.pop("_partial_json", None)
            if partial is not None and partial.strip():
                block["input"] = json.loads(partial)
        elif kind == "message_delta":
            for key, value in (event.get("delta") or {}).items():
                self.message[key] = value
            if event.get("usage"):
                self.message.setdefault("usage", {}).update(event["usage"])
                self.message["_usage_final"] = True
        elif kind == "error":
            error = event.get("error") or {}
            raise StreamError(f"Anthropic stream error: {error.get('type')}: {error.get('message')}")
        return kind == "message_stop"

    def started(self):
        return self.message is not None


async def _stream_turn(client, headers, payload, job, settings, deadline):
    """One streamed request with retries only for explicit transient rejections."""
    attempts, base, cap = retry_policy(settings)
    controller = getattr(job, "rate_controller", None)
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("Anthropic request deadline elapsed before dispatch")
        if controller is not None:
            async with asyncio.timeout(remaining):
                await _controller_call(controller, "wait_ready")
        assembler = _Assembler()
        job.save(submission_unknown=True, submitted_at=time.time())
        timeout = httpx.Timeout(60, read=min(600., max(1., deadline - time.time())))
        try:
            async with client.stream("POST", API_URL, headers=headers, json=payload, timeout=timeout) as response:
                if controller is not None:
                    await _controller_call(controller, "observe_headers", response.headers)
                if response.status_code != 200:
                    body = await response.aread()
                    try:
                        rejection = json.loads(body)
                    except ValueError:
                        rejection = {"http_status": response.status_code, "body": body.decode("utf-8", "replace")}
                    # An explicit error response is never billed and never generated.
                    job.save(submission_unknown=False, last_rejection=rejection, submission_http_status=response.status_code)
                    delay = backoff(attempt, base, cap, response.headers)
                    if response.status_code == 429 and controller is not None:
                        await _controller_call(controller, "rate_limited", delay)
                    event = _record(job, method="POST", attempt=attempt, delay=delay, response=response,
                                    retrying=response.status_code in RETRYABLE and attempt < attempts
                                    and time.time() + delay < deadline)
                    if not event["retrying"]:
                        raise ProviderError(f"Anthropic HTTP {response.status_code}; submission rejected")
                    if not (response.status_code == 429 and controller is not None):
                        await asyncio.sleep(delay)
                    continue
                async with asyncio.timeout(max(.001, deadline - time.time())):
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        if assembler.feed(json.loads(data)):
                            break
        except Exception as exc:
            if isinstance(exc, ProviderError) and not isinstance(exc, StreamError):
                raise  # An HTTP rejection raised above; nothing was generated.
            # A server error event before any content is a rejection; anything after message_start
            # on a transport failure, or after content on a server error, was billed.
            billed = assembler.started() and (not isinstance(exc, StreamError) or assembler.message.get("content"))
            if billed:
                _record_interruption(job, assembler.message, f"{type(exc).__name__}: {exc}")
                raise StreamInterrupted("Anthropic stream interrupted after generation started; the attempt is recorded") from exc
            if isinstance(exc, StreamError):
                delay = backoff(attempt, base, cap)
                job.save(submission_unknown=False, last_rejection=str(exc))
                event = _record(job, method="POST", attempt=attempt, delay=delay, error=exc,
                                retrying="overloaded" in str(exc) and attempt < attempts and time.time() + delay < deadline)
                if event["retrying"]:
                    await asyncio.sleep(delay)
                    continue
                raise
            if isinstance(exc, TimeoutError):
                raise TimeoutError("Anthropic request exceeded its deadline before a response") from exc
            raise ProviderError("Anthropic submission status unknown after transport failure") from exc
        if assembler.message is None or assembler.message.get("stop_reason") is None:
            _record_interruption(job, assembler.message, "stream ended without a terminal message_delta")
            raise StreamInterrupted("Anthropic stream ended without a terminal message")
        job.save(submission_unknown=False)
        return assembler.message
    raise AssertionError("retry loop did not return or raise")


def _record_interruption(job, message, error):
    """Generation began, so the attempt was billed for an unknown amount; keep what was observed."""
    record = {"error": error, "at": time.time(), "cost_usd": None, "model": (message or {}).get("model"),
              "observed_usage": _turn_cost(message)[0] if message else {}}
    job.save(submission_unknown=False, interrupted_attempts=[*job.state.get("interrupted_attempts", []), record])


async def _run(prompt, settings, job, *, client, is_judge):
    saved = (job.state.get("raw") or {}).get("turns") if isinstance(job.state.get("raw"), dict) else None
    if saved and saved[-1].get("stop_reason") not in (None, "pause_turn"):
        # A finished exchange already exists for this job; reuse it instead of paying again (even after an
        # interrupt left submission_unknown set). A round below the budget floor cannot be deepened from a
        # checkpoint, so it is final (and warned about).
        return _result(saved, settings, job, is_judge)
    if job.state.get("submission_unknown"):
        raise ProviderError("Anthropic submission status unknown; refusing an automatic second paid submission")
    retries = max(1, int(settings.get("retry_attempts", 4)))
    if saved:
        # Paused turns cannot be resumed from a checkpoint (encrypted search results are not kept),
        # so the exchange restarts; its billed turns stay in the accounting.
        job.save(raw=None, consecutive_interruptions=job.state.get("consecutive_interruptions", 0) + 1,
                 interrupted_attempts=[*job.state.get("interrupted_attempts", []), {
            "error": "abandoned paused exchange", "at": time.time(), "cost_usd": _account(saved)[1],
            "model": saved[-1].get("model"), "turns": len(saved)}])
    streak = job.state.get("consecutive_interruptions", len(job.state.get("interrupted_attempts", [])))
    if streak >= retries:
        raise ProviderError(f"Anthropic stream was interrupted {streak} times in a row; review before retrying")
    if client is None:
        async with httpx.AsyncClient() as owned:
            return await _run(prompt, settings, job, client=owned, is_judge=is_judge)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ProviderError("ANTHROPIC_API_KEY is required")
    headers = _headers(key, settings)
    deadline = time.time() + float(settings.get("timeout_seconds", 900 if is_judge else 5400))
    history = [("user", prompt)]
    turns, rounds, pauses = [], 1, 0
    limit = max(0, int(settings.get("max_continuations", 10)))
    while True:
        payload = _payload(_messages(history), settings, is_judge)
        try:
            message = await _stream_turn(client, headers, payload, job, settings, deadline)
        except (StreamInterrupted, ProviderError, TimeoutError) as exc:
            if isinstance(exc, StreamInterrupted):
                recorded = job.state.get("consecutive_interruptions")  # The interruption itself is already recorded.
                streak = len(job.state.get("interrupted_attempts", [])) if recorded is None else recorded + 1
                job.save(consecutive_interruptions=streak)
                if streak < retries:
                    # The broken turn is recorded as a billed attempt; the same turn is retried while
                    # the conversation (with its encrypted search results) is still in memory.
                    continue
            if any(_finished(turn) for turn in turns):
                return _result(turns, settings, job, is_judge)  # Keep the paid earlier round's answer.
            raise
        message["_round"] = rounds
        turns.append(message)
        job.save(raw=_raw(turns), remote_status=message.get("stop_reason"), consecutive_interruptions=0)
        usage, cost = _account(turns, job.state.get("interrupted_attempts", []))
        over_budget = cost is not None and cost > settings.get("budget_usd", DEFAULT_BUDGET_USD)
        if over_budget:
            job.save(budget_exceeded=True)
        paused = message.get("stop_reason") == "pause_turn" or (
            message.get("stop_reason") == "tool_use"  # The server loop stopped on one of its own tools.
            and not any(block.get("type") == "tool_use" for block in message.get("content") or []))
        if paused:
            pauses += 1
            stop_for_budget = over_budget and budget_is_hard(settings)
            if pauses > limit or stop_for_budget:
                if any(_finished(turn) for turn in turns):
                    return _result(turns, settings, job, is_judge)  # Keep the paid earlier round's answer.
                job.save(provider_result={"model": message.get("model"), "usage": usage, "cost_usd": cost,
                                          "cost_estimated": cost is not None, "raw": _raw(turns)})
                raise ProviderError("Anthropic budget ceiling exceeded; not starting another server turn" if stop_for_budget
                                    else f"Anthropic paused {pauses} times without finishing; max_continuations reached")
            # Resume exactly where the server paused: echo the assistant turn, including encrypted search results.
            history.append(("assistant", message["content"]))
            continue
        if (not is_judge and message.get("stop_reason") == "end_turn"
                and needs_more_research(settings, rounds, cost, sum(_turn_cost(turn)[1] or 0. for turn in turns if turn.get("_round") == rounds))):
            # Below the budget floor: ask for more research and a full rewrite in a new round.
            rounds, pauses = rounds + 1, 0
            history += [("assistant", message["content"]), ("user", continuation_prompt(settings, cost))]
            continue
        return _result(turns, settings, job, is_judge)
