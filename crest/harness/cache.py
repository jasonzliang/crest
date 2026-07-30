"""Cross-run generation cache: never pay twice for the same agent answer.

The problem this closes. `--resume` only reuses work from an INTERRUPTED run (records.jsonl present,
run_manifest.json absent) and only within that one run directory. So the moment a run FINALIZES its
generations become dead weight: re-running the same benchmark re-paid for all of them -- 250 tasks
including deep-research entrants at ~$6-9 each. Judge-only changes (a new panel, a fixed rubric, a
re-scored axis) forced a full re-generation.

This cache indexes the agent outputs already stored in EVERY run under `<result_root>/runs/` and
serves them by content-addressed key, so generation is paid once per distinct
(challenge text, agent, model) and everything downstream is free to re-run.

Correctness is the whole point, so the key includes a hash of the QUERY TEXT, not just the
challenge id. Editing a challenge's wording (as happened when 12 items were rewritten to remove
references to judge-side fields the agent never receives) must invalidate its cached answers --
otherwise you would silently score answers generated against a prompt that no longer exists.
Records written before `query_sha` existed are therefore ignored rather than trusted.

Also skipped: empty-text outputs (far more likely a parser bug than a real answer, and caching one
would make the bug permanent).

Enabled by default; disable with `use_cache: false` in the config or `--override-cache` on the CLI.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

CACHE_KEY_VERSION = "gen/1"


def query_sha(query: str) -> str:
    """Stable short hash of the exact agent-visible prompt text."""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:16]


def cache_key(challenge_id: str, agent_key: str, model: str, q_sha: str) -> str:
    return f"{CACHE_KEY_VERSION}|{challenge_id}|{agent_key}|{model}|{q_sha}"


class CachedOutput:
    """Reconstructed agent output. Mirrors AgentOutput's read surface."""
    __slots__ = ("text", "citations", "n_tokens", "n_searches", "trace", "source_run")
    def __init__(self, text, citations, n_tokens, n_searches, source_run):
        self.text, self.citations = text, citations
        self.n_tokens, self.n_searches = n_tokens, n_searches
        self.trace, self.source_run = {}, source_run


class GenerationCache:
    """Read-only index over all prior runs' stored generations."""

    def __init__(self, result_root, enabled: bool = True, verbose: bool = True):
        self.enabled = enabled
        self._idx: dict[str, dict] = {}
        self.n_runs = 0
        if enabled:
            self._build(Path(result_root), verbose)

    def _build(self, result_root: Path, verbose: bool) -> None:
        runs = result_root / "runs"
        if not runs.exists():
            return
        skipped_no_sha = 0
        for run_dir in sorted(d for d in runs.iterdir() if d.is_dir()):
            recs_f, tr_f = run_dir / "records.jsonl", run_dir / "transcripts.jsonl"
            if not (recs_f.exists() and tr_f.exists()):
                continue
            try:
                texts = {t["record_id"]: t for t in
                         (json.loads(l) for l in tr_f.open() if l.strip())}
                recs = [json.loads(l) for l in recs_f.open() if l.strip()]
            except Exception:
                continue                       # a half-written run must never break a new one
            self.n_runs += 1
            for r in recs:
                qs = r.get("query_sha")
                if not qs:                     # pre-dates content addressing -> cannot verify
                    skipped_no_sha += 1
                    continue
                tr = texts.get(r.get("record_id"))
                if not tr or not (tr.get("output_text") or "").strip():
                    continue                   # no/empty generation: regenerate rather than cache it
                k = cache_key(r["challenge_id"], r["agent"], r.get("model", ""), qs)
                self._idx.setdefault(k, {                     # first run wins (oldest generation)
                    "text": tr["output_text"], "citations": tr.get("citations") or [],
                    "n_tokens": r.get("output_len_tokens", 0) or 0,
                    "n_searches": r.get("n_searches", 0) or 0,
                    "source_run": r.get("run_id") or run_dir.name,
                })
        if verbose:
            msg = f"generation cache: {len(self._idx)} entries from {self.n_runs} prior run(s)"
            if skipped_no_sha:
                msg += f"; {skipped_no_sha} record(s) skipped (no query_sha -- pre-dates cache)"
            print(msg)

    def get(self, challenge_id: str, agent_key: str, model: str, q_sha: str):
        if not self.enabled:
            return None
        hit = self._idx.get(cache_key(challenge_id, agent_key, model, q_sha))
        if hit is None:
            return None
        return CachedOutput(hit["text"], hit["citations"], hit["n_tokens"],
                            hit["n_searches"], hit["source_run"])

    def __len__(self) -> int:
        return len(self._idx)


def backfill_query_sha(run_dir, challenges_file) -> int:
    """Add `query_sha` to records written before content addressing existed.

    Only safe when you know those records were generated against the CURRENT challenge text -- it
    asserts nothing and simply stamps the present query hash, so running it on a run that used older
    wording would make stale answers look valid. Returns the number of records stamped."""
    from crest.harness.run_crest import load_challenges
    run_dir = Path(run_dir)
    q = {c.id: query_sha(c.query) for c in load_challenges(str(challenges_file))}
    f = run_dir / "records.jsonl"
    rows = [json.loads(l) for l in f.open() if l.strip()]
    n = 0
    for r in rows:
        if not r.get("query_sha") and r["challenge_id"] in q:
            r["query_sha"] = q[r["challenge_id"]]; n += 1
    if n:
        tmp = f.with_suffix(".jsonl.tmp")
        with tmp.open("w") as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.replace(f)
    return n
