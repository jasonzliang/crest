"""Durable OpenAI Responses REST transport with safe rejected-request retries.

Pricing reference: https://developers.openai.com/api/docs/models/gpt-6.1-sol
                 https://developers.openai.com/api/docs/models/gpt-6-astra
Web search billing: https://developers.openai.com/api/docs/guides/tools-web-search
The budget is a soft target or, under a hard cap, a cancel ceiling: background usage may only arrive at completion.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from crest.providers import (DEFAULT_BUDGET_USD, budget_is_hard, budget_warnings, continuation_prompt, count,
                             needs_more_research, sum_usage)
from crest.providers.http import RequestNotSent, request

if TYPE_CHECKING:
    from crest.cache import Job

ADAPTER_VERSION = "openai-responses-v4"
API_URL = "https://api.openai.com/v1/responses"
ACTIVE = {"queued", "in_progress"}
TERMINAL = {"completed", "failed", "incomplete", "cancelled"}


class ProviderError(RuntimeError):
    """A response cannot safely be accepted or submitted automatically."""


async def generate(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _run(prompt, settings, job, client=client, is_judge=False)


async def judge(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _run(prompt, settings, job, client=client, is_judge=True)


def _payload(prompt, settings, is_judge, previous_response_id=None):
    payload = {
        "model": settings.get("model", "gpt-6.1-sol"), "input": prompt,
        "background": True, "store": True, "service_tier": "default",
        "reasoning": {"effort": settings.get("reasoning_effort", "medium" if is_judge else "high")},
        "max_output_tokens": settings.get("max_output_tokens", 12000 if is_judge else 40000),
        "truncation": "disabled",
    }
    if is_judge:
        from crest.judging import SCHEMA
        payload["text"] = {"format": {"type": "json_schema", "name": "crest_verdict",
                                        "strict": True, "schema": SCHEMA}}
    else:
        tool = {"type": "web_search"}
        if settings.get("search_context_size"):
            tool["search_context_size"] = settings["search_context_size"]
        payload.update(tools=[tool], tool_choice="required",
                       include=["web_search_call.action.sources"],
                       max_tool_calls=settings.get("max_tool_calls", 25))
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    return payload


def _raw(response):
    try:
        return response.json()
    except ValueError:
        return {"http_status": response.status_code, "body": response.text}


def _account(raw):
    """Output usage already includes reasoning tokens; never add them again."""
    original = raw.get("usage") or {}
    details = original.get("input_tokens_details") or {}
    out_details = original.get("output_tokens_details") or {}
    searches, unknown_search = 0, False
    for item in raw.get("output") or []:
        if item.get("type") == "web_search_call":
            action = (item.get("action") or {}).get("type")
            searches += action == "search"
            unknown_search |= action not in {"search", "open_page", "find_in_page"}
    usage = {
        "input_tokens": count(original.get("input_tokens")),
        "cached_input_tokens": count(details.get("cached_tokens", 0)),
        "cache_write_tokens": count(details.get("cache_write_tokens", 0)),
        "output_tokens": count(original.get("output_tokens")),
        "reasoning_tokens": count(out_details.get("reasoning_tokens")),
        "total_tokens": count(original.get("total_tokens")),
        "web_search_calls": None if unknown_search else searches,
    }
    required = [usage[k] for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "web_search_calls")]
    # Standard USD per million tokens; cache writes use the default 30m TTL.
    rates = {"gpt-6.1-sol": (2, .10, 2.50, 10), "gpt-6-astra": (10, 1, 12.50, 50)}.get(raw.get("model"))
    if rates is None or raw.get("service_tier", "default") != "default" or None in required:
        return usage, None
    inp, cached, writes, output, searches = required
    if cached + writes > inp:
        return usage, None
    input_rate, cached_rate, write_rate, output_rate = rates
    long_context = inp > 272000
    input_cost = ((inp - cached - writes) * input_rate + cached * cached_rate + writes * write_rate) * (2 if long_context else 1)
    output_cost = output * output_rate * (1.5 if long_context else 1)
    return usage, (input_cost + output_cost) / 1_000_000 + searches * .01


def _total(rounds):
    """Usage and cost summed over research rounds; unknown if any round is unknown."""
    accounts = [_account(raw) for raw in rounds]
    usage = sum_usage(usage for usage, _ in accounts) | {"rounds": len(rounds)}
    costs = [cost for _, cost in accounts]
    return usage, None if any(cost is None for cost in costs) else sum(costs)


def _result(rounds, settings, is_judge):
    """The last completed round is the answer; every round is billed and contributes citations."""
    answer = next((raw for raw in reversed(rounds) if raw.get("status") == "completed"), None)
    if answer is None:
        raise ProviderError(f"OpenAI response status is {rounds[-1].get('status')!r}, expected completed")
    if answer.get("error") or answer.get("incomplete_details"):
        raise ProviderError("OpenAI completed response contains an error or incomplete details")
    parts, citations, seen = [], [], set()
    for raw in rounds:
        for item in raw.get("output") or []:
            if item.get("type") != "message":
                continue
            if raw is answer and item.get("status") not in (None, "completed"):
                raise ProviderError("OpenAI completed response contains a message with incomplete status")
            for content in item.get("content") or []:
                if content.get("type") != "output_text":
                    continue
                if raw is answer:
                    parts.append(content.get("text", ""))
                for annotation in content.get("annotations") or []:
                    url = annotation.get("url")
                    if annotation.get("type") == "url_citation" and url and url not in seen:
                        citations.append({"url": url, "title": annotation.get("title", "")})
                        seen.add(url)
    text = "\n\n".join(parts)
    if not text.strip():
        raise ProviderError("OpenAI completed response contains empty answer text")
    usage, cost = _total(rounds)
    warnings = [] if is_judge else [("Budget is a ceiling; " if budget_is_hard(settings) else "Budget is a soft target; ") + "hosted usage may be unavailable until completion, and cancellation can incur charges."]
    warnings += budget_warnings(settings, cost, len(rounds),
                                unknown_reason="essential usage, search actions, or applicable model/service-tier pricing is unavailable.")
    if rounds[-1] is not answer:
        warnings.append(f"The final round ended with status {rounds[-1].get('status')!r}; the previous round's answer is kept.")
    return {"text": text, "citations": citations, "model": answer.get("model", settings.get("model", "gpt-6.1-sol")),
            "usage": usage, "cost_usd": cost, "cost_estimated": cost is not None, "warnings": warnings,
            "raw": answer if len(rounds) == 1 else {**rounds[-1], "previous_rounds": rounds[:-1]}}


async def _cancel(client, job, reason, settings):
    _observe_pre_cancel(job, job.state.get("raw"))
    job.save(cancel_requested=True, cancel_reason=reason, cancel_status="unknown",
             pre_cancel_raw=job.state.get("raw"))
    url = f"{API_URL}/{quote(job.state['remote_id'], safe='')}/cancel"
    try:
        response = await request(client, "POST", url, job=job, settings=settings,
                                 deadline=time.time() + 15, timeout=15)
        raw = _raw(response)
        job.save(cancel_raw=raw)
        response.raise_for_status()
        if not isinstance(raw, dict):
            raise ProviderError("Invalid cancellation response")
        status = raw.get("status")
        job.save(cancel_status=status or "unknown", raw=raw, remote_status=status)
    except (httpx.HTTPError, ProviderError) as exc:
        job.save(cancel_error=str(exc), cancel_status="unknown")


def _saved_terminal(job):
    """The checkpointed terminal response for the current round, if it is the known remote one."""
    saved, remote_id = job.state.get("raw"), job.state.get("remote_id")
    if (isinstance(saved, dict) and saved.get("status") in TERMINAL
            and isinstance(saved.get("id"), str) and saved["id"]
            and (saved["id"] == remote_id or not remote_id and job.state.get("submission_unknown"))):
        return saved
    return None


async def _run(prompt, settings, job, *, client, is_judge):
    saved = _saved_terminal(job)
    if client is None and not (saved and (saved["status"] == "completed" or _account(saved)[1] is not None)):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is required")
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}) as owned:
            return await _run(prompt, settings, job, client=owned, is_judge=is_judge)
    earlier = job.state.get("rounds", [])  # Completed earlier rounds; the flat keys hold the current one.
    while True:
        prior = _total(earlier)[1]
        try:
            raw = await _response(prompt if not earlier else continuation_prompt(settings, prior),
                                  earlier[-1]["id"] if earlier else None, prior, settings, job, client, is_judge)
        except (ProviderError, TimeoutError):
            if not earlier:
                raise
            # A later round failed or was cancelled: keep the paid earlier answer and account for the attempt.
            failed = job.state.get("raw")
            return _terminal_result([*earlier, failed] if isinstance(failed, dict) else earlier, settings, job, is_judge)
        rounds = [*earlier, raw]
        if (not is_judge and raw.get("status") == "completed"
                and needs_more_research(settings, len(rounds), _total(rounds)[1], _account(raw)[1])):
            # One save closes this round and clears the per-response keys for the next one.
            earlier = [*earlier, _trim(raw)]
            job.save(rounds=earlier, remote_id=None, raw=None, remote_status=None,
                     submission_unknown=False, submitted_at=None, pre_cancel_raw=None)
            continue
        return _terminal_result(rounds, settings, job, is_judge)


def _trim(raw):
    """An earlier round without its retrieved source lists, which only the live round needs."""
    output = []
    for item in raw.get("output") or []:
        if item.get("type") == "web_search_call" and isinstance(item.get("action"), dict):
            item = {**item, "action": {k: v for k, v in item["action"].items() if k != "sources"}}
        output.append(item)
    return {**raw, "output": output}


async def _response(prompt, previous_response_id, prior_cost, settings, job, client, is_judge):
    """Submit or resume one background response and return its terminal body."""
    _observe_pre_cancel(job, job.state.get("pre_cancel_raw"))
    saved = _saved_terminal(job)
    if saved is not None:
        job.save(remote_id=saved["id"], remote_status=saved["status"], submission_unknown=False)
        # Cancellation acknowledgments can omit usage. Keep the known ID and
        # retrieve a final receipt rather than making that omission permanent.
        if saved["status"] == "completed" or _account(saved)[1] is not None:
            return saved
    if job.state.get("submission_unknown") and not job.state.get("remote_id"):
        raise ProviderError("OpenAI submission status unknown; refusing an automatic second paid submission")
    if client is None:  # A key-free resume may only read a saved response, never submit.
        raise ProviderError("OPENAI_API_KEY is required")
    timeout = float(settings.get("timeout_seconds", 1800))
    interval = max(0, float(settings.get("poll_interval_seconds", 5)))
    raw = None
    if not job.state.get("remote_id"):
        payload = _payload(prompt, settings, is_judge, previous_response_id)
        job.save(submission_unknown=True, submitted_at=time.time())
        try:
            response = await request(client, "POST", API_URL, job=job, settings=settings,
                                     deadline=job.state["submitted_at"] + timeout,
                                     json=payload, timeout=max(.001, min(60, timeout)))
        except httpx.HTTPError as exc:
            job.save(submission_error=str(exc))
            if isinstance(exc, RequestNotSent):
                raise ProviderError("OpenAI submission was not sent before its deadline") from exc
            raise ProviderError("OpenAI submission status unknown after transport failure") from exc
        raw = _raw(response)
        if not response.is_success:
            # These HTTP responses explicitly reject the request. Other failures may
            # have occurred after acceptance, so must never trigger another POST.
            rejected = response.status_code in {400, 401, 403, 404, 413, 422, 429}
            job.save(raw=raw, submission_unknown=not rejected, submission_http_status=response.status_code)
            raise ProviderError(f"OpenAI submit HTTP {response.status_code}; submission status {'rejected' if rejected else 'unknown'}")
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            job.save(raw=raw)
            raise ProviderError("OpenAI submission status unknown: response missing remote id")
        job.save(remote_id=raw["id"], raw=raw, remote_status=raw.get("status"), submission_unknown=False)
    deadline = float(job.state.get("submitted_at", time.time())) + timeout
    while True:
        if raw is not None:
            job.save(raw=raw, remote_status=raw.get("status"))
            if raw.get("status") not in ACTIVE:
                return raw
            usage, cost = _account(raw)
            if cost is not None and prior_cost + cost > settings.get("budget_usd", DEFAULT_BUDGET_USD):
                job.save(observed_usage=usage, observed_cost_usd=cost, budget_exceeded=True)
                if budget_is_hard(settings):
                    await _cancel(client, job, "budget", settings)
                    raise ProviderError("OpenAI observable usage exceeded budget ceiling; cancellation requested")
        # On resume raw is None: retrieve once before using the submission age
        # to cancel. The paid response may have completed while Crest was stopped.
        if raw is not None and time.time() >= deadline:
            await _cancel(client, job, "timeout", settings)
            raise TimeoutError("OpenAI response timed out; cancellation requested (see cancel_status)")
        if raw is not None:
            await asyncio.sleep(min(interval, max(0, deadline - time.time())))
            if time.time() >= deadline:
                continue
        url = f"{API_URL}/{quote(job.state['remote_id'], safe='')}"
        try:
            retrieval_timeout = 60 if raw is None else max(.001, min(60, deadline - time.time()))
            response = await request(client, "GET", url, job=job, settings=settings,
                                     deadline=time.time() + 60 if raw is None else deadline,
                                     timeout=retrieval_timeout)
            fetched = _raw(response)
            matching = isinstance(fetched, dict) and fetched.get("id") == job.state["remote_id"]
            if not response.is_success or not matching:
                job.save(poll_raw=fetched, poll_http_status=response.status_code)
            response.raise_for_status()
            if not matching:
                raise ProviderError("OpenAI retrieval returned invalid or mismatched response data")
            raw = fetched
        except httpx.HTTPError as exc:
            job.save(poll_error=str(exc))
            if raw is not None and time.time() >= deadline:
                await _cancel(client, job, "timeout", settings)
                raise TimeoutError("OpenAI response timed out; cancellation requested (see cancel_status)") from exc
            raise


def _terminal_result(rounds, settings, job, is_judge):
    """Keep a priced receipt even when the terminal response cannot be an answer."""
    try:
        return _result(rounds, settings, is_judge)
    except ProviderError:
        usage, cost = _total(rounds)
        job.save(provider_result={"model": rounds[-1].get("model", settings.get("model", "gpt-6.1-sol")),
                                  "usage": usage, "cost_usd": cost,
                                  "cost_estimated": cost is not None, "raw": rounds[-1]})
        raise


def _observe_pre_cancel(job, raw):
    if isinstance(raw, dict) and raw.get("status") in ACTIVE:
        usage, cost = _account(raw)
        if cost is not None:
            job.save(observed_usage=usage, observed_cost_usd=cost,
                     observed_cost_scope="partial_pre_cancel")
