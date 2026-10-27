"""Durable OpenAI Responses REST transport with safe rejected-request retries.

Pricing reference: https://developers.openai.com/api/docs/models/gpt-6.1-sol
Web search billing: https://developers.openai.com/api/docs/guides/tools-web-search
The budget is a soft target: background usage may only arrive at completion.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from crest.providers.http import RequestNotSent, request

if TYPE_CHECKING:
    from crest.cache import Job

ADAPTER_VERSION = "openai-responses-v3"
API_URL = "https://api.openai.com/v1/responses"
ACTIVE = {"queued", "in_progress"}


class ProviderError(RuntimeError):
    """A response cannot safely be accepted or submitted automatically."""


async def generate(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _run(prompt, settings, job, client=client, is_judge=False)


async def judge(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    return await _run(prompt, settings, job, client=client, is_judge=True)


def _payload(prompt, settings, is_judge):
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
        payload.update(tools=[{"type": "web_search"}], tool_choice="required",
                       include=["web_search_call.action.sources"],
                       max_tool_calls=settings.get("max_tool_calls", 25))
    return payload


def _raw(response):
    try:
        return response.json()
    except ValueError:
        return {"http_status": response.status_code, "body": response.text}


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


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
        "input_tokens": _count(original.get("input_tokens")),
        "cached_input_tokens": _count(details.get("cached_tokens", 0)),
        "cache_write_tokens": _count(details.get("cache_write_tokens", 0)),
        "output_tokens": _count(original.get("output_tokens")),
        "reasoning_tokens": _count(out_details.get("reasoning_tokens")),
        "total_tokens": _count(original.get("total_tokens")),
        "web_search_calls": None if unknown_search else searches,
    }
    required = [usage[k] for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "web_search_calls")]
    if raw.get("model") != "gpt-6.1-sol" or raw.get("service_tier", "default") != "default" or None in required:
        return usage, None
    inp, cached, writes, output, searches = required
    if cached + writes > inp:
        return usage, None
    long_context = inp > 272000
    input_cost = ((inp - cached - writes) * 2 + cached * .10 + writes * 2.50) * (2 if long_context else 1)
    output_cost = output * 10 * (1.5 if long_context else 1)
    return usage, (input_cost + output_cost) / 1_000_000 + searches * .01


def _result(raw, settings, is_judge):
    if raw.get("status") != "completed":
        raise ProviderError(f"OpenAI response status is {raw.get('status')!r}, expected completed")
    if raw.get("error") or raw.get("incomplete_details"):
        raise ProviderError("OpenAI completed response contains an error or incomplete details")
    parts, citations, seen = [], [], set()
    for item in raw.get("output") or []:
        if item.get("type") != "message":
            continue
        if item.get("status") not in (None, "completed"):
            raise ProviderError("OpenAI completed response contains a message with incomplete status")
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
                for annotation in content.get("annotations") or []:
                    url = annotation.get("url")
                    if annotation.get("type") == "url_citation" and url and url not in seen:
                        citations.append({"url": url, "title": annotation.get("title", "")})
                        seen.add(url)
    text = "\n\n".join(parts)
    if not text.strip():
        raise ProviderError("OpenAI completed response contains empty answer text")
    usage, cost = _account(raw)
    warnings = [] if is_judge else ["Budget is a soft target; hosted usage may be unavailable until completion, and cancellation can incur charges."]
    if cost is None:
        warnings.append("Cost unknown: essential usage, search actions, or applicable model/service-tier pricing is unavailable.")
    if cost is not None and cost > settings.get("budget_usd", 5.0):
        warnings.append(f"Observed cost ${cost:.6f} exceeded the ${settings.get('budget_usd', 5.0):.2f} budget target.")
    return {"text": text, "citations": citations, "model": raw.get("model", settings.get("model", "gpt-6.1-sol")),
            "usage": usage, "cost_usd": cost, "cost_estimated": cost is not None, "warnings": warnings, "raw": raw}


async def _cancel(client, job, reason, settings):
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


async def _run(prompt, settings, job, *, client, is_judge):
    if job.state.get("submission_unknown") and not job.state.get("remote_id"):
        raise ProviderError("OpenAI submission status unknown; refusing an automatic second paid submission")
    if client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is required")
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}) as owned:
            return await _run(prompt, settings, job, client=owned, is_judge=is_judge)
    timeout = float(settings.get("timeout_seconds", 1800))
    interval = max(0, float(settings.get("poll_interval_seconds", 5)))
    raw = None
    if not job.state.get("remote_id"):
        payload = _payload(prompt, settings, is_judge)
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
            if raw.get("status") == "completed":
                return _result(raw, settings, is_judge)
            if raw.get("status") not in ACTIVE:
                raise ProviderError(f"OpenAI response status is {raw.get('status')!r}, expected completed")
            usage, cost = _account(raw)
            if cost is not None and cost > settings.get("budget_usd", 5.0):
                job.save(observed_usage=usage, observed_cost_usd=cost)
                await _cancel(client, job, "budget", settings)
                raise ProviderError("OpenAI observable usage exceeded budget target; cancellation requested")
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
            if not response.is_success:
                job.save(poll_raw=fetched, poll_http_status=response.status_code)
            response.raise_for_status()
            if not isinstance(fetched, dict):
                raise ProviderError("OpenAI retrieval returned invalid response data")
            raw = fetched
        except httpx.HTTPError as exc:
            job.save(poll_error=str(exc))
            if raw is not None and time.time() >= deadline:
                await _cancel(client, job, "timeout", settings)
                raise TimeoutError("OpenAI response timed out; cancellation requested (see cancel_status)") from exc
            raise
