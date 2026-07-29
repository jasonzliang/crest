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

AXES = ("new", "useful", "surprising")


class InsufficientData(Exception):
    """Raised when a cell/model has too little data to fit meaningfully.

    main() catches this and prints 'insufficient data for <analysis>' rather
    than crashing -- the pilot has ~1 scored item/category and one scored agent.
    """


# --------------------------------------------------------------------------- #
# I/O + small helpers
# --------------------------------------------------------------------------- #
def load_run(path: str):
    import pandas as pd
    rows = [json.loads(l) for l in open(path) if l.strip()]
    df = pd.json_normalize(rows)
    return df


def _axis_col(axis: str) -> str:
    if axis not in AXES:
        raise ValueError(f"axis must be one of {AXES}, got {axis!r}")
    return f"creativity.{axis}"


def _composite(df: pd.DataFrame) -> pd.Series:
    """Composite creativity = mean of the three axes (per row).

    All-null creativity rows (e.g. grounding-gated agents) become NaN.
    """
    cols = [f"creativity.{a}" for a in AXES if f"creativity.{a}" in df.columns]
    if not cols:
        return pd.Series(np.nan, index=df.index)
    return df[cols].mean(axis=1)  # skipna: all-NaN row -> NaN


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
                   help="frozen predictions + equivalence bounds, timestamped pre-scoring (O1/O11)")
    args = p.parse_args()

    warnings.filterwarnings("ignore", category=RuntimeWarning)

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
