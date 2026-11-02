"""Derive Caesar's depth settings from one per-answer budget.

Exploration and Q&A pace come from the published 2026-10-26 run (Sol medium for
the main agent and synthesis, Luna low for exploration and the knowledge base,
one knowledge-base call per query); draft and merge costs for 600-word answers
come from the 2026-11-02 pilot. That pilot's exploration pace is not used: it
ran under llama-index-core 0.14.23, which split every knowledge-base query into
several calls (see caesar_worker.compatibility), doubling cost and time. The plan favors exploration: half of
the target goes to setup plus exploration iterations and the rest to three
drafts and a merge, keeping a margin below the audit ceiling so the final merge
is never refused for lack of budget. Q&A rounds per draft are also capped so
the worker's per-draft allowance covers them after the write reserves. One timeout covers setup, exploration and
synthesis with a margin; no phase has its own time limit.

    python -m crest.caesar_budget 3.5
"""
from __future__ import annotations

import argparse
import json
import math

# Exploration. Iteration i costs ITERATION_USD[0] + ITERATION_USD[1] * i and takes ITERATION_SECONDS[0]
# + ITERATION_SECONDS[1] * i: October's 5,573 iterations rose from $0.0031 (iterations 1-25) to $0.0043
# (126-150) at a flat 21.7 s, with 5 Luna calls each (one knowledge-base call per query).
EXPLORATION_RUN = "2026-10-26 (5,573 iterations across 50 answers)"
ITERATION_USD = (.0031, .00001)
ITERATION_SECONDS = (21.7, 0.)
SETUP_USD, SETUP_SECONDS = .05, 120.  # Sol role adaptation and starting queries before iteration 1
# Synthesis. A Q&A round is one knowledge-base query (Luna) plus the next query (Sol) whose prompt
# carries every earlier pair, so round r costs QA_ROUND_USD[0] + QA_ROUND_USD[1] * r and takes
# QA_ROUND_SECONDS[0] + QA_ROUND_SECONDS[1] * r: October's 2,245 rounds rose from $0.0072 and 21 s at
# round 1 to $0.0302 and 29 s at round 14. Draft, refinement and merge figures are the 2026-11-02
# pilot's 600-word drafts (Sol calls, unaffected by the knowledge-base split).
SYNTHESIS_RUN = "2026-10-26 (2,245 Q&A rounds); 600-word drafts from the 2026-11-02 pilot"
QA_ROUND_USD = (.005, .00175)      # per round: intercept and growth per round index
QA_ROUND_SECONDS = (20.5, .55)
DRAFT_WRITE_USD, DRAFT_WRITE_SECONDS = .05, 40.  # $0.026 after 8 pairs, $0.060 after 25
DRAFT_REFINE_USD, DRAFT_REFINE_SECONDS = .01, 10.
MERGE_USD, MERGE_SECONDS = .03, 30.
# Standard prices: https://developers.openai.com/api/docs/models/gpt-6.1-sol
# Luna: https://developers.openai.com/api/docs/models/gpt-6-luna
SOL = "gpt-6.1-sol"
LUNA = "gpt-6-luna"
PRICES = {LUNA: {"input": .1, "output": .5, "cache_read": .01, "cache_write": .125}, SOL: {"input": 2., "output": 10., "cache_read": .1, "cache_write": 2.5},
          "text-embedding-3-small": {"input": .02, "output": 0.},
          "text-embedding-3-large": {"input": .13, "output": 0.},
          "text-embedding-ada-002": {"input": .10, "output": 0.}}
# The audit reserves each request's bound (bytes as tokens at the cache-write rate plus the full
# completion limit) before sending it. Before each draft's Q&A the worker therefore holds one such
# bound for the final write (the merge, or the last draft) plus twice the measured cost of every
# other remaining write and refinement.
DEFAULT_COMPLETION_TOKENS = 10000
WRITE_INPUT_BYTES = 30_000  # Q&A pairs or drafts that a write or merge prompt carries
# The single worker timeout is the estimated total time times this margin. October's slowest answer
# took 1.17 times the mean; the margin also covers Chroma startup and shutdown.
TIME_MARGIN = 1.5
DERIVED = ("max_iterations", "synthesis_drafts", "synthesis_iterations", "synthesis_reserve_usd", "timeout_seconds")
DRAFTS = 3


def write_bound(settings: dict | None = None) -> float:
    """What the audit reserves for one draft write or merge under the configured limits and prices."""
    settings = settings or {}
    prices = {**PRICES, **(settings.get("model_pricing") or {})}
    rates = prices.get(settings.get("model", SOL), PRICES[SOL])
    input_part = WRITE_INPUT_BYTES * max(rates.get("input", 0), rates.get("cache_write", 0))
    return (input_part + settings.get("max_completion_tokens", DEFAULT_COMPLETION_TOKENS) * rates.get("output", 0)) / 1e6


def write_hold(settings: dict | None, remaining_drafts: int, merge: bool = True) -> float:
    """USD to keep out of a draft's Q&A allowance so every later write and the merge can still be sent."""
    other_writes = remaining_drafts if merge else max(0, remaining_drafts - 1)
    later = other_writes * DRAFT_WRITE_USD + max(0, remaining_drafts - 1) * DRAFT_REFINE_USD
    return write_bound(settings) + 2 * later


def _growing_total(start: float, slope: float, count: int) -> float:
    return start * count + slope * count * (count + 1) / 2


def qa_rounds_cost(rounds: int) -> float:
    """Cost of ``rounds`` Q&A rounds for one draft, with the per-round growth."""
    return _growing_total(*QA_ROUND_USD, rounds)


def qa_rounds_seconds(rounds: int) -> float:
    return _growing_total(*QA_ROUND_SECONDS, rounds)


def exploration(iterations: int) -> tuple[float, float]:
    """Cumulative cost in USD and time in seconds for the first ``iterations`` exploration steps."""
    return _growing_total(*ITERATION_USD, iterations), _growing_total(*ITERATION_SECONDS, iterations)


def plan(budget_usd: float, *, margin: float = .85, exploration_share: float = .5, settings: dict | None = None) -> dict:
    """Settings that fit ``margin`` of the budget, with the estimate that justifies them.

    ``settings`` may carry the Caesar completion limits, which set the write reserve the worker holds
    back during synthesis, and explicit ``max_iterations``, ``synthesis_drafts`` or
    ``synthesis_iterations``; explicit depth is kept and only costed, derived depth is capped so the
    first draft's allowance covers its rounds even when exploration spends its full plan.
    """
    if not (math.isfinite(budget_usd) and budget_usd > 0):
        raise ValueError("budget_usd must be positive and finite")
    settings = settings or {}
    chosen = {key: settings.get(key) for key in ("max_iterations", "synthesis_drafts", "synthesis_iterations")}
    target, drafts = budget_usd * margin, int(DRAFTS if chosen["synthesis_drafts"] is None else chosen["synthesis_drafts"])
    fixed = drafts * DRAFT_WRITE_USD + (drafts - 1) * DRAFT_REFINE_USD + MERGE_USD  # Rome refines between drafts
    if chosen["max_iterations"] is not None:
        iterations = int(chosen["max_iterations"])
    else:
        iterations = 0
        exploration_target = target * exploration_share - SETUP_USD
        while exploration(iterations + 1)[0] <= exploration_target:
            iterations += 1
    exploration_usd, exploration_seconds = exploration(iterations)
    first_draft_allowance = (budget_usd - SETUP_USD - exploration_usd - write_hold(settings, drafts)) / drafts
    if chosen["synthesis_iterations"] is not None:
        rounds = int(chosen["synthesis_iterations"])
    else:
        per_draft = min((target * (1 - exploration_share) - fixed) / drafts, first_draft_allowance)
        rounds = 0
        while qa_rounds_cost(rounds + 1) <= per_draft:
            rounds += 1
    if rounds < 1 or iterations < 1:
        raise ValueError(f"budget_usd {budget_usd} is below the minimum for {drafts} drafts, one Q&A round and one iteration")
    synthesis_usd = fixed + drafts * qa_rounds_cost(rounds)
    total_usd = SETUP_USD + exploration_usd + synthesis_usd
    warnings = []
    soft = settings.get("budget_cap") == "soft"
    if total_usd > budget_usd:
        warnings.append(f"{iterations} iterations and {drafts} x {rounds} Q&A rounds are estimated at ${total_usd:.2f}, above budget_usd {budget_usd}; "
                        + ("a soft cap only flags the overrun." if soft else "a hard cap would refuse requests before the depth completes."))
    elif total_usd > target:
        warnings.append(f"Estimate ${total_usd:.2f} is above the ${target:.2f} target ({margin:.0%} of the budget); "
                        + ("a soft cap only flags an overrun." if soft else "the audit ceiling still applies."))
    if qa_rounds_cost(rounds) > first_draft_allowance:
        warnings.append(f"The first draft's allowance (${first_draft_allowance:.2f}) covers fewer than {rounds} Q&A rounds if exploration spends its full plan.")
    synthesis_seconds = drafts * (qa_rounds_seconds(rounds) + DRAFT_WRITE_SECONDS) + (drafts - 1) * DRAFT_REFINE_SECONDS + MERGE_SECONDS
    total_seconds = SETUP_SECONDS + exploration_seconds + synthesis_seconds
    settings_out = {"max_iterations": iterations, "synthesis_drafts": drafts, "synthesis_iterations": rounds,
                    "synthesis_reserve_usd": round(synthesis_usd * 1.1, 2),
                    "timeout_seconds": int(math.ceil(total_seconds * TIME_MARGIN / 300) * 300)}
    estimate = {"budget_usd": budget_usd, "target_usd": round(target, 4), "setup_usd": SETUP_USD,
                "exploration_usd": round(exploration_usd, 4), "synthesis_usd": round(synthesis_usd, 4),
                "total_usd": round(total_usd, 4),
                "qa_usd_per_draft": round(qa_rounds_cost(rounds), 4),
                "first_draft_allowance_usd": round(first_draft_allowance, 4),
                "write_hold_usd": round(write_hold(settings, drafts), 4),
                "exploration_minutes": round(exploration_seconds / 60, 1),
                "synthesis_minutes": round(synthesis_seconds / 60, 1),
                "total_minutes": round(total_seconds / 60, 1), "timeout_margin": TIME_MARGIN,
                "chosen": {key: value for key, value in chosen.items() if value is not None}, "warnings": warnings,
                "measured_runs": {"exploration": EXPLORATION_RUN, "synthesis": SYNTHESIS_RUN}}
    return {"settings": settings_out, "estimate": estimate}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print Caesar settings that fit a per-answer budget.")
    parser.add_argument("budget_usd", type=float)
    parser.add_argument("--margin", type=float, default=.85, help="Share of the budget the estimate may use")
    parser.add_argument("--exploration-share", type=float, default=.5, help="Share of the target spent on setup and exploration")
    parser.add_argument("--max-completion-tokens", type=int, default=DEFAULT_COMPLETION_TOKENS, help="Caesar's draft and merge completion limit")
    parser.add_argument("--max-iterations", type=int, help="Cost this exploration depth instead of deriving it")
    parser.add_argument("--synthesis-iterations", type=int, help="Cost this many Q&A rounds per draft instead of deriving them")
    parser.add_argument("--synthesis-drafts", type=int, help="Cost this many drafts instead of the default three")
    args = parser.parse_args(argv)
    settings = {"max_completion_tokens": args.max_completion_tokens, "max_iterations": args.max_iterations,
                "synthesis_iterations": args.synthesis_iterations, "synthesis_drafts": args.synthesis_drafts}
    print(json.dumps(plan(args.budget_usd, margin=args.margin, exploration_share=args.exploration_share, settings=settings), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
