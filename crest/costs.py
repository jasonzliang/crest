"""Deterministic estimates derived from saved receipts; no billing or file I/O."""
from __future__ import annotations

from collections import Counter
import copy
import math
import posixpath

COST_VERSION = "crest-cost-assessment-v2"
PRICING_DATE = "2026-10-27"
OPENAI_SOURCES = ["https://developers.openai.com/api/docs/pricing",
                  "https://developers.openai.com/api/docs/models/gpt-6-astra",
                  "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
                  "https://developers.openai.com/api/docs/models/gpt-6-luna",
                  "https://developers.openai.com/api/docs/models/text-embedding-3-small",
                  "https://developers.openai.com/api/docs/guides/prompt-caching",
                  "https://developers.openai.com/api/docs/guides/tools-web-search",
                  "https://developers.openai.com/api/reference/python/resources/responses/methods/create"]
GOOGLE_SOURCES = ["https://ai.google.dev/gemini-api/docs/pricing",
                  "https://ai.google.dev/api/interactions-api",
                  "https://ai.google.dev/gemini-api/docs/google-search"]
OPENAI_RATES = {
    "gpt-6-astra": {"input": 10, "cached_input": 1, "cache_write_30m": 12.5, "output": 50},
    "gpt-6.1-sol": {"input": 2, "cached_input": .1, "cache_write_30m": 2.5, "output": 10},
    "gpt-6-luna": {"input": .1, "cached_input": .01, "cache_write_30m": .125, "output": .5},
    "text-embedding-3-small": {"input": .02, "output": 0},
}


def _money(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _first(*values):
    return next((v for v in values if _money(v)), None)


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _history(history):
    seen, attempts = set(), []
    for row in history.get("ancestry") or []:
        if not isinstance(row, dict) or not isinstance(row.get("source_job"), str):
            continue
        source = posixpath.normpath(row["source_job"])
        key = posixpath.basename(source)
        if key in seen:
            continue
        seen.add(key)
        attempts.append({"job_key": key, "source_job": source,
                         "known_estimate_usd": _first(row.get("known_cost_usd")),
                         "unresolved_reserved_exposure_usd": _first(row.get("unknown_reserved_usd")) or 0,
                         "estimate_incomplete": bool(row.get("cost_unknown"))})
    return attempts


def _reserved(audit):
    events = [e for e in audit.get("events", []) if isinstance(e, dict)
              and (e.get("unknown_cost") or e.get("status") == "failed" and not _money(e.get("cost_usd")))]
    events += [e for e in audit.get("in_flight", []) if isinstance(e, dict)]
    return math.fsum(e["reserved_usd"] for e in events if _money(e.get("reserved_usd")))


def _caesar(result):
    raw, usage = _mapping(result.get("raw")), _mapping(result.get("usage"))
    cumulative = _mapping(raw.get("usage_audit")) or usage
    current = _mapping(raw.get("new_attempt_usage_audit"))
    history = _mapping(raw.get("budget_history")) or _mapping(raw.get("recovery"))
    attempts = _history(history)
    prior = _first(history.get("previous_known_cost_usd"),
                   usage.get("budget_history_previous_known_cost_usd"),
                   usage.get("recovery_previous_known_cost_usd"))
    if prior is None:
        prior = math.fsum(a["known_estimate_usd"] for a in attempts if a["known_estimate_usd"] is not None)
    historical_reserve = _first(history.get("previous_unknown_reserved_usd"),
                               usage.get("budget_history_previous_unknown_reserved_usd"),
                               usage.get("recovery_previous_unknown_reserved_usd"))
    if historical_reserve is None:
        historical_reserve = math.fsum(a["unresolved_reserved_exposure_usd"] for a in attempts)
    cumulative_scope = (bool(raw.get("usage_audit")) or "cumulative_known_cost_usd" in cumulative
                        or "new_attempt_cost_usd" in cumulative
                        or any(k in cumulative for k in ("budget_history_previous_known_cost_usd",
                                                         "recovery_previous_known_cost_usd")))
    if cumulative_scope:
        known = _first(cumulative.get("cumulative_known_cost_usd"), cumulative.get("known_cost_usd"), result.get("cost_usd"))
        new = _first(current.get("known_cost_usd"), cumulative.get("new_attempt_cost_usd"))
        if new is None and known is not None and known >= prior:
            new = known - prior
    else:
        new = _first(current.get("known_cost_usd"), usage.get("known_cost_usd"), result.get("cost_usd"))
        known = new + prior if new is not None else prior if history else None
    ledger = current or cumulative
    reserve = _reserved(ledger)
    current_unknown = bool(ledger.get("unknown_cost")) or new is None or reserve > 0
    incomplete = (current_unknown or bool(history.get("previous_cost_unknown"))
                  or bool(cumulative.get("unknown_cost")) or historical_reserve > 0 or result.get("cost_usd") is None)
    return {"current_attempt_known_estimate_usd": new, "prior_attempt_known_estimate_usd": prior,
            "cumulative_known_estimate_usd": known, "current_attempt_estimate_incomplete": current_unknown,
            "historical_unresolved_reserved_exposure_usd": historical_reserve,
            "current_unresolved_reserved_exposure_usd": reserve,
            "unresolved_reserved_exposure_usd": historical_reserve + reserve,
            "estimate_incomplete": incomplete, "history_attempts": attempts}


def _google_scenarios(usage):
    names = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "tool_use_tokens")
    values = [usage.get(k) for k in names]
    grounding = usage.get("grounding_tool_count")
    if (not all(type(v) is int and v >= 0 for v in values) or not isinstance(grounding, list)
            or values[1] > values[0]):
        return {}
    searches = 0
    for item in grounding:
        if not isinstance(item, dict) or type(item.get("count")) is not int or item["count"] < 0:
            return {}
        if item.get("type") != "google_search" and item["count"]:
            return {}  # Other billable tools need their own validated tariff.
        searches += item["count"]
    inputs, cached, outputs, reasoning, tools = values
    scenarios = {}
    for tier, rates in (("low", (2, .2, 12)), ("high", (4, .4, 18))):
        for include_tools in (False, True):
            for search_paid in (False, True):
                tool_name = "included" if include_tools else "excluded"
                search_name = "full_price_search" if search_paid else "search_allowance"
                token_cost = ((inputs - cached + (tools if include_tools else 0)) * rates[0]
                              + cached * rates[1] + (outputs + reasoning) * rates[2]) / 1_000_000
                search_cost = searches * .014 if search_paid else 0
                scenarios[f"{tier}_tool_input_{tool_name}_{search_name}"] = {
                    "estimate_usd": token_cost + search_cost, "token_estimate_usd": token_cost,
                    "search_estimate_usd": search_cost, "classification": "conditional_scenario",
                    "context_tier": tier, "tool_input_included": include_tools,
                    "search_allowance_assumed": not search_paid, "is_invoice": False, "is_proven_bound": False}
    return scenarios


def assess_cost(result: dict, *, agent: str | None = None, settings: dict | None = None) -> dict:
    """Describe saved estimates without modifying the result or inferring an invoice."""
    settings, raw, usage = settings or {}, _mapping(result.get("raw")), _mapping(result.get("usage"))
    model = result.get("model") or settings.get("billing_model") or settings.get("model")
    caesar = agent == "caesar" or bool(raw.get("usage_audit") or raw.get("new_attempt_usage_audit"))
    managed_agent = settings.get("agent") or raw.get("agent")
    research_google = (agent in {"gemini", "google"} and model == "gemini-3.1-pro-preview"
                       and isinstance(managed_agent, str) and managed_agent.startswith("deep-research-"))
    recorded = _first(result.get("cost_usd"))
    details = {"version": COST_VERSION, "recorded_provider_estimate_usd": recorded,
        "invoice_status": "unverified", "actual_billed_usd": None, "actual_internal_model": model,
        "cost_basis": "usage_priced_estimate" if model in OPENAI_RATES else "recorded_provider_estimate",
        "current_attempt_known_estimate_usd": recorded, "prior_attempt_known_estimate_usd": 0,
        "cumulative_known_estimate_usd": recorded,
        "historical_unresolved_reserved_exposure_usd": 0, "current_unresolved_reserved_exposure_usd": 0,
        "unresolved_reserved_exposure_usd": 0, "estimate_incomplete": recorded is None,
        "current_attempt_estimate_incomplete": recorded is None, "history_attempts": [], "conditional_scenarios": {},
        "pricing": {"model": model, "reference_model": model, "date": result.get("pricing_date") or PRICING_DATE,
                    "source_urls": OPENAI_SOURCES[:] if model in OPENAI_RATES or caesar else [], "rates": {}},
        "assumptions": ["Published-price estimates are not invoices; account discounts, taxes and unrecorded charges remain unverified."]}
    if model in OPENAI_RATES or caesar:
        details["pricing"]["rates"] = copy.deepcopy(OPENAI_RATES)
        details["assumptions"] += ["OpenAI standard service tier and default 30-minute cache-write tariff unless the receipt records otherwise.",
            "Legacy prompt_cache_retention=24h is a maximum retention policy, not evidence that the 12-hour cache-write tariff was selected.",
            "Reasoning is already included in OpenAI output tokens; cache reads and writes replace ordinary input tokens.",
            "Sol/Luna per-request contexts over 272,000 input tokens multiply input/cache rates by 2 and output rates by 1.5."]
        if not caesar:
            details["pricing"]["tool_rates"] = {"web_search_search_action_usd": .01}
            details["assumptions"].append("Only search actions add the web-search tool fee; search content tokens are already included in input usage.")
    if caesar:
        details.update(_caesar(result))
        details["cost_basis"] = "sdk_usage_priced_estimate"
        details["assumptions"] += ["Cumulative usage-audit cost already includes prior attempts; current per-model usage is not added again.",
                                   "Iteration and phase metrics allocate the same canonical SDK ledger and are not additional charges.",
                                   "Recorded unresolved reservations are exposure, not measured spend."]
    elif research_google:
        details.update(cost_basis="conditional_list_price_scenario", actual_internal_model=raw.get("model"),
                       estimate_incomplete=True, current_attempt_estimate_incomplete=True,
                       conditional_scenarios=_google_scenarios(usage))
        details["pricing"] = {"model": raw.get("model"), "reference_model": "gemini-3.1-pro-preview",
            "date": PRICING_DATE, "source_urls": GOOGLE_SOURCES[:], "rates": {
                "low": {"input": 2, "cached_input": .2, "output_and_reasoning": 12},
                "high": {"input": 4, "cached_input": .4, "output_and_reasoning": 18}, "search_per_query": .014}}
        scenario = "high_tool_input_included_full_price_search"
        reference = details["conditional_scenarios"].get(scenario, {}).get("estimate_usd")
        details["recorded_scenario"] = scenario
        details["recorded_scenario_matches"] = (math.isclose(recorded, reference, rel_tol=1e-9, abs_tol=1e-9)
                                                  if recorded is not None and reference is not None else None)
        details["assumptions"] += ["The reported model is an adapter billing reference; the managed agent's actual per-loop model and context tiers are unavailable.",
            "The recorded estimate assumes high context pricing, all tool-use tokens as additional input, and full-price searches.",
            "Aggregate tool tokens do not distinguish retrieved Search content from billable URL-context content.",
            "The shared monthly search allowance and per-query billable eligibility are unknown; zero-search-fee scenarios assume all eligible searches are covered.",
            "These eight conditional cases are not verified bills or proven bounds; cache storage and account-specific discounts are excluded."]
        if details["recorded_scenario_matches"] is False:
            details["assumptions"].append("The recorded estimate differs from the independently recomputed reference scenario; both are preserved explicitly.")
    if details["cumulative_known_estimate_usd"] is None:
        details["cost_basis"] = "unpriced"
    return details


def cost_for_row(row: dict) -> dict:
    """Read attached metadata or deterministically derive it for a legacy row."""
    attached = row.get("cost_details")
    if isinstance(attached, dict) and attached.get("version") == COST_VERSION:
        return copy.deepcopy(attached)
    result = row.get("result") if isinstance(row.get("result"), dict) else row
    if row.get('cost_scope') == 'all_judgment_attempts' and row.get('attempts'):
        attempts = row['attempts']
        keys = [attempt.get('key') for attempt in attempts]
        if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError('Judgment attempt receipts require distinct keys')
        details = assess_cost(result, agent=row.get('judge') or row.get('provider'), settings=row.get('settings'))
        amounts = [_first(attempt.get('cost_usd')) for attempt in attempts]
        known = [value for value in amounts if value is not None]
        details.update(
            recorded_provider_estimate_usd=_first(row.get('cost_usd')),
            current_attempt_known_estimate_usd=amounts[-1],
            prior_attempt_known_estimate_usd=math.fsum(v for v in amounts[:-1] if v is not None),
            cumulative_known_estimate_usd=math.fsum(known) if known else None,
            current_attempt_estimate_incomplete=amounts[-1] is None,
            estimate_incomplete=any(value is None for value in amounts),
            history_attempts=[{'job_key': attempt['key'], 'source_job': attempt.get('cache_record'),
                               'known_estimate_usd': amount, 'unresolved_reserved_exposure_usd': 0,
                               'cost_unknown': amount is None}
                              for attempt, amount in zip(attempts[:-1], amounts[:-1])])
        details['assumptions'].append(
            'Judgment costs include retained rejected attempts; displayed response usage belongs only to the selected attempt.')
        return details
    return assess_cost(result, agent=row.get("agent") or row.get("provider") or row.get("judge"),
                       settings=row.get("settings"))


def summarize_costs(rows: list[dict]) -> dict:
    """Sum known estimate components once, with conditional prices and exposure separate."""
    unique, seen = [], set()
    for index, row in enumerate(rows):
        stage = row.get("stage") or ("judge" if row.get("judge") else "generate")
        identity = (stage, row.get("key")) if row.get("key") else ("row", index)
        if identity not in seen:
            seen.add(identity)
            unique.append((row, cost_for_row(row), identity))
    covered = {(a["job_key"]) for _, cost, _ in unique for a in cost["history_attempts"]}
    included = [(row, cost) for row, cost, identity in unique
                if not (identity[0] == "generate" and row.get("key") in covered)]
    fields = ("current_attempt_known_estimate_usd", "prior_attempt_known_estimate_usd",
              "cumulative_known_estimate_usd", "historical_unresolved_reserved_exposure_usd",
              "current_unresolved_reserved_exposure_usd", "unresolved_reserved_exposure_usd")
    amounts = {name: [] for name in fields}
    bases, history_seen, partial = Counter(), set(), []
    classified = {"usage_priced_estimate_usd": [], "conditional_scenario_estimate_usd": [],
                  "recorded_provider_estimate_usd": []}
    for _, cost in included:
        duplicate_known = duplicate_reserve = 0
        for attempt in cost["history_attempts"]:
            if attempt["job_key"] in history_seen:
                duplicate_known += attempt["known_estimate_usd"] or 0
                duplicate_reserve += attempt["unresolved_reserved_exposure_usd"]
            history_seen.add(attempt["job_key"])
        prior_adjustment = min(duplicate_known, cost["prior_attempt_known_estimate_usd"] or 0)
        reserve_adjustment = min(duplicate_reserve, cost["historical_unresolved_reserved_exposure_usd"])
        for field in fields:
            value = cost[field]
            if value is not None:
                if field in {"prior_attempt_known_estimate_usd", "cumulative_known_estimate_usd"}:
                    value -= prior_adjustment
                if field in {"historical_unresolved_reserved_exposure_usd", "unresolved_reserved_exposure_usd"}:
                    value -= reserve_adjustment
                amounts[field].append(value)
        basis = cost["cost_basis"]
        bases[basis] += 1
        value = cost["cumulative_known_estimate_usd"]
        category = ("conditional_scenario_estimate_usd" if basis == "conditional_list_price_scenario" else
                    "usage_priced_estimate_usd" if basis in {"usage_priced_estimate", "sdk_usage_priced_estimate"}
                    else "recorded_provider_estimate_usd")
        if value is not None:
            classified[category].append(value - prior_adjustment)
            if cost["estimate_incomplete"] and basis != "conditional_list_price_scenario":
                partial.append(value - prior_adjustment)
    return {"version": COST_VERSION, "records": len(unique), "history_covered_records": len(unique) - len(included),
            "unknown_count": sum(c["estimate_incomplete"] for _, c in included),
            "current_attempt_unknown_count": sum(c["current_attempt_estimate_incomplete"] for _, c in included),
            "partial_known_estimate_usd": math.fsum(partial),
            **{name: math.fsum(values) for name, values in amounts.items()},
            **{name: math.fsum(values) for name, values in classified.items()}, "basis_counts": dict(bases),
            "invoice_status": "unverified", "actual_billed_usd": None}
