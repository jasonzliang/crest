"""Design-based analysis of uniformly sampled, released-paper comparisons.

A paper pair is the sampling unit. Its four overall judge/order verdicts are
averaged before taking equally weighted opponent means. Individual votes
and papers shared by multiple sampled pairs are never treated as independent
replicates. No network access or stochastic resampling is used here.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
import math
from statistics import fmean, variance

from crest_ais.protocol import PROTOCOL_VERSION, requires_reason_quality, validate_plan_fingerprint, validate_verdict


def _identity(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _validate_plan(plan):
    """Verify the schedule itself cannot silently omit an expected judge/order."""
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    agents, judges = plan.get("agents"), plan.get("judges")
    if not isinstance(agents, dict) or len(agents) < 2:
        raise ValueError("plan must contain at least two agents")
    if not isinstance(judges, dict) or len(judges) != 2:
        raise ValueError("plan must contain exactly two judges")
    for identity in list(agents) + list(judges):
        _identity(identity, "agent/judge id")
    requested_sample = _count(plan.get("pairs_per_matchup"), "pairs_per_matchup")
    if not requested_sample:
        raise ValueError("pairs_per_matchup must be positive")

    catalogs = {}
    eligible = defaultdict(int)
    for paper in plan.get("catalog", []):
        if not isinstance(paper, dict):
            raise ValueError("catalog paper must be an object")
        identity = _identity(paper.get("id"), "paper id")
        if identity in catalogs or paper.get("agent") not in agents:
            raise ValueError("duplicate catalog paper or unknown agent")
        catalogs[identity] = paper
        if paper.get("eligible_primary") is True:
            eligible[paper["agent"]] += 1
    selected = {}
    for paper in plan.get("papers", []):
        if not isinstance(paper, dict):
            raise ValueError("selected paper must be an object")
        identity = _identity(paper.get("id"), "selected paper id")
        original = catalogs.get(identity)
        if (identity in selected or original is None
                or original.get("eligible_primary") is not True
                or paper.get("agent") != original["agent"]):
            raise ValueError("selected papers must be unique eligible catalog records")
        selected[identity] = paper

    strata = {}
    for stratum in plan.get("strata", []):
        if not isinstance(stratum, dict):
            raise ValueError("stratum must be an object")
        pair = stratum.get("agents")
        if (not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(a, str) or a not in agents for a in pair)
                or pair != sorted(pair) or pair[0] == pair[1]):
            raise ValueError("stratum agents must be a canonical pair")
        pair = tuple(pair)
        if pair in strata:
            raise ValueError("duplicate stratum")
        population = _count(stratum.get("population_pairs"), "population_pairs")
        sample = _count(stratum.get("sampled_pairs"), "sampled_pairs")
        if population != eligible[pair[0]] * eligible[pair[1]] or sample > population:
            raise ValueError("stratum counts disagree with eligible fixed pools")
        if sample != min(requested_sample, population):
            raise ValueError("stratum sample must equal min(pairs_per_matchup, population_pairs)")
        strata[pair] = stratum
    if set(strata) != set(combinations(sorted(agents), 2)):
        raise ValueError("plan must include every scientist matchup")

    jobs, blocks = {}, {}
    paper_pair_ids = {}
    for job in plan.get("jobs", []):
        if not isinstance(job, dict):
            raise ValueError("job must be an object")
        key = _identity(job.get("key"), "job key")
        pair_id = _identity(job.get("pair_id"), "pair_id")
        if key in jobs:
            raise ValueError("duplicate job key")
        pair = job.get("agents")
        if not isinstance(pair, list) or any(not isinstance(a, str) for a in pair):
            raise ValueError("job agents must be a canonical pair")
        pair = tuple(pair)
        if pair not in strata:
            raise ValueError("job has unknown stratum")
        papers = job.get("papers")
        if (not isinstance(papers, list) or len(papers) != 2
                or any(not isinstance(p, str) or p not in selected for p in papers)
                or [selected[p]["agent"] for p in papers] != list(pair)):
            raise ValueError("job papers must match its canonical agents")
        papers = tuple(papers)
        order = job.get("order")
        if not isinstance(order, list) or order not in [list(papers), list(reversed(papers))]:
            raise ValueError("job order must contain the two compared papers")
        judge = job.get("judge")
        if not isinstance(judge, str) or judge not in judges:
            raise ValueError("job has unknown judge")
        if papers in paper_pair_ids and paper_pair_ids[papers] != pair_id:
            raise ValueError("same paper pair has multiple pair ids")
        paper_pair_ids[papers] = pair_id
        if pair_id not in blocks:
            blocks[pair_id] = {"agents": pair, "papers": papers, "jobs": {}, "pair_id": pair_id}
        block = blocks[pair_id]
        cell = (judge, tuple(order))
        if block["agents"] != pair or block["papers"] != papers or cell in block["jobs"]:
            raise ValueError("inconsistent pair block or duplicate judge/order cell")
        block["jobs"][cell] = key
        jobs[key] = job
    stratum_blocks = defaultdict(list)
    for block in blocks.values():
        expected_cells = {(judge, order) for judge in judges
                          for order in (block["papers"], block["papers"][::-1])}
        if set(block["jobs"]) != expected_cells:
            raise ValueError("each pair must schedule both judges in both orders")
        stratum_blocks[block["agents"]].append(block)
    for pair, stratum in strata.items():
        if len(stratum_blocks[pair]) != stratum["sampled_pairs"]:
            raise ValueError("stratum sample count disagrees with scheduled pairs")
    return agents, judges, catalogs, selected, strata, jobs, blocks


def _validate_results(results, jobs, *, require_reason_quality=False):
    if not isinstance(results, list):
        raise ValueError("results must be a list")
    validated = {}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        key = _identity(result.get("key"), "result key")
        if key not in jobs:
            raise ValueError(f"unknown result key: {key}")
        if key in validated:
            raise ValueError(f"duplicate result key: {key}")
        verdict = validate_verdict(result.get("verdict"), require_reason_quality=require_reason_quality)
        cost = result.get("cost_usd")
        if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float))
                                 or not math.isfinite(cost) or cost < 0):
            raise ValueError("cost_usd must be finite, nonnegative, or null")
        validated[key] = {**deepcopy(result), "verdict": verdict}
    return validated


def _sampling(values, population, family_size, *, complete):
    """SRS mean variance plus a simultaneous, bounded finite-population band.

    Serfling's two-sided bound applies to the fixed [0,1] pair values. A
    Bonferroni correction covers every matchup at once; the linear agent
    summaries therefore inherit that simultaneous coverage.
    The possible values of unsampled units give a second deterministic bound.
    """
    n = len(values)
    sample_variance = variance(values) if n > 1 else None
    fpc = 1 - n / population if population else None
    mean_variance = (0.0 if n and n == population else
                     fpc * sample_variance / n if n > 1 else None)
    interval = None
    if complete and n:
        mean = fmean(values)
        if n == population:
            low = high = mean
        else:
            radius = math.sqrt((1 - (n - 1) / population)
                               * math.log(2 * family_size / 0.05) / (2 * n))
            fraction = n / population
            low = max(0.0, mean - radius, fraction * mean)
            high = min(1.0, mean + radius, fraction * mean + 1 - fraction)
        interval = {"low": 100 * low, "high": 100 * high}
    return {"sample_size": n, "population_pairs": population,
            "sample_variance": sample_variance, "variance_fpc": fpc,
            "mean_variance": mean_variance,
            "standard_error_pct": 100 * math.sqrt(mean_variance) if mean_variance is not None else None,
            "interval": interval,
            "variance_valid_for_design": bool(complete and n)}


def _percentage(count, total):
    return 100 * count / total if total else None


def _observed_summary(agent, scores_by_opponent, agents, decisions_per_pair):
    """Equal-opponent sensitivity summary; preserve missing opponent cells."""
    covered = all(scores_by_opponent.get(opponent) for opponent in agents if opponent != agent)
    overall = 100 * fmean(fmean(scores_by_opponent[opponent])
                          for opponent in agents if opponent != agent) if covered else None
    return {"overall_pct": overall,
            "complete_pairs_by_opponent": {opponent: len(scores_by_opponent.get(opponent, []))
                                            for opponent in agents if opponent != agent},
            "decision_count": sum(len(rows) for rows in scores_by_opponent.values()) * decisions_per_pair}


def _winner_paper(job, result):
    return job["order"][0 if result["verdict"]["winner"] == "A" else 1]


def _sensitivity_diagnostics(agents, judges, catalog, selected, blocks, complete_blocks, results, jobs):
    """Show judge/order effects and actual reuse of each released manuscript."""
    appearances = {identity: {"agent": paper["agent"], "sampled_pairs": 0, "complete_pairs": 0}
                   for identity, paper in selected.items()}
    for block in blocks.values():
        for identity in block["papers"]:
            appearances[identity]["sampled_pairs"] += 1
            appearances[identity]["complete_pairs"] += int(block["pair_id"] in complete_blocks)
    pool_sizes = {agent: {"eligible": sum(p["agent"] == agent and p.get("eligible_primary") is True
                                          for p in catalog.values()),
                          "distinct_sampled": sum(p["agent"] == agent and p["sampled_pairs"] > 0 for p in appearances.values()),
                          "distinct_complete": sum(p["agent"] == agent and p["complete_pairs"] > 0 for p in appearances.values())}
                  for agent in agents}
    paper_scores = defaultdict(lambda: defaultdict(list))
    judge_scores = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    order_scores = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for block in complete_blocks.values():
        a, b = block["agents"]
        for identity, agent, opponent in ((block["papers"][0], a, b), (block["papers"][1], b, a)):
            paper_scores[identity][opponent].append(block["score"] if agent == a else 1 - block["score"])
        for kind, groups, destination in (("judge", judges, judge_scores),
                                          ("order", ("canonical", "reversed"), order_scores)):
            for group in groups:
                matching = [key for key in block["jobs"].values()
                            if (jobs[key]["judge"] == group if kind == "judge" else
                                (jobs[key]["order"] == list(block["papers"])) == (group == "canonical"))]
                score = fmean(_winner_paper(jobs[key], results[key]) == block["papers"][0] for key in matching)
                destination[group][a][b].append(score)
                destination[group][b][a].append(1 - score)
    return {"per_judge": {judge: {agent: _observed_summary(agent, judge_scores[judge][agent], agents, 2)
                                  for agent in agents} for judge in judges},
            "per_order": {order: {agent: _observed_summary(agent, order_scores[order][agent], agents, 2)
                                  for agent in agents} for order in ("canonical", "reversed")},
            "paper_appearances": appearances, "pool_sizes": pool_sizes,
            "per_paper": {identity: {"agent": paper["agent"],
                                     **_observed_summary(paper["agent"], paper_scores[identity], agents, 4)}
                          for identity, paper in selected.items()},
            "sensitivity_note": "Judge/order rates use complete blocks and equal opponent means. Per-paper rates condition on that observed manuscript and its sampled matches; missing opponent cells stay unavailable. Appearance counts are actual pair reuse, not independent paper samples or equal realized paper influence. Two-paper pools cannot support inference about unseen system outputs."}


def _diagnostics(blocks, results, jobs):
    """Available judgments diagnose position; matched cells diagnose disagreement."""
    numerators = {"position_a": 0, "swapped_inconsistency": 0, "judge_disagreement": 0}
    denominators = dict.fromkeys(numerators, 0)
    by_judge = defaultdict(lambda: {"position_a_count": 0, "decisions": 0})

    def add(kind, condition):
        numerators[kind] += int(condition)
        denominators[kind] += 1

    for key, result in results.items():
        judge = jobs[key]["judge"]
        label_a = result["verdict"]["winner"] == "A"
        add("position_a", label_a)
        by_judge[judge]["position_a_count"] += int(label_a)
        by_judge[judge]["decisions"] += 1
    for block in blocks.values():
        winners = {}
        for (judge, order), key in block["jobs"].items():
            if key in results:
                winners[judge, order] = _winner_paper(jobs[key], results[key])
        judges = sorted({cell[0] for cell in block["jobs"]})
        orders = (block["papers"], block["papers"][::-1])
        for judge in judges:
            cells = [(judge, order) for order in orders]
            if all(cell in winners for cell in cells):
                add("swapped_inconsistency", winners[cells[0]] != winners[cells[1]])
        for order in orders:
            cells = [(judge, order) for judge in judges]
            if all(cell in winners for cell in cells):
                add("judge_disagreement", winners[cells[0]] != winners[cells[1]])
    return {"position_a_pct": _percentage(numerators["position_a"], denominators["position_a"]),
            "swapped_inconsistency_pct": _percentage(numerators["swapped_inconsistency"], denominators["swapped_inconsistency"]),
            "judge_disagreement_pct": _percentage(numerators["judge_disagreement"], denominators["judge_disagreement"]),
            "denominators": denominators, "counts": numerators,
            "by_judge": {judge: {**counts, "position_a_pct": _percentage(counts["position_a_count"], counts["decisions"])}
                         for judge, counts in sorted(by_judge.items())},
            "scope": "All available validated judgments; disagreements require both matched cells. Scores use complete four-judgment blocks only."}


def analyze(plan: dict, results: list[dict]) -> dict:
    """Validate frozen inputs and return a JSON-serializable contract report."""
    if isinstance(plan, dict) and "fingerprint" in plan:
        validate_plan_fingerprint(plan)
    agents, judges, catalog, selected, strata, jobs, blocks = _validate_plan(plan)
    results_by_key = _validate_results(results, jobs, require_reason_quality=requires_reason_quality(plan))
    extension = plan.get("extension")
    posthoc = isinstance(extension, dict) and extension.get("stage") == "post_initial_results"
    complete_blocks = {}
    values = defaultdict(list)
    ties = {"overall": 0}
    for pair_id, block in blocks.items():
        if not all(key in results_by_key for key in block["jobs"].values()):
            continue
        score = fmean(_winner_paper(jobs[key], results_by_key[key]) == block["papers"][0]
                      for key in block["jobs"].values())
        complete_blocks[pair_id] = {**block, "score": score}
        values[block["agents"]].append(score)
        ties["overall"] += int(math.isclose(score, 0.5, abs_tol=1e-12))

    completed = len(results_by_key)
    full_plan = bool(jobs) and completed == len(jobs)
    status = "complete" if full_plan else "partial" if completed else "not_judged"
    comparisons = []
    family_size = len(strata)
    for pair, stratum in strata.items():
        observed = values[pair]
        n = len(observed)
        stratum_complete = n == stratum["sampled_pairs"] and n > 0
        sampling = {"overall": _sampling(observed, stratum["population_pairs"], family_size,
                                          complete=stratum_complete)}
        if posthoc:
            sampling["overall"]["variance_valid_for_design"] = False
        comparisons.append({"agents": list(pair), "overall_pct_a": 100 * fmean(observed) if n else None,
                            "complete_pairs": n, "sampled_pairs": stratum["sampled_pairs"],
                            "population_pairs": stratum["population_pairs"], "decision_count": n * 4,
                            "sampling": sampling})

    rankings = []
    for agent in agents:
        opponents = [comparison for comparison in comparisons if agent in comparison["agents"]]
        covered = bool(opponents) and all(comparison["complete_pairs"] for comparison in opponents)
        scores, lows, highs = [], [], []
        for comparison in opponents:
            forward = comparison["agents"][0] == agent
            score = comparison["overall_pct_a"]
            if score is not None:
                scores.append(score if forward else 100 - score)
            band = comparison["sampling"]["overall"]["interval"]
            if band is not None:
                lows.append(band["low"] if forward else 100 - band["high"])
                highs.append(band["high"] if forward else 100 - band["low"])
        overall = fmean(scores) if covered else None
        intervals = {"overall": {"low": fmean(lows), "high": fmean(highs)}
                     if full_plan and covered and len(lows) == len(opponents) else None}
        variances = [comparison["sampling"]["overall"]["mean_variance"] for comparison in opponents]
        design_variance = (math.fsum(variances) / len(opponents) ** 2
                           if full_plan and covered and all(v is not None for v in variances) else None)
        design_sampling = {"overall": {"mean_variance": design_variance,
                                        "standard_error_pct": 100 * math.sqrt(design_variance) if design_variance is not None else None,
                                        "variance_valid_for_design": design_variance is not None and not posthoc}}
        rankings.append({"agent": agent, "rank": None, "overall_pct": overall,
                         "intervals": intervals, "paper_count": sum(p["agent"] == agent for p in selected.values()),
                         "decision_count": sum(c["decision_count"] for c in opponents),
                         "opponents_with_data": sum(bool(c["complete_pairs"]) for c in opponents),
                         "expected_opponents": len(opponents), "design_sampling": design_sampling})
    rankings.sort(key=lambda row: (row["overall_pct"] is None, -(row["overall_pct"] or 0), row["agent"]))
    previous, last_rank = None, None
    if full_plan:
        for index, row in enumerate(rankings, 1):
            if row["overall_pct"] is None:
                continue
            score = round(row["overall_pct"], 12)
            if score != previous:
                last_rank = index
            row["rank"] = last_rank
            previous = score

    per_agent = {a: {"downloaded": sum(p["agent"] == a and bool(p.get("pdf_path")) for p in catalog.values()),
                     "eligible": sum(p["agent"] == a and p.get("eligible_primary") is True for p in catalog.values()),
                     "selected": sum(p["agent"] == a for p in selected.values())} for a in agents}
    diagnostics = _diagnostics(blocks, results_by_key, jobs)
    diagnostics.update(_sensitivity_diagnostics(agents, judges, catalog, selected, blocks,
                                                complete_blocks, results_by_key, jobs))
    diagnostics["ties"] = {"pair_blocks": ties,
                           "definition": "A tie is an exact 50% aggregate pair score; individual verdicts are binary.",
                           "primary_rank_groups": [[r["agent"] for r in rankings if r["rank"] == rank]
                                                   for rank in sorted({r["rank"] for r in rankings if r["rank"] is not None})]}
    judgments = []
    for key, job in jobs.items():
        if key in results_by_key:
            result = results_by_key[key]
            judgments.append({**deepcopy(result), "pair_id": job["pair_id"], "agents": deepcopy(job["agents"]),
                              "papers": deepcopy(job["papers"]), "order": deepcopy(job["order"]),
                              "judge": job["judge"], "model": result.get("model"),
                              "cost_usd": result.get("cost_usd"), "used_in_scores": job["pair_id"] in complete_blocks})
    report = {"version": plan.get("version", PROTOCOL_VERSION),
            "generated_at": datetime.now(timezone.utc).isoformat(), "status": status,
            "agents": deepcopy(agents), "judges": deepcopy(judges), "selection": deepcopy(plan.get("selection", {})),
            "coverage": {"expected_jobs": len(jobs), "completed_jobs": completed,
                         "usable_jobs": len(complete_blocks) * 4, "expected_pairs": len(blocks),
                         "complete_pairs": len(complete_blocks), "expected_decisions": len(jobs),
                         "used_decisions": len(complete_blocks) * 4,
                         "downloaded_papers": sum(c["downloaded"] for c in per_agent.values()),
                         "eligible_papers": sum(c["eligible"] for c in per_agent.values()),
                         "selected_papers": len(selected), "per_agent": per_agent},
            "rankings": rankings, "comparisons": comparisons, "diagnostics": diagnostics,
            "costs": {"known_usd": math.fsum(r["cost_usd"] for r in results_by_key.values() if r.get("cost_usd") is not None),
                      "unknown_jobs": sum(r.get("cost_usd") is None for r in results_by_key.values()),
                      "completed_jobs": completed},
            "papers": deepcopy(list(selected.values())), "catalog": deepcopy(list(catalog.values())), "judgments": judgments,
            "uncertainty": {"method": "Simultaneous Serfling finite-population bounds with Bonferroni correction, intersected with deterministic unsampled-mass bounds.",
                            "confidence": 0.95, "coverage_guarantee": "at least 95% under the stated fixed-design assumptions",
                            "nominal_fixed_size_level": 0.95, "inference_scope": "fixed_design_sampling",
                            "sequential_valid": False,
                            "family_size": family_size,
                            "assumptions": ["Frozen eligible paper pools and fixed potential judge/order outcomes for every population pair.",
                                            "Predeclared SRS without replacement in each matchup; no adaptive sample-size choice or optional stopping.",
                                            "Sampling bands exclude judge stochasticity, model drift, publication selection, and unseen outputs."],
                            "bound_formula": "sqrt((1-(n-1)/N)*log(2*K/alpha)/(2*n)); alpha=.05, K=number of declared matchups. A census has zero selection uncertainty.",
                            "references": [{"title": "Bardenet and Maillard, Concentration inequalities for sampling without replacement",
                                            "url": "https://arxiv.org/html/1309.4029v2",
                                            "location": "Proposition 2.2 and the preceding classical Serfling inequality"}],
                            "note": "Conditional on frozen eligible released-paper pools and the fixed judge/order instrument. Uniform sampling without replacement is within matchup; paper-pair blocks are the units, each averaging four overall creativity votes. Bounds cover all matchup means jointly and propagate through equal opponent averages. Census strata have zero sampling uncertainty. These are not confidence intervals for future systems, judge reliability, or future papers. Primary intervals require a complete plan; partial-data variances are descriptive only. Variances use scores in [0,1] and standard errors use percentage points. Agent design variances assume independent matchup selection. Shared papers do not invalidate finite-pool pair-selection variance; paper-generation uncertainty is outside this estimand."},
            "limitations": [
                "This compares fixed released public-paper pools, not future-system capability or a controlled benchmark.",
                "Topic, date, model backbone, compute, and publication-selection differences confound causal interpretation.",
                "PDF text extraction excludes visual plot inspection and may omit equations, tables, or other content.",
                "Only two judges and two answer orders define the fixed instrument; their errors and rubric validity are not quantified by sampling bands.",
                "Only complete four-judgment paper-pair blocks contribute scores. Partial completion may be selective; primary ranks require the entire plan.",
                "Opponent matchups receive equal weight, regardless of released collection sizes or sampled pair counts. Each verdict is one overall creativity choice guided jointly by New, Useful, and Surprising.",
                "Small eligible pools, including Agentic v3's two autonomous papers when present, sharply limit representativeness.",
                "Costs are usage-based estimates rather than provider invoices; missing usage is unknown, not free, and can leave charges unrecorded.",
            ]}
    if isinstance(extension, dict):
        report["extension"] = deepcopy(extension)
    if posthoc:
        if extension.get("kind") == "cohort_addition":
            previous_count = extension["previous_agent_count"]
            current_count = len(agents)
            report["cohort_comparability"] = {
                "previous_agent_count": previous_count, "current_agent_count": current_count,
                "previous_opponents": previous_count - 1, "current_opponents": current_count - 1,
                "directly_comparable": False}
            decision_note = (f"The cohort expanded from {previous_count} to {current_count} scientists after earlier results were observed. "
                             f"Each current score averages {current_count - 1} opponents equally; the previous cohort averaged {previous_count - 1}. "
                             "These percentages summarize different opponent sets and are not directly comparable. "
                             "Each opponent mean receives equal weight even when matchups contain different numbers of paper pairs.")
            sampling_assumption = ("Existing scientist matchups and their recorded verdicts retained. New scientist matchups sampled uniformly "
                                   "without replacement from frozen paper pools after earlier cohort results were observed.")
        else:
            initial_pairs = extension.get("original_pairs")
            initial_per_matchup = (initial_pairs // len(strata)
                                   if isinstance(initial_pairs, int) and initial_pairs % len(strata) == 0 else None)
            initial_description = (f"the initial {initial_per_matchup}-pair-per-matchup results"
                                   if initial_per_matchup is not None else "the initial results")
            target = extension.get("target_pairs_per_matchup", plan["pairs_per_matchup"])
            decision_note = f"The target of {target} paper pairs per matchup was chosen after observing {initial_description}."
            sampling_assumption = ("Original sampled pairs retained; additional pairs drawn uniformly without replacement from unused pairs "
                                   "within matchup. The final target was chosen after initial results were observed.")
        adaptive_note = (decision_note + " The displayed ranges use the nominal 95% fixed-size calculation as an exploratory reference. "
                         "They have no 95% coverage guarantee for this post hoc extension and are not sequentially valid.")
        report["uncertainty"].update(
            method="Exploratory fixed-size Serfling reference ranges with Bonferroni correction, intersected with deterministic unsampled-mass bounds.",
            confidence=None, coverage_guarantee="No coverage guarantee for the post hoc extension; these are exploratory reference ranges.",
            inference_scope="exploratory_fixed_size_reference",
            assumptions=[
                "Frozen eligible paper pools and fixed potential judge/order outcomes for every population pair.",
                sampling_assumption,
                "Reference ranges exclude judge stochasticity, model drift, publication selection, and unseen outputs.",
            ],
            note=(adaptive_note + " Calculations condition on the frozen released-paper pools and fixed judge/order instrument. "
                  "Each pair averages four overall creativity votes; agent summaries weight opponents equally. "
                  "Variance estimates and standard errors are fixed-size descriptive references for this extension. "
                  "These ranges do not quantify uncertainty about future systems, future papers, or judge reliability."))
        report["limitations"].append(adaptive_note)
    return report
