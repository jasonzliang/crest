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


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _readme_bytes(run_dir: Path, manifest: dict, writer) -> bytes:
    """Render the run README without writing it, so it can join the all-or-nothing commit.

    _write_run_readme writes directly, which is fine for finalize_run but not here: a repair must not
    leave README.md updated and records.jsonl not, or vice versa."""
    readme = run_dir / "README.md"
    saved = readme.read_bytes() if readme.exists() else None
    try:
        writer(run_dir, manifest)
        return readme.read_bytes()
    finally:
        if saved is not None:
            readme.write_bytes(saved)
        elif readme.exists():
            readme.unlink()


def _decide(before: int, before_ver, now: int, allow_downgrade: bool) -> tuple[str, str]:
    """One place, three outcomes: keep | upgrade | downgrade, with the reason.

    This replaces a three-way decision that was spread across two `if`s, a `_downgraded` sentinel
    stuffed into the live record dict and popped 24 lines later, and an arithmetic expression that
    converted the sentinel back into a counter. That structure produced two bugs in two rounds -- an
    outage silently overwriting good scores and counting them as upgrades, then --allow-downgrade
    becoming a no-op because the write gate read only one of the counters."""
    if now <= before and before_ver == JUDGE_PROMPT_VERSION:
        # Same panel size AND same rubric: nothing to gain, so never rewrite. Version-awareness is
        # what makes the prescribed v1->v2 migration possible at all -- an unconditional
        # `now <= before` discarded every result on a healthy full panel, after paying for it.
        return "keep", f"no gain ({before} -> {now} judges, both {JUDGE_PROMPT_VERSION})"
    if now < before:
        if not allow_downgrade:
            return "keep", (f"REFUSING downgrade ({before} -> {now} judges); a judge is probably "
                            f"capped, which is transient. Re-run when the panel is healthy, or pass "
                            f"--allow-downgrade")
        return "downgrade", f"prompt {before_ver} -> {JUDGE_PROMPT_VERSION}, accepted with --allow-downgrade"
    return "upgrade", f"prompt {before_ver} -> {JUDGE_PROMPT_VERSION}" if now == before else f"{before} -> {now} judges"


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
            action, why = _decide(before, before_ver, scores.n_judges, allow_downgrade)
            if action == "keep":
                print(f"  [{rec['challenge_id']}/{rec['agent']}] keeping original: {why}")
                unchanged += 1
                continue
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
            if action == "downgrade":
                downgraded += 1
            else:
                upgraded += 1
            print(f"  [{rec['challenge_id']}/{rec['agent']}] {action.upper()}: {before} -> "
                  f"{scores.n_judges} judges, N/U/S="
                  f"{scores.new:.0f}/{scores.useful:.0f}/{scores.surprising:.0f} "
                  f"-> {live['scoring_status']} ({why})")

    # BOTH counters. Keying the write gate on `upgraded` alone made --allow-downgrade a no-op in
    # exactly the case it exists for: a uniform vendor outage, where every accepted change is a
    # downgrade. The records were mutated in memory, then discarded, and the caller got
    # {n_upgraded: 0, n_unchanged: 0} for records that had already been re-judged and paid for. The
    # flag worked only when at least one genuine upgrade rode along -- i.e. only when it was not
    # needed. Third generation of this defect: R4's guard blocked the migration outright, R5's
    # version-aware guard let an outage destroy data, R6's refusal discarded it after paying.
    if not (upgraded or downgraded):
        print("\nno records changed; leaving the run untouched")
        return {"n_targets": len(targets), "n_upgraded": 0, "n_downgraded": 0,
                "n_unchanged": unchanged, "n_missing": len(missing)}
    # ---- COMMIT PHASE: compute everything, back up everything, then write everything.
    #
    # Four bugs in this function came from partial mutation, so it is now transactional in the only
    # sense that matters here: nothing is written until every artifact has been computed, and every
    # file about to be overwritten is backed up first.
    #   * only records.jsonl was backed up; summary.json, run_manifest.json and README.md were
    #     overwritten unbacked, destroying the shipped manifest's totals and judge_prompt_version;
    #   * records.jsonl was written BEFORE compute_summary ran, so an exception there (a record
    #     missing `category` is enough) left the canonical file repaired and the derived files stale
    #     -- the state this function's own comment calls "worse than no repair";
    #   * `if not bak.exists()` kept the generation-0 backup on a second repair, so restoring it
    #     silently reverted repair #1 while printing no backup line at all.
    from crest.harness.results import compute_summary, manifest_totals, _write_run_readme

    pending: dict[Path, bytes] = {}
    pending[run_dir / "records.jsonl"] = (
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode())
    pending[run_dir / "summary.json"] = json.dumps(
        compute_summary(records), indent=2, ensure_ascii=False).encode()

    mf = run_dir / "run_manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text())
        # REPLACE, don't merge. manifest_totals derives its keys from the statuses PRESENT in the
        # data, so a status that vanishes after a repair stops emitting a key and .update() would
        # leave the stale count in place. Measured: repairing all degraded+error rows left
        # n_judge_degraded 3 and n_judge_error 2 beside n_scored 12 of n_records 12 -- parts summing
        # to 17 of 12. n_task_errors is carried over because finalize_run counts it from
        # errors.jsonl and it is not derivable from the records.
        m["totals"] = {**manifest_totals(records),
                       "n_task_errors": m.get("totals", {}).get("n_task_errors", 0)}
        # DERIVE the version. Stamping the current one run-wide asserted v2 for a file that could
        # hold {v1: 7, v2: 5}, moving the unlabelled mixture up a level instead of removing it.
        vers = sorted({(r.get("creativity") or {}).get("judge_prompt_version")
                       for r in records if r.get("creativity")}, key=lambda x: (x is None, x))
        m["judge_prompt_version"] = vers[0] if len(vers) == 1 else vers
        if len(vers) > 1:
            print(f"\n  WARNING: this run now holds MORE THAN ONE judge prompt version {vers}. "
                  f"score.py states versions must not be mixed; the mixture tracks which vendor was "
                  f"capped, hence entrant family, so it is not random. Re-judge the whole run under "
                  f"one version before quoting any number from it.")
        m["repaired_at"] = _utc_now_iso()
        m["repair_counts"] = {"upgraded": upgraded, "downgraded": downgraded,
                              "unchanged": unchanged, "un_repairable": len(missing)}
        pending[mf] = json.dumps(m, indent=2, ensure_ascii=False).encode()
        pending[run_dir / "README.md"] = _readme_bytes(run_dir, m, _write_run_readme)

    # Back up EVERY file we are about to replace, into one timestamped directory so repeated repairs
    # do not overwrite each other's backups and each can be undone individually.
    bak_dir = run_dir / f"pre_repair_{_utc_now_iso().replace(':', '').replace('-', '')[:15]}"
    bak_dir.mkdir(exist_ok=True)
    for path in pending:
        if path.exists():
            (bak_dir / path.name).write_bytes(path.read_bytes())
    print(f"  backup: {bak_dir.name}/ ({sum(1 for p in pending if p.exists())} file(s))")

    _atomic_write_jsonl(run_dir / "records.jsonl", records)
    for path, blob in pending.items():
        if path.name != "records.jsonl":
            path.write_bytes(blob)

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
