#!/usr/bin/env python3
"""Re-judge existing records WITHOUT re-paying for generation.

Why this exists: a judge-side outage (a vendor out of credit, or a spend-rate cap tripped by high
concurrency) drops judges from the leave-one-family-out panel. The affected records are flagged
`judge_degraded` (scored by fewer than `min_judges`) or `judge_error` (no judge survived) rather
than being silently averaged in. This tool repairs such records IN PLACE, which is useful when you
want to keep an existing run_id rather than mint a new one -- re-running the agents to fix a *judge*
problem would otherwise re-pay for generation (~$9/task for an OpenAI deep-research entrant).
(For most cases prefer a fresh run: the generation cache now serves prior answers for free, so a new
run re-judges everything cleanly without re-paying. Use this when in-place repair is what you want.)

The agent output is already durably stored: `transcripts.jsonl` holds the full `output_text` and
`citations` keyed by `record_id`. So we can rebuild exactly what the judges saw and re-score for the
cost of the judge calls alone.

Safety properties:
  * never downgrades WITHIN a prompt version -- a re-judged record is written back only if it
    gained judges, UNLESS the judge prompt version changed, in which case the new score is taken
    even at equal or fewer judges (an unconditional guard made the prescribed v1->v2 migration
    impossible: a healthy full panel re-judges to the same 3 judges, so every result was discarded
    after being paid for);
  * records.jsonl is rewritten atomically (temp file + replace), so an interrupted repair cannot
    truncate the run's canonical data;
  * grounding results are preserved as-recorded (the gate is generation-side, not judge-side);
  * refuses to touch a FINALIZED run (run_manifest.json present) unless --force, since a completed
    run is meant to be immutable -- prefer a fresh run_id.

Usage:
    python -m crest.harness.rejudge --run crest/result/runs/<run_id>

  To migrate a run to a NEW JUDGE PROMPT VERSION -- the case score.py prescribes -- the default
  invocation does nothing: it targets only judge_degraded/judge_error rows, and a finalized run is
  refused outright. Both doors were documented and neither worked. The one that works:
    python -m crest.harness.rejudge --run <dir> --status scored --force
    python -m crest.harness.rejudge --run <dir> --status judge_degraded judge_error --concurrency 4
    python -m crest.harness.rejudge --run <dir> --dry-run
"""
from __future__ import annotations
import argparse, dataclasses, json, os, sys, tempfile, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from crest.harness.run_crest import load_challenges, _judges_list   # noqa: E402
from crest.judge.score import JudgePanel, JUDGE_PROMPT_VERSION      # noqa: E402


class StoredReport:
    """Minimal stand-in for AgentOutput, rebuilt from a stored transcript. `JudgePanel.score` only
    reads `.text`; `.citations` is carried so the object is a faithful substitute."""
    __slots__ = ("text", "citations")
    def __init__(self, text: str, citations: list):
        self.text, self.citations = text or "", citations or []


def _load_jsonl(p: Path) -> list:
    return [json.loads(l) for l in p.open() if l.strip()] if p.exists() else []


def _atomic_write_jsonl(path: Path, rows: list) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)                     # atomic on POSIX
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def rejudge(run_dir: Path, panel: JudgePanel, challenges_file: str,
            statuses=("judge_degraded", "judge_error"), concurrency: int = 4,
            dry_run: bool = False, force: bool = False,
            allow_downgrade: bool = False) -> dict:
    run_dir = Path(run_dir)
    if (run_dir / "run_manifest.json").exists() and not force:
        raise SystemExit(f"{run_dir.name} is FINALIZED (run_manifest.json present). A completed run "
                         f"is immutable -- re-run as a new run_id, or pass --force if you really "
                         f"mean to repair it in place.")
    records = _load_jsonl(run_dir / "records.jsonl")
    if not records:
        raise SystemExit(f"no records.jsonl in {run_dir}")
    text_by_id = {t["record_id"]: t for t in _load_jsonl(run_dir / "transcripts.jsonl")}
    ch_by_id = {c.id: c for c in load_challenges(challenges_file)}

    targets = [r for r in records if r.get("scoring_status") in set(statuses)]
    print(f"{run_dir.name}: {len(records)} records, {len(targets)} matching {list(statuses)}")
    if not targets:
        return {"n_targets": 0, "n_upgraded": 0, "n_unchanged": 0, "n_missing": 0}

    missing = [r["record_id"] for r in targets if r["record_id"] not in text_by_id]
    if missing:
        print(f"  WARNING: {len(missing)} target(s) have no stored transcript and cannot be "
              f"re-judged without re-generating: {missing[:3]}{'...' if len(missing) > 3 else ''}")
    todo = [r for r in targets if r["record_id"] in text_by_id]
    if dry_run:
        by = collections.Counter(r["agent"] for r in todo)
        print(f"  [dry-run] would re-judge {len(todo)} record(s): {dict(by)}")
        return {"n_targets": len(targets), "n_upgraded": 0, "n_unchanged": 0, "n_missing": len(missing)}

    def one(rec):
        tr = text_by_id[rec["record_id"]]
        report = StoredReport(tr.get("output_text", ""), tr.get("citations", []))
        ch = ch_by_id.get(rec["challenge_id"])
        if ch is None:
            return rec, None, "challenge_id not in challenges file"
        scores = panel.score(dataclasses.asdict(ch), report,
                             exclude_family=rec.get("model_family"))
        return rec, scores, None

    upgraded = unchanged = downgraded = 0   # three outcomes need three counters: one shared
                                            # counter reported a destructive downgrade as an upgrade
    by_id = {r["record_id"]: r for r in records}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = {ex.submit(one, r): r for r in todo}
        for fut in as_completed(futs):
            rec = futs[fut]
            try:
                rec, scores, err = fut.result()
            except Exception as e:
                print(f"  [{rec['challenge_id']}/{rec['agent']}] re-judge FAILED: "
                      f"{type(e).__name__}: {str(e)[:110]}")
                unchanged += 1
                continue
            if err or scores is None:
                print(f"  [{rec['challenge_id']}/{rec['agent']}] still unscored ({err or 'all judges failed'})")
                unchanged += 1
                continue
            before = (rec.get("creativity") or {}).get("n_judges", 0)
            before_ver = (rec.get("creativity") or {}).get("judge_prompt_version")
            # The never-downgrade guard must be VERSION-AWARE, or it blocks the one migration
            # score.py prescribes. A v1->v2 re-judge of a healthy full-panel record returns the same
            # 3 judges it already had, so `<= before` discarded every result -- AFTER paying for it.
            # Measured on a copy of the shipped run with a stubbed panel: 250 targets, 0 upgraded,
            # 250x "no gain (3 -> 3 judges)", records.jsonl untouched, judge_prompt_version still
            # None on all 250. In a real run that is 750 wasted judge calls and the prescribed
            # remedy for the run's headline caveat simply does not exist.
            if scores.n_judges <= before and before_ver == JUDGE_PROMPT_VERSION:
                print(f"  [{rec['challenge_id']}/{rec['agent']}] no gain "
                      f"({before} -> {scores.n_judges} judges, both {JUDGE_PROMPT_VERSION}); "
                      f"keeping original")
                unchanged += 1
                continue
            if scores.n_judges < before:
                # A judge outage during the prescribed v1->v2 migration would otherwise overwrite
                # good full-panel scores with degraded ones, atomically and with no backup, and count
                # each as "upgraded". Measured: 6/6 records went scored(3) -> judge_degraded(1),
                # manifest n_scored 250 -> 0, summary said "6 upgraded, 0 unchanged". Refuse by
                # default -- a capped vendor is the likeliest cause, and it is transient.
                if not allow_downgrade:
                    print(f"  [{rec['challenge_id']}/{rec['agent']}] REFUSING downgrade "
                          f"({before} -> {scores.n_judges} judges); a judge is probably capped. "
                          f"Re-run when the panel is healthy, or pass --allow-downgrade.")
                    unchanged += 1
                    continue
                print(f"  [{rec['challenge_id']}/{rec['agent']}] DOWNGRADE accepted "
                      f"({before} -> {scores.n_judges} judges) for prompt {before_ver} -> "
                      f"{JUDGE_PROMPT_VERSION}")
                downgraded += 1
                by_id[rec["record_id"]]["_downgraded"] = True
            live = by_id[rec["record_id"]]
            live["creativity"] = {
                "new": scores.new, "useful": scores.useful, "surprising": scores.surprising,
                "creative_all_three": scores.creative_all_three,
                "n_judges": scores.n_judges,
                "judge_protocol": panel.protocol,
                # run_crest stamps this; rejudge is the OTHER writer and omitted it, so repairing
                # the shipped v1 run produced exactly the v1/v2 mixture score.py says must never
                # happen -- unlabelled, on a non-random subset.
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                # signature drift: _judges_list gained (panel, entrant_family) so it can stamp
                # same_family. Calling it without them wrote same_family=False on every repaired row,
                # silently zeroing the self-preference covariate the whole LOFO->covariate design
                # rests on -- and only on the repaired subset, which is not random.
                "judges": _judges_list(scores.per_judge, panel, rec.get("model_family")),
            }
            live["scoring_status"] = ("scored" if scores.n_judges >= panel.min_judges
                                     else "judge_degraded")
            live["rejudged"] = True                  # provenance: this row was repaired, not fresh
            print(f"  [{rec['challenge_id']}/{rec['agent']}] {before} -> {scores.n_judges} judges, "
                  f"N/U/S={scores.new:.0f}/{scores.useful:.0f}/{scores.surprising:.0f} "
                  f"-> {live['scoring_status']}")
            upgraded += 0 if by_id[rec['record_id']].pop('_downgraded', False) else 1

    if not upgraded:
        print("\nno records upgraded; leaving the run untouched")
        return {"n_targets": len(targets), "n_upgraded": 0,
                "n_unchanged": unchanged, "n_missing": len(missing)}
    # Back up before an in-place overwrite. The write is atomic, so it cannot truncate -- but atomic
    # replacement of good data with bad data is still data loss, and this tool is invoked with --force
    # on runs whose numbers ship.
    bak = run_dir / "records.jsonl.bak"
    if not bak.exists():
        bak.write_bytes((run_dir / "records.jsonl").read_bytes())
        print(f"  backup: {bak.name}")
    _atomic_write_jsonl(run_dir / "records.jsonl", records)
    # keep the derived artifacts consistent: a repair that leaves summary.json reporting the OLD
    # means and the manifest the OLD n_judge_degraded is worse than no repair
    from crest.harness.results import compute_summary, manifest_totals
    (run_dir / "summary.json").write_text(json.dumps(compute_summary(records), indent=2,
                                                     ensure_ascii=False))
    mf = run_dir / "run_manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text())
        # REPLACE, don't merge. manifest_totals now derives its keys from the statuses present in
        # the data, so a status that vanishes after a repair stops emitting a key -- and .update()
        # then leaves the stale count in place. Measured: repairing all degraded+error rows left
        # n_judge_degraded 3 and n_judge_error 2 beside n_scored 12 of n_records 12, parts summing
        # to 17 of 12. n_task_errors is carried over because it is counted from errors.jsonl by
        # finalize_run, not derivable from the records.
        prev = m.get("totals", {})
        m["totals"] = {**manifest_totals(records),
                       "n_task_errors": prev.get("n_task_errors", 0)}
        # DERIVE it. Stamping the current version run-wide asserted v2 for a file that could hold
        # {v1: 7, v2: 5} -- moving the unlabelled mixture up a level instead of removing it.
        vers = sorted({(r.get("creativity") or {}).get("judge_prompt_version")
                       for r in records if r.get("creativity")}, key=lambda x: (x is None, x))
        m["judge_prompt_version"] = vers[0] if len(vers) == 1 else vers
        m["repaired_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat()
        mf.write_text(json.dumps(m, indent=2, ensure_ascii=False))
        # README.md is the THIRD derived artifact and was the one left stale: it embeds the record
        # count and a literal `Totals:` line, and it is the file a human opens first. Leaving it
        # describing the pre-repair run is exactly what the comment above calls "worse than no
        # repair".
        from crest.harness.results import _write_run_readme
        _write_run_readme(run_dir, m)
    print(f"\nrewrote {run_dir/'records.jsonl'}: {upgraded} upgraded, {downgraded} DOWNGRADED, "
          f"{unchanged} unchanged, {len(missing)} un-repairable")
    print("status now: " + str(dict(collections.Counter(r.get("scoring_status") for r in records))))
    return {"n_targets": len(targets), "n_upgraded": upgraded, "n_downgraded": downgraded,
            "n_unchanged": unchanged, "n_missing": len(missing)}


def main():
    ap = argparse.ArgumentParser(description="Re-judge degraded/unscored records from stored transcripts.")
    ap.add_argument("--run", required=True, help="run directory (crest/result/runs/<run_id>)")
    ap.add_argument("--judge-config", default="crest/judge/judge_config.live.yaml")
    ap.add_argument("--challenges", default="crest/questions/crest_challenges.jsonl")
    ap.add_argument("--status", nargs="+", default=["judge_degraded", "judge_error"],
                    help="scoring_status values to repair")
    ap.add_argument("--concurrency", type=int, default=4,
                    help="records re-judged in parallel (judges within each also run in parallel); "
                         "keep modest so a provider spend-rate cap is not re-tripped")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="allow repairing a FINALIZED run in place")
    ap.add_argument("--allow-downgrade", action="store_true",
                    help="accept a re-judge that returns FEWER judges (default: refuse -- a capped "
                         "vendor would otherwise overwrite good full-panel scores)")
    a = ap.parse_args()
    _p = lambda s: Path(s) if Path(s).is_absolute() else REPO / s
    panel = JudgePanel.from_config(str(_p(a.judge_config)))
    print(f"judges: {[(j['id'], j['model']) for j in panel.judges]} (min_judges={panel.min_judges})")
    rejudge(_p(a.run), panel, str(_p(a.challenges)), tuple(a.status),
            a.concurrency, a.dry_run, a.force, a.allow_downgrade)


if __name__ == "__main__":
    main()
