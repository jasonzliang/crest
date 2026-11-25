"""Point estimates for calls whose cost was never reported; saved rows are read, never changed.

Every call that failed with an unknown outcome is counted at the mean known cost of comparable
calls, so a mean over answers becomes an estimate instead of a lower bound. The known subtotal,
the imputed amount and (where one exists) a hard per-call upper bound are kept apart.

Answer ledgers with per-call events (Caesar):
  * comparables are known calls of the same model in the same answer;
  * a known call with the same ``reserved_usd`` is the same request size (in the 2026-11-24
    study it is always the immediate retry of the failed request), so when any exist their mean
    is used; otherwise the mean of the K_NEAREST calls by ``reserved_usd``;
  * with fewer than K_NEAREST comparables in the answer, the pool is the same model across that
    system's answers (K_NEAREST nearest by reservation);
  * each imputed call is capped at its reservation, which is also its upper bound.
Anthropic answers (one lost POST after the last saved turn):
  * the lost turn's kind follows the last turn: a ``tool_use`` stop means a continuation in the
    same round, anything else the first turn of the next round;
  * comparables are priced known turns of the same kind in the same round, then of the same kind
    in the answer, then any priced turn in the answer; no reservation is recorded, so no bound.
Judgments (attempts resent after an unknown outcome):
  * the completed resend of the same job (same prompt and judge) in the same row; else the
    median known cost of the same judge on the same question in the supplied rows; else the
    median of the same judge. The bound is the resend's prompt at the dearest input-side rate
    plus the judge's ``max_output_tokens`` at the output rate, when judge settings are supplied.
"""
from __future__ import annotations

import math
import statistics

from crest.costs import cost_for_row

IMPUTATION_VERSION = "crest-cost-imputation-v1"
K_NEAREST = 5


def _money(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _mean(values):
    return math.fsum(values) / len(values)


# Answer ledgers --------------------------------------------------------------------------

def _ledger(result):
    raw, usage = _mapping(result.get("raw")), _mapping(result.get("usage"))
    return (_mapping(raw.get("new_attempt_usage_audit")) or _mapping(raw.get("usage_audit"))
            or usage)


def _unknown_event(event):
    return isinstance(event, dict) and (bool(event.get("unknown_cost"))
                                        or event.get("status") == "failed" and not _money(event.get("cost_usd")))


def _known_events(ledger):
    return [e for e in ledger.get("events") or []
            if isinstance(e, dict) and not _unknown_event(e) and _money(e.get("cost_usd"))]


def _lost_events(ledger):
    lost = [(i, "events", e) for i, e in enumerate(ledger.get("events") or []) if _unknown_event(e)]
    lost += [(i, "in_flight", e) for i, e in enumerate(ledger.get("in_flight") or []) if isinstance(e, dict)]
    return lost


def _nearest(target, pool, k):
    """Mean cost of the k calls whose reservation is closest to ``target`` (ties: smaller first)."""
    ranked = sorted(pool, key=lambda rc: (abs(rc[0] - target), rc[0], rc[1]))[:k]
    return _mean([c for _, c in ranked]), len(ranked)


def _impute_event(event, answer_known, system_pool, k):
    model, reserved = event.get("model"), event.get("reserved_usd")
    same = [e for e in answer_known if e.get("model") == model]
    bounded = _money(reserved)
    if not bounded:
        pool = same or [e for e in system_pool if e.get("model") == model]
        if not pool:
            return None
        basis = "same_model_mean_in_answer" if same else "same_model_mean_in_system"
        return _mean([e["cost_usd"] for e in pool]), basis, len(pool), None
    with_res = [(e["reserved_usd"], e["cost_usd"]) for e in same if _money(e.get("reserved_usd"))]
    exact = [c for r, c in with_res if math.isclose(r, reserved, rel_tol=1e-12, abs_tol=0)]
    if exact:
        estimate, basis, count = _mean(exact), "same_reservation_in_answer", len(exact)
    elif len(with_res) >= k:
        (estimate, count), basis = _nearest(reserved, with_res, k), "nearest_reservation_in_answer"
    else:
        pool = [(e["reserved_usd"], e["cost_usd"]) for e in system_pool
                if e.get("model") == model and _money(e.get("reserved_usd"))]
        if not pool:
            return None
        (estimate, count), basis = _nearest(reserved, pool, k), "nearest_reservation_in_system"
    return estimate, basis, count, reserved


# Anthropic turns -------------------------------------------------------------------------

def _rates(turn, raw):
    snapshot = _mapping(turn.get("_pricing"))
    if "rates" in snapshot:
        return _mapping(snapshot.get("rates"))
    return _mapping(_mapping(_mapping(raw.get("pricing")).get("rates_by_model")).get(turn.get("model")))


def _prompt_tokens(usage):
    values = [usage.get(k) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
    return values if all(type(v) is int and v >= 0 for v in values) else None


def _turn_cost(turn, raw):
    usage, rates = _mapping(turn.get("usage")), _rates(turn, raw)
    prompt, output = _prompt_tokens(usage), usage.get("output_tokens")
    names = ("input", "cached_input", "cache_write_5m", "output")
    if prompt is None or type(output) is not int or not all(_money(rates.get(n)) for n in names):
        return None
    if _mapping(usage.get("cache_creation")).get("ephemeral_1h_input_tokens"):
        return None  # One-hour cache writes need a tariff these receipts do not record.
    inp, read, write = prompt
    searches = _mapping(usage.get("server_tool_use")).get("web_search_requests") or 0
    return ((inp * rates["input"] + read * rates["cached_input"] + write * rates["cache_write_5m"]
             + output * rates["output"]) / 1_000_000 + searches * (rates.get("web_search") or 0))


def _turn_kinds(turns):
    return ["continuation" if i and turns[i - 1].get("_round") == t.get("_round") else "round_start"
            for i, t in enumerate(turns)]


def _anthropic_lost(raw):
    interrupted = [a for a in raw.get("interrupted_attempts") or []
                   if isinstance(a, dict) and not _money(a.get("cost_usd"))]
    # An interruption on a gateway also marks the submission unresolved: count that call once.
    return len(interrupted) or (1 if raw.get("unresolved_submission") else 0)


def _impute_turn(raw, system_turns):
    turns = [t for t in raw.get("turns") or [] if isinstance(t, dict)]
    if turns:
        last = turns[-1]
        continuation = last.get("stop_reason") == "tool_use"
        kind = "continuation" if continuation else "round_start"
        rnd = (last.get("_round") or 1) + (0 if continuation else 1)
    else:
        kind, rnd = "round_start", 1
    priced = [(t, k, c) for t, k in zip(turns, _turn_kinds(turns)) if (c := _turn_cost(t, raw)) is not None]
    for basis, pool in (("same_kind_turns_in_round", [c for t, k, c in priced if k == kind and t.get("_round") == rnd]),
                        ("same_kind_turns_in_answer", [c for _, k, c in priced if k == kind]),
                        ("any_turn_in_answer", [c for _, _, c in priced]),
                        ("same_kind_turns_in_system", [c for k, c in system_turns if k == kind])):
        if pool:
            return {"kind": kind, "round": rnd, "imputed_usd": _mean(pool), "basis": basis,
                    "comparable_count": len(pool), "upper_bound_usd": None}
    return None


# Records -----------------------------------------------------------------------------------

def _record(row, cost, calls, residual_reason=None, unimputed=0):
    known = cost["cumulative_known_estimate_usd"]
    imputed = math.fsum(c["imputed_usd"] for c in calls)
    bounds = [c["upper_bound_usd"] for c in calls]
    incomplete = bool(cost["estimate_incomplete"])
    if incomplete and residual_reason is None and (unimputed or not calls):
        residual_reason = "unimputable_unknown_cost"
    return {"version": IMPUTATION_VERSION, "key": row.get("key"), "question_id": row.get("question_id"),
            "agent": row.get("agent") or row.get("provider"), "judge": row.get("judge"),
            "known_usd": known, "estimate_incomplete": incomplete,
            "imputed_calls": len(calls), "imputed_usd": imputed,
            "upper_bound_usd": None if any(b is None for b in bounds) else math.fsum(bounds),
            "estimate_usd": None if known is None else known + imputed,
            "residual_incomplete": incomplete and residual_reason is not None,
            "residual_reason": residual_reason if incomplete else None,
            "calls": calls}


def impute_answer_costs(rows: list[dict], *, k: int = K_NEAREST) -> list[dict]:
    """One record per answer row: known subtotal, imputed calls and their upper bound."""
    results = [_mapping(r.get("result")) for r in rows]
    agents = [r.get("agent") or r.get("provider") for r in rows]
    system_events, system_turns = {}, {}
    for agent, result in zip(agents, results):
        system_events.setdefault(agent, []).extend(_known_events(_ledger(result)))
        raw = _mapping(result.get("raw"))
        turns = [t for t in raw.get("turns") or [] if isinstance(t, dict)]
        system_turns.setdefault(agent, []).extend(
            (kind, c) for t, kind in zip(turns, _turn_kinds(turns)) if (c := _turn_cost(t, raw)) is not None)
    records = []
    for row, agent, result in zip(rows, agents, results):
        cost = cost_for_row(row)
        calls, unimputed, reason = [], 0, None
        if cost["cost_basis"] == "conditional_list_price_scenario":
            reason = "conditional_list_price_scenario"
        elif cost["estimate_incomplete"]:
            ledger = _ledger(result)
            raw = _mapping(result.get("raw"))
            if ledger.get("events") is not None or ledger.get("in_flight"):
                known = _known_events(ledger)
                for index, source, event in _lost_events(ledger):
                    found = _impute_event(event, known, system_events[agent], k)
                    if found is None:
                        unimputed += 1
                        continue
                    estimate, basis, count, bound = found
                    capped = bound is not None and estimate > bound
                    calls.append({"index": index, "source": source, "model": event.get("model"),
                                  "status_code": event.get("status_code"), "reserved_usd": bound,
                                  "imputed_usd": min(estimate, bound) if capped else estimate,
                                  "capped_at_reservation": capped, "basis": basis,
                                  "comparable_count": count, "upper_bound_usd": bound})
                if cost["historical_unresolved_reserved_exposure_usd"]:
                    reason = "prior_attempt_reservation"
            elif raw.get("turns") is not None:
                for _ in range(_anthropic_lost(raw)):
                    found = _impute_turn(raw, system_turns[agent])
                    if found is None:
                        unimputed += 1
                    else:
                        calls.append({"source": "unresolved_submission",
                                      "model": next((t.get("model") for t in reversed(raw["turns"])
                                                     if isinstance(t, dict) and t.get("model")), None),
                                      **found})
        records.append(_record(row, cost, calls, reason, unimputed))
    return records


# Judgments ---------------------------------------------------------------------------------

def _prompt_bound(result, settings):
    """Upper bound for resending the same prompt: dearest input-side rate, max output tokens."""
    max_out = _mapping(settings).get("max_output_tokens")
    raw = _mapping(result.get("raw"))
    turns = [t for t in raw.get("turns") or [] if isinstance(t, dict)]
    if type(max_out) is not int or len(turns) != 1:
        return None
    rates, prompt = _rates(turns[0], raw), _prompt_tokens(_mapping(turns[0].get("usage")))
    names = ("input", "cached_input", "cache_write_5m")
    if prompt is None or not all(_money(rates.get(n)) for n in names) or not _money(rates.get("output")):
        return None
    return (sum(prompt) * max(rates[n] for n in names) + max_out * rates["output"]) / 1_000_000


def impute_judgment_costs(rows: list[dict], *, judges: dict | None = None) -> list[dict]:
    """One record per judgment row in a single judge stage (one rubric run)."""
    judges = judges or {}
    costs = [cost_for_row(r) for r in rows]
    complete = [(r.get("judge"), r.get("question_id"), c["cumulative_known_estimate_usd"])
                for r, c in zip(rows, costs)
                if not c["estimate_incomplete"] and _money(c["cumulative_known_estimate_usd"])]
    records = []
    for row, cost in zip(rows, costs):
        calls, unimputed = [], 0
        if cost["estimate_incomplete"]:
            attempts = [a for a in row.get("attempts") or [] if isinstance(a, dict)]
            if not attempts:
                attempts = [{"key": row.get("key"), "cost_usd": None, "result": _mapping(row.get("result"))}]
            resends = [a for a in attempts if _money(a.get("cost_usd")) and a.get("status", "completed") == "completed"]
            judge, qid = row.get("judge"), row.get("question_id")
            for attempt in attempts:
                if _money(attempt.get("cost_usd")):
                    continue
                bound = None
                if resends:
                    estimate, basis, count = _mean([a["cost_usd"] for a in resends]), "same_job_resend", len(resends)
                    bound = _prompt_bound(_mapping(resends[-1].get("result")), judges.get(judge))
                else:
                    same_q = [c for j, q, c in complete if j == judge and q == qid]
                    same_j = [c for j, _, c in complete if j == judge]
                    if same_q:
                        estimate, basis, count = statistics.median(same_q), "same_question_and_judge_median", len(same_q)
                    elif same_j:
                        estimate, basis, count = statistics.median(same_j), "same_judge_median", len(same_j)
                    else:
                        unimputed += 1
                        continue
                capped = bound is not None and estimate > bound
                calls.append({"attempt_key": attempt.get("key"), "error": attempt.get("error"),
                              "imputed_usd": min(estimate, bound) if capped else estimate,
                              "capped_at_reservation": capped, "basis": basis,
                              "comparable_count": count, "upper_bound_usd": bound})
        records.append(_record(row, cost, calls, None, unimputed))
    return records


# Summary -----------------------------------------------------------------------------------

def summarize_imputation(records: list[dict], *, by: str = "agent") -> dict:
    """Per-group totals and means before and after imputation (``by`` is 'agent' or 'judge')."""
    groups = {}
    for record in records:
        groups.setdefault(record.get(by), []).append(record)
    summary = {}
    for name, items in groups.items():
        known = [r["known_usd"] for r in items if r["known_usd"] is not None]
        estimates = [r["estimate_usd"] for r in items if r["estimate_usd"] is not None]
        imputed = [r for r in items if r["imputed_calls"]]
        bounds = [r["upper_bound_usd"] for r in imputed]
        upper = None if any(b is None for b in bounds) else math.fsum(bounds)
        known_mean = _mean(known) if known else None
        estimate_mean = _mean(estimates) if estimates else None
        summary[name] = {
            "records": len(items),
            "incomplete_before": sum(r["estimate_incomplete"] for r in items),
            "incomplete_after": sum(r["residual_incomplete"] for r in items),
            "imputed_records": len(imputed), "imputed_calls": sum(r["imputed_calls"] for r in items),
            "known_usd": math.fsum(known), "imputed_usd": math.fsum(r["imputed_usd"] for r in items),
            "upper_bound_usd": upper,
            "known_mean_usd": known_mean, "estimate_mean_usd": estimate_mean,
            "mean_change_usd": None if known_mean is None or estimate_mean is None else estimate_mean - known_mean,
            "upper_bound_mean_usd": (None if upper is None or not known else (math.fsum(known) + upper) / len(known)),
        }
    return summary
