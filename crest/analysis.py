"""Offline descriptive preferences on common complete-question blocks."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from itertools import combinations
import json
import math
import os
from pathlib import Path
import random

from .costs import summarize_costs

ANALYSIS_VERSION = "8"


def _valid_verdict(value):
    return (isinstance(value, dict) and set(value) == {"reason", "winner"}
            and isinstance(value["reason"], str) and bool(value["reason"].strip())
            and value["winner"] in ("A", "B"))


def _interval(values):
    if not values:
        return None
    values = sorted(values)
    def percentile(p):
        index = (len(values) - 1) * p
        lower, upper = math.floor(index), math.ceil(index)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)
    return [percentile(0.025), percentile(0.975)]


def _known_cost(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _costs(records):
    summary = summarize_costs(records)
    return summary | {"known_usd": summary["cumulative_known_estimate_usd"]}


def _failure_costs(records):
    observed = [r["observed_cost_usd"] for r in records
                if not _known_cost(r.get("cost_usd")) and _known_cost(r.get("observed_cost_usd"))]
    return {**_costs(records), "partial_observed_estimate_usd": math.fsum(observed),
            "observed_count": len(observed),
            "budget_exceeded_count": sum(r.get("budget_exceeded") is True for r in records)}


def _summarize_view(task):
    """Picklable independent view, sharing the parent's exact question draws."""
    agents, votes, draws, selected_judges, include_contrasts = task
    vectors, wins, opportunities = [], Counter(), Counter()
    for block in votes:
        vector = Counter()
        for judge, winner, loser, _ in block:
            if judge in selected_judges:
                vector[winner] += 1
                wins[winner, loser] += 1
                opportunities[winner, loser] += 1
                opportunities[loser, winner] += 1
        vectors.append(vector)
    denominator = (len(agents) - 1) * 2 * len(selected_judges) * len(votes)
    totals = {a: sum(v[a] for v in vectors) for a in agents}
    scores, ranks = {a: [] for a in agents}, {a: [] for a in agents}
    contrast_draws = {pair: [] for pair in combinations(agents, 2)} if include_contrasts else {}
    for draw in draws:
        sample = {a: sum(vectors[i][a] for i in draw) for a in agents}
        for a in agents:
            scores[a].append(sample[a] / denominator)
            ranks[a].append(1 + sum(value > sample[a] for value in sample.values()))
        for (a, b), differences in contrast_draws.items():
            differences.append((sample[a] - sample[b]) / denominator)
    ranking = [{"agent": a, "rank": 1 + sum(v > totals[a] for v in totals.values()) if denominator else None,
                "preference_rate": totals[a] / denominator if denominator else None,
                "wins": totals[a], "choices": denominator,
                "ci95": _interval(scores[a]), "rank_ci95": _interval(ranks[a])}
               for a in sorted(agents, key=lambda a: (-totals[a], a))]
    matrix = {a: {b: wins[a, b] / opportunities[a, b] if opportunities[a, b] else None
                  for b in agents} for a in agents}
    contrasts = [{"pair": [a, b], "difference": (totals[a] - totals[b]) / denominator if denominator else None,
                  "ci95": _interval(values), "bootstrap_samples": len(values),
                  "ordering_stability": {
                      "first_higher": sum(v > 0 for v in values) / len(values) if values else None,
                      "equal": sum(v == 0 for v in values) / len(values) if values else None,
                      "second_higher": sum(v < 0 for v in values) / len(values) if values else None}}
                 for (a, b), values in contrast_draws.items()]
    return ranking, matrix, contrasts


def analyze(questions: list[dict], answers: list[dict], judgments: list[dict], *,
            agents: list[str], judges: list[str], bootstrap_samples: int = 1000,
            seed: int = 2026, failures: list[dict] | None = None, workers: int = 1,
            prior_judgments: list[dict] | None = None) -> dict:
    """Rank binary preferences without imputing missing observations.

    A duplicate valid answer or judgment excludes its question. All views share
    complete blocks; bootstrap draws retain each question's dependent votes.
    Failed paid jobs contribute costs, never votes; repeated stage/key failure
    entries count once. Current-run spend cannot be inferred from these records.
    Workers parallelize substantial bootstrap views; zero chooses available CPUs.
    """
    if len(agents) < 2 or not judges or len(set(agents)) != len(agents) or len(set(judges)) != len(judges):
        raise ValueError("Provide distinct agents (at least two) and distinct judges.")
    if type(bootstrap_samples) is not int or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer")
    if type(workers) is not int or workers < 0:
        raise ValueError("workers must be a nonnegative integer (zero selects CPU count)")
    agents, judges = sorted(agents), sorted(judges)
    prior_judgments = [row | {'stage': 'judge'} for row in prior_judgments or []]
    superseded_keys = {row['key'] for row in prior_judgments}
    superseded_excluded = 0
    question_ids = [q["id"] for q in questions]
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("Question IDs must be unique")
    pairs = list(combinations(agents, 2))
    cells = [(pair, order, judge) for pair in pairs for order in (pair, pair[::-1]) for judge in judges]
    expected = set(cells)
    answer_counts = {q: Counter() for q in question_ids}
    observed = {q: {} for q in question_ids}
    duplicates = {q: 0 for q in question_ids}
    invalid, ignored = Counter(), 0
    for answer in answers:
        q, agent = answer.get("question_id"), answer.get("agent")
        text = (answer.get("result") or {}).get("text")
        if (q in answer_counts and agent in agents and isinstance(text, str) and text.strip()
                and answer.get("status", "completed") == "completed"):
            answer_counts[q][agent] += 1
    for judgment in judgments:
        if judgment.get('key') in superseded_keys:
            superseded_excluded += 1
            continue
        q = judgment.get("question_id")
        if q not in observed:
            ignored += 1
            continue
        pair, order = judgment.get("pair"), judgment.get("order")
        if (not isinstance(pair, (list, tuple)) or not isinstance(order, (list, tuple))
                or not all(isinstance(a, str) for a in (*pair, *order))):
            invalid[q] += 1
            continue
        cell = (tuple(pair), tuple(order), judgment.get("judge"))
        if (cell not in expected or not _valid_verdict(judgment.get("verdict"))
                or judgment.get("status", "completed") != "completed"):
            invalid[q] += 1
            continue
        if cell in observed[q]:
            duplicates[q] += 1
        else:
            observed[q][cell] = judgment["verdict"]
    complete, excluded = [], []
    for q in question_ids:
        missing_answers = [a for a in agents if not answer_counts[q][a]]
        duplicate_answers = [a for a in agents if answer_counts[q][a] > 1]
        missing_cells = [cell for cell in cells if cell not in observed[q]]
        reasons = [name for name, condition in (
            ("missing_answers", missing_answers), ("duplicate_answers", duplicate_answers),
            ("missing_judgments", missing_cells), ("duplicate_judgments", duplicates[q])) if condition]
        if not reasons:
            complete.append(q)
        else:
            excluded.append({"question_id": q, "reasons": reasons,
                             "missing_answers": missing_answers, "duplicate_answers": duplicate_answers,
                             "missing_judgments": [{"pair": list(p), "order": list(o), "judge": j}
                                                   for p, o, j in missing_cells],
                             "duplicate_judgments": duplicates[q], "invalid_judgments": invalid[q]})
    votes = []
    for q in complete:
        block = []
        for pair, order, judge in cells:
            choice = observed[q][pair, order, judge]
            index = 0 if choice["winner"] == "A" else 1
            block.append((judge, order[index], order[1 - index], choice["winner"]))
        votes.append(block)
    rng = random.Random(seed)
    draws = [[rng.randrange(len(complete)) for _ in complete]
             for _ in range(bootstrap_samples)] if complete else []

    tasks = [(agents, votes, draws, selected_judges, i == 0)
             for i, selected_judges in enumerate([judges] + [(j,) for j in judges])]
    worker_count = min(workers or (os.cpu_count() or 1), len(tasks))
    # Pool startup costs more than small bootstrap calculations. A single
    # question's repeated draws cannot provide additional bootstrap variation.
    use_pool = (worker_count > 1 and bootstrap_samples >= 100 and len(complete) >= 2
                and bootstrap_samples * len(complete) >= 200_000)
    if use_pool:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            summaries = list(executor.map(_summarize_view, tasks))
    else:
        summaries = list(map(_summarize_view, tasks))
    ranking, matrix, paired_contrasts = summaries[0]
    judge_views = dict(zip(judges, summaries[1:]))
    switched = disagreed = switch_count = disagreement_count = 0
    swap_counts, swap_totals = Counter(), Counter()
    judge_counts, judge_totals = Counter(), Counter()
    for q in complete:
        def winner(pair, order, judge):
            return order[0 if observed[q][pair, order, judge]["winner"] == "A" else 1]
        for pair in pairs:
            for judge in judges:
                switch_count += 1
                changed = winner(pair, pair, judge) != winner(pair, pair[::-1], judge)
                switched += changed
                swap_counts[judge] += changed
                swap_totals[judge] += 1
            for order in (pair, pair[::-1]):
                for first, second in combinations(judges, 2):
                    disagreement_count += 1
                    changed = winner(pair, order, first) != winner(pair, order, second)
                    disagreed += changed
                    for judge in (first, second):
                        judge_counts[judge] += changed
                        judge_totals[judge] += 1
    def disagreement(count, total):
        return {"disagreements": count, "comparisons": total, "rate": count / total if total else None}
    def position(count, total):
        return {"wins": count, "choices": total, "rate": count / total if total else None}
    cycles = []
    for a, b, c in combinations(agents, 3):
        for cycle in ((a, b, c, a), (a, c, b, a)):
            if all(matrix[x][y] is not None and matrix[x][y] > 0.5 for x, y in zip(cycle, cycle[1:])):
                cycles.append(list(cycle))
    a_counts = Counter(j for block in votes for j, _, _, label in block if label == "A")
    choice_counts = Counter(j for block in votes for j, _, _, _ in block)
    generation_cost, judging_cost = _costs(answers), _costs(judgments)
    unique_failures = {}
    for failure in failures or []:
        unique_failures.setdefault((failure["stage"], failure["key"]), failure)
    failure_records = list(unique_failures.values())
    failure_cost = _failure_costs(failure_records)
    failure_by_stage = {stage: _failure_costs([f for f in failure_records if f["stage"] == stage])
                        for stage in ("generate", "judge")}
    return {
        "analysis_version": ANALYSIS_VERSION,
        "interpretation": "Exploratory overall creativity preference ranking of these observed answers under this rubric and selected judges; not an absolute creativity measurement.",
        "method": "Each judgment chooses one overall A/B creativity winner guided by New, Useful and Surprising. Rank by wins divided by comparisons, weighting questions, opponents, judges and answer orders equally on common complete questions. Ties share competition ranks.",
        "agents": agents, "judges": judges,
        "coverage": {"total_questions": len(questions), "complete_questions": len(complete),
                     "complete_question_ids": complete, "excluded_questions": excluded,
                     "expected_judgments_per_question": len(cells),
                     "valid_judgments": sum(map(len, observed.values())),
                     "superseded_judgments_excluded": superseded_excluded,
                     "invalid_judgments": sum(invalid.values()), "ignored_judgments": ignored},
        "ranking": ranking, "paired_contrasts": paired_contrasts,
        "per_judge": {j: view[0] for j, view in judge_views.items()},
        "pairwise": {"overall": matrix, "per_judge": {j: v[1] for j, v in judge_views.items()}},
        "diagnostics": {"cycles": cycles,
            "position_a_preference": position(sum(a_counts.values()), sum(choice_counts.values())),
            "swapped_inconsistency": disagreement(switched, switch_count),
            "judge_disagreement": disagreement(disagreed, disagreement_count),
            "by_judge": {j: {
                "position_a_preference": position(a_counts[j], choice_counts[j]),
                "swapped_inconsistency": disagreement(swap_counts[j], swap_totals[j]),
                "judge_disagreement": disagreement(judge_counts[j], judge_totals[j])} for j in judges},
            "swap_note": "Swapped-presentation inconsistency mixes order effects and sampling variability; one call per presentation cannot separate them."},
        "costs": {"generation": generation_cost, "judging": judging_cost,
                  "failures": failure_cost, "failure_by_stage": failure_by_stage,
                  "prior_judgments": _costs(prior_judgments),
                  "total": _costs([*answers, *judgments, *failure_records, *prior_judgments]),
                  "scope": "All supplied experiment records, including cached results, excluded questions and paid failures. Totals deduplicate jobs and prior attempts already covered by cumulative answer histories; stage subtotals can overlap. Known amounts are recorded estimate components, including the explicitly conditional Google pricing scenario, not invoices. Unknown portions are excluded, and reservations remain separate exposure.",
                  "observed_cost_note": "Partial observed estimates use incomplete usage and may use conservative pricing envelopes. Final billed costs remain unknown for these jobs; estimates are excluded from known totals.",
                  "this_run_usd": None, "this_run_note": "Current-run spending requires orchestration cache metadata and is not inferred here."},
        "bootstrap": {"unit": "question", "samples": bootstrap_samples, "seed": seed,
                      "confidence": 0.95, "method": "Percentile intervals from complete-question resampling; descriptive, not independent-vote inference.",
                      "scope": "Intervals condition on frozen answers, selected judges, rubric and observed judgments. They describe sensitivity to the empirical mix of completed curated questions. They omit variability from regenerating answers or selecting other judges, and uncertainty about the validity of the rubric. They do not guarantee coverage across creative tasks. Ordering stability is a fraction of bootstrap draws, not a Bayesian probability of true superiority."},
    }


def write_report(report: dict, output_dir: Path) -> None:
    """Write machine-readable results and a self-contained human report locally."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ranking.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    with (output_dir / "ranking.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["agent", "rank", "preference_rate", "ci95_low", "ci95_high", "rank_ci95_low", "rank_ci95_high", "wins", "choices"])
        for row in report["ranking"]:
            writer.writerow([row["agent"], row["rank"], row["preference_rate"], *(row["ci95"] or [None, None]),
                             *(row["rank_ci95"] or [None, None]), row["wins"], row["choices"]])
    def number(value):
        return "unavailable" if value is None else f"{value:.4f}"
    def label(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    def format_interval(values):
        return " to ".join(number(v) for v in values) if values else "unavailable"
    coverage = report["coverage"]
    lines = ["# CREST preference ranking", "", report["interpretation"], "", report["method"], "",
             f"Complete question coverage: {coverage['complete_questions']} / {coverage['total_questions']}. "
             f"Each complete question requires {coverage['expected_judgments_per_question']} valid judgments and every agent answer.", "",
             "Bootstrap 95% intervals resample whole questions, retaining all dependent judge and order observations. "
             "Intervals are descriptive; few complete questions can give degenerate intervals.", "",
             report["bootstrap"]["scope"], ""]
    def table(title, rows):
        lines.extend([f"## {title}", "", "| Rank | Agent | Preference | 95% interval |", "| --- | --- | --- | --- |"])
        for row in rows:
            interval = format_interval(row["ci95"])
            lines.append(f"| {row['rank'] if row['rank'] is not None else 'unavailable'} | {label(row['agent'])} | {number(row['preference_rate'])} | {interval} |")
        lines.append("")
    table("Overall creativity", report["ranking"])
    lines.extend(["## Paired overall-index contrasts", "",
                  "Each difference subtracts the second agent's overall index from the first, using the same question draws for both. Ordering fractions count bootstrap draws, including exact index ties.", "",
                  "| Pair (first − second) | Index difference | 95% paired interval | First higher | Equal | Second higher | Draws |",
                  "| --- | --- | --- | --- | --- | --- | --- |"])
    for contrast in report["paired_contrasts"]:
        stability = contrast["ordering_stability"]
        lines.append(f"| {' − '.join(map(label, contrast['pair']))} | {number(contrast['difference'])} | {format_interval(contrast['ci95'])} | {number(stability['first_higher'])} | {number(stability['equal'])} | {number(stability['second_higher'])} | {contrast['bootstrap_samples']} |")
    lines.append("")
    for name, rows in report["per_judge"].items():
        table(f"Judge: {label(name)}", rows)
    agents = report["agents"]
    lines.extend(["## Opponent preferences", "", "Row agent's preference fraction against each column agent.", "",
                  "| Agent | " + " | ".join(map(label, agents)) + " |", "| --- | " + " | ".join("---" for _ in agents) + " |"])
    for a in agents:
        lines.append("| " + label(a) + " | " + " | ".join(number(report["pairwise"]["overall"][a][b]) for b in agents) + " |")
    lines.extend(["", "## Diagnostics", ""])
    for name in ("position_a_preference", "swapped_inconsistency", "judge_disagreement"):
        detail = report["diagnostics"][name]
        count, total = (detail["wins"], detail["choices"]) if name == "position_a_preference" else (detail["disagreements"], detail["comparisons"])
        title = "swapped-presentation inconsistency" if name == "swapped_inconsistency" else name.replace('_', ' ')
        lines.append(f"- {title}: {count}/{total}; fraction {number(detail['rate'])}.")
    lines.append("- Pairwise cycles: " + ("; ".join(" → ".join(map(label, c)) for c in report["diagnostics"]["cycles"]) or "none observed") + ".")
    lines.extend(["", report["diagnostics"]["swap_note"], "", "## Judge diagnostics", "",
                  "| Judge | A wins / choices | A preference | Swapped inconsistencies / comparisons | Inconsistency fraction | Judge disagreements / comparisons | Disagreement fraction |",
                  "| --- | --- | --- | --- | --- | --- | --- |"])
    for judge, detail in report["diagnostics"]["by_judge"].items():
        position, swapped, disagreed = (detail[name] for name in (
            "position_a_preference", "swapped_inconsistency", "judge_disagreement"))
        lines.append(f"| {label(judge)} | {position['wins']}/{position['choices']} | {number(position['rate'])} | {swapped['disagreements']}/{swapped['comparisons']} | {number(swapped['rate'])} | {disagreed['disagreements']}/{disagreed['comparisons']} | {number(disagreed['rate'])} |")
    lines.extend(["", "## Excluded coverage", "", f"Invalid judgments: {coverage['invalid_judgments']}; records for unknown questions: {coverage['ignored_judgments']}.", ""])
    lines.extend(f"- {label(q['question_id'])}: {', '.join(q['reasons'])}; missing answers: {', '.join(map(label, q['missing_answers'])) or 'none'}; missing judgment cells: {len(q['missing_judgments'])}." for q in coverage["excluded_questions"])
    if not coverage["excluded_questions"]:
        lines.append("No questions excluded.")
    lines.extend(["", "## Costs", "", report["costs"]["scope"], ""])
    for name in ("generation", "judging", "total"):
        cost = report["costs"][name]
        lines.append(f"- {name}: ${cost['known_usd']:.6f} known estimate components; {cost['unknown_count']} incomplete estimates across {cost['records']} records.")
    prior = report["costs"]["prior_judgments"]
    lines.append(f"- superseded paid judgments: ${prior['known_usd']:.6f} known estimate components across {prior['records']} jobs; included once in total and excluded from ranking votes.")
    total = report["costs"]["total"]
    lines.extend(["", f"The estimate subtotal includes ${total['partial_known_estimate_usd']:.6f} in partial known components and ${total['conditional_scenario_estimate_usd']:.6f} in conditional Google pricing scenarios. Recorded unresolved reserved exposure is ${total['unresolved_reserved_exposure_usd']:.6f}, separate from estimated spend. Actual billed amounts remain unverified."])
    for stage, name in (("generate", "failed generations"), ("judge", "failed judgments")):
        cost = report["costs"]["failure_by_stage"][stage]
        lines.append(f"- {name}: ${cost['known_usd']:.6f} known; {cost['unknown_count']} unknown costs across {cost['records']} records (included in total).")
    observed = report["costs"]["failures"]
    lines.extend(["", f"Partial observed failure estimate: ${observed['partial_observed_estimate_usd']:.6f} across {observed['observed_count']} jobs with unknown final costs. Budget-exceeded failures: {observed['budget_exceeded_count']}.",
                  "", report["costs"]["observed_cost_note"]])
    lines.extend(["", report["costs"]["this_run_note"], ""])
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
