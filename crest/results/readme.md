# Run outputs

Local answers, judgments, reports, and resumable pipeline state.

New runs use `YYYY-MM-DD/HH-MM-SS-TZ-<agents>-q<count>-<id>/`.
Long provider slugs use `<N>-research-agents`; question counts reflect the selected data.
Each run's `run.json` records its frozen inputs/settings and numbered stage directories.
`setup-validation-*` and `high-reasoning-validation/` hold local setup, pilot, and test artifacts, not published benchmarks.

The top-level `.cache/` holds shared generation jobs, latest-run pointers, and provenance.
Per-run `.cache/` directories hold judging and analysis state.
**`.cache` is not disposable during active runs:** checkpoints and receipts support safe resumption.

The 50-question study shares one set of answers across three judged runs: NUS v1 in `2026-11-24/04-13-43-CST-5-research-agents-q50-6324120b`, NUS v3 in `2026-11-23/22-38-07-CST-5-research-agents-q50-1eaaa56c`, and NUS v2 in `2026-11-24/04-14-01-CST-5-research-agents-q50-d1ec03a9`.
[Deep Research Comparison v3](../../docs/deep-research-comparison-v3.html) renders the v1 run, with the other two passed as `--rubric-run`.

Historical reports and runs are immutable; keep their original names and saved artifacts.
Resume with the exact `--run` path; do not hand-edit live manifests or worker receipts.
Generated results/caches are ignored by Git; this readme is retained.
See [saved results](../../docs/research-pipeline.html#files) and [configuration](../configs/crest.yaml).
