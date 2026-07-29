# CREST — CREativity of reSearch agenTs

A released benchmark for the **creativity** of deep-research web agents. Existing
deep-research benchmarks score correctness, coverage, and citation faithfulness;
CREST is the first to score **creativity** — rated **New / Useful / Surprising**
(each 1–10; an output counts as creative only if all three hold) by a
human-validated LLM-judge panel.

Companion to the Caesar agent (see `../caesar/`, arXiv:2604.20855). In CREST,
Caesar is **one cited entrant among many frontier agents** — the benchmark and
the cross-agent finding are the contribution, not any single system.

## The finding CREST is built to test
Agent creativity is **axis/task-dependent** and the pattern holds **across the
frontier**: strong on cross-domain (C3) and counterfactual (C2) synthesis, at
parity on meta-creativity (C4), with predicted nulls on constrained (C1) and
open-ended (C5) tasks. (Mechanistic-scope hypothesis; see `DESIGN.md`.)

## The five categories (failure-mode axes)
| ID | Category | What it tests | Predicted direction |
|----|----------|---------------|---------------------|
| C1 | Constrained Synthesis | invent within strict, checkable rules | predicted null |
| C2 | Counterfactual Reasoning | reason through a what-if world | agent win |
| C3 | Cross-Domain Synthesis | map a distant field's formal structure | agent win |
| C4 | Meta-Creativity | invent a method, not an answer | parity |
| C5 | Open-Ended Synthesis | many valid answers | predicted null |

~30 challenges (≥6 domains: biology/medicine, materials/chemistry,
economics/business, law/policy, engineering, arts/humanities), ~5–6 per category.

## Repository layout
```
crest/
  DESIGN.md            # full benchmark design spec (P2)
  datasheet.md         # Datasheets-for-Datasets-style documentation
  questions/           # the challenge dataset (crest_challenges.jsonl) + per-category files
  judge/               # N/U/S rubric + leave-one-family-out judge config
  harness/             # eval harness (run agents, score, mixed-effects stats)
  snapshots/           # frozen dated corpus snapshots (contamination control)
  analysis/            # human-validation re-analysis + figures
```

## Each challenge ships with
- a **dated list of already-known answers** (so "New" is judged against what is known),
- **hard rules** to check (for constrained items),
- an **expert-baseline answer** (so "Surprising" has a reference),
- labels: category, domain, isolated axis, pre/post-training-cutoff.

## Scoring protocol (summary; see `DESIGN.md`)
- Multi-vendor judge panel incl. ≥1 open-weight; **leave-one-family-out** is the
  default reported number (drop the judge sharing an entrant's model family).
- **Grounding gate:** citation-faithfulness (DeepResearch Bench FACT); fail ⇒ creativity = 0.
- Humans own the New/Surprising axes; report a **profile per category × length bin**, not one number.
- Per-item **mixed-effects** stats (item + rater random effects), multiplicity correction, ≥3 length bins.

## Status
Design + dataset scaffolding in progress. Challenge set generated across the
5×6 category-domain grid; judge harness and human-validation pipeline to follow.
Not for creativity claims until the judge is human-validated (≥4/5 categories).

License: see repository root.
