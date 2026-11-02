"""Provider adapters; credentials are read only when a live request is needed.

Shared budget-range logic for hosted single-call research agents: when a finished
answer cost less than ``budget_floor_usd``, the agent is asked to research further
and rewrite the answer, until the floor is reached or ``max_research_rounds`` is spent.
"""

DEFAULT_BUDGET_USD = 4.0


def count(value):
    """A nonnegative integer from a provider usage field, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def budget_cap(settings: dict) -> str:
    """hard: budget_usd is enforced; auto: enforced and the depth settings were derived from it; soft: only flagged."""
    return settings.get("budget_cap", "hard")


def budget_is_hard(settings: dict) -> bool:
    return budget_cap(settings) != "soft"


def needs_more_research(settings: dict, rounds: int, cost, last_cost=0.) -> bool:
    """Another round is due while the total is under the floor and rounds remain. With a hard or auto
    cap a round as costly as the last one (context grows every round) must also stay under the ceiling
    and not overshoot the floor by more than the current shortfall, so totals settle near the floor.
    With a soft cap the ceiling never cuts a round, but the overshoot guard still applies; without a
    floor there is one round."""
    floor, ceiling = settings.get("budget_floor_usd"), settings.get("budget_usd", DEFAULT_BUDGET_USD)
    if cost is None or rounds >= int(settings.get("max_research_rounds", 6)):
        return False
    if floor is None or not cost < floor:
        return False
    projected = cost + (last_cost or 0.)
    if not budget_is_hard(settings):
        return projected <= 2 * floor - cost  # The aim still lands totals near the floor; the ceiling never cuts.
    return floor <= ceiling + 1e-9 and projected <= min(ceiling, 2 * floor - cost)


def continuation_prompt(settings: dict, spent: float) -> str:
    text = settings["continuation_prompt"]
    for tag, value in (("{spent}", f"{spent:.2f}"), ("{floor}", f"{settings['budget_floor_usd']:.2f}"),
                       ("{ceiling}", f"{settings.get('budget_usd', DEFAULT_BUDGET_USD):.2f}"),
                       ("{max_words}", str(settings.get("answer_word_limit")))):
        text = text.replace(tag, value)
    return text


def sum_usage(usages):
    """Sum usage dicts key by key; a None in any part makes that total None."""
    totals = {}
    for usage in usages:
        for key, value in usage.items():
            totals[key] = None if value is None or totals.get(key, 0) is None else totals.get(key, 0) + value
    return totals


def budget_warnings(settings, cost, rounds, *, unknown_reason):
    """Warnings shared by the hosted research adapters about cost, ceiling, floor and rounds."""
    budget, floor = settings.get("budget_usd", DEFAULT_BUDGET_USD), settings.get("budget_floor_usd")
    warnings = []
    if cost is None:
        warnings.append(f"Cost unknown: {unknown_reason}")
    elif cost > budget:
        warnings.append(f"Observed cost ${cost:.6f} exceeded the ${budget:.2f} budget "
                        + ("ceiling." if budget_is_hard(settings) else "target (soft cap: nothing was stopped)."))
    if rounds > 1:
        warnings.append(f"The answer took {rounds} research rounds; every round is billed and the last completed rewrite is the answer.")
    if cost is not None and floor is not None and cost < floor:
        warnings.append(f"Research stopped at ${cost:.2f}, below the ${floor:.2f} budget floor, after {rounds} round(s).")
    return warnings
