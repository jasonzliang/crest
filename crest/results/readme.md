# Run outputs

Local answers, judgments, reports, and resumable pipeline state.

New runs use `YYYY-MM-DD/HH-MM-SS-TZ-<agents>-q<count>-<id>/`.
Long provider slugs use `<N>-research-agents`; question counts reflect the selected data.
Each run's `run.json` records its frozen inputs/settings and numbered stage directories.
`setup-validation-*` directories hold local setup/pilot artifacts, not published benchmarks.

The top-level `.cache/` holds shared generation jobs, latest-run pointers, and provenance.
Per-run `.cache/` directories hold judging and analysis state.
**`.cache` is not disposable during active runs:** checkpoints and receipts support safe resumption.

Historical reports and runs are immutable; keep their original names and saved artifacts.
Resume with the exact `--run` path; do not hand-edit live manifests or worker receipts.
Generated results/caches are ignored by Git; this readme is retained.
See [saved results](../../docs/research-pipeline.html#files) and [configuration](../configs/crest.yaml).
