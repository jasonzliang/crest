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
import json, subprocess, sys, platform, collections, statistics
from datetime import datetime, timezone
from pathlib import Path

RECORD_SCHEMA_VERSION = "crest-record/1.0.0"


def _utc_now():
    return datetime.now(timezone.utc)

def _git(args, cwd) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""

def git_info(repo_root) -> dict:
    sha = _git(["rev-parse", "--short", "HEAD"], repo_root)
    dirty = bool(_git(["status", "--porcelain"], repo_root))
    return {"git_commit": sha, "git_dirty": dirty}

def pkg_versions() -> dict:
    import importlib.metadata as m
    out = {}
    for p in ("anthropic", "openai", "google-genai", "statsmodels", "pandas", "numpy"):
        try: out[p] = m.version(p)
        except Exception: out[p] = None
    return out


def new_run(result_root, subset: str, repo_root) -> tuple[str, Path]:
    """Create result/runs/<run_id>/ and return (run_id, run_dir). run_id is sortable + provenance-encoding."""
    ts = _utc_now().strftime("%Y-%m-%dT%H%M%SZ")
    sha = git_info(repo_root)["git_commit"] or "nogit"
    nonce = f"{abs(hash((ts, subset))) % 100000:05d}"
    run_id = f"{ts}__crest__{subset}__git{sha}__{nonce}"
    run_dir = Path(result_root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def compute_summary(records: list) -> dict:
    """Cheap aggregates for a leaderboard (per agent, and per agent x category). Inferential stats
    (mixed-effects, TOST, Krippendorff alpha / ICC) are left to crest.analysis.stats on records.jsonl."""
    def agg(rows):
        scored = [r for r in rows if r.get("creativity")]
        n = len(rows)
        gpass = sum(1 for r in rows if r.get("grounding", {}).get("passed"))
        out = {"n": n, "n_scored": len(scored),
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


def finalize_run(result_root, run_dir: Path, run_id: str, records: list, manifest: dict) -> None:
    """Write summary.json + run_manifest.json (last, as the completion marker), append index.jsonl,
    and repoint the `latest` symlink. Manifest is written last so a crashed run can't look complete."""
    result_root = Path(result_root)
    summary = compute_summary(records)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    manifest = {**manifest,
                "completed_at": _utc_now().isoformat(),
                "record_schema_version": RECORD_SCHEMA_VERSION,
                "totals": {"n_records": len(records),
                           "n_scored": sum(1 for r in records if r.get("creativity")),
                           "n_grounding_fail": sum(1 for r in records if not r.get("grounding", {}).get("passed"))},
                "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                                "packages": pkg_versions()},
                "outputs": {"records": "records.jsonl", "transcripts": "transcripts.jsonl", "summary": "summary.json"}}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    # discovery registry
    top = manifest.get("agents", [])
    with (result_root / "index.jsonl").open("a") as fo:
        fo.write(json.dumps({"run_id": run_id, "created_at": manifest.get("created_at"),
                             "benchmark": manifest.get("benchmark", {}).get("name"),
                             "subset": manifest.get("benchmark", {}).get("subset"),
                             "mode": manifest.get("execution_mode", {}).get("retrieval_mode"),
                             "n_records": len(records), "canonical": False,
                             "summary": f"runs/{run_id}/summary.json"}, ensure_ascii=False) + "\n")
    # latest symlink (only mutable pointer in the tree)
    latest = result_root / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(Path("runs") / run_id)
    except OSError:
        pass
