"""Derive each research agent's depth settings from its per-answer budget.

Under ``budget_cap: auto`` the derived values override the configured ones and each
override is printed when the config loads; under hard and soft caps the config still
calls it to cost Caesar's chosen depth and derive its reserve and timeout. Caesar's plan comes from
:mod:`crest.caesar_budget`; the hosted agents that loop over research rounds
(OpenAI, Anthropic) get a budget floor and a round cap from their measured
per-round costs; Google's managed agent exposes no depth control, so it only
gets an expectation.

    python -m crest.budget 4.0            # every agent at one ceiling
    python -m crest.budget 3.5 --agent caesar
"""
from __future__ import annotations

import argparse
import json
import math

from .caesar_budget import plan as caesar_plan

# Round r of a hosted agent costs ROUND_USD[0] + ROUND_USD[1] * (r - 1): every round re-reads the
# earlier rounds' research, so rounds grow. Measured in the 2026-11-02 one-question pilots.
HOSTED = {
    "openai": {"round_usd": (.23, .26), "measured_run": "2026-11-02 pilot: rounds $0.23, $0.41, $0.67, $1.00, then a $0.81 landing round; $3.13 total"},
    "anthropic": {"round_usd": (.12, .02), "measured_run": "2026-11-02 pilot: 13 rounds of $0.09-0.39; $3.09 total"},
}
GEMINI_EXPECTED_USD = 1.81  # 2026-11-02 pilot at 600 words; $3.71 at 5,000 words in the 2026-10-26 run
FLOOR_SHARE = .75  # Aim at three quarters of the ceiling: $3 inside $4, the middle of the $2-4 range.
AGENTS = ("caesar", "openai", "gemini", "anthropic")


def rounds_cost(agent: str, rounds: int) -> float:
    """Cumulative cost of ``rounds`` research rounds for a hosted agent."""
    first, growth = HOSTED[agent]["round_usd"]
    return first * rounds + growth * rounds * (rounds - 1) / 2


def plan(agent: str, budget_usd: float, settings: dict | None = None) -> dict:
    """Settings that keep ``agent`` under ``budget_usd`` and the estimate behind them."""
    if not (isinstance(budget_usd, (int, float)) and math.isfinite(budget_usd) and budget_usd > 0):
        raise ValueError("budget_usd must be positive and finite")
    if agent == "caesar":
        return caesar_plan(float(budget_usd), settings=settings)
    if agent in HOSTED:
        floor = round(budget_usd * FLOOR_SHARE, 2)
        rounds = 1
        while rounds_cost(agent, rounds) < floor:
            rounds += 1
        # The landing round is a partial top-up, so expect the midpoint of the last two cumulative totals.
        expected = min(float(budget_usd), (rounds_cost(agent, rounds - 1) + rounds_cost(agent, rounds)) / 2)
        return {"settings": {"budget_floor_usd": floor, "max_research_rounds": rounds + 1},
                "estimate": {"budget_usd": budget_usd, "floor_usd": floor, "rounds_to_floor": rounds,
                             "expected_usd": round(expected, 2), "measured_run": HOSTED[agent]["measured_run"],
                             "note": "The landing rule stops earlier when the next round would overshoot; one spare round is allowed."}}
    if agent == "gemini":
        return {"settings": {}, "estimate": {"budget_usd": budget_usd, "expected_usd": GEMINI_EXPECTED_USD,
                                             "note": "No depth control: the managed agent decides its own research. Measured $1.81 at 600 words."}}
    raise ValueError(f"No budget calculator for research agent {agent!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the settings that keep each research agent under a per-answer budget.")
    parser.add_argument("budget_usd", type=float)
    parser.add_argument("--agent", choices=AGENTS, help="One agent instead of all four")
    args = parser.parse_args(argv)
    agents = [args.agent] if args.agent else list(AGENTS)
    print(json.dumps({agent: plan(agent, args.budget_usd) for agent in agents}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
