"""Gemini v1beta Interactions adapter with safe rejected-request retries.

Protocol and pricing checked 2026-10-26:
https://ai.google.dev/gemini-api/docs/deep-research
https://ai.google.dev/api/interactions-api
https://ai.google.dev/gemini-api/docs/pricing
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from crest.providers.http import request

if TYPE_CHECKING:
    from crest.cache import Job


ADAPTER_VERSION = "gemini-interactions-v1beta-2"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
RESEARCH_AGENT = "deep-research-preview-04-2026"
BILLING_MODEL = "gemini-3.1-pro-preview"
ARGON_MODEL = "gemini-4-argon"
ACTIVE_STATUSES = ("queued", "in_progress")


async def generate(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    """Run the managed research agent, or retrieve its checkpointed interaction."""
    body = {
        "input": prompt,
        "agent": settings.get("agent", RESEARCH_AGENT),
        "background": True,
        "store": True,
        "agent_config": {
            "type": "deep-research",
            "thinking_summaries": "none",
            "visualization": "off",
            "collaborative_planning": False,
        },
    }
    return await _run(body, settings, job, client, research=True)


async def judge(prompt: str, settings: dict, job: Job, *, client=None) -> dict:
    """Request the shared binary rubric as JSON without enabling any tools."""
    from crest.judging import SCHEMA

    body = {
        "input": prompt,
        "model": settings.get("model", BILLING_MODEL),
        "background": True,
        "store": True,
        "generation_config": {
            "thinking_level": settings.get("thinking_level", "high"),
            "max_output_tokens": settings.get("max_output_tokens", 12000),
        },
        "response_format": {"type": "text", "mime_type": "application/json", "schema": SCHEMA},
    }
    return await _run(body, settings, job, client, research=False)


async def _run(body, settings, job, client, *, research):
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("Set GOOGLE_API_KEY or GEMINI_API_KEY to use Gemini")
    if job.state.get("submission_unknown") and not job.state.get("remote_id"):
        raise RuntimeError("Gemini submission outcome unknown; reconcile before submitting again")
    if client is None:
        async with httpx.AsyncClient() as owned_client:
            return await _interact(body, settings, job, owned_client, key, research=research)
    return await _interact(body, settings, job, client, key, research=research)


def _submitted_at(job):
    value = job.state.get("submitted_at")
    if value is None:
        return time.time()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    return float(value)


async def _interact(body, settings, job, client, key, *, research):
    headers = {"x-goog-api-key": key}
    timeout = float(settings.get("timeout_seconds", 1800))
    remote_id = job.state.get("remote_id")
    # A known-unsent or explicitly rejected create starts a fresh timeout. Only
    # an existing remote interaction retains its original elapsed-time limit.
    deadline = (_submitted_at(job) if remote_id else time.time()) + timeout
    if remote_id:
        # A local timeout does not establish the remote outcome: paid work may
        # have completed while this process was stopped. Retrieve it first.
        raw = await _request(client, "GET", _url(remote_id), headers, job, settings,
                             deadline=time.time() + 60)
        status = raw.get("status")
        job.save(remote_status=status)
        if status == "completed":
            return _result(raw, settings, research=research)
        if status not in ACTIVE_STATUSES:
            raise RuntimeError(f"Gemini interaction ended with status {status!r}: {raw.get('error')}")
    try:
        async with asyncio.timeout(max(0, deadline - time.time())):
            if remote_id:
                if deadline <= time.time():
                    raise TimeoutError("Gemini interaction exceeded its timeout")
            else:
                # Checkpoint before sending: even a crash between POST and saving
                # the remote id must never result in a second paid submission.
                job.save(submission_unknown=True, submitted_at=time.time())
                raw = await _request(client, "POST", BASE_URL, headers, job, settings,
                                     body=body, deadline=deadline)
                remote_id = raw.get("id")
                if not isinstance(remote_id, str) or not remote_id:
                    raise RuntimeError("Gemini submission outcome unknown: response has no interaction id")
                job.save(remote_id=remote_id, remote_status=raw.get("status"), submission_unknown=False)

            while True:
                status = raw.get("status")
                job.save(raw=raw, remote_status=status)
                if status == "completed":
                    return _result(raw, settings, research=research)
                if status not in ACTIVE_STATUSES:
                    raise RuntimeError(f"Gemini interaction ended with status {status!r}: {raw.get('error')}")
                if research:
                    usage = _usage(raw)
                    cost = _cost(usage, settings.get("billing_model", BILLING_MODEL), research=True)
                    if cost is not None and cost > settings.get("budget_usd", 5.0):
                        job.save(observed_usage=usage, observed_cost_usd=cost, budget_exceeded=True)
                        break
                await asyncio.sleep(float(settings.get("poll_interval_seconds", 5)))
                raw = await _request(client, "GET", _url(remote_id), headers, job, settings, deadline=deadline)
        await _cancel(client, remote_id, headers, job, settings)
        raise RuntimeError(f"Gemini research budget target exceeded by conservative estimate ${cost:.4f}; cancellation attempted")
    except TimeoutError:
        if remote_id:
            await _cancel(client, remote_id, headers, job, settings)
        raise TimeoutError("Gemini interaction exceeded its timeout") from None


def _url(remote_id):
    return BASE_URL + "/" + quote(remote_id, safe="")


async def _request(client, method, url, headers, job, settings, *, body=None, deadline=None):
    try:
        response = await request(client, method, url, job=job, settings=settings,
                                 deadline=deadline, headers=headers, json=body, timeout=60)
    except httpx.HTTPError as error:
        job.save(transport_error={"type": type(error).__name__, "message": str(error)})
        raise
    if response.is_client_error and response.status_code not in {408, 409} and url == BASE_URL:
        # An explicit rejection is distinguishable from an ambiguous POST failure.
        job.save(submission_unknown=False)
    try:
        raw = response.json()
    except ValueError:
        job.save(raw={"http_status": response.status_code, "body": response.text})
        response.raise_for_status()
        raise
    job.save(raw=raw)
    response.raise_for_status()
    if not isinstance(raw, dict):
        raise RuntimeError("Gemini response must be an interaction object")
    return raw


async def _cancel(client, remote_id, headers, job, settings):
    try:
        async with asyncio.timeout(10):
            response = await request(client, "POST", _url(remote_id) + "/cancel",
                                     job=job, settings=settings, deadline=time.time() + 10,
                                     headers=headers, timeout=10)
            try:
                raw = response.json()
            except ValueError:
                raw = {"http_status": response.status_code, "body": response.text}
            job.save(cancellation=raw)
            response.raise_for_status()
            if isinstance(raw, dict):
                job.save(remote_status=raw.get("status", job.state.get("remote_status")))
    except (httpx.HTTPError, TimeoutError) as error:
        job.save(cancellation_error={"type": type(error).__name__, "message": str(error)})


def _answer(raw):
    if "steps" in raw:
        content = [part for step in raw["steps"] if step.get("type") == "model_output"
                   for part in step.get("content", [])]
    else:
        # Older Interactions revisions emitted outputs instead of steps.
        content = raw.get("outputs", [])
    text = []
    citations = []
    seen = set()
    for part in content:
        if part.get("type") != "text" or part.get("thought"):
            continue
        if isinstance(part.get("text"), str):
            text.append(part["text"])
        for annotation in part.get("annotations", []):
            url = annotation.get("url")
            if annotation.get("type") == "url_citation" and url and url not in seen:
                citations.append({"url": url, "title": annotation.get("title", "")})
                seen.add(url)
    answer = "\n".join(text)
    if not answer.strip():
        raise RuntimeError("Gemini completed without nonempty answer text")
    return answer, citations


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(raw):
    source = raw.get("usage") or {}
    usage = {name: _count(source.get(field)) for name, field in {
        "input_tokens": "total_input_tokens",
        "cached_input_tokens": "total_cached_tokens",
        "output_tokens": "total_output_tokens",
        "reasoning_tokens": "total_thought_tokens",
        "tool_use_tokens": "total_tool_use_tokens",
        "total_tokens": "total_tokens",
    }.items()}
    grounding = source.get("grounding_tool_count")
    usage["grounding_tool_count"] = grounding
    usage["search_queries"] = None
    if isinstance(grounding, list):
        searches = [item.get("count") for item in grounding if item.get("type") == "google_search"]
        if all(_count(count) is not None for count in searches):
            usage["search_queries"] = sum(searches)
    return usage


def _pricing_date(raw):
    created = raw.get("created")
    if isinstance(created, str):
        try:
            timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return timestamp.astimezone(timezone.utc).date().isoformat(), "response.created"
        except (ValueError, OverflowError):
            pass
    return datetime.fromtimestamp(time.time(), timezone.utc).date().isoformat(), "processing_date_utc"


def _cost(usage, model, *, research, pricing_date=None):
    fields = [usage[name] for name in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")]
    if model not in {BILLING_MODEL, ARGON_MODEL} or any(value is None for value in fields):
        return None
    if research and model != BILLING_MODEL:
        return None
    inputs, cached, outputs, thoughts = fields
    if cached > inputs:
        return None
    grounding = usage["grounding_tool_count"]
    tools = usage["tool_use_tokens"]
    tool_cost = 0
    if research:
        if tools is None or not isinstance(grounding, list):
            return None
        for item in grounding:
            if item.get("type") not in {"google_search", "google_maps"} or _count(item.get("count")) is None:
                return None
            tool_cost += item["count"] * .014
        # Aggregate loops do not expose each request's context tier. The
        # upper envelope uses the high tier and charges tool-use prompts as
        # additional input; account-level free searches are not deducted.
        inputs += tools
    elif tools not in (None, 0) or any(item.get("count") != 0 for item in (grounding or [])):
        return None
    if model == ARGON_MODEL:
        if pricing_date is None:
            return None
        # Argon has one context price; its introductory rates end Nov 30.
        input_rate, cached_rate, output_rate = ((2, .1, 10) if pricing_date < "2026-12-01"
                                               else (4, .2, 20))
    else:
        input_rate, cached_rate, output_rate = (4, .4, 18) if research or inputs > 200_000 else (2, .2, 12)
    # The official v1beta example has input=7, output=20, thought=22,
    # total=49: output and thought counts are disjoint. Bill each once.
    return ((inputs - cached) * input_rate + cached * cached_rate
            + (outputs + thoughts) * output_rate) / 1_000_000 + tool_cost


def _result(raw, settings, *, research):
    text, citations = _answer(raw)
    usage = _usage(raw)
    model = (settings.get("billing_model", BILLING_MODEL) if research
             else raw.get("model", settings.get("model", BILLING_MODEL)))
    warnings = []
    pricing = {}
    if not research and model == ARGON_MODEL:
        pricing_date, source = _pricing_date(raw)
        pricing = {"pricing_date": pricing_date, "pricing_date_source": source}
        if source != "response.created":
            warnings.append("Response creation date unavailable; Argon pricing uses the recorded UTC processing date.")
    cost = _cost(usage, model, research=research, pricing_date=pricing.get("pricing_date"))
    if research:
        budget = settings.get("budget_usd", 5.0)
        warnings.append(f"Research budget ${budget:g} is a target; the managed agent exposes no dollar cap.")
        if cost is not None:
            warnings.append("Research cost is a conservative upper-envelope estimate: high context tier, tool-use prompts as additional input, and undiscounted searches; per-loop context tiers are unavailable.")
            if cost > budget:
                warnings.append(f"Estimated cost ${cost:.4f} exceeds the ${budget:g} research budget target.")
        else:
            warnings.append("Research cost unknown: essential token usage, search usage, or model pricing is unavailable.")
    if cost is None and not research:
        warnings.append("Cost unknown: model pricing or essential usage is unavailable.")
    if cost is not None:
        warnings.append("Cost uses published standard model rates; excludes account-specific discounts and cache storage.")
    return {"text": text, "citations": citations, "model": model, "usage": usage,
            "cost_usd": cost, "cost_estimated": cost is not None, "warnings": warnings, "raw": raw, **pricing}
