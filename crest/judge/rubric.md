# CREST Judge Rubric — New / Useful / Surprising

An output counts as **creative** only if it scores at or above threshold on **all three** axes.
Grounded in the standard definition of creativity (novelty + usefulness) plus Boden's surprise.
Judges are **blind** to agent identity, see answers in **randomized order**, and never judge an
entrant from their own model family (**leave-one-family-out**). Humans own New and Surprising;
the LLM panel is authoritative only on categories where it clears the human-agreement threshold
(C2/C3/C4) — on C1/C5 the human panel is primary.

For each output, given the challenge's `known_answers` (dated), `hard_rules`, and `expert_baseline`:

## New (novelty / rarity) — 1–10
- **1–3:** restates content already in the dated `known_answers` list.
- **4–6:** recombines known elements with minor extension.
- **7–8:** a genuinely new synthesis/connection not in `known_answers`.
- **9–10:** a new synthesis that reframes the problem.
- *Judge against the dated known-answers list, NOT against the web at large (avoids penalizing grounding).*

## Useful (viability / soundness / appropriateness) — 1–10
- Is the idea sound, workable, and appropriate to the challenge? For constrained items, **all `hard_rules` must be satisfied** (a violated hard rule caps Useful at ≤3).
- Useful is scored on the idea's merit, **not** on citations. *(Grounding is a separate gate — see below.)*
- A fabricated or incoherent claim fails Useful. Useful thus **gates** New: novelty without usefulness is not creativity.

## Surprising (non-obviousness) — 1–10
- Relative to the `expert_baseline` (the expected expert answer): an output that merely reproduces the expert baseline scores **low**; one that violates a well-calibrated prior while remaining correct scores **high**.
- Surprise is **expectation-violation conditioned on correctness**, not raw improbability (do not reward nonsense).

## Grounding gate (applied before scoring, not part of the axes)
Every load-bearing claim must be supported by a cited source in the frozen snapshot
(FACT-style precision ≥ threshold). **Fail ⇒ creativity score = 0.** This is computed
separately (`judge/score.py::grounding_gate`) and reported cross-agent.

## Reporting
Report the three axes **separately per category × length bin** (a profile, not one number),
with inter-judge reliability (Krippendorff α / ICC) and judge↔human agreement.
