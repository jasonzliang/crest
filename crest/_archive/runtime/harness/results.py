"""Result recording for CREST runs — immutable, self-describing per-run directories.

Format (from the two result-format research audits; see result/readme.md):

    result/
      readme.md                    how to read results; canonical vs latest
      index.jsonl                  append-only registry, one line per run (discovery)
      latest -> runs/<run_id>      symlink to the newest run (convenience, NOT canonical)
      leaderboard.json             promoted canonical numbers cited in the paper (hand-promoted)
      runs/<run_id>/
        records.jsonl              analysis-grade, one line per (challenge, agent); no heavy text
        transcripts.jsonl          heavy: full agent output text + citations, keyed by record_id
        run_manifest.json          provenance: git, config, pinned models, mode+contamination caveat
        config.snapshot.<ext>      literal copy of the config as-run
        summary.json               aggregates per agent x category (+ grounding/creative rates)

Design rules the audits stressed: JSONL canonical (crash-safe, append-only, pandas-native);
split heavy text out of the analysis rows; store judge sub-scores as a list-of-objects (LOFO-safe
and ready for a rater random effect); a run is immutable — a re-run is a NEW run_id, never a
mutation; record the live-web contamination caveat + effective corpus date as first-class fields.
"""
from __future__ import annotations
import json, re, subprocess, sys, platform, collections, statistics, secrets
from datetime import datetime, timezone
from pathlib import Path

# 1.1.0: adapter_fp/truncated/answer_chars/answer_words were added to every record while the version
# stayed 1.0.0 -- one version string denoting two shapes, and the shipped run has 0/250 of them.
# 1.2.0: the BILLING surface -- tokens{}, billed_tools{}, n_calls, calls[], usage_raw[]. Cost per
# question was previously unanswerable: each adapter read only output_tokens off a usage object that
# already carried input tokens, cache counters and billed tool counts. Input dominates for a
# research agent, so the single field kept was the one that could not answer the question. Bumped
# rather than added silently, which is the 1.0.0->1.1.0 mistake recorded above.
RECORD_SCHEMA_VERSION = "crest-record/1.2.0"


def _utc_now():
    return datetime.now(timezone.utc)

def _git(args, cwd) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""

_GIT_CACHE: dict = {}


def git_info(repo_root) -> dict:
    """Read git ONCE per process. new_run stamps the commit into the run_id and make_manifest read it
    again ~45 minutes later, after HEAD had moved: the shipped run dir says `gitb0cdbe7` while its own
    manifest says `754d005` (a commit that touched judge/score.py and did not exist when generation
    started), so one run's two provenance records disagreed about which code produced it. Caching
    makes them agree by construction, without threading the value through four call sites."""
    k = str(repo_root)
    if k not in _GIT_CACHE:
        sha = _git(["rev-parse", "--short", "HEAD"], repo_root)
        dirty = bool(_git(["status", "--porcelain"], repo_root))
        _GIT_CACHE[k] = {"git_commit": sha, "git_dirty": dirty}
    return dict(_GIT_CACHE[k])

def pkg_versions() -> dict:
    import importlib.metadata as m
    out = {}
    for p in ("anthropic", "openai", "google-genai", "statsmodels", "pandas", "numpy"):
        try: out[p] = m.version(p)
        except Exception: out[p] = None
    return out


def new_run(result_root, subset: str, repo_root, benchmark: str = "crest") -> tuple[str, Path]:
    """Create result/runs/<run_id>/ and return (run_id, run_dir). run_id is sortable + provenance-encoding.

    `benchmark` was HARDCODED to "crest", which made the run_id actively misleading once a second
    item set existed: runs over crest_aiml_challenges.jsonl (50 AI/ML items) and over
    crest_challenges.jsonl (50 science items) produced directory names identical apart from the
    timestamp and commit, so the only way to tell which 50 items a run covered was to open its
    config.snapshot.yaml. It now comes from the config's benchmark name.

    Sanitised because the run_id is parsed on delimiters and used as a path component: `__` is the
    field separator (promote_leaderboard splits on "__git"), and a slash would silently create a
    nested directory. Single underscores are KEPT, so `crest_aiml` stays legible; only runs of two
    or more are collapsed, and anything outside [A-Za-z0-9._-] becomes '-'.
    """
    ts = _utc_now().strftime("%Y-%m-%dT%H%M%SZ")
    sha = git_info(repo_root)["git_commit"] or "nogit"
    nonce = secrets.token_hex(3)   # real entropy: distinct even for same-second, same-subset runs
    bench = re.sub(r"[^A-Za-z0-9._-]+", "-", str(benchmark or "crest"))
    bench = re.sub(r"_{2,}", "_", bench).strip("-_") or "crest"   # never emit the `__` separator
    run_id = f"{ts}__{bench}__{subset}__git{sha}__{nonce}"
    run_dir = Path(result_root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)   # fail loudly on the (now vanishingly rare) collision
    return run_id, run_dir


def is_scored(r: dict) -> bool:
    """THE definition of a scored record. Three competing ones used to coexist (this status check,
    `r.get("creativity")` in finalize_run's totals, `creativity.notna()` in stats.py) and they
    disagreed: repairing one judge_degraded row via rejudge made the manifest's n_scored DROP from
    100 to 91, because finalize_run counted degraded rows as scored and rejudge did not. BOTH
    conditions are required: the status is authoritative, and the dict must actually be there
    (rejudge and hand-imported records can desync the two)."""
    return r.get("scoring_status") == "scored" and bool(r.get("creativity"))


def manifest_totals(records: list) -> dict:
    """The manifest `totals` block. Shared so a repair recomputes ALL of it -- rejudge used to
    refresh three keys and leave n_grounding_fail / n_empty_answer / n_truncated / n_judge_error
    stale, the same 'derived artifacts left inconsistent' defect rejudge exists to fix. Counting is
    driven by the statuses PRESENT in the data, not a hand-listed set of keys: the hand-listed
    version silently counted `too_short` nowhere when that status was added."""
    counts = collections.Counter(r.get("scoring_status") or "unset" for r in records)
    out = {"n_records": len(records), "n_scored": sum(1 for r in records if is_scored(r)),
           "n_truncated": sum(1 for r in records if r.get("truncated"))}
    for status, n in sorted(counts.items()):
        if status != "scored":            # n_scored is the stricter is_scored() count, set above
            out[f"n_{status}"] = n
    return out


def compute_summary(records: list) -> dict:
    """Cheap aggregates for a leaderboard (per agent, and per agent x category). Inferential stats
    (mixed-effects, TOST, Krippendorff alpha / ICC) are left to crest.analysis.stats on records.jsonl."""
    def agg(rows):
        # ONLY status=="scored". A judge_degraded row carries a creativity dict, so the old
        # `if r.get("creativity")` swept it into the headline means while the console printed
        # "excluded from headline numbers" for that very record -- and summary.json is what gets
        # promoted to leaderboard.json, so the contradiction shipped downstream.
        scored = [r for r in rows if is_scored(r)]
        degraded = [r for r in rows if r.get("scoring_status") == "judge_degraded"]
        n = len(rows)
        gpass = sum(1 for r in rows if r.get("grounding", {}).get("passed"))
        out = {"n": n, "n_scored": len(scored), "n_degraded": len(degraded),
               "grounding_pass_rate": round(gpass / n, 3) if n else None}
        if scored:
            for ax in ("new", "useful", "surprising"):
                out[f"mean_{ax}"] = round(statistics.mean(r["creativity"][ax] for r in scored), 2)
            out["creative_rate"] = round(sum(1 for r in scored if r["creativity"]["creative_all_three"]) / len(scored), 3)
        return out
    by_agent = collections.defaultdict(list)
    by_agent_cat = collections.defaultdict(list)
    for r in records:
        by_agent[r["agent"]].append(r)
        by_agent_cat[(r["agent"], r["category"])].append(r)
    return {
        "per_agent": {a: agg(rs) for a, rs in sorted(by_agent.items())},
        "per_agent_category": {f"{a}|{c}": agg(rs) for (a, c), rs in sorted(by_agent_cat.items())},
    }


def _write_run_readme(run_dir: Path, manifest: dict) -> None:
    """Drop a README into every run dir. The two main files are named misleadingly for historical
    reasons -- `records.jsonl` is the JUDGE output and `transcripts.jsonl` is the AGENT output -- so
    a reader opening a released run cannot tell which is which without reading the harness."""
    t = manifest.get("totals", {})
    agents = ", ".join(a.get("key", "?") for a in manifest.get("agents", []))
    judges = ", ".join(j.get("id", "?") for j in manifest.get("judges", []))
    (run_dir / "README.md").write_text(f"""# Run `{manifest.get('run_id', run_dir.name)}`

{manifest.get('created_at', '')} · {t.get('n_records', '?')} records · agents: {agents}
judges: {judges} · protocol: {manifest.get('judge_protocol', '?')}

## Which file is which

| file | produced by | contains |
|---|---|---|
| `transcripts.jsonl` | **the AGENTS** | what each agent actually wrote: `output_text` + `citations` |
| `records.jsonl` | **the JUDGES** | the scores: per-axis New/Useful/Surprising, per-judge rows, grounding verdict, `scoring_status` |
| `errors.jsonl` | the harness | tasks that produced no record at all |
| `summary.json` | the harness | per-agent and per-agent-x-category aggregates |
| `run_manifest.json` | the harness | provenance; written last, so it marks completion |

The names are historical: "records" is the judge output and "transcripts" is the agent output, which
is the reverse of what most readers assume. **Join them on `record_id`.**

```python
import json
scores = {{r["record_id"]: r for r in map(json.loads, open("records.jsonl", encoding="utf-8"))}}
answers = {{t["record_id"]: t for t in map(json.loads, open("transcripts.jsonl", encoding="utf-8"))}}
rid = next(iter(scores))
print(scores[rid]["agent"], scores[rid]["creativity"]["new"], answers[rid]["output_text"][:200])
```

## Reading the scores
`creativity` is null on every UNSCORED path -- but **`judge_degraded` is the exception**: it carries
a full `creativity` dict scored by too few judges. Filter on `scoring_status == "scored"`, NOT on
`creativity is not None`, or degraded rows land in your headline means. Other statuses: `judge_degraded` (fewer
judges than `min_judges` survived), `empty_answer` (the agent returned literally nothing -- an
ADAPTER failure, not a grounding failure), `too_short` (non-empty but under the substantive-length
floor; same adapter root cause, but the threshold is a judgement call and the emptiness is not),
`grounding_fail`, `judge_error`. Per-axis values are the MEDIAN across the
judges in `creativity.judges`; each judge row carries `same_family`, so the leave-one-family-out
subset is recoverable by filtering those rows out.

Totals: {json.dumps(t)}
""", encoding="utf-8")   # the template contains a literal U+00B7; an ASCII locale would
    # otherwise crash HERE, as the last statement of finalize_run, after the whole run is paid for.


def finalize_run(result_root, run_dir: Path, run_id: str, records: list, manifest: dict) -> None:
    """Write summary.json + run_manifest.json (last, as the completion marker), append index.jsonl,
    and repoint the `latest` symlink. Manifest is written last so a crashed run can't look complete."""
    result_root = Path(result_root)
    summary = compute_summary(records)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    errf = run_dir / "errors.jsonl"
    # DISTINCT failing tasks, not raw rows. A task that fails in the main pass and fails AGAIN in the
    # auto-sweep writes two rows for one task, and a task that fails then RECOVERS leaves its main-pass
    # row in place on purpose (run_crest keeps it as the evidence the retry was needed). Counting lines
    # made run 2026-08-01T015432Z report n_records=249 + n_task_errors=2 -- parts summing to 251 of
    # 250 -- for a single failing task, and would report a lost task on a run that lost none.
    n_task_errors = 0
    if errf.exists():
        failed, recovered = set(), {r["record_id"] for r in records if r.get("record_id")}
        for line in open(errf, encoding="utf-8"):
            if line.strip():
                try:
                    failed.add(json.loads(line).get("record_id"))
                except json.JSONDecodeError:
                    n_task_errors += 1          # unparseable row: count it rather than lose it
        n_task_errors += len(failed - recovered - {None})
    manifest = {**manifest,
                "completed_at": _utc_now().isoformat(),
                "status": "completed" if records else "failed",   # empty run is a FAILED run, not a clean one
                "record_schema_version": RECORD_SCHEMA_VERSION,
                "totals": {**manifest_totals(records), "n_task_errors": n_task_errors},
                "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                                "packages": pkg_versions()},
                # describe each output by WHO PRODUCED IT: the bare filenames are historical and
                # opaque -- "records" is the judge scores and "transcripts" the agent answers, the
                # opposite of what most readers assume.
                "outputs": {
                    "records.jsonl": "JUDGE EVALUATIONS + metadata, one line per (challenge, agent). "
                                     "Analysis-grade: per-axis scores, per-judge breakdown with "
                                     "same_family, grounding verdict, scoring_status. No answer text.",
                    "transcripts.jsonl": "AGENT ANSWERS, one line per (challenge, agent), joined to "
                                         "records.jsonl on record_id. The full output_text the agent "
                                         "produced plus its citations. This is the heavy file.",
                    "errors.jsonl": "tasks that produced NO record: agent exceptions and "
                                    "circuit-open skips. A short run is explained here.",
                    "summary.json": "aggregates per agent and per agent x category.",
                    "run_manifest.json": "provenance: git commit, pinned models, judge protocol, "
                                         "totals, environment. Written LAST, so its presence marks "
                                         "a completed run.",
                    "config.snapshot.yaml": "the config exactly as run.",
                    "README.md": "what each file holds and how to join them."}}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_run_readme(run_dir, manifest)
    # discovery registry
    top = manifest.get("agents", [])
    with (result_root / "index.jsonl").open("a", encoding="utf-8") as fo:
        fo.write(json.dumps({"run_id": run_id, "created_at": manifest.get("created_at"),
                             "benchmark": manifest.get("benchmark", {}).get("name"),
                             "subset": manifest.get("benchmark", {}).get("subset"),
                             "mode": manifest.get("execution_mode", {}).get("retrieval_mode"),
                             "n_records": len(records), "canonical": False,
                             "summary": f"runs/{run_id}/summary.json"}, ensure_ascii=False) + "\n")
    # latest symlink (only mutable pointer in the tree) -- don't repoint at an all-failed/empty run
    if records:
        latest = result_root / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(Path("runs") / run_id)
        except OSError:
            pass
