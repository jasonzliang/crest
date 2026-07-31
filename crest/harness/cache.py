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

CACHE_KEY_VERSION = "gen/2"   # bumped: gen/1 keys omitted the adapter fingerprint (see below)


def adapter_fingerprint(agent) -> str:
    """Identity of the CODE that produced an answer, not just the model name.

    gen/1 keyed on (challenge, agent, model, query_sha) only, so ANY adapter change short of a model
    rename silently served stale generations: raising Anthropic max_tokens 9k->32k, adding pause_turn
    handling, or changing reasoning effort all left the key untouched. In the 2026-07-31 run that
    meant 45 of 49 records per agent came from a run whose manifest records git_dirty=true at a
    commit predating every committed adapter change -- 80% of the deep arm produced by code that
    cannot be reconstructed.

    The key is the RAW SOURCE of every module the generation path runs through. Two cleverer schemes
    were tried and both were unsound in the expensive direction:

      * per-class `inspect.getsource(type(agent))` saw neither inherited methods
        (OpenAIDeepResearchMini defines no `run`) nor module-level helpers -- and `_parse_openai`
        and `_parse_gemini_interaction` are where two of three adapter fixes landed. 5 of 7 adapters
        would have served pre-fix answers forever.
      * stripping prose so a comment edit stayed free. The line-filter version stripped '#' lines
        INSIDE string literals, so two system prompts differing by a markdown header collided. The
        ast+tokenize replacement fixed that and introduced a worse one: it is not stable across
        Python versions. PEP 701 changed f-string tokenization in 3.12, so identical source hashed
        2fcc45daca97 on 3.12-3.14 and b9b383d649b4 on 3.9 -- and pyproject declares
        requires-python >=3.10,<3.14, i.e. the instability sits inside the SUPPORTED range. A minor
        version bump would have been a 100% cache miss and a full re-generation.

    So: no normalization. A comment edit re-pays generation. That is a real cost and it is the one
    being chosen deliberately -- the saving was always hypothetical (no run has yet written an
    adapter_fp, so the cache has served exactly zero entries to date), while both attempts at it
    produced silent-correctness bugs. Raw source is sound, version-stable, and one line."""
    import hashlib, inspect
    from crest.harness import agents as A
    from crest.harness import keys as K
    # keys.py is in the key because ClaudeShallowResearch.run goes through call_anthropic: the pool,
    # its cooldown and its exhaustion handling all affect whether and how a generation completes.
    # It was extracted from agents.py without revisiting this invariant, leaving the docstring's
    # "nothing outside this module" claim false.
    src = "".join(_module_source(m) for m in (A, K))
    parts = [type(agent).__name__, getattr(agent, "model", ""), str(getattr(agent, "budget", "")),
             hashlib.sha256(src.encode()).hexdigest()[:12]]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]


def _module_source(mod) -> str:
    """Raise rather than degrade. Returning a `<nosource:...>` sentinel collapsed the fingerprint to
    a CONSTANT for every adapter -- silently restoring the exact "serve answers from unknown code"
    failure gen/2 exists to prevent, in the one environment (zipapp, frozen build) where nobody
    would think to check. If source is unreadable the cache must not be trusted at all."""
    import inspect
    try:
        return inspect.getsource(mod)
    except (OSError, TypeError) as e:
        raise RuntimeError(
            f"cannot read source of {getattr(mod, '__name__', mod)!r} ({type(e).__name__}), so an "
            f"answer cannot be attributed to the code that produced it. Run from a source checkout, "
            f"or disable the cache explicitly with --override-cache.") from e


def query_sha(query: str) -> str:
    """Stable short hash of the exact agent-visible prompt text."""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:16]


def cache_key(challenge_id: str, agent_key: str, model: str, q_sha: str, fp: str = "") -> str:
    return f"{CACHE_KEY_VERSION}|{challenge_id}|{agent_key}|{model}|{q_sha}|{fp}"


class CachedOutput:
    """Reconstructed agent output. Mirrors AgentOutput's read surface."""
    # `truncated` must be here: run_crest records it via getattr(report, "truncated", False), so
    # omitting it silently wrote 0 for every CACHE HIT -- and cache hits are the normal path on a
    # re-run, so the metric read 0 exactly when it mattered.
    __slots__ = ("text", "citations", "n_tokens", "n_searches", "truncated", "trace", "source_run")
    # `truncated` is keyword-only: AgentOutput's 5th positional is `truncated` while this class's is
    # `source_run`, so a positional call would silently swap them between the two duck-typed classes.
    def __init__(self, text, citations, n_tokens, n_searches, source_run, *, truncated=False):
        self.text, self.citations = text, citations
        self.n_tokens, self.n_searches = n_tokens, n_searches
        self.truncated = bool(truncated)
        self.trace, self.source_run = {}, source_run


class GenerationCache:
    """Read-only index over all prior runs' stored generations."""

    def __init__(self, result_root, enabled: bool = True, verbose: bool = True,
                 trust_legacy: bool = False):
        # trust_legacy: reuse pre-fingerprint (gen/1) generations, matching on
        # (challenge, agent, model, query_sha) alone. OFF by default because those answers cannot be
        # attributed to a known adapter state -- the run that produced most of them records
        # git_dirty=true at a commit predating every committed adapter fix. Turning it on is a
        # deliberate, stated trade: it saves a full re-generation (~$500) at the cost of mixing
        # answers from code you cannot reconstruct. Never turn it on for a run whose numbers ship.
        self.trust_legacy = trust_legacy
        self.enabled = enabled
        self._idx: dict[str, dict] = {}
        self.n_runs = 0
        if enabled:
            self._build(Path(result_root), verbose)

    def _build(self, result_root: Path, verbose: bool) -> None:
        runs = result_root / "runs"
        if not runs.exists():
            return
        skipped_no_sha = skipped_legacy = skipped_failed = 0
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
                # A too_short or truncated answer is a FAILED generation, not a cheap one. score.py
                # calls sub-1000-char answers "the SAME adapter failure as the 0-char answers", so
                # caching them re-serves the failure forever: the module hash cannot invalidate a
                # provider-side hiccup, and the only escape would be --override-cache (all-or-
                # nothing, ~$450) to refresh a handful of records.
                # Judge on the TEXT IN HAND, not on the label a past run happened to write. Checking
                # scoring_status alone trusted history: an answer recorded `scored` under the old
                # 40-char floor is below today's _MIN_SUBSTANTIVE_CHARS, so it was served from cache,
                # re-failed the gate on arrival, and would be served again forever. Records with no
                # status at all (the trust_legacy path) bypassed the check entirely.
                from crest.judge.score import _MIN_SUBSTANTIVE_CHARS
                if (r.get("scoring_status") in ("empty_answer", "too_short") or r.get("truncated")
                        or len((tr.get("output_text") or "").strip()) < _MIN_SUBSTANTIVE_CHARS):
                    skipped_failed += 1
                    continue
                fp = r.get("adapter_fp", "")
                if not fp and not self.trust_legacy:
                    skipped_legacy += 1          # pre-fingerprint answer, provenance unverifiable
                    continue
                k = cache_key(r["challenge_id"], r["agent"], r.get("model", ""), qs, fp)
                self._idx.setdefault(k, {                     # first run wins (oldest generation)
                    "text": tr["output_text"], "citations": tr.get("citations") or [],
                    "n_tokens": r.get("output_len_tokens", 0) or 0,
                    "n_searches": r.get("n_searches", 0) or 0,
                    "truncated": bool(r.get("truncated", False)),
                    "source_run": r.get("run_id") or run_dir.name,
                })
        if verbose:
            msg = f"generation cache: {len(self._idx)} entries from {self.n_runs} prior run(s)"
            if skipped_no_sha:
                msg += f"; {skipped_no_sha} skipped (no query_sha)"
            if skipped_legacy:
                msg += (f"; {skipped_legacy} skipped (pre-fingerprint: adapter state unverifiable, "
                        f"use trust_legacy to reuse them anyway)")
            if skipped_failed:
                msg += f"; {skipped_failed} skipped (empty/too_short/truncated -- will regenerate)"
            print(msg)

    def get(self, challenge_id: str, agent_key: str, model: str, q_sha: str, fp: str = ""):
        if not self.enabled:
            return None
        hit = self._idx.get(cache_key(challenge_id, agent_key, model, q_sha, fp))
        if hit is None and self.trust_legacy:      # fall back to a pre-fingerprint entry
            hit = self._idx.get(cache_key(challenge_id, agent_key, model, q_sha, ""))
        if hit is None:
            return None
        return CachedOutput(hit["text"], hit["citations"], hit["n_tokens"],
                            hit["n_searches"], hit["source_run"],
                            truncated=hit.get("truncated", False))

    def __len__(self) -> int:
        return len(self._idx)

