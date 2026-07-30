# crest/result — run outputs

Each evaluation writes an **immutable** run directory. A re-run is a new `run_id`, never a mutation.

```
result/
  readme.md                     this file
  index.jsonl                   append-only registry: one line per run (discovery)
  latest -> runs/<run_id>       symlink to the newest run (convenience, NOT canonical)
  leaderboard.json              promoted canonical numbers cited in the paper (created by hand)
  runs/<run_id>/
    records.jsonl               analysis-grade, one line per (challenge, agent); no heavy text
    transcripts.jsonl           heavy: full agent output text + citations, keyed by record_id
    run_manifest.json           provenance: git commit, config, pinned models, judge panel,
                                 live-vs-frozen mode + contamination caveat, totals, env
    summary.json                aggregates per agent × category (grounding/creative rates, means)
```

`run_id = <UTC-timestamp>__crest__<subset>__git<sha>__<nonce>` — sortable and provenance-encoding.

- **"the numbers in the paper"** → `leaderboard.json` (hand-promoted, pins source run ids).
- **"the latest run"** → `latest`.
- **"what runs exist"** → `index.jsonl`.
- Analyze a run: `python -m crest.analysis.stats --run runs/<run_id>/records.jsonl`.

Records are `crest-record/1.0.0`. Per-judge scores are a list under `creativity.judges` so
`pandas.json_normalize(record_path=["creativity","judges"], meta=[...])` yields a rater-level frame
for the mixed-effects model. Reliability (Krippendorff α / ICC) and inferential stats live in
`crest/analysis/stats.py`, not in `summary.json`.
