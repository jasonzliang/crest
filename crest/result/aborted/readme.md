# Aborted runs

Runs that were stopped before writing a `run_manifest.json`, kept rather than deleted because each
holds **generations that were paid for**. They live here and not in `runs/` for two reasons:

1. `harness/cache.py` scans `<result_root>/runs` only, so anything here is deliberately **excluded
   from the generation cache**. Every run below was aborted for a reason that makes its records unfit
   to reuse, and an aborted record silently serving a later run is exactly the failure the
   `adapter_fp` fingerprint exists to prevent.
2. `analysis/stall_check.py` and `analysis/ci_check.sh` walk `runs/`. Leaving dead partials there
   made every check report a permanently DEAD+INCOMPLETE run and re-warn about defects already
   diagnosed and recorded, which trains the reader to ignore the output.

Deleting them instead would have destroyed the only record of that spend, so they stay.

| run | records | why aborted |
|---|---|---|
| `175342Z…__ABORTED_buggy_google_token_norm` | 3 | The Google adapters recorded `candidates_token_count` as `output_total`, which **excludes** thinking tokens, under-counting billable output **7.9x** (measured: candidates 1615 + thoughts 11156 = 12771). Fixed in `233b57f`. |
| `180017Z…__STOPPED_to_raise_concurrency_4rec` | 4 | Stopped deliberately to raise concurrency 4 -> 8 after confirming the science run had used 8 safely. Its 4 records carry **empty billing fields**: the process predated the `cache.py` fix, so cache hits lost `tokens`/`calls`. |
| `180746Z…__KILLED_anthropic_spend_cap_31rec_11_thinned_panels` | 31 | Anthropic hit its configured spend cap. 3 `claude_shallow` tasks failed outright and **`judge_anthropic` is missing from 11 of the 31 records** — every one of which still reads `scoring_status: "scored"`, because `min_judges` was 2 against a 3-judge panel. That is the defect `49cb7ff` fixed. These 11 records carry a systematic severity shift and must not be analysed. |

A run with 0 records is simply deleted rather than archived here — there is nothing to preserve.
`2026-07-31T184726Z` (launched into a still-active spend cap) was removed on that basis.

Provenance for runs whose directories were deleted *before* this convention existed is in
`../superseded_runs.json`.
