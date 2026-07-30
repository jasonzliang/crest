# CREST — Creativity of deep-Research agenTs

A benchmark for the **creativity** (New / Useful / Surprising) of deep-research web agents.
50 expert-authored challenges, 10 per category (C1 Constrained, C2 Counterfactual, C3 Cross-Domain,
C4 Meta-Creativity, C5 Open-Ended) across 6 domains (8–9 each). Each item is scored 1–10 on New,
Useful, and Surprising — creative only if all three clear threshold — by a multi-vendor,
leave-one-family-out judge panel, after a factual-grounding check.

## The finding CREST is built to test
Agent creativity is **task-dependent**: predicted strong on cross-domain (C3) and counterfactual
(C2) synthesis, at parity on meta-creativity (C4), with predicted nulls on constrained (C1) and
open-ended (C5) tasks. The mixed win/loss pattern is the point — see `docs/design.md`.

## Quickstart (run from the repo root, the parent of `crest/`)
```bash
$EDITOR crest/config/eval_config.yaml           # choose benchmark subset, agents, judges
python crest/run_eval.py                         # writes crest/result/runs/<run_id>/
python crest/eval/eval_claude_sonnet.py          # or evaluate a single model
python -m crest.analysis.stats --run crest/result/latest/records.jsonl
```
Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`.

## Entrants (pinned in `harness/agents.py`)
`claude_dr` claude-sonnet-5 · `openai_dr` gpt-5.6 · `gemini_dr` gemini-3.1-pro-preview · plus the
OpenAI Deep Research API (`openai_deepresearch` = o3-deep-research, `..._mini` = o4-mini-deep-research).
All use provider-native web search. See `eval/readme.md`.

## The five categories
| ID | Category | What it tests | Predicted direction |
|----|----------|---------------|---------------------|
| C1 | Constrained Synthesis | invent within strict, checkable rules | predicted null |
| C2 | Counterfactual Reasoning | reason through a what-if world | favored |
| C3 | Cross-Domain Synthesis | map a distant field's formal structure | favored |
| C4 | Meta-Creativity | invent a method, not an answer | parity |
| C5 | Open-Ended Synthesis | many valid answers | predicted null |

Each challenge ships with a **dated known-answers list** (baseline for New), **hard rules** (Useful),
and an **expert baseline** (Surprising), plus labels (category, domain, isolated axis, pre/post-cutoff).
The agent sees only a short, open prompt; that judge-side machinery is never shown to it.

## Layout
```
crest/
  readme.md            you are here
  run_eval.py          MAIN entry point (config-driven)
  config/              eval_config.yaml — choose benchmark(s), agents, judges
  questions/           crest_challenges.jsonl (50) + schema.json
  harness/             agents.py (entrants) · run_crest.py (core loop) · results.py (run-dir writer)
  judge/               score.py (LOFO panel + grounding check) · rubric.md · judge_config*.yaml
  analysis/            stats.py (mixed-effects, TOST, crossover, bootstrap)
  eval/                per-model eval scripts + readme
  result/              run outputs (runs/<run_id>/…); see result/readme.md
  docs/                design.md · datasheet.md · related_work.md · analysis notes
  paper/               p2_benchmark_only/ (chosen) · p3_caesar_hybrid/ (IP-gated upgrade) · compile.sh
```

## Status (honest)
Scaffolding + a small live-web pilot only. **No headline results yet** — the papers carry
`[PLACEHOLDER]`s until a powered run + the human-validation study are done. Live web search is
**not** contamination-controlled (a frozen shared index is future work). Do not cite creativity
numbers until the judge is human-validated. See `docs/design.md` and `docs/datasheet.md`.
