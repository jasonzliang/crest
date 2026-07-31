#!/usr/bin/env python3
"""Ablate judge-side fields to measure whether they actually move a score.

Why this exists. `known_answers` (30% of the dataset's bytes) and `expert_baseline` (18%) are
defended as load-bearing, but neither had ever been ablated -- so there was no evidence either
changes a single score. Worse, the only dose-response ever measured for `known_answers` ran the
WRONG way: more prior-art entries correlated with HIGHER novelty awards. This script settles it.

It is nearly free because generation is already paid for: a finalized run's `transcripts.jsonl`
holds every agent answer, so each ablation arm costs judge calls only, and the FULL arm is not
re-run at all -- it is read from the run's existing records.

Arms (the judge's CURRENT default is: known_answers shown, expert_baseline withheld):
  full                  (baseline; read from the run, not re-scored)
  no_known              known_answers also withheld
  with_expert           expert_baseline restored
  no_known_with_expert  both flipped

Interpretation:
  * If New does not drop when `known_answers` is withheld, the novelty baseline is not doing the
    work claimed for it, and the field should be cut rather than defended.
  * If Surprising does not drop when `expert_baseline` is withheld, the third axis is not anchored
    by it, the axis rests on the judge's own prior -- a limitation to report, NOT grounds to drop
    the axis. (An earlier version of this line argued for two axes on the strength of r~0.93; the
    measured value is 0.883 at record level, and Surprising is the sole binding axis in 51/250
    records, so the endpoint keeps all three.)

Usage:
    python -m crest.analysis.ablate_fields --run crest/result/runs/<run_id> --per-category 2
    python -m crest.analysis.ablate_fields --run <dir> --arms no_known --per-category 3
"""
from __future__ import annotations
import argparse, dataclasses, json, statistics, sys, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from crest.harness.run_crest import load_challenges          # noqa: E402
from crest.judge.score import JudgePanel, _ABLATABLE, JUDGE_PROMPT_VERSION   # noqa: E402
from crest.harness.rejudge import StoredReport, _load_jsonl   # noqa: E402

# NOTE the INVERTED semantics. This script's own first run proved expert_baseline does not anchor
# Surprising (-0.02), so score.py now withholds it BY DEFAULT and `restore_expert_baseline` is the
# key that adds it back. The old arms ("no_expert"/"neither", keyed on `expert_baseline`) named a
# key that no longer exists.
ARMS = {"no_known": {"known_answers"},                                 # withhold prior art
        "with_expert": {"restore_expert_baseline"},                    # add the baseline back
        "no_known_with_expert": {"known_answers", "restore_expert_baseline"}}
AXES = ("new", "useful", "surprising")

# Fail at import, before a single judge call. _judge_prompt raises on an unknown ablate key, but it
# raises inside a worker whose exception JudgePanel.score swallows per-judge -- so a stale key here
# dropped every judge, returned None for every record, and crashed on `mean([])` AFTER paying in
# full for the preceding arm. A typo in this dict must cost $0, not one arm's worth of judge calls.
_bad = set().union(*ARMS.values()) - _ABLATABLE
if _bad:   # NOT an assert: `python -O` strips asserts, which would restore the very failure
           # this guard exists to prevent, at full cost per arm
    raise SystemExit(f"ARMS references ablate key(s) score.py does not accept: {sorted(_bad)}")


def _balanced(records: list, per_category: int) -> list:
    """A balanced subset: the first `per_category` CHALLENGES of each category, all agents on each.
    Sampling whole challenges (not random records) keeps every arm comparable within an item."""
    by_cat = collections.defaultdict(list)
    for r in records:
        if r["challenge_id"] not in by_cat[r["category"]]:
            by_cat[r["category"]].append(r["challenge_id"])
    keep = {c for cat, ids in by_cat.items() for c in ids[:per_category]}
    return [r for r in records if r["challenge_id"] in keep]


def main():
    ap = argparse.ArgumentParser(description="Measure whether judge-side fields change scores.")
    ap.add_argument("--run", required=True)
    ap.add_argument("--judge-config", default="crest/judge/judge_config.live.yaml")
    ap.add_argument("--challenges", default="crest/questions/crest_challenges.jsonl")
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument("--per-category", type=int, default=2, help="challenges per category to ablate")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--out", default=None, help="defaults to <run>/ablation.json")
    a = ap.parse_args()
    _p = lambda s: Path(s) if Path(s).is_absolute() else REPO / s
    run_dir = _p(a.run)

    # is_scored, not a bare creativity check: a judge_degraded row carries a full creativity dict, so
    # filtering on the dict alone let under-judged records into the FULL arm and every delta.
    from crest.harness.results import is_scored
    records = [r for r in _load_jsonl(run_dir / "records.jsonl") if is_scored(r)]
    # The FULL arm is read from the run; every other arm is re-scored with the CURRENT prompt. If the
    # rubric has moved since the run, each delta conflates the ablation with the rubric bump -- and
    # the with_expert -> Surprising verdict is precisely the one v2 changed the prompt to enable.
    vers = {(r.get("creativity") or {}).get("judge_prompt_version") for r in records}
    if vers != {JUDGE_PROMPT_VERSION}:
        raise SystemExit(
            f"judge prompt version mismatch: this run was scored under {sorted(vers, key=str)} but "
            f"the current prompt is {JUDGE_PROMPT_VERSION}. The FULL arm comes from the run and the "
            f"ablation arms from the current prompt, so every delta would mix the ablation with the "
            f"rubric change. Re-judge the run first (harness/rejudge.py), or ablate a run scored "
            f"under {JUDGE_PROMPT_VERSION}.")
    texts = {t["record_id"]: t for t in _load_jsonl(run_dir / "transcripts.jsonl")}
    ch_by_id = {c.id: c for c in load_challenges(str(_p(a.challenges)))}
    subset = [r for r in _balanced(records, a.per_category) if r["record_id"] in texts]
    print(f"{run_dir.name}: {len(records)} scored records -> ablating {len(subset)} "
          f"({a.per_category}/category x all agents) across arms {a.arms}")
    print(f"judge calls ~= {len(subset)} x {len(a.arms)} arms x panel size\n")

    # FULL arm is free: read the scores the run already produced.
    results = {"full": {ax: [r["creativity"][ax] for r in subset] for ax in AXES}}
    results["full"]["_min3"] = [min(r["creativity"][ax] for ax in AXES) for r in subset]

    for arm in a.arms:
        panel = JudgePanel.from_config(str(_p(a.judge_config)))
        panel.ablate = frozenset(ARMS[arm])
        got = {}

        def one(rec):
            tr = texts[rec["record_id"]]
            rep = StoredReport(tr.get("output_text", ""), tr.get("citations", []))
            sc = panel.score(dataclasses.asdict(ch_by_id[rec["challenge_id"]]), rep,
                             exclude_family=rec.get("model_family"))
            return rec["record_id"], sc

        with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as ex:
            futs = [ex.submit(one, r) for r in subset]
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    rid, sc = fut.result()
                    if sc is not None:
                        got[rid] = sc
                except Exception as e:
                    print(f"  [arm {arm}] a record failed: {type(e).__name__}: {str(e)[:90]}")
                if i % 10 == 0:
                    print(f"  [{arm}] {i}/{len(subset)}")
        # keep arms paired: compare only records scored in BOTH arms
        paired = [r for r in subset if r["record_id"] in got]
        results[arm] = {ax: [got[r["record_id"]].__dict__[ax] for r in paired] for ax in AXES}
        results[arm]["_min3"] = [min(got[r["record_id"]].__dict__[ax] for ax in AXES) for r in paired]
        results[arm]["_paired_ids"] = [r["record_id"] for r in paired]
        print(f"  [{arm}] scored {len(paired)}/{len(subset)}")

    print("\n" + "=" * 76)
    print(f"{'arm':<12}{'n':>5}{'New':>9}{'Useful':>9}{'Surp':>9}{'min3':>9}   delta vs full")
    print("=" * 76)
    base = {ax: statistics.mean(results['full'][ax]) for ax in list(AXES) + ["_min3"]}
    print(f"{'full':<12}{len(results['full']['new']):>5}"
          f"{base['new']:>9.2f}{base['useful']:>9.2f}{base['surprising']:>9.2f}{base['_min3']:>9.2f}")
    verdict = {}
    for arm in a.arms:
        ids = set(results[arm].get("_paired_ids", []))
        idx = [i for i, r in enumerate(subset) if r["record_id"] in ids]
        pb = {ax: statistics.mean([results["full"][ax][i] for i in idx]) for ax in list(AXES) + ["_min3"]}
        cur = {ax: statistics.mean(results[arm][ax]) for ax in list(AXES) + ["_min3"]}
        d = {ax: cur[ax] - pb[ax] for ax in list(AXES) + ["_min3"]}
        print(f"{arm:<12}{len(results[arm]['new']):>5}"
              f"{cur['new']:>9.2f}{cur['useful']:>9.2f}{cur['surprising']:>9.2f}{cur['_min3']:>9.2f}"
              f"   dN={d['new']:+.2f} dU={d['useful']:+.2f} dS={d['surprising']:+.2f}")
        verdict[arm] = d
    print("=" * 76)
    if "no_known" in verdict:
        dn = verdict["no_known"]["new"]
        print(f"known_answers -> New: {dn:+.2f}. "
              + ("FIELD IS LOAD-BEARING (removing it inflates novelty as predicted)." if dn >= 0.5 else
                 "NO MEASURABLE EFFECT -- the novelty baseline is not doing the work claimed for it."
                 if abs(dn) < 0.5 else
                 "WRONG SIGN: removing the baseline LOWERED novelty, which the design cannot explain."))
    # Keyed on "with_expert", the arm that RESTORES the baseline; the delta's sign is therefore the
    # opposite of the old "no_expert" arm's. This consumer kept the deleted arm name through the
    # rename, so the one verdict the arm exists to produce was never printed.
    if "with_expert" in verdict:
        ds = verdict["with_expert"]["surprising"]
        print(f"expert_baseline -> Surprising: {ds:+.2f} when RESTORED. "
              + ("anchors the axis -- reinstate it in the judge prompt." if abs(ds) >= 0.5 else
                 "NO MEASURABLE EFFECT -- the axis is not anchored by anything the judge sees, "
                 "which is a limitation to report, not grounds to drop the axis."))
    out = Path(a.out) if a.out else run_dir / "ablation.json"
    out.write_text(json.dumps({"run": run_dir.name, "per_category": a.per_category,
                               "arms": a.arms, "means": {k: {ax: statistics.mean(v[ax]) for ax in AXES}
                                                         for k, v in results.items()},
                               "deltas": verdict}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
