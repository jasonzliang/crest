# CREST — Creativity of deep-Research agenTs

A benchmark for the **creativity** (New / Useful / Surprising) of deep-research web agents.
50 expert-authored challenges, 10 per category (C1 Constrained, C2 Counterfactual, C3 Cross-Domain,
C4 Meta-Creativity, C5 Open-Ended) across 6 domains (8–9 each). Each item is scored 1–10 on
**New** (the axis reported as `new` — departure from a dated prior-art set, not novelty
in the world), **Useful**, and **Surprising** (a primary axis, but weakly anchored) by a multi-vendor judge panel, after a
factual-grounding check. The **full panel scores every entrant** and `same_family` is stamped on
each judge row; leave-one-family-out is a post-hoc robustness filter, not the protocol. Primary
endpoint is `min(New, Useful, Surprising)` — all three axes; see `judge/rubric.md`.

## The finding CREST is built to test
Agent creativity is **task-dependent**: predicted strong on cross-domain (C3) and counterfactual
(C2) synthesis, at parity on meta-creativity (C4), with predicted nulls on constrained (C1) and
open-ended (C5) tasks. The mixed win/loss pattern is the point — see `doc/design.md`.

## Quickstart (run from the repo root, the parent of `crest/`)
```bash
$EDITOR crest/config/eval_config.yaml           # choose benchmark subset, agents, judges
python crest/run_eval.py                         # writes crest/result/runs/<run_id>/
python crest/run_eval.py --config crest/config/eval_config.aiml.yaml   # the AI/ML item set instead
python -m crest.harness.run_crest --agents claude_shallow --subset adhoc   # one entrant, ad-hoc
python -m crest.analysis.stats --run crest/result/latest/records.jsonl
python -m crest.analysis.costs --run crest/result/runs/<run_id>   # cost, from config/prices.yaml
bash crest/analysis/ci_check.sh                  # pre-release gate
```
`--dry-run` resolves config, agents, challenges and keys and makes **no model calls** — always the
first thing to run against a config you have edited. A deep-arm run costs real money per task, so
`run_eval.py` also requires `--yes` before it will start one.
Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` (pool several Anthropic keys via
`ANTHROPIC_API_KEYS` — see `harness/keys.py`).

There is **no `--resume`**: every run mints a fresh, immutable `run_id`. Cost control is the
**cross-run generation cache** (`harness/cache.py`, on by default), which serves an already-paid-for
answer keyed by (challenge text, agent, model, adapter fingerprint) from *any* prior run, so a
re-run costs only judging. `--override-cache` re-generates everything; `--override-cache-agents
<keys>` re-generates only the named entrants. To repair judge failures in an existing run without
re-paying for generation, use `python -m crest.harness.rejudge --run <run_dir>`.
The per-entrant scripts in `eval/` work; each goes through `_common.py::cli()`, which applies the
same key preflight and cost guard as `run_eval.py` — see `eval/readme.md`.

## Entrants (pinned in `harness/agents.py`) — TWO DISTINCT ARMS
**Shallow** (chat model + provider-native web search, ONE turn — *not* deep research):
`claude_shallow` claude-sonnet-5 · `openai_shallow` gpt-5.6 · `gemini_shallow` gemini-3.1-pro-preview.

**Deep** (managed multi-step background research loop; minutes and dollars per call):
`openai_deepresearch` gpt-5.6-sol (effort=high, max_tool_calls=40) · `gemini_deepresearch_max`
deep-research-max-preview-04-2026 (Interactions API).

The `*_dr` keys were renamed `*_shallow` because they are single-turn search-augmented chat, and the
old name overstated them. `o3-deep-research` / `o4-mini-deep-research` were **shut down 2026-07-23**
(they still appear in `models.list()` but every call 404s), so OpenAI deep research is now a pattern
on a general model. Anthropic ships no turnkey deep-research endpoint, so the deep arm has no
Anthropic entrant — an asymmetry to disclose, not a null result for Claude.
See `eval/readme.md` and `doc/misc/deep_research_apis.md`.

## The five categories
| ID | Category | What it tests | Predicted direction |
|----|----------|---------------|---------------------|
| C1 | Constrained Synthesis | invent within strict, checkable rules | predicted null |
| C2 | Counterfactual Reasoning | reason through a what-if world | favored |
| C3 | Cross-Domain Synthesis | map a distant field's formal structure | favored |
| C4 | Meta-Creativity | invent a method, not an answer | parity |
| C5 | Open-Ended Synthesis | many valid answers | predicted null |

Each challenge ships with a **dated known-answers list** (the prior-art set novelty is scored
against) and **hard rules** (Useful), plus labels (category, domain, isolated axis, pre/post-cutoff).
`expert_baseline` and `author_expected_surprises` are retained for provenance but are **judge-hidden**
since 2026-07-30: ablating the baseline barely moved Surprising, and in 7 items it doubled as an
answer key. `predicted_direction` moved to `analysis/preregistration.yaml`, `rationale` to
`question/item_design.jsonl`, and `category_name` was dropped; `question/schema.json` is now
actually enforced on load (it never was before). The agent sees only a short, open prompt; that
judge-side machinery is never shown to it.
Field list, counts and balance: `doc/datasheet.md` §2. Every measured figure from the shipped
run: `doc/design.md` §0 — the single source of truth, cited rather than restated everywhere else.

## Layout
```
crest/
  readme.md            you are here
  run_eval.py          MAIN entry point (config-driven)
  config/              eval_config.yaml — choose benchmark(s), agents, judges
                       eval_config.aiml.yaml — same, pointed at the AI/ML item set
                       prices.yaml — per-model prices for analysis/costs.py; ships ALL NULL
  question/           crest_challenges.jsonl (50) · schema.json (enforced on load)
                       item_design.jsonl (per-item rationale) · quarantine.yaml
                       crest_aiml_challenges.jsonl (a SECOND 50-item AI/ML set, 10/category over 6
                       AI/ML domains; validates under schema v3.2.0). It is NOT part of the released
                       benchmark and no paper claims it: it has NO item_design.jsonl rows and has
                       had no citation or live-web audit. It now has its own config
                       (config/eval_config.aiml.yaml) and is NOT gated by ci_check.sh at all: the
                       schema-load, sidecar-bijection and second-item-file checks were all REMOVED
                       from that script (see its header). The earlier claim of coverage here named
                       checks that no longer exist; its own run validates it on load. It HAS been
                       run and scored -- three runs at 243/249/1 records, the 249 promoted into
                       tracked result/leaderboard.crest_aiml.json -- so "not part of the released
                       benchmark" describes what the papers claim, not what exists.
                       On the mechanical checks it is CLEANER than the science set
                       (100% of prior-art entries dated, vs 51%). See doc/misc/aiml_dataset_build.md
  harness/             agents.py (entrants) · run_crest.py (core loop) · results.py (run-dir writer)
                       cache.py (cross-run generation cache) · keys.py (key pooling) · rejudge.py
  judge/               score.py (judge panel + grounding check) · rubric.md · judge_config*.yaml
  analysis/            stats.py (mixed-effects, TOST, crossover, bootstrap, ICC/α)
                       preregistration.yaml · ci_check.sh (pre-release gate) · validate_items.py
                       ablate_fields.py · apply_audit_fixes.py · stall_check.py
                       costs.py (cost from records × config/prices.yaml; refuses to guess — emits
                       null with a reason and reports priced-vs-total coverage)
                       audit_novelty_gate.py (items whose novelty rule offers an example their own
                       prior-art set already contains; heuristic, and its docstring states the
                       defect class it CANNOT see)
                       promote_leaderboard.py (tracked result/leaderboard.json)
  eval/                per-entrant eval scripts + readme (one entrant each; --dry-run supported)
  result/              run outputs (runs/<run_id>/…), gitignored; see result/readme.md
  doc/                design.md · datasheet.md · related_work.md · analysis notes
  paper/               p2_benchmark_only/ (chosen) · p3_caesar_hybrid/ (IP-gated upgrade) · compile.sh
```

## Status (honest)
A full 250-task run exists (50 items x 5 entrants, all three judges per record). **Do not cite
per-agent creativity numbers yet**, for three reasons:

1. **No ranking claim is supportable.** Judge severity exceeds the between-entrant spread on every
   axis, and the earlier leave-one-family-out protocol assigned judge panels *by entrant family*,
   which made the leaderboard unidentifiable. Scoring is now full-panel; LOFO is a robustness check.
2. **Surprising is weakly anchored, but it binds.** Ablating `expert_baseline` barely moves
   Surprising, so it is no longer sent to the judge — the axis rests on the judge's own expert
   prior, which is a limitation to report. It was briefly dropped from the endpoint on the further
   argument that it is redundant with novelty; that argument does not survive its own numbers —
   Surprising is the sole binding axis in a fifth of all records, and the high New/Surprising
   correlation is **contaminated by the v1 judge prompt**, which stated that correlation *to the
   judge*, so it cannot be cited as evidence the axes are inseparable. The primary endpoint is
   `min(New, Useful, Surprising)` — all three axes — consistently across
   `analysis/stats.py::_composite`, `analysis/preregistration.yaml` and `judge/rubric.md`.
   `stats.py::min2()` reports the New/Useful pair as a robustness check.
3. **The gate is green, and that is not the same as release-ready.** `analysis/ci_check.sh` now
   passes all of its checks, including the `C1_materials_chemistry_01` self-consistency failure this
   entry used to describe. What still blocks release is in `doc/datasheet.md`: no human study, no
   Croissant metadata, the run directory undistributed, and both field-ablation deltas
   unreproducible. Run the gate for the live
   failure list rather than trusting a transcript of it; two failures previously counted against
   `C2_materials_chemistry_07` and `C4_materials_chemistry_43` were validator false positives — a
   50% false-positive rate on a blocking gate — and were fixed.
   The quarantine is now **empty** — the one quarantined item was released 2026-07-31 with a
   redrafted baseline that is model-drafted, *not* expert-written, and still needs a physiologist's
   review; `question/quarantine.yaml` keeps that record plus a watch-list of same-class items.

All figures behind points 1 and 2 are in `doc/design.md` §0.

Live web search is **not** contamination-controlled (`FrozenIndex` raises; a frozen shared index is
future work) and the judge panel is **not** human-validated. What the run *does* support is a
methodological finding: LOFO over a three-vendor panel makes an LLM-judge leaderboard
unidentifiable. See `doc/misc/iclr_metareview.md` and `doc/misc/field_justification.md`
(both measured on superseded runs — read their headers first).
