# CREST — Creativity of deep-Research agenTs

A benchmark for the **creativity** (Non-redundancy / Useful / Surprising) of deep-research web agents.
50 expert-authored challenges, 10 per category (C1 Constrained, C2 Counterfactual, C3 Cross-Domain,
C4 Meta-Creativity, C5 Open-Ended) across 6 domains (8–9 each). Each item is scored 1–10 on
**NON-REDUNDANCY** (the axis reported as `new` — departure from a dated prior-art set, not novelty
in the world), **Useful**, and **Surprising** (exploratory) by a multi-vendor judge panel, after a
factual-grounding check. The **full panel scores every entrant** and `same_family` is stamped on
each judge row; leave-one-family-out is a post-hoc robustness filter, not the protocol. Primary
endpoint is `min(non-redundancy, Useful)` — see `judge/rubric.md`.

## The finding CREST is built to test
Agent creativity is **task-dependent**: predicted strong on cross-domain (C3) and counterfactual
(C2) synthesis, at parity on meta-creativity (C4), with predicted nulls on constrained (C1) and
open-ended (C5) tasks. The mixed win/loss pattern is the point — see `docs/design.md`.

## Quickstart (run from the repo root, the parent of `crest/`)
```bash
$EDITOR crest/config/eval_config.yaml           # choose benchmark subset, agents, judges
python crest/run_eval.py                         # writes crest/result/runs/<run_id>/
python -m crest.harness.run_crest --agents claude_shallow --subset adhoc   # one entrant, ad-hoc
python -m crest.analysis.stats --run crest/result/latest/records.jsonl
bash crest/analysis/ci_check.sh                  # pre-release gate (currently RED — see Status)
```
Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` (pool several Anthropic keys via
`ANTHROPIC_API_KEYS` — see `harness/keys.py`).

There is **no `--resume`**: every run mints a fresh, immutable `run_id`. Cost control is the
**cross-run generation cache** (`harness/cache.py`, on by default), which serves an already-paid-for
answer keyed by (challenge text, agent, model, adapter fingerprint) from *any* prior run, so a
re-run costs only judging. `--override-cache` re-generates everything; `--override-cache-agents
<keys>` re-generates only the named entrants. To repair judge failures in an existing run without
re-paying for generation, use `python -m crest.harness.rejudge --run <run_dir>`.
**The per-entrant scripts in `eval/` do not currently run** — see `eval/readme.md`.

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
See `eval/readme.md` and `docs/notes/deep_research_apis.md`.

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
A full 250-task run exists (50 items x 5 entrants, all three judges per record). **Do not cite
per-agent creativity numbers yet**, for three reasons:

1. **No ranking claim is supportable.** Judge severity exceeds the between-agent spread
   (judge_google is +2.0 to +3.2 points more lenient than the others), and the earlier
   leave-one-family-out protocol assigned judge panels *by entrant family*, which made the
   leaderboard unidentifiable. Scoring is now full-panel; LOFO is a robustness check.
2. **New and Surprising are not separable** (r ~ 0.93). Ablating `expert_baseline` moves Surprising
   by -0.02, so the primary endpoint is `min(New, Useful, Surprising)` over two real axes, not three.
3. **The gate is red.** `analysis/ci_check.sh` fails on 1 quarantined item and 4 items whose own
   rules contradict each other. `questions/quarantine.yaml` lists what is excluded and why.

Live web search is **not** contamination-controlled (`FrozenIndex` raises; a frozen shared index is
future work) and the judge panel is **not** human-validated. What the run *does* support is a
methodological finding: LOFO over a three-vendor panel makes an LLM-judge leaderboard
unidentifiable. See `docs/notes/iclr_metareview.md` and `docs/notes/field_justification.md`.
