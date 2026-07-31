# CREST Judge Rubric — Non-redundancy / Useful / (Surprising, exploratory)

> **What changed and why (2026-07-30).** Two axes are primary, not three, and the first is renamed to
> what it actually measures. Both changes follow from an ablation on the deployed judge:
> withholding the prior-art set moved the first axis by **+0.98** (it is load-bearing), while
> withholding `expert_baseline` moved Surprising by **-0.02** (it anchored nothing). `expert_baseline`
> is therefore no longer sent to the judge. Surprising is still scored and reported, but is
> **exploratory and unanchored**, and correlates with non-redundancy at r ~ 0.95.

**Primary endpoint: `min(non-redundancy, Useful)`.** The old "at or above threshold on all three
axes" indicator is retained only for backward comparability: its rate swung 5.4–36.1% across
thresholds 5–7 with ~26% of records sitting exactly on 6.00, and Surprising eliminated 2 of 116.
Grounded in the standard definition of creativity (novelty + usefulness) plus Boden's surprise.
Judges are **blind** to agent identity, see answers in **randomized order**, and never judge an
entrant from their own model family (**leave-one-family-out**). Humans own New and Surprising;
the LLM panel is authoritative only on categories where it clears the human-agreement threshold
(C2/C3/C4) — on C1/C5 the human panel is primary.

For each output, given the challenge's `known_answers` (dated), `hard_rules`, and `expert_baseline`:

## Non-redundancy (reported as `new`) — 1–10
This is **not** a claim about novelty in the world. It is non-redundancy against a specific, dated,
published reference set — which is precisely what makes it reproducible, and what an unanchored
novelty rating is not: LLM judges rate generated content as highly novel while domain experts
conclude the opposite (the "novelty mirage"), and our own ablation reproduces that at +0.98.
The honest reading of a high score is "not reducible to the listed prior art as of the stated date",
and the reference set is published so any omission can be contested.
- **1–3:** restates an entry in the dated prior-art set.
- **4–6:** recombines entries with minor extension.
- **7–8:** a synthesis/connection not reducible to the entries.
- **9–10:** a synthesis that reframes the problem.
- *Judge against the dated set ONLY, not the web at large and not your own knowledge.*
- **Known limitation:** the set is author-assembled and was found INCOMPLETE by live audit (e.g. a
  voting-methods item omitted Phragmén 1894, Nanson 1882 and random ballot), so an agent
  rediscovering absent prior art is over-credited. Requiring a resolvable DOI per entry is the fix.

## Useful (viability / soundness / appropriateness) — 1–10
- Is the idea sound, workable, and appropriate to the challenge? For constrained items, **all `hard_rules` must be satisfied** (a violated hard rule caps Useful at ≤3).
- Useful is scored on the idea's merit, **not** on citations. *(Grounding is a separate gate — see below.)*
- A fabricated or incoherent claim fails Useful. Useful thus **gates** New: novelty without usefulness is not creativity.

## Surprising — 1–10, EXPLORATORY, NOT a primary endpoint
- Non-obviousness conditioned on correctness, judged against the judge's own sense of expert
  expectation. **Deliberately unanchored:** `expert_baseline` was supplied here until 2026-07-30 and
  an ablation showed it moved this axis by −0.02. In 7 items it also carried the author's enumeration
  of the intended surprises (58–64% of the field in three of them), making Surprising graded recall
  against a key rather than expectation-violation.
- It is reported for continuity and because Boden's surprise criterion motivates the design, but
  r(non-redundancy, Surprising) ≈ 0.95 and adding it to a two-axis gate eliminates 2 records in 116.
  **Do not treat it as independent evidence.**

## Grounding gate (applied before scoring, not part of the axes)
Every load-bearing claim must be supported by a cited source in the frozen snapshot
(FACT-style precision ≥ threshold). **Fail ⇒ creativity score = 0.** This is computed
separately (`judge/score.py::grounding_gate`) and reported cross-agent.

## Reporting
Report the three axes **separately per category × length bin** (a profile, not one number),
with inter-judge reliability (Krippendorff α / ICC) and judge↔human agreement.
