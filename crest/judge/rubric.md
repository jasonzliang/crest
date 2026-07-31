# CREST Judge Rubric — New / Useful / (Surprising, exploratory)

> **This file is the human-readable mirror of the deployed prompt, `judge/score.py::_judge_prompt`.**
> It has drifted before — it specified a "judge against the dated set, not the web" *anti-web clause*
> and a separate **9–10** band that the deployed prompt did not contain — so it is now maintained
> clause-by-clause against that function. Where the two disagree, **the code is authoritative and
> this file is the bug.** Last diffed against `_judge_prompt` at commit `af65640` (2026-07-31).

> **What changed and why (2026-07-30).** Two axes are primary, not three, and the first is renamed to
> what it actually measures. Both changes follow from an ablation on the deployed judge
> (`analysis/ablate_fields.py`, 10 items × 5 entrants = 50 answers; result in the run's
> `ablation.json`): withholding the prior-art set moved the first axis by **+0.98** (it is
> load-bearing), while withholding `expert_baseline` moved Surprising by **−0.02** (it anchored
> nothing). `expert_baseline` is therefore no longer sent to the judge. Surprising is still scored
> and reported, but is **exploratory and unanchored**, and correlates with novelty at
> **r = 0.94** (n = 234 scored records, 2026-07-31 full run; the deployed prompt rounds this to
> "r~0.95").

## What the judge actually receives

`_judge_prompt` assembles exactly four content blocks:

1. **TASK** — the item's `query`.
2. **DATED PRIOR-ART SET** — `known_answers`, capped at 200 entries (a runaway guard that *warns*
   rather than truncating in silence).
3. **HARD RULES** — `hard_rules`.
4. **ANSWER TO SCORE (author identity withheld)** — the full answer text, capped at 400,000 chars
   (guard only: the longest answer observed is 57,282).

Nothing else reaches the judge. In particular **`expert_baseline`, `author_expected_surprises`,
`category`, `domain`, `axis_isolated`, `time_sensitivity`, the agent's name, and every other
entrant's answer are all withheld.** The judge returns one JSON object —
`{"new", "useful", "surprising", "hard_rules_violated", "rationale" (≤40 words)}` — and no prose.

**Panel and aggregation** (`judge/score.py::JudgePanel`, `judge/judge_config.live.yaml`):

- **Blind** to agent identity — de facto, by construction: the prompt carries no agent name.
- **Full panel, not leave-one-family-out.** `leave_one_family_out: false` is the shipped default:
  with only three vendors, LOFO made judge identity perfectly confounded with entrant family and
  introduced a larger bias than the self-preference it removed. Every judge row is stamped
  `same_family`, so LOFO is recoverable post-hoc as a robustness filter and self-preference enters
  the model as a covariate instead.
- **No answer-order randomization** — and this is not an unimplemented control, it is a *vacuous*
  one: scoring is single-answer, not pairwise, so there is no order to randomize. Earlier versions
  of this file and of `judge_config.yaml` asserted it; the claim has been withdrawn rather than
  left standing. Known-answer-list order and axis order are also **not** randomized.
- Per-axis scores are aggregated by **median** across surviving judges. Below `min_judges: 2` the
  record is flagged `judge_degraded` rather than silently averaged; if every judge fails the record
  is `judge_error` with `creativity: null` — never a fake 0.

## Primary endpoint

**`min(New, Useful, Surprising)` — graded, on the 1–10 scale, not a threshold.**
This is now the definition in code (`analysis/stats.py::_composite`) and in
`analysis/preregistration.yaml`. Surprising binds alone in 20% of records, so it is not a
redundant axis. `stats.py::min2()` reports the New/Useful pair as a robustness check only.
Surprising is deliberately **excluded** from the endpoint: including a demoted, unanchored axis in a
`min` smuggles it back in as a binding constraint (a 9/7/2 record would score 2, not 7), and it is
the sole binding axis in roughly 1 record in 147.

The old "at or above threshold on all three axes" indicator survives only for backward comparability
(`threshold_all_three: 6.0`, reported per record as `creative_all_three`): it is unpre-registered,
its rate swung **5.4–36.1%** across thresholds 5–7 on the pilot run and 38.9–48.7% on the most recent
full run, and 24.9% of records on the first full run sat exactly on 6.00 on some axis (17.5% on the
latest). Adding Surprising to a two-axis gate removes 0 of 234 records at t = 6 and 2 at t = 7.

Grounded in the standard definition of creativity (novelty + usefulness) plus Boden's surprise.
Humans do **not** currently own any axis: **no human validation study has been run** (see
"Reporting" below), so every number in this repo is LLM-panel-derived.

For each output, given the challenge's `known_answers` (dated) and `hard_rules`:

## New — 1–10
This is **not** a claim about novelty in the world. It is novelty against a specific, dated,
published reference set — which is precisely what makes it reproducible, and what an unanchored
novelty rating is not: LLM judges rate generated content as highly novel while domain experts
conclude the opposite (the "novelty mirage"), and our own ablation reproduces that at +0.98.
The honest reading of a high score is "not reducible to the listed prior art as of the stated date",
and the reference set is published so any omission can be contested.
- **1–3:** restates an entry in the dated prior-art set.
- **4–6:** recombines entries with minor extension.
- **7–10:** a synthesis or connection not reducible to the entries.
- *Judge against the dated set ONLY, not the web at large and not your own knowledge: content
  absent from the set counts as non-redundant even if the judge believes it has seen it, and
  content present in the set does not, even if it looks fresh.*
- **Known limitation:** the set is author-assembled and was found INCOMPLETE by live audit (e.g.
  `C5_law_policy_47` lists 20 voting methods but still omits Phragmén 1894, Nanson 1882 and random
  ballot — verified against the shipped file), so an agent rediscovering absent prior art is
  over-credited. Requiring a resolvable DOI per entry is the fix. A second, larger defect: only
  **52% of `known_answers` entries carry an explicit year** file-wide, and just **22% (`_3x`) /
  18% (`_4x`)** in the back half of the file, so for those items "dated prior-art set" overstates
  what is shipped (`docs/notes/audit_live_C4_remainder.md` §2).

## Useful (viability / soundness / appropriateness) — 1–10
- Is the idea sound, workable, and appropriate to the challenge? **Every hard rule must be
  satisfied; a violated hard rule caps Useful at ≤3.**
- Useful is scored on the idea's merit, **not** on citations. *(Grounding is a separate gate — see
  below.)*
- Hard rules are checked **by the judge, in-prompt** — there is no deterministic pre-filter. The
  only programmatic rule checking that ships is `analysis/validate_items.py`, which tests items
  against *themselves* (it currently reports 4 BLOCKING contradictions), not answers against rules.
- *Not a judge instruction:* "Useful gates New" is an **aggregation** property, delivered by the
  `min` endpoint, not a clause in the prompt. The prompt's only anti-nonsense instruction is "Do
  NOT reward nonsense", attached to Surprising.

## Surprising — 1–10, EXPLORATORY, NOT a primary endpoint
- Non-obviousness conditioned on correctness, judged against the judge's own sense of expert
  expectation. **Deliberately unanchored:** `expert_baseline` was supplied here until 2026-07-30 and
  an ablation showed it moved this axis by −0.02. In 7 items it also carried the author's enumeration
  of the intended surprises (58–64% of the field in three of them), making Surprising graded recall
  against a key rather than expectation-violation. That enumeration now lives in the judge-hidden
  `author_expected_surprises` field.
- It is reported for continuity and because Boden's surprise criterion motivates the design, but
  r(New, Surprising) = 0.94 and adding it to a two-axis gate eliminates 0 of 234 records
  at t = 6. **Do not treat it as independent evidence.**

## Grounding gate (applied before scoring, not part of the axes)
`judge/score.py::grounding_gate`. **What ships is a PILOT proxy, not the FACT-precision gate this
section used to describe.** It counts *citation-worthy cues* (dated facts, statistics, currency,
named studies) with a regex, and:

- an empty / near-empty answer (<40 chars) **fails**;
- an answer carrying ≥1 real source URL **passes**;
- a pure-invention answer making ≤2 uncited verifiable factual claims **passes** with zero citations
  (the old `>= min_citations` floor wrongly zeroed the invent tasks, C1/C5);
- an answer piling up many external factual claims with no citation **fails**.

There is **no frozen snapshot**, no per-claim entailment check, and no FACT precision threshold —
`judge_config.yaml` still declares `metric: fact_precision, threshold: 0.8`, which is marked
`[NOT IMPLEMENTED]` in that file and must not be cited as a shipped control.

**Fail ⇒ the answer is UNSCORED (`creativity: null`), not zero.** A fake 0 folded into results was
explicitly rejected; a failing record carries `scoring_status` ∈ {`empty_answer`, `grounding_fail`}.

**Measured contribution: none, so far.** Across 245 records (2026-07-31 full run) the
anti-fabrication clause fired **zero** times. All 11 rejections were **empty strings** from one
entrant (`claude_shallow`, an adapter failure), which is why `empty_answer` is now a *separate*
`scoring_status` from `grounding_fail` — conflating them mislabelled an adapter bug as Claude being
ungrounded. The gate is retained as a cheap guard against an untooled or confabulating entrant, but
**the paper must not claim it as a working control on this field of entrants.**

## Reporting
Report the axes **separately per category** (a profile, not one number).

- **Implemented:** inter-judge reliability — Krippendorff's α (interval) and ICC(1,1)/ICC(1,k), plus
  the per-judge severity table, in `analysis/stats.py::reliability_report`. Measured on the full
  panel, ICC(1,k) is **.774 / .746 / .671** across the three axes, against a 0.80 bar — the panel
  misses it on every axis, and by the most on Surprising. Severity is reported alongside α by
  design: judge severity varied by 2–3 points on a 1–10 scale, exceeding the entire between-agent
  spread, so α alone would hide the effect that decided the leaderboard.
- **Not implemented:** length bins — length is logged per record (`output_len_tokens`) but no
  analysis stratifies or adjusts for it, so "per category × length bin" is not something this repo
  currently produces.
- **Not implemented:** judge↔human agreement. There is no human panel, no human scores, and no
  human-agreement threshold anywhere in the code — only a `human_validation_required_categories`
  key in `judge_config.yaml` that nothing reads. Any claim that C1/C5 are human-anchored, or that
  the panel is "authoritative on C2/C3/C4", is unsupported by the shipped artifact.
- **No ranking claim is made** (`analysis/preregistration.yaml: ranking_claims: none`), because
  judge severity exceeded the between-agent spread.
