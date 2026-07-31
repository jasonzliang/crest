# crest/result — run outputs

Each evaluation writes a run directory. Runs are **immutable**: every invocation mints a new
`run_id` and nothing is ever resumed into an existing one. There is no `--resume` / `--no-resume`.
What stops you re-paying is the **cross-run generation cache** (`harness/cache.py`, on by default):
an agent answer already stored in *any* previous run is served for free, keyed by
(challenge text, agent, model, adapter fingerprint), so a re-run costs judge calls only. Disable it
with `--override-cache` (all entrants) or `--override-cache-agents <keys>` (just the named ones), or
`use_cache: false` in the config. To repair judge failures in place without minting a new run, use
`python -m crest.harness.rejudge --run <run_dir>`.

```
result/
  readme.md                     this file (the only tracked thing in here)
  index.jsonl                   append-only registry: one line per run (discovery)   [gitignored]
  latest -> runs/<run_id>       symlink to the newest run (convenience, NOT canonical) [gitignored]
  leaderboard.json              promoted canonical numbers cited in the paper (by hand; NOT YET
                                 CREATED — no ranking claim is currently supportable)
  runs/<run_id>/                                                                     [gitignored]
    records.jsonl               analysis-grade, one line per (challenge, agent); no heavy text
    transcripts.jsonl           heavy: full agent output text + citations, keyed by record_id
    errors.jsonl                one line per failed task (agent error / circuit-broken provider)
    config.snapshot.yaml        literal copy of the config as-run (run_eval.py only)
    run_manifest.json           provenance: git commit, config, pinned models, judge panel,
                                 live-vs-frozen mode + contamination caveat, totals, env
    summary.json                aggregates per agent × category (grounding/creative rates, means)
    ablation.json               written only by `analysis/ablate_fields.py`
```

`run_id = <UTC-timestamp>__crest__<subset>__git<sha>__<nonce>` — sortable and provenance-encoding.
Run outputs are ~7 MB per run, so `runs/`, `index.jsonl` and `latest` are **gitignored** and
live on disk only; they are both the generation cache and the evidence base, so do not delete them.

- **"the numbers in the paper"** → `leaderboard.json` (hand-promoted, pins source run ids).
- **"the latest run"** → `latest`.
- **"what runs exist"** → `index.jsonl`.
- Analyze a run: `python -m crest.analysis.stats --run crest/result/runs/<run_id>/records.jsonl`.
- Is a long run still alive? `python -m crest.analysis.stall_check`.

Records are `crest-record/1.0.0`. `scoring_status` is one of `scored` · `judge_degraded` (scored,
but by fewer than `min_judges` — excluded from headline numbers) · `empty_answer` (the adapter
returned no text; an ADAPTER failure, deliberately distinguished from fabrication) ·
`too_short` (non-empty but under the substantive-length floor -- same adapter root cause as
`empty_answer`, but kept separate because the threshold is a judgement call) · `grounding_fail` ·
`judge_error` (no judge survived). `creativity` is `null` on every UNSCORED path — never a fake 0 —
but **`judge_degraded` is the exception: it carries a full `creativity` dict** scored by too few
judges, which is why `results.py::is_scored` requires BOTH `scoring_status == "scored"` and a
non-empty dict (three disagreeing definitions of "scored" once made a repair drop the headline count
from 100 to 91). Records written by `run_crest` carry `query_sha` + `adapter_fp` (the cache's
content address); **the shipped run 040653Z predates `adapter_fp`, `truncated`, `answer_chars` and
`answer_words` — 0 of its 250 records have them**, so the cache indexes none of it and answer-length
covariates cannot be computed from that release. Also
and `generation_cached` / `cache_source_run` so a reused answer is visible in the data.

Per-judge scores are a list under `creativity.judges`, each row stamped with `same_family`, so
`pandas.json_normalize(record_path=["creativity","judges"], meta=[...])` yields a rater-level frame
for the mixed-effects model and the leave-one-family-out subset is recoverable post-hoc by filtering
`same_family == True`. `creativity.judge_protocol` records which protocol produced the row
(`full-panel (same-family as covariate)` by default).

Reliability (Krippendorff α / ICC) and inferential stats live in `crest/analysis/stats.py`, not in
`summary.json`.

> **Fixed.** `make_manifest` used to hardcode `"judge_protocol": "leave-one-family-out; blind;
> median aggregation"` even on full-panel runs. It now reads `panel.protocol`, so the manifest and
> the per-record `creativity.judge_protocol` agree; the shipped run records
> `"full-panel (same-family as covariate); blind; median aggregation"` and carries a
> `judge_protocol_note` recording the correction.
