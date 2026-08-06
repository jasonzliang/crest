# CREST — Creativity of deep-Research agenTs

A benchmark for the **creativity** of deep-research web agents, scored on three axes:
**New**, **Useful**, and **Surprising**.

50 expert-authored challenges — 10 in each of 5 categories, spread over 6 domains — each scored
1–10 per axis by a multi-vendor LLM judge panel after a factual-grounding check. The primary
endpoint is `min(New, Useful, Surprising)`: an answer is only as creative as its weakest axis.

> **Status: research preview. Do not cite per-agent numbers yet.**
> A full 250-task run exists, but judge severity currently exceeds the between-entrant spread on
> every axis, so no ranking claim is supportable. The `Surprising` axis is also weakly anchored.
> Both limitations, and what still blocks release, are documented without varnish in
> [`crest/readme.md`](crest/readme.md) and [`crest/doc/datasheet.md`](crest/doc/datasheet.md).
> The benchmark items, harness, and judge protocol are stable and usable today; the leaderboard
> is not.

## The five categories

| ID | Category | What it tests | Predicted direction |
|----|----------|---------------|---------------------|
| C1 | Constrained Synthesis | invent within strict, checkable rules | predicted null |
| C2 | Counterfactual Reasoning | reason through a what-if world | favored |
| C3 | Cross-Domain Synthesis | map a distant field's formal structure | favored |
| C4 | Meta-Creativity | invent a method, not an answer | parity |
| C5 | Open-Ended Synthesis | many valid answers | predicted null |

CREST is built to test one claim: that agent creativity is **task-dependent**, showing a mixed
win/loss pattern across categories rather than a single ordering. The predicted directions above
are preregistered in [`crest/analysis/preregistration.yaml`](crest/analysis/preregistration.yaml).

Each challenge ships with a **dated known-answers list** (the prior-art set that `New` is scored
against) and **hard rules** (scored under `Useful`). The agent sees only a short, open prompt —
never the judge-side machinery.

## Install

```bash
git clone https://github.com/jasonzliang/crest.git
cd crest
pip install -r requirements.txt
```

Set the keys for whichever entrants you plan to run:

```bash
export ANTHROPIC_API_KEY=...     # or ANTHROPIC_API_KEYS=key1,key2,... to pool several
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
```

## Quickstart

Run from the repository root (the parent of `crest/`):

```bash
$EDITOR crest/config/eval_config.yaml     # choose benchmark subset, agents, judges
python crest/run_eval.py --dry-run        # resolves config, agents, challenges, keys; no model calls
python crest/run_eval.py --yes            # a deep-arm run costs real money per task
python -m crest.analysis.stats --run crest/result/latest/records.jsonl
```

**Always `--dry-run` first** against a config you have edited. There is no `--resume`: every run
mints a fresh, immutable `run_id`. Cost control is the cross-run generation cache
([`crest/harness/cache.py`](crest/harness/cache.py)), which serves an already-paid-for answer keyed
by (challenge text, agent, model, adapter fingerprint) from *any* prior run — so a re-run costs
only judging.

## Entrants

Two deliberately distinct arms, pinned in [`crest/harness/agents.py`](crest/harness/agents.py):

- **Shallow** — chat model plus provider-native web search, one turn:
  `claude_shallow`, `openai_shallow`, `gemini_shallow`.
- **Deep** — managed multi-step background research loops, minutes and dollars per call:
  `openai_deepresearch`, `gemini_deepresearch_max`.

Anthropic ships no turnkey deep-research endpoint, so the deep arm has no Anthropic entrant. That
is an asymmetry to disclose, not a null result for Claude.

## Layout

```
crest/
  readme.md      full documentation — start here for anything beyond this page
  run_eval.py    main entry point (config-driven)
  question/      the 50 challenges, JSON-schema-enforced on load
  harness/       entrants, core loop, run-dir writer, generation cache, key pooling
  judge/         judge panel, grounding check, rubric
  analysis/      mixed-effects stats, preregistration, pre-release gate
  eval/          per-entrant scripts
  doc/           design notes, datasheet, related work
  paper/         LaTeX sources (anonymized for double-blind review)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
