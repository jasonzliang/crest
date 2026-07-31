"""CREST statistical analysis.

Implements the analysis plan that answers the methodology objections:
  - O5 power: per-item MIXED-EFFECTS models (crossed random effects: challenge + rater),
    effect sizes with bootstrap CIs, MDE/power curves; TOST EQUIVALENCE tests so
    'nulls/parity' read as evidence-for-equivalence, not absence of power.
  - O11 finding: the agent x category CROSSOVER (rank-reversal) interaction test.
  - O8 length: output length as a covariate (not just bins).
  - O16 grounding: a two-part (hurdle) model for the gate-zero-inflated score.
  - validity-stratified: C1/C5 analyzed on human scores; judge-valid cells (C2/C3/C4)
    on the panel (see judge/score.py).
Requires: statsmodels, scipy, numpy, pandas (see pyproject/requirements).
"""
from __future__ import annotations
import argparse, json, warnings

import numpy as np
import pandas as pd

ALL_AXES = ("new", "useful", "surprising")
PRIMARY_AXES = ("new", "useful")     # Surprising is EXPLORATORY: ablation moved it by -0.02, it
                                     # correlates with non-redundancy at r~0.95, and it is the sole
                                     # binding axis in ~1 record in 147. Single source of truth --
                                     # four separate copies of the axis tuple caused the drift that
                                     # left the primary endpoint defined three different ways.
AXES = ALL_AXES                      # back-compat alias


class InsufficientData(Exception):
    """Raised when a cell/model has too little data to fit meaningfully.

    main() catches this and prints 'insufficient data for <analysis>' rather
    than crashing -- the pilot has ~1 scored item/category and one scored agent.
    """


# --------------------------------------------------------------------------- #
# I/O + small helpers
# --------------------------------------------------------------------------- #
def load_run(path: str):
    """Tolerate a partially-written final line: analysing a LIVE run is the normal case, and an
    uncaught JSONDecodeError there is a crash for no reason."""
    import pandas as pd
    rows, bad = [], 0
    for line in open(path):
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
    """PRIMARY ENDPOINT: min(non-redundancy, Useful) -- TWO axes, not three.

    Surprising is deliberately EXCLUDED. It is reported as exploratory because ablating
    expert_baseline moved it by -0.02 (it is not separately anchored), it correlates with
    non-redundancy at r ~ 0.95, and it is the sole binding axis in roughly 1 record in 147 --
    so including it in the primary endpoint smuggles the third axis back in while adding no
    information. This also replaces the mean (which lets a strong axis mask a failing one) and the
    thresholded all-three indicator (whose rate swung 5.4-36.1% across thresholds 5..7).
    Use min3() if you need the old three-axis minimum for comparability.

    All-null creativity rows (e.g. grounding-gated agents) become NaN.
    """
    cols = [f"creativity.{a}" for a in PRIMARY_AXES]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        # HARD ERROR, not silent degradation. Dropping a missing axis turned min(new, useful) into
        # a one-axis endpoint: composite 5.18 -> 7.65 and the crossover interaction flipped
        # p=0.91 -> p=0.00015, with main() still printing the two-axis label.
        raise InsufficientData(f"primary endpoint needs {cols}; missing {missing}")
    return df[cols].min(axis=1, skipna=False)   # a NaN axis must NOT be silently skipped



# --------------------------------------------------------------------------- #
# Judge reliability: ICC + Krippendorff alpha + per-judge severity
#
# judge/judge_config.yaml has always specified `report: [krippendorff_alpha, icc]` with thresholds
# per Koo & Li 2016, and this module contained ZERO references to either -- a mandated control that
# was never computed. Per-judge scores ARE persisted (creativity.judges[]), so it is computable
# directly from any run's records.jsonl.
#
# Why severity matters as much as agreement: on this project's data judge severity varied by 2-3
# points on a 1-10 scale, which exceeded the entire between-agent spread. Reporting alpha/ICC
# WITHOUT per-judge means would hide the effect that actually decided the leaderboard.
# --------------------------------------------------------------------------- #
def judge_ratings(records_path: str) -> dict:
    """{axis: [[ratings for record 1], [record 2], ...]} plus per-judge means, from raw JSONL.

    Read from the file rather than the flattened frame because `creativity.judges` is a nested list
    and json_normalize leaves it as an object column."""
    rows = [json.loads(l) for l in open(records_path) if l.strip()]
    out = {ax: [] for ax in AXES}
    by_judge = {ax: {} for ax in AXES}
    for r in rows:
        c = r.get("creativity")
        if not c or not c.get("judges"):
            continue
        for ax in AXES:
            vals = [j[ax] for j in c["judges"] if j.get(ax) is not None]
            if len(vals) >= 2:                       # a unit needs >=2 raters to inform agreement
                out[ax].append(vals)
            for j in c["judges"]:
                if j.get(ax) is not None:
                    by_judge[ax].setdefault(j["judge_id"], []).append(j[ax])
    return {"units": out, "by_judge": by_judge, "n_records": len(rows)}


def icc_oneway(units: list[list[float]]) -> dict:
    """ICC(1,1) and ICC(1,k) from a one-way random-effects ANOVA on ragged rater groups.

    ICC(1,1) = reliability of a SINGLE judge; ICC(1,k) = reliability of the k-judge mean actually
    used (Spearman-Brown). judge_config's 0.80 bar applies to ICC(1,k), not ICC(1,1) -- conflating
    them overstates how badly the panel misses. Also returns judges_needed: how many raters ICC(k)
    >= 0.80 would require at the measured single-rater reliability."""
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
    icc1 = max(0.0, min(1.0, icc1))
    icck = (k_bar * icc1) / (1 + (k_bar - 1) * icc1) if icc1 > 0 else 0.0
    need = float("inf")
    if 0 < icc1 < 1:
        need = 0.80 * (1 - icc1) / (icc1 * (1 - 0.80))
    return {"icc_1_1": round(icc1, 3), "icc_1_k": round(icck, 3), "k_bar": round(k_bar, 2),
            "n_units": n, "judges_needed_for_0.80": (None if need == float("inf") else round(need, 1))}


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
    """Everything judge_config.yaml asked for, plus the severity table that explains the rest."""
    r = judge_ratings(records_path)
    rep = {}
    for ax in AXES:
        entry = {}
        try:
            entry.update(icc_oneway(r["units"][ax]))
        except InsufficientData as e:
            entry["icc_error"] = str(e)
        try:
            entry["krippendorff_alpha_interval"] = krippendorff_alpha_interval(r["units"][ax])
        except InsufficientData as e:
            entry["alpha_error"] = str(e)
        entry["per_judge_mean"] = {j: round(float(np.mean(v)), 2) for j, v in sorted(r["by_judge"][ax].items())}
        sev = entry["per_judge_mean"]
        if len(sev) >= 2:
            entry["severity_spread"] = round(max(sev.values()) - min(sev.values()), 2)
        rep[ax] = entry
    return rep


def _prep(df: pd.DataFrame, axis: str | None = None, composite: bool = False) -> pd.DataFrame:
    """Build a patsy-safe modeling frame with a clean 'y' column.

    (The raw axis columns are named 'creativity.new' etc. -- the dot breaks
    patsy formulas, so we always model against a renamed 'y'.)
    """
    if composite:
        y = _composite(df)
    else:
        y = df[_axis_col(axis)]
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
    composite = mean of the three axes). Reports the interaction F-test and the
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
    top_agent = {c: lst[0][0] for c, lst in rankings.items() if lst}
    rank_reversal = len(set(top_agent.values())) > 1

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
    from statsmodels.tools.sm_exceptions import PerfectSeparationError

    col = _axis_col(axis)

    # Build the gate frame: prefer grounding.passed, else creativity>0.
    if "grounding.passed" in df.columns:
        passed = df["grounding.passed"].astype("boolean")
    else:
        passed = _composite(df) > 0
    y_axis = pd.to_numeric(df.get(col, pd.Series(np.nan, index=df.index)), errors="coerce")

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
        except (PerfectSeparationError, Exception) as e:  # noqa: B014
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
    """Read the registration. Returns {} and says so if absent -- an analysis that silently proceeds
    without its stated plan is how `--prereg` came to be a flag pointing at a missing file."""
    try:
        import yaml
        d = yaml.safe_load(open(path)) or {}
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
                   help="frozen predictions + equivalence bounds. NOW ACTUALLY READ: this flag "
                        "previously defaulted to a nonexistent file and was never opened.")
    args = p.parse_args()

    warnings.filterwarnings("ignore", category=RuntimeWarning)

    prereg = load_prereg(args.prereg)          # stated plan, printed up front
    _bounds = tuple((prereg.get("analysis_plan", {}) or {})
                    .get("tost_equivalence_bounds", (-1.0, 1.0)))

    df = load_run(args.run)
    agents = sorted(df["agent"].dropna().astype(str).unique())
    cats = sorted(df["category"].dropna().astype(str).unique())
    print(f"loaded {len(df)} records; agents={agents}; categories={cats}")

    comp = _composite(df)
    scored = df.assign(_composite=comp.to_numpy())
    scored_rows = scored.dropna(subset=["_composite"])
    scored_agents = sorted(scored_rows["agent"].astype(str).unique())
    print(f"scored items: {len(scored_rows)}/{len(df)}; "
          f"agents with scores={scored_agents}; "
          f"scored categories={sorted(scored_rows['category'].astype(str).unique())}")

    # Descriptive: per-agent composite mean.
    if len(scored_rows):
        print("\n-- descriptive (composite mean by agent) --")
        for ag, sub in scored_rows.groupby(scored_rows["agent"].astype(str)):
            print(f"  {ag}: mean={sub['_composite'].mean():.3f} (n={len(sub)})")

    # Judge reliability -- previously computed by a function nothing called, while rubric.md,
    # design.md, related_work.md, benchmark_best_practices.md and preregistration.yaml all stated
    # reliability was reported.
    print("\n-- judge reliability (ICC / Krippendorff alpha / per-judge severity) --")
    try:
        rep = reliability_report(args.run)
        for ax, v in rep.items():
            print(f"  {ax:<12} ICC(1,1)={v.get('icc_1_1','-')}  ICC(1,k)={v.get('icc_1_k','-')}  "
                  f"alpha={v.get('krippendorff_alpha_interval','-')}  "
                  f"severity_spread={v.get('severity_spread','-')}  "
                  f"judges_for_0.80={v.get('judges_needed_for_0.80','-')}")
            print(f"               per-judge mean: {v.get('per_judge_mean', {})}")
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
                res = _run(f"bootstrap[{ax}]", lambda c=col: bootstrap_ci(df[c].to_numpy()))
                if res is not None:
                    n_ax = int(np.sum(~np.isnan(pd.to_numeric(df[col], errors='coerce'))))
                    print(f"  {ax}: {_fmt_ci(*res)} (n={n_ax})")
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
        for cat, rk in res["rankings"].items():
            print(f"    {cat}: " + ", ".join(f"{a}={v:.2f}" for a, v in rk))

    # TOST equivalence per category.
    print("\n-- TOST equivalence (composite vs 0, bounds +/-1) --")
    for cat in cats:
        res = _run(f"tost_equivalence[{cat}]", lambda c=cat: tost_equivalence(df, c))
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
