#!/usr/bin/env python3
"""Promote one run's numbers into the tracked `result/leaderboard.json`.

WHY THIS EXISTS. Until this script, the repository contained no copy of its own results. Every
headline figure -- the per-agent primary endpoint, the per-axis means, the per-category cells -- lived
only in `result/runs/<run_id>/summary.json`, and `result/runs/` is gitignored (deliberately: the run
dir is ~7 MB). So git held no record of what CREST measured, while the paper's results section carried
`[PLACEHOLDER]` where those numbers belong. A repo-wide scan found the shipped numbers matched no
tracked file at all.

`summary.json` is NOT a substitute for this file, for three reasons:
  * it carries per-axis MEANS but not the primary endpoint, min(New, Useful, Surprising) -- the
    quantity every claim rests on is absent from it;
  * it carries no provenance, so a number cannot be tied to the code, judge panel or prompt version
    that produced it;
  * it carries no caveats, so a reader has no way to know that the ordering is not identifiable, or
    that the New/Surprising correlation is contaminated by the v1 judge prompt.

WHAT THIS IS NOT. It is not a claim that the leaderboard ordering is real. The `caveats` block states
plainly that judge severity exceeds the between-agent spread, so the ranking is not identifiable from
this run. The file exists so the numbers are citable and auditable, not so they are authoritative.

Usage:
    python -m crest.analysis.promote_leaderboard --run crest/result/runs/<run_id>
    python -m crest.analysis.promote_leaderboard --run <dir> --dry-run
"""
from __future__ import annotations
import argparse, collections, json, statistics, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from crest.harness.results import is_scored          # noqa: E402  ONE definition of "scored"

AXES = ("new", "useful", "surprising")


def _composite(c: dict) -> float:
    """The primary endpoint for one record: min over all three axes."""
    return min(c[a] for a in AXES)


def build(run_dir: Path) -> dict:
    recs = [json.loads(l) for l in (run_dir / "records.jsonl").open(encoding="utf-8") if l.strip()]
    mf = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary_path = run_dir / "summary.json"
    summ = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    scored = [r for r in recs if is_scored(r)]
    by_agent: dict = collections.defaultdict(list)
    by_ac: dict = collections.defaultdict(list)
    for r in scored:
        by_agent[r["agent"]].append(r)
        by_ac[(r["agent"], r["category"])].append(r)

    # A run scored under a DIFFERENT judge prompt is not comparable with one scored under the current
    # prompt. Record the run's own stamp and say so, rather than letting a reader assume.
    stamps = sorted({(r.get("creativity") or {}).get("judge_prompt_version")
                     for r in scored}, key=lambda x: (x is None, x))

    # Derive the provenance warnings rather than hand-writing them, so a regeneration cannot drop
    # them. Both are real defects in THIS run that a reader must not have to rediscover.
    notes = {}
    run_sha = (mf.get("run_id") or "").split("__git")[-1].split("__")[0] or None
    code_sha = mf.get("code", {}).get("git_commit")
    if run_sha and code_sha and not code_sha.startswith(run_sha) and not run_sha.startswith(code_sha):
        notes["git_commit_mismatch"] = (
            f"run_id encodes {run_sha} (git read at run START) but code.git_commit is {code_sha} "
            f"(read again at finalize, ~45min later). HEAD moved mid-run, so this run has TWO "
            f"provenance values and they disagree. git_info is cached per process now; this run "
            f"predates that fix.")
    if stamps == [None]:
        notes["judge_prompt_version_absent"] = (
            "All scored records store judge_prompt_version=null: this run predates the stamp. The "
            "current prompt is a later version whose rubric differs in ways that move scores, so "
            "these numbers are NOT comparable to any run scored under it, and ablate_fields will "
            "refuse to ablate against them.")
    elif len(stamps) > 1:
        notes["judge_prompt_version_mixed"] = (
            f"Records carry MORE THAN ONE prompt version {stamps}. score.py states versions must not "
            f"be mixed; the mixture is not random (it tracks which vendor was capped, hence entrant "
            f"family). Do not quote any aggregate from this run.")

    return {
        "_README": (
            "Promoted, tracked copy of the run whose numbers are cited. Regenerate with "
            "`python -m crest.analysis.promote_leaderboard --run <run_dir>`. summary.json is NOT a "
            "substitute: it lacks the primary endpoint, the provenance and the caveats."),
        "provenance": {
            "run_id": mf.get("run_id"),
            "created_at": mf.get("created_at"),
            "code_git_commit": mf.get("code", {}).get("git_commit"),
            "judge_protocol": mf.get("judge_protocol"),
            "judge_prompt_version_per_record": stamps if len(stamps) != 1 else stamps[0],
            "judges": mf.get("judges"),
            "record_schema_version": mf.get("record_schema_version"),
            "n_records": len(recs),
            "n_scored": len(scored),
            "totals": mf.get("totals"),
            **({"warnings": notes} if notes else {}),
        },
        "primary_endpoint": {
            "definition": "min(New, Useful, Surprising), graded on the 1-10 scale",
            "per_agent": {a: {"mean": round(statistics.mean(_composite(r["creativity"]) for r in rs), 3),
                              "n": len(rs)}
                          for a, rs in sorted(by_agent.items())},
        },
        "per_axis_means": {a: d for a, d in sorted(summ.get("per_agent", {}).items())},
        "per_agent_category_primary": {
            f"{a}|{c}": round(statistics.mean(_composite(r["creativity"]) for r in rs), 3)
            for (a, c), rs in sorted(by_ac.items())},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, help="a finalized run dir under result/runs/")
    # NO clobbering default. This defaulted to crest/result/leaderboard.json -- the SCIENCE run's
    # numbers, cited by four .tex files across both papers -- so promoting any other run without
    # remembering a flag silently overwrote the paper's results. That happened on 2026-07-31 and had
    # to be restored from git. The path is now DERIVED from the run's own manifest benchmark name, so
    # it structurally cannot pick the wrong file; --out still overrides.
    ap.add_argument("--out", default=None,
                    help="output path; default is derived from the run's benchmark name")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run_dir = Path(a.run) if Path(a.run).is_absolute() else REPO / a.run
    if a.out:
        out = Path(a.out) if Path(a.out).is_absolute() else REPO / a.out
    else:
        # DERIVED from the run's own manifest, so promoting run X can only ever write X's file.
        import json as _j
        _mf = _j.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        _bench = ((_mf.get("benchmark") or {}).get("name") or "crest")
        out = REPO / "crest/result" / ("leaderboard.json" if _bench == "crest"
                                       else f"leaderboard.{_bench}.json")
        print(f"  --out derived from benchmark '{_bench}': {out.relative_to(REPO)}")

    lb = build(run_dir)
    # Preserve the hand-written caveats across regeneration. They are editorial judgements about what
    # the numbers do and do not support, and they must NOT be silently dropped by a re-run -- that
    # would turn "the ordering is not identifiable" into an unqualified leaderboard.
    if out.exists():
        prev = json.loads(out.read_text(encoding="utf-8"))
        if prev.get("caveats"):
            lb["caveats"] = prev["caveats"]
            print(f"  carried over {len(prev['caveats'])} caveat(s) from the existing file")
    if "caveats" not in lb:
        lb["caveats"] = ["TODO: no caveats recorded. State at minimum whether the ordering is "
                         "identifiable given the measured judge-severity spread."]
        print("  WARNING: no caveats found to carry over; wrote a TODO placeholder")

    for agent, d in lb["primary_endpoint"]["per_agent"].items():
        print(f"  {agent:26} {d['mean']:.3f}  (n={d['n']})")
    if a.dry_run:
        print("\n[dry-run] nothing written")
        return
    out.write_text(json.dumps(lb, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
