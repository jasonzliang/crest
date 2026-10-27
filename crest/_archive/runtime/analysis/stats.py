"""CREST statistical analysis.

What this module actually computes (claims here must match the code below -- nothing else in the
repo is checked against it):
  - O5 power: per-item MIXED-EFFECTS models (random intercept for challenge_id) with effect sizes
    and deterministic bootstrap CIs; TOST EQUIVALENCE tests so 'nulls/parity' read as
    evidence-for-equivalence rather than absence of power.
  - O11 finding: the agent x category CROSSOVER (rank-reversal) interaction test.
  - O16 grounding: a two-part (hurdle) model for the gate-zero-inflated score.
  - judge reliability: ICC(1,*), ICC(3,*), Krippendorff's alpha, per-judge severity.
NOT here (do not cite this file for them): MDE/power curves, a rater random effect, and the
output-length covariate -- none are implemented. Validity stratification (which cells are scored by
panel vs human) happens upstream in judge/score.py; this module analyses whatever it emitted.
Requires: statsmodels, scipy, numpy, pandas (see pyproject/requirements).
"""
from __future__ import annotations
import argparse, json, math, warnings
from pathlib import Path

import numpy as np
import pandas as pd

AXES = ("new", "useful", "surprising")
# AXES is the single source of truth -- for the axis set (scattered copies of this tuple once left the
# primary endpoint defined three different ways) and for the New-vs-Surprising argument below, which
# _composite() and min2() defer to instead of restating. Three copies of that argument are what let
# one copy claim Surprising was "deliberately EXCLUDED" while the code included it.
#
# All THREE axes are in the primary endpoint. On the clean 250-record full-panel run Surprising is
# UNIQUELY the lowest axis in 51/250 records (20%), so a conjunctive endpoint that omits it is not
# measuring the gate the benchmark claims to apply. (The "sole binding axis in ~1 record in 147"
# figure that once justified dropping it was threshold-based on a smaller LOFO run and did not survive
# re-measurement.) Including it lowers every agent by 0.06-0.38 and changes no ranking
# (corr(min2, min3) = 0.989), so it costs nothing in conclusions and buys consistency with the stated
# three-axis design.
#
# Two caveats to carry into the paper:
#   - r(New, Surprising) = 0.883 at record level. The r~0.95 once quoted here was the pooled per-judge
#     figure AND was stated in the v1 judge prompt, so it is contaminated -- see JUDGE_PROMPT_VERSION.
#   - Surprising is UNANCHORED since expert_baseline was withdrawn from the judge prompt (ablating it
#     moved the axis by -0.02), so 20% of primary-endpoint values rest on an unanchored judgement.
#     min2() is the two-axis variant for when that caveat matters.


class InsufficientData(Exception):
    """Raised when a cell/model has too little data to fit meaningfully.

    main() catches this and prints 'insufficient data for <analysis>' rather
    than crashing -- the pilot has ~1 scored item/category and one scored agent.
    """


# --------------------------------------------------------------------------- #
# I/O + small helpers
# --------------------------------------------------------------------------- #
def resolve_records_path(path: str) -> str:
    """Accept a run DIRECTORY as well as a records.jsonl, and resolve it ONCE.

    rejudge and ablate_fields both take --run as a directory, so stats must too. Resolving inside
    load_run alone is not enough: main() also hands the path to reliability_report, which opens it
    directly -- a directory would load fine and then silently produce no reliability table."""
    p = Path(path)
    if p.is_dir():
        f = p / "records.jsonl"
        if not f.exists():
            raise InsufficientData(f"{p} is a directory with no records.jsonl")
        return str(f)
    return path


def load_run(path: str):
    """Tolerate a partially-written final line: analysing a LIVE run is the normal case, and an
    uncaught JSONDecodeError there is a crash for no reason."""
    path = resolve_records_path(path)
    rows, bad = [], 0
    for line in open(path, encoding="utf-8"):   # records.jsonl is written UTF-8; the platform
        # default is not it. Pin every reader in this module, not just judge_ratings.
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"  [skipped {bad} unparseable line(s) -- run still being written?]")
    if not rows:
        raise InsufficientData(f"no parseable records in {path}")
    return pd.json_normalize(rows)


def _axis_col(axis: str) -> str:
    if axis not in AXES:
        raise ValueError(f"axis must be one of {AXES}, got {axis!r}")
    return f"creativity.{axis}"


def _composite(df: pd.DataFrame) -> pd.Series:
    """PRIMARY ENDPOINT: min(New, Useful, Surprising) -- the graded form of "creative on all three".

    All three axes are INCLUDED; see the AXES note at the top of this module for why, and for the two
    caveats that come with Surprising. min2() is the New/Useful robustness check.

    min() replaces the mean (which lets a strong axis mask a failing one) and the thresholded
    all-three indicator (whose rate swung 5.4-36.1% across thresholds 5..7 ON THE PILOT, and
    46.4-56.0% on the canonical run 040653Z).

    All-null creativity rows (e.g. grounding-gated agents) become NaN.
    """
    cols = [f"creativity.{a}" for a in AXES]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        # HARD ERROR, not silent degradation. Dropping a missing axis turned min(new, useful) into
        # a one-axis endpoint: composite 5.18 -> 7.65 and the crossover interaction flipped
        # p=0.91 -> p=0.00015, with main() still printing the two-axis label.
        raise InsufficientData(f"primary endpoint needs {cols}; missing {missing}")
    return df[cols].min(axis=1, skipna=False)   # a NaN axis must NOT be silently skipped


def min2(df: pd.DataFrame) -> pd.Series:
    """Two-axis ROBUSTNESS variant, min(New, Useful) -- Surprising excluded because it is unanchored
    (see the AXES note). Report alongside the primary endpoint when that caveat matters."""
    cols = [f"creativity.{a}" for a in ("new", "useful")]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise InsufficientData(f"min2 needs {cols}; missing {missing}")
    return df[cols].min(axis=1, skipna=False)


# --------------------------------------------------------------------------- #
# Judge reliability: ICC + Krippendorff alpha + per-judge severity
#
# doc/judge_protocol_intent.md (the retired judge_config.yaml's content) mandates
# `report: [krippendorff_alpha, icc]` with thresholds per Koo & Li
# 2016; per-judge scores are persisted in creativity.judges[], so all of it is computable from any
# run's records.jsonl.
#
# Severity is reported beside agreement because on this data judge severity varied by 3.2-3.7 points
# on a 1-10 scale, exceeding the entire between-agent spread. Reporting alpha/ICC WITHOUT per-judge
# means would hide the effect that actually decided the leaderboard.
# --------------------------------------------------------------------------- #
def judge_ratings(records_path: str) -> dict:
    """{axis: [[ratings for record 1], [record 2], ...]} plus per-judge means, from raw JSONL.

    Read from the file rather than the flattened frame because `creativity.judges` is a nested list
    and json_normalize leaves it as an object column."""
    rows = [json.loads(l) for l in open(records_path, encoding="utf-8") if l.strip()]
    out = {ax: [] for ax in AXES}
    ids = {ax: [] for ax in AXES}                    # per-unit judge-id tuples, aligned with out[ax]
    by_judge = {ax: {} for ax in AXES}
    for r in rows:
        c = r.get("creativity")
        if not c or not c.get("judges"):
            continue
        for ax in AXES:
            rated = [j for j in c["judges"] if j.get(ax) is not None]
            if len(rated) >= 2:                      # a unit needs >=2 raters to inform agreement
                out[ax].append([j[ax] for j in rated])
                # Track WHICH judges, not just how many. ICC(1,*) and alpha are rater-agnostic so
                # positional lists suffice for them, but ICC(3,*) treats column position AS rater
                # identity. Under leave_one_family_out every unit has the same COUNT from a different
                # PAIR, so a count-only balance check passes on a matrix whose columns mix judges.
                ids[ax].append(tuple(j.get("judge_id") for j in rated))
            for j in c["judges"]:
                if j.get(ax) is not None:
                    by_judge[ax].setdefault(j["judge_id"], []).append(j[ax])
    return {"units": out, "judge_ids": ids, "by_judge": by_judge, "n_records": len(rows)}


def icc_oneway(units: list[list[float]], judge_ids: list[tuple] | None = None) -> dict:
    """ICC(1,1) and ICC(1,k) from a one-way random-effects ANOVA on ragged rater groups.

    ICC(1,1) = reliability of a SINGLE judge; ICC(1,k) = reliability of the k-judge mean actually
    used (Spearman-Brown). judge_config's 0.80 bar applies to ICC(1,k), not ICC(1,1) -- conflating
    them overstates how badly the panel misses. Also returns judges_needed: how many raters ICC(k)
    >= 0.80 would require at the measured single-rater reliability."""
    # Filter BOTH lists in lockstep: filtering units alone misaligns judge_ids, which makes a
    # genuinely fixed panel with one 1-rating unit report "rater set varies (2 distinct panels)" and
    # silently skip ICC(3,*). Unreachable today only because judge_ratings pre-filters.
    if judge_ids is not None and len(judge_ids) == len(units):
        pairs = [(u, i) for u, i in zip(units, judge_ids) if len(u) >= 2]
        units = [u for u, _ in pairs]
        judge_ids = [i for _, i in pairs]
    elif judge_ids is not None:
        # RAISE, do not discard. Setting judge_ids = None here strips _icc_twoway's fixed-panel guard,
        # so a length mismatch yields ICC(3,1)=1.0 on columns that mix judges -- a false NUMBER, where
        # skipping is merely a conservative false SKIP.
        raise InsufficientData(f"judge_ids ({len(judge_ids)}) and units ({len(units)}) are not "
                               f"parallel; refusing to compute ICC(3,*) on an unverifiable panel")
    else:
        units = [u for u in units if len(u) >= 2]
    if len(units) < 3:
        raise InsufficientData("need >=3 units with >=2 ratings for ICC")
    n = len(units)
    all_v = [v for u in units for v in u]
    grand = float(np.mean(all_v))
    k_bar = float(np.mean([len(u) for u in units]))
    ss_b = sum(len(u) * (np.mean(u) - grand) ** 2 for u in units)
    ss_w = sum(sum((v - np.mean(u)) ** 2 for v in u) for u in units)
    df_b, df_w = n - 1, len(all_v) - n
    if df_w <= 0:
        raise InsufficientData("no within-unit variance available for ICC")
    ms_b, ms_w = ss_b / df_b, ss_w / df_w
    icc1 = (ms_b - ms_w) / (ms_b + (k_bar - 1) * ms_w) if (ms_b + (k_bar - 1) * ms_w) else float("nan")
    # Report the RAW value alongside the clamped one. For interval data ICC(1,1) and Krippendorff's
    # alpha are the SAME statistic and unclamped they agree to 3dp, so clamping only one of them makes
    # "ICC(1,1)=0.0  alpha=-0.042" read as two controls corroborating each other -- it is one control
    # printed twice, once with the negative sign hidden.
    icc1_raw = icc1
    icc1 = max(0.0, min(1.0, icc1))
    icck = (k_bar * icc1) / (1 + (k_bar - 1) * icc1) if icc1 > 0 else 0.0
    need = float("inf")
    if 0 < icc1 < 1:
        need = 0.80 * (1 - icc1) / (icc1 * (1 - 0.80))
    out = {"icc_1_1": round(icc1, 3), "icc_1_1_raw": round(icc1_raw, 3),
           "icc_1_k": round(icck, 3), "k_bar": round(k_bar, 2),
           "n_units": n, "judges_needed_for_0.80": (None if need == float("inf") else round(need, 1))}
    out.update(_icc_twoway(units, judge_ids))
    return out


def _icc_twoway(units: list[list[float]], judge_ids: list[tuple] | None = None) -> dict:
    """ICC(3,1) / ICC(3,k): two-way MIXED model, judge main effect removed (Shrout & Fleiss 1979).

    Reported NEXT TO the one-way figures, not instead of them. ICC(1,*) treats raters as
    interchangeable and pushes systematic severity into the error term; this panel's severity spread
    is 3.2-3.7 points on a 1-10 scale, so the one-way numbers collapse to ~0 and read as "the judges
    agree on nothing". That is the correct answer to "can I trust ONE randomly-chosen judge in
    absolute terms?" and the wrong answer to "do the judges RANK answers the same way?", which is what
    a leaderboard rests on. Quoting either alone misleads in a different direction.

    Requires balanced data (every unit rated by the same k). Skipped otherwise rather than
    approximated -- the shipped run is full-panel, so k = 3 exactly."""
    ks = {len(u) for u in units}
    if len(ks) != 1:
        return {"icc_3_note": f"skipped: unbalanced panel (ratings per unit: {sorted(ks)})"}
    # Equal COUNTS are not a fixed panel. On a LOFO fixture built from the run's real severities every
    # unit had k=2, the count check passed, and ICC(3,k) came out 0.789 from a matrix with three
    # different column patterns whose positional means (6.26, 8.60) matched no actual judge -- the
    # severity effect this model exists to remove was only partly removed.
    if judge_ids is not None:
        distinct = {tuple(t) for t in judge_ids}
        if len(distinct) != 1:
            return {"icc_3_note": f"skipped: rater set varies across units "
                                  f"({len(distinct)} distinct panels, e.g. leave-one-family-out) "
                                  f"-- ICC(3,*) requires a fixed panel"}
    k = ks.pop()
    if k < 2 or len(units) < 3:
        return {}
    a = np.asarray(units, dtype=float)                       # n units x k raters
    n = a.shape[0]
    grand = a.mean()
    ss_rows = k * ((a.mean(axis=1) - grand) ** 2).sum()      # between targets
    ss_cols = n * ((a.mean(axis=0) - grand) ** 2).sum()      # between judges (the severity effect)
    ss_err = ((a - a.mean(axis=1, keepdims=True) - a.mean(axis=0, keepdims=True) + grand) ** 2).sum()
    df_r, df_e = n - 1, (n - 1) * (k - 1)
    if df_e <= 0:
        return {}
    ms_r, ms_e = ss_rows / df_r, ss_err / df_e
    if ms_r <= 0:
        return {}
    icc31 = (ms_r - ms_e) / (ms_r + (k - 1) * ms_e) if (ms_r + (k - 1) * ms_e) else float("nan")
    icc3k = (ms_r - ms_e) / ms_r
    # Report BOTH shares, and name them for what they are. The SS share understates the judge
    # contribution because SS_judge carries k-1 df against SS_target's n-1 (2 vs 249 here): on the
    # shipped run it reads 0.535/0.215/0.590 where the variance-component share is 0.632/0.290/0.682,
    # an understatement of 7.5-9.7pp in the direction that flatters the panel -- and the single key it
    # replaces was printed as "judge share of variance", the number a paper would copy.
    ms_c = ss_cols / (k - 1) if k > 1 else 0.0
    v_t = max(0.0, (ms_r - ms_e) / k)                 # target variance component
    v_j = max(0.0, (ms_c - ms_e) / len(units))        # judge (column) variance component
    tot = v_t + v_j + ms_e
    return {"icc_3_1": round(float(icc31), 3), "icc_3_k": round(float(icc3k), 3),
            "judge_effect_ss_share": round(float(ss_cols / (ss_rows + ss_cols + ss_err)), 3),
            "judge_effect_var_share": (round(float(v_j / tot), 3) if tot > 0 else None)}


def krippendorff_alpha_interval(units: list[list[float]]) -> float:
    """Krippendorff's alpha with the INTERVAL difference function, for 1-10 rating scales.

    alpha = 1 - Do/De, Do computed over within-unit rater pairs and De over all value pairs, so
    missing/ragged ratings are handled natively. Interval (not ordinal) metric: a defensible choice
    for an equal-appearing 1-10 scale and the simpler claim to defend; ordinal alpha is a refinement.
    alpha <= 0 means agreement no better than chance."""
    units = [u for u in units if len(u) >= 2]
    if len(units) < 3:
        raise InsufficientData("need >=3 units with >=2 ratings for alpha")
    n_total = sum(len(u) for u in units)
    do = sum((1.0 / (len(u) - 1)) * sum((a - b) ** 2 for i, a in enumerate(u) for b in u[i + 1:])
             for u in units) * (2.0 / n_total)
    vals = [v for u in units for v in u]
    de = sum((a - b) ** 2 for i, a in enumerate(vals) for b in vals[i + 1:]) * 2.0 / (n_total * (n_total - 1))
    return float("nan") if de == 0 else round(1 - do / de, 3)


def reliability_report(records_path: str) -> dict:
    """Everything doc/judge_protocol_intent.md asks for, plus the severity table explaining the rest."""
    r = judge_ratings(records_path)
    rep = {}
    for ax in AXES:
        entry = {}
        try:
            entry.update(icc_oneway(r["units"][ax], r["judge_ids"][ax]))
        except InsufficientData as e:
            entry["icc_error"] = str(e)
        try:
            entry["krippendorff_alpha_interval"] = krippendorff_alpha_interval(r["units"][ax])
        except InsufficientData as e:
            entry["alpha_error"] = str(e)
        raw_mean = {j: float(np.mean(v)) for j, v in sorted(r["by_judge"][ax].items())}
        entry["per_judge_mean"] = {j: round(m, 2) for j, m in raw_mean.items()}
        # Spread from the RAW means, not the display-rounded ones: subtracting rounded values turned a
        # true 3.7440 into a printed 3.75 that then propagated into five docs. The measured triple is
        # 3.320 / 3.196 / 3.744.
        if len(raw_mean) >= 2:
            entry["severity_spread"] = round(max(raw_mean.values()) - min(raw_mean.values()), 2)
        rep[ax] = entry
    return rep


def _is_scored(df: pd.DataFrame):
    """Boolean mask matching harness/results.py::is_scored -- status AND a present creativity dict.

    A bare `scoring_status == "scored"` test was used in three places here while the docstring claimed
    it was "the SAME predicate" as results.is_scored. It wasn't: is_scored also requires the dict, and
    a judge_degraded row carries one while a desynced row can carry the status without one. That kind
    of drift is what made a repair report n_scored dropping from 100 to 91."""
    ok = df["scoring_status"].astype(str) == "scored" if "scoring_status" in df.columns else True
    axis_cols = [f"creativity.{a}" for a in AXES if f"creativity.{a}" in df.columns]
    if axis_cols:
        ok = ok & df[axis_cols].notna().any(axis=1)
    return ok


def _prep(df: pd.DataFrame, axis: str | None = None, composite: bool = False) -> pd.DataFrame:
    """Build a patsy-safe modeling frame with a clean 'y' column.

    (The raw axis columns are named 'creativity.new' etc. -- the dot breaks
    patsy formulas, so we always model against a renamed 'y'.)

    Rows are dropped unless the record is scored, by the SAME predicate
    harness/results.py::is_scored applies, for the same reason: a judge_degraded row carries a full
    creativity dict, so keying on non-nullness alone folds rows into every model (MixedLM, TOST, the
    crossover interaction, the bootstrap CIs) that summary.json, the run manifest and run_crest's own
    console all EXCLUDE from the headline. Two files disagreeing about which records count is how a
    paper ends up quoting two different n.
    """
    y = _composite(df) if composite else df[_axis_col(axis)]
    if "scoring_status" in df.columns:
        # BOTH conditions, matching results.is_scored: the status is authoritative AND the
        # creativity dict must be present. Three files now agree; a bare status check was a
        # fourth definition of "scored" while claiming to be the same one.
        y = y.where(_is_scored(df))
    work = pd.DataFrame(
        {
            "y": pd.to_numeric(y, errors="coerce").to_numpy(),
            "agent": df["agent"].astype(str).to_numpy(),
            "category": df["category"].astype(str).to_numpy(),
            "challenge_id": df["challenge_id"].astype(str).to_numpy(),
        }
    )
    return work.dropna(subset=["y"]).reset_index(drop=True)


def _extract_effects(res, names) -> list[dict]:
    ci = res.conf_int()
    pvals = res.pvalues
    terms = []
    for name in names:
        row = ci.loc[name]
        terms.append(
            {
                "term": str(name),
                "coef": float(res.params[name]),
                "ci_low": float(row.iloc[0]),
                "ci_high": float(row.iloc[1]),
                "p": (float(pvals[name]) if name in pvals.index else None),
            }
        )
    return terms


# --------------------------------------------------------------------------- #
# O5: per-item mixed-effects model
# --------------------------------------------------------------------------- #
def mixed_effects_axis(df, axis: str):
    """Per-item mixed model: creativity.<axis> ~ C(agent) [+ C(category)]
    with a random intercept for challenge_id (statsmodels MixedLM).

    Returns a tidy dict of fixed effects + 95% CIs. On a singular / failed
    fit, falls back to OLS and flags it (method='ols_fallback', singular=True).
    """
    import statsmodels.formula.api as smf
    from statsmodels.tools.sm_exceptions import ConvergenceWarning

    col = _axis_col(axis)
    work = _prep(df, axis=axis)
    n_obs = len(work)
    n_agents = work["agent"].nunique()
    n_groups = work["challenge_id"].nunique()
    if n_obs < 3 or n_agents < 2:
        raise InsufficientData(
            f"axis={axis}: {n_obs} scored obs across {n_agents} agent(s) "
            f"(need >=3 obs and >=2 agents)"
        )

    multi_cat = work["category"].nunique() > 1
    formula = "y ~ C(agent)" + (" + C(category)" if multi_cat else "")

    method = "mixedlm"
    singular = False
    res = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            md = smf.mixedlm(formula, work, groups=work["challenge_id"])
            res = md.fit(reml=True)
        re_var = float(np.asarray(res.cov_re)[0, 0])
        if not getattr(res, "converged", True) or re_var < 1e-8:
            # random intercept unidentified -> effectively OLS; flag + fall back
            singular = True
            res = None
    except Exception:
        res = None

    if res is None:
        method = "ols_fallback"
        singular = True
        res = smf.ols(formula, work).fit()
        fe_names = list(res.params.index)
        re_var = None
    else:
        fe_names = list(res.fe_params.index)
        re_var = float(np.asarray(res.cov_re)[0, 0])

    return {
        "axis": axis,
        "column": col,
        "formula": formula,
        "method": method,
        "singular": singular,
        "n_obs": n_obs,
        "n_groups": n_groups,
        "n_agents": n_agents,
        "re_var_challenge_id": re_var,
        "fixed_effects": _extract_effects(res, fe_names),
    }


# --------------------------------------------------------------------------- #
# O11: agent x category crossover / rank-reversal
# --------------------------------------------------------------------------- #
def crossover_interaction(df, axis: str | None = None):
    """OLS creativity ~ C(agent)*C(category) for a chosen axis (default the
    composite = min of the three axes). Reports the interaction F-test and the
    per-category agent ranking, and flags rank reversals (the top agent differs
    across categories) -- the headline O11 finding is a crossover, not a level
    shift.
    """
    import statsmodels.formula.api as smf
    import statsmodels.api as sm

    composite = axis is None
    work = _prep(df, axis=axis, composite=composite)
    label = "composite" if composite else axis

    n_agents = work["agent"].nunique()
    n_cats = work["category"].nunique()
    if n_agents < 2 or n_cats < 2 or len(work) < 4:
        raise InsufficientData(
            f"crossover ({label}): {len(work)} obs, {n_agents} agent(s), "
            f"{n_cats} categor(y/ies) (need >=2 agents, >=2 categories, >=4 obs)"
        )

    # Per-category agent ranking (works even on saturated designs).
    means = work.groupby(["category", "agent"])["y"].mean()
    rankings: dict[str, list[tuple[str, float]]] = {}
    for cat, sub in means.groupby(level=0):
        ordered = sub.droplevel(0).sort_values(ascending=False)
        rankings[str(cat)] = [(str(a), float(v)) for a, v in ordered.items()]
    # A reversal exists iff NO SINGLE AGENT CAN TOP EVERY CATEGORY -- i.e. the intersection of the
    # per-category argmax SETS is empty. Two wrong versions preceded this one and each failed on a
    # case the other handled:
    #   (a) `lst[0][0]`, comparing single winners, broke ties by whichever name sort_values left
    #       first -- alphabetical order. On run 2026-08-01T015432Z, C4 is an exact tie
    #       (openai_deepresearch == openai_shallow == 6.5000) while openai_shallow tops the other
    #       four, so it reported rank_reversal=True -- the module's headline finding -- on data with
    #       no reversal. Renaming the tied agent to zz_* with IDENTICAL scores flipped the verdict:
    #       a pure relabeling moved the result.
    #   (b) EXCLUDING tied categories fixed that and broke the converse. Given C1 {A:9,B:5,C:4} and
    #       C2 {B:8,C:8,A:3}, no agent can top both, so a reversal plainly exists -- but C2 is
    #       dropped as tied and the verdict comes back False. Dropping a category also silently
    #       shrinks the evidence, and all-tied would answer "no reversal" from zero categories.
    # The argmax-set intersection handles both: a tie makes a category admit MORE possible winners,
    # which is weaker evidence of a reversal, not a reason to discard the category.
    # isclose, not ==: composites are means over 3 judges, so exact mathematical ties land on
    # different floats (6.199999999999999 vs 6.2 vs 6.200000000000001 all occur for 31/5).
    winners: dict[str, set] = {}
    for c, lst in rankings.items():
        if not lst:
            continue
        best = lst[0][1]
        winners[c] = {a for a, v in lst if math.isclose(v, best, rel_tol=0.0, abs_tol=1e-9)}
    rank_reversal = bool(winners) and not set.intersection(*winners.values())
    top_agent = {c: sorted(s)[0] for c, s in winners.items() if len(s) == 1}
    tied_cats = sorted(c for c, s in winners.items() if len(s) > 1)

    # Interaction F-test (may be non-estimable on a fully saturated design).
    model = smf.ols("y ~ C(agent)*C(category)", work).fit()
    interaction = {"F": None, "p": None, "df_num": None, "df_resid": float(model.df_resid)}
    if model.df_resid > 0:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                aov = sm.stats.anova_lm(model, typ=2)
            key = "C(agent):C(category)"
            if key in aov.index:
                row = aov.loc[key]
                F = row["F"]
                p = row["PR(>F)"]
                interaction["F"] = None if pd.isna(F) else float(F)
                interaction["p"] = None if pd.isna(p) else float(p)
                interaction["df_num"] = float(row["df"])
        except Exception:
            pass

    return {
        "axis": label,
        "n_obs": len(work),
        "n_agents": n_agents,
        "n_categories": n_cats,
        "interaction": interaction,
        "rankings": rankings,
        "top_agent_by_category": top_agent,
        "rank_reversal": rank_reversal,
        # Reported, never silently dropped: excluding a category from the reversal test is a
        # narrowing of the evidence and has to be visible wherever the verdict is.
        "categories_with_tied_top": sorted(tied_cats),
    }


# --------------------------------------------------------------------------- #
# O5: TOST equivalence
# --------------------------------------------------------------------------- #
def tost_equivalence(df, category: str, bounds: tuple[float, float] = (-1.0, 1.0),
                     reference: float = 0.0, alpha: float = 0.05):
    """Two one-sided t-tests (TOST) for equivalence of a category's per-item
    composite scores against a reference (default 0) within +/- bounds.

    equivalent == both one-sided nulls rejected (score lies inside the band).
    """
    from scipy import stats

    lower, upper = float(bounds[0]), float(bounds[1])
    work = _prep(df, composite=True)
    x = work.loc[work["category"].astype(str) == str(category), "y"].to_numpy()
    x = x[~np.isnan(x)]
    if x.size < 2:
        raise InsufficientData(
            f"category {category}: {x.size} scored item(s) (need >=2 for a t-test)"
        )

    # H0_lower: mean <= reference+lower ; reject via one-sided 'greater'
    t_lower = stats.ttest_1samp(x, reference + lower, alternative="greater")
    # H0_upper: mean >= reference+upper ; reject via one-sided 'less'
    t_upper = stats.ttest_1samp(x, reference + upper, alternative="less")
    p_lower = float(t_lower.pvalue)
    p_upper = float(t_upper.pvalue)

    return {
        "category": str(category),
        "n": int(x.size),
        "mean": float(np.mean(x)),
        "reference": reference,
        "bounds": (lower, upper),
        "p_lower": p_lower,
        "p_upper": p_upper,
        "equivalent": bool(p_lower < alpha and p_upper < alpha),
    }


# --------------------------------------------------------------------------- #
# O16: two-part (hurdle) model for the grounding-gated, zero-inflated score
# --------------------------------------------------------------------------- #
def hurdle_model(df, axis: str):
    """Two-part model for the grounding-gate zero-inflation (O16):

      1. gate  -- logistic regression of grounding.passed (else creativity>0)
                  on C(agent)+C(category);
      2. cond. -- linear model of creativity.<axis> on C(agent)[+C(category)]
                  over the passing subset.

    Returns both fits' summaries. Guarded for tiny data / perfect separation.
    """
    import statsmodels.formula.api as smf

    col = _axis_col(axis)

    # Build the gate frame: prefer grounding.passed, else creativity>0.
    if "grounding.passed" in df.columns:
        passed = df["grounding.passed"].astype("boolean")
    else:
        passed = _composite(df) > 0
    y_axis = pd.to_numeric(df.get(col, pd.Series(np.nan, index=df.index)), errors="coerce")
    # Same scoring_status mask _prep applies: the conditional arm builds its own frame rather than
    # going through _prep, so it counted judge_degraded rows the rest of the module excludes (n_obs 250
    # where the masked count is 210). The GATE arm deliberately keeps every row -- it models whether a
    # record passed at all, so unscored rows are the outcome, not noise.
    if "scoring_status" in df.columns:
        y_axis = y_axis.where(_is_scored(df))

    gate_df = pd.DataFrame(
        {
            "passed": pd.to_numeric(passed, errors="coerce"),
            "agent": df["agent"].astype(str).to_numpy(),
            "category": df["category"].astype(str).to_numpy(),
        }
    ).dropna(subset=["passed"])
    gate_df["passed"] = gate_df["passed"].astype(int)

    gate: dict = {"status": None}
    n_pass_classes = gate_df["passed"].nunique()
    if len(gate_df) < 3 or n_pass_classes < 2:
        gate = {"status": "insufficient",
                "note": f"{len(gate_df)} rows, {n_pass_classes} outcome class(es)"}
    else:
        multi_cat = gate_df["category"].nunique() > 1
        gform = "passed ~ C(agent)" + (" + C(category)" if multi_cat else "")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gres = smf.logit(gform, gate_df).fit(disp=False)
                gate = {"status": "ok", "formula": gform,
                        "n_obs": int(gres.nobs), "summary": gres.summary().as_text()}
        except Exception as e:   # PerfectSeparationError included -- it is a plain Exception subclass
            gate = {"status": "perfect_separation_or_failed",
                    "formula": gform, "error": f"{type(e).__name__}: {e}"}

    # Conditional (passing subset) linear model.
    cond_df = pd.DataFrame(
        {
            "y": y_axis.to_numpy(),
            "agent": df["agent"].astype(str).to_numpy(),
            "category": df["category"].astype(str).to_numpy(),
            "passed": pd.to_numeric(passed, errors="coerce").to_numpy(),
        }
    )
    cond_df = cond_df[(cond_df["passed"] == 1)].dropna(subset=["y"]).reset_index(drop=True)

    cond: dict = {"status": None}
    if len(cond_df) < 2:
        cond = {"status": "insufficient", "note": f"{len(cond_df)} passing scored row(s)"}
    else:
        multi_cat_c = cond_df["category"].nunique() > 1
        multi_agent_c = cond_df["agent"].nunique() > 1
        terms = []
        if multi_agent_c:
            terms.append("C(agent)")
        if multi_cat_c:
            terms.append("C(category)")
        cform = "y ~ " + (" + ".join(terms) if terms else "1")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cres = smf.ols(cform, cond_df).fit()
                cond = {
                    "status": "ok" if cres.df_resid > 0 else "saturated",
                    "formula": cform,
                    "n_obs": int(cres.nobs),
                    "df_resid": float(cres.df_resid),
                    "summary": cres.summary().as_text(),
                }
        except Exception as e:
            cond = {"status": "failed", "formula": cform, "error": f"{type(e).__name__}: {e}"}

    if gate.get("status") in {"insufficient", "perfect_separation_or_failed"} and \
            cond.get("status") in {"insufficient", "failed"}:
        raise InsufficientData(
            f"hurdle[{axis}]: gate={gate.get('status')}, conditional={cond.get('status')}"
        )

    return {"axis": axis, "column": col, "gate": gate, "conditional": cond}


# --------------------------------------------------------------------------- #
# O5: nonparametric bootstrap CI (deterministic)
# --------------------------------------------------------------------------- #
def bootstrap_ci(values, stat=np.mean, n: int = 10000):
    """Nonparametric bootstrap 95% CI for any statistic.

    Deterministic: uses np.random.default_rng(0). Returns (point, lo, hi).
    """
    v = np.asarray(list(values), dtype=float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        raise InsufficientData("no non-NaN values to bootstrap")
    point = float(stat(v))
    if v.size == 1:
        return point, point, point
    rng = np.random.default_rng(0)
    idx = rng.integers(0, v.size, size=(n, v.size))
    resamples = v[idx]
    try:
        boot = np.asarray(stat(resamples, axis=1), dtype=float)
    except TypeError:
        boot = np.array([float(stat(resamples[i])) for i in range(n)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return point, float(lo), float(hi)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def load_prereg(path: str) -> dict:
    """Read the registration. Returns {} and SAYS SO if absent -- an analysis that silently proceeds
    without its stated plan is indistinguishable from one that has none."""
    try:
        import yaml
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"  [WARNING: no pre-registration at {path}; predictions/bounds NOT loaded]")
        return {}
    except Exception as e:
        print(f"  [WARNING: could not parse {path}: {type(e).__name__}]")
        return {}
    reg, plan = d.get("registration", {}), d.get("analysis_plan", {})
    print(f"  pre-registration: created {reg.get('created_at','?')}, "
          f"externally_timestamped={reg.get('externally_timestamped')}")
    if not reg.get("externally_timestamped"):
        print("  [CAVEAT: NOT externally timestamped -- these are the authors' stated prior "
              "expectations, recorded in-repo. Do not describe them as pre-registered.]")
    print(f"  predictions: {d.get('predictions', {})}")
    print(f"  primary endpoint: {plan.get('primary_endpoint','?')}  "
          f"| TOST bounds: {plan.get('tost_equivalence_bounds','?')}")
    return d


def _run(label: str, fn):
    """Run one analysis, degrading gracefully. Returns the result or None."""
    try:
        return fn()
    except InsufficientData as e:
        print(f"insufficient data for {label}: {e}")
    except Exception as e:  # never crash the whole run
        print(f"skipping {label}: {type(e).__name__}: {e}")
    return None


def _fmt_ci(pt, lo, hi):
    return f"{pt:.3f}  95% CI [{lo:.3f}, {hi:.3f}]"


def main():
    p = argparse.ArgumentParser(description="Analyze a CREST run.")
    p.add_argument("--run", required=True)
    p.add_argument("--prereg", default="crest/analysis/preregistration.yaml",
                   help="frozen predictions + equivalence bounds; read and echoed before any fit.")
    args = p.parse_args()

    warnings.filterwarnings("ignore", category=RuntimeWarning)

    prereg = load_prereg(args.prereg)          # stated plan, printed up front
    _bounds = tuple((prereg.get("analysis_plan", {}) or {})
                    .get("tost_equivalence_bounds", (-1.0, 1.0)))

    # Resolve ONCE; every consumer gets the file. Caught because InsufficientData's contract is that
    # main() prints and continues -- a traceback for "you pointed me at a directory" contradicts it.
    try:
        records_path = resolve_records_path(args.run)
        df = load_run(records_path)
    except (InsufficientData, FileNotFoundError, OSError) as e:
        print(f"cannot read run: {type(e).__name__}: {e}")
        raise SystemExit(1)
    agents = sorted(df["agent"].dropna().astype(str).unique())
    cats = sorted(df["category"].dropna().astype(str).unique())
    print(f"loaded {len(df)} records; agents={agents}; categories={cats}")

    # Wrapped like every other analysis: _composite RAISES on a missing axis, and a live run's first
    # minutes (or a fully grounding-gated agent) have no creativity columns at all.
    comp = _run("composite", lambda: _composite(df))
    scored_rows = df.iloc[0:0]
    if comp is not None:
        scored = df.assign(_composite=comp.to_numpy())
        if "scoring_status" in scored.columns:     # same predicate as _prep and results.is_scored
            scored = scored[_is_scored(scored)]
        scored_rows = scored.dropna(subset=["_composite"])
        scored_agents = sorted(scored_rows["agent"].astype(str).unique())
        print(f"scored items: {len(scored_rows)}/{len(df)}; "
              f"agents with scores={scored_agents}; "
              f"scored categories={sorted(scored_rows['category'].astype(str).unique())}")

    # min2 as the stated robustness check: rubric.md, benchmark_best_practices.md and
    # preregistration.yaml all describe min(New, Useful) as the two-axis comparison, so it must be
    # COMPUTED, not just documented.
    if len(scored_rows):
        m2 = _run("min2", lambda: min2(df))
        if m2 is not None:
            both = pd.DataFrame({"three": scored_rows["_composite"].to_numpy(),
                                 "two": m2.reindex(scored_rows.index).to_numpy()}).dropna()
            if len(both) > 2:
                print("\n-- robustness: min(New,Useful) vs min(New,Useful,Surprising) --")
                print(f"  two-axis mean={both['two'].mean():.3f}  three-axis mean="
                      f"{both['three'].mean():.3f}  delta={both['three'].mean()-both['two'].mean():+.3f}"
                      f"  corr={both['two'].corr(both['three']):.4f}  (n={len(both)})")

    # Descriptive: per-agent composite mean.
    if len(scored_rows):
        print("\n-- descriptive (composite mean by agent) --")
        for ag, sub in scored_rows.groupby(scored_rows["agent"].astype(str)):
            print(f"  {ag}: mean={sub['_composite'].mean():.3f} (n={len(sub)})")

    # Judge reliability. rubric.md, design.md, related_work.md, benchmark_best_practices.md and
    # preregistration.yaml all state this table is reported, and the severity spread is the headline
    # methodological finding, so it must actually print.
    print("\n-- judge reliability (ICC / Krippendorff alpha / per-judge severity) --")
    try:
        # `records_path`, NOT args.run: reliability_report opens the path directly, so a directory
        # argument dies on IsADirectoryError inside the bare `except` below and prints "insufficient
        # data" for a run with 250 records x 3 judges.
        rep = reliability_report(records_path)
        for ax, v in rep.items():
            print(f"  {ax:<12} ICC(1,1)={v.get('icc_1_1','-')} (raw {v.get('icc_1_1_raw','-')})  "
                  f"ICC(1,k)={v.get('icc_1_k','-')}  "
                  f"alpha={v.get('krippendorff_alpha_interval','-')}  "
                  f"severity_spread={v.get('severity_spread','-')}  "
                  f"judges_for_0.80={v.get('judges_needed_for_0.80','-')}")
            print(f"               two-way (judge effect removed): ICC(3,1)={v.get('icc_3_1','-')}  "
                  f"ICC(3,k)={v.get('icc_3_k','-')}  "
                  f"judge share: SS={v.get('judge_effect_ss_share','-')} "
                  f"var={v.get('judge_effect_var_share','-')}"
                  f"{'  ' + v['icc_3_note'] if v.get('icc_3_note') else ''}")
            print(f"               per-judge mean: {v.get('per_judge_mean', {})}")
            # surface the reason rather than printing a row of dashes: an all-'-' line reads as
            # "not enough data" when it actually means a computation raised
            for k in ("icc_error", "alpha_error"):
                if v.get(k):
                    print(f"               {k}: {v[k]}")
    except Exception as e:
        print(f"  insufficient data for reliability_report: {type(e).__name__}: {e}")

    # Bootstrap CIs (this generally works even with one scored agent).
    print("\n-- bootstrap CIs --")
    if len(scored_rows):
        pt = bootstrap_ci(scored_rows["_composite"].to_numpy())
        print(f"  composite: {_fmt_ci(*pt)} (n={len(scored_rows)})")
        for ax in AXES:
            col = f"creativity.{ax}"
            if col in df.columns:
                # Through _prep, NOT raw df: unmasked, these CIs sit directly beneath a correctly-masked
                # composite CI while including judge_degraded rows, contradicting the "scored items:
                # N/M" line above. Measured on a fixture with 40 of 250 rows degraded, the printed New
                # mean moved -1.14 (6.964 at n=250 vs 8.100 at n=210).
                sub = _run(f"bootstrap[{ax}]", lambda a=ax: _prep(df, axis=a))
                if sub is not None and len(sub):
                    res = _run(f"bootstrap[{ax}]", lambda s=sub: bootstrap_ci(s["y"].to_numpy()))
                    if res is not None:
                        print(f"  {ax}: {_fmt_ci(*res)} (n={len(sub)})")
    else:
        print("  insufficient data for bootstrap_ci: no scored items")

    # Per-axis mixed-effects models.
    print("\n-- mixed-effects (per axis) --")
    for ax in AXES:
        res = _run(f"mixed_effects[{ax}]", lambda a=ax: mixed_effects_axis(df, a))
        if res is not None:
            print(f"  [{ax}] method={res['method']} singular={res['singular']} "
                  f"n={res['n_obs']} groups={res['n_groups']} formula='{res['formula']}'")
            for t in res["fixed_effects"]:
                pval = "NA" if t["p"] is None else f"{t['p']:.3g}"
                print(f"      {t['term']}: coef={t['coef']:.3f} "
                      f"CI[{t['ci_low']:.3f},{t['ci_high']:.3f}] p={pval}")

    # Crossover / rank-reversal (headline O11).
    print("\n-- crossover interaction (composite) --")
    res = _run("crossover_interaction", lambda: crossover_interaction(df))
    if res is not None:
        it = res["interaction"]
        Ftxt = "NA" if it["F"] is None else f"{it['F']:.3f}"
        ptxt = "NA" if it["p"] is None else f"{it['p']:.3g}"
        print(f"  interaction F={Ftxt} p={ptxt} (df_resid={it['df_resid']})")
        print(f"  rank_reversal={res['rank_reversal']}  top_by_category={res['top_agent_by_category']}")
        if res.get("categories_with_tied_top"):
            print(f"    (excluded from the reversal test -- exact tie for top, so no single winner: "
                  f"{res['categories_with_tied_top']})")
        for cat, rk in res["rankings"].items():
            print(f"    {cat}: " + ", ".join(f"{a}={v:.2f}" for a, v in rk))

    # TOST equivalence per category.
    print(f"\n-- TOST equivalence (composite vs 0, bounds {list(_bounds)}) --")
    for cat in cats:
        # bounds=_bounds: pass the REGISTERED bounds, don't just print them in the header. Omitted,
        # tost_equivalence silently falls back to its own (-1, 1) default, so one run can print two
        # different bounds and editing the registration does nothing.
        res = _run(f"tost_equivalence[{cat}]",
                   lambda c=cat: tost_equivalence(df, c, bounds=_bounds))
        if res is not None:
            print(f"  {cat}: mean={res['mean']:.3f} n={res['n']} "
                  f"equivalent={res['equivalent']} "
                  f"p_lower={res['p_lower']:.3g} p_upper={res['p_upper']:.3g}")

    # Hurdle (two-part) model.
    print("\n-- hurdle model (gate + conditional) --")
    res = _run("hurdle_model[useful]", lambda: hurdle_model(df, "useful"))
    if res is not None:
        print(f"  gate: status={res['gate'].get('status')} "
              f"{res['gate'].get('note') or res['gate'].get('formula', '')}")
        print(f"  conditional: status={res['conditional'].get('status')} "
              f"{res['conditional'].get('note') or res['conditional'].get('formula', '')}")

    print("\ndone.")


if __name__ == "__main__":
    main()
