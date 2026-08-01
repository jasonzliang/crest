# CREST Judge Rubric — New / Useful / Surprising (all three primary)

> **This file is the human-readable mirror of the deployed prompt, `judge/score.py::_judge_prompt`
> (`JUDGE_PROMPT_VERSION = v2`, hash `e2ce119c`, gated by `analysis/ci_check.sh`).** It has drifted
> before, so it is maintained clause-by-clause against that function. Where the two disagree, **the
> code is authoritative and this file is the bug.** Last diffed at commit `af65640` (2026-07-31).

> **What changed and why.** `expert_baseline` is no longer sent to the judge, and all three axes are
> primary. Both follow from an ablation on the deployed judge (`analysis/ablate_fields.py`, 10 items
> × 5 entrants = 50 answers; result in the run's `ablation.json`): withholding the prior-art set
> moved New by **+0.98** (load-bearing), while withholding `expert_baseline` moved Surprising by
> **−0.02** (it anchored nothing). Surprising is still scored and reported and is a PRIMARY axis, but
> it is **unanchored**, and correlates with New at **r = 0.883** on run 2026-07-31T040653Z (n = 250,
> at RECORD level, which is what the endpoint uses; pooling the 750 per-judge rows gives 0.946).
> Recompute per run — never quote a fixed figure. **This correlation is CONTAMINATED and is not
> evidence that the axes are inseparable:** 040653Z was judged under prompt v1, which told the judge
> Surprising "correlates with non-redundancy at r~0.95". v2 dropped that clause (and the −0.02
> figure) as circular, so the correlation must be re-measured on a v2 re-judge from stored
> transcripts (`harness/rejudge.py`) before it is quoted as a finding.

## What the judge actually receives

`_judge_prompt` assembles exactly four content blocks:

1. **TASK** — the item's `query`.
2. **DATED PRIOR-ART SET** — `known_answers`, capped at 200 entries (a runaway guard that *warns*
   rather than truncating in silence).
3. **HARD RULES** — `hard_rules`.
4. **ANSWER TO SCORE (author identity withheld)** — the full answer text, capped at 400,000 chars
   (guard only: the longest answer observed is 57,282).

Nothing else reaches the judge on a scoring run. In particular **`expert_baseline`,
`author_expected_surprises`, `category`, `domain`, `axis_isolated`, `time_sensitivity`, the agent's
name, and every other entrant's answer are all withheld** — `expert_baseline` reappears as a fifth
block only under the `restore_expert_baseline` ablation arm, which exists to reproduce the
pre-withdrawal condition. The judge returns one JSON object —
`{"new", "useful", "surprising", "hard_rules_violated", "rationale" (≤40 words)}` — and no prose.

**Panel and aggregation** (`judge/score.py::JudgePanel`, `judge/judge_config.live.yaml`):

- **Blind** to agent identity — de facto, by construction: the prompt carries no agent name.
- **Full panel, not leave-one-family-out.** `leave_one_family_out: false` is the shipped default:
  with only three vendors, LOFO made judge identity perfectly confounded with entrant family and
  introduced a larger bias than the self-preference it removed. Every judge row is stamped
  `same_family`, so LOFO is recoverable post-hoc (the `same_family == False` rows) and
  self-preference enters the model as a covariate instead. Measured justification:
  `judge_config.live.yaml`.
- **No answer-order randomization** — not an unimplemented control but a *vacuous* one: scoring is
  single-answer, not pairwise, so there is no order to randomize. The claim has been withdrawn
  rather than left standing. Known-answer-list order and axis order are also **not** randomized.
- Per-axis scores are aggregated by **median** across surviving judges. Below `min_judges: 2` the
  record is flagged `judge_degraded` rather than silently averaged; if every judge fails the record
  is `judge_error` with `creativity: null` — never a fake 0.

## Primary endpoint

**`min(New, Useful, Surprising)` — graded, on the 1–10 scale, not a threshold.**
This is the definition in code (`analysis/stats.py::_composite`) and in
`analysis/preregistration.yaml`; `stats.py::min2()` reports the New/Useful pair as a robustness check
only. All three axes are in the `min`, because on the shipped run Surprising is the **sole binding
axis in 51 of 250 records (20%)** — the `min` is doing real work on a fifth of the data. Mechanically
this is a floor, not an average: a 9/7/2 record scores 2, not 7.

The old "at or above threshold on all three axes" indicator survives only for backward comparability
(`threshold_all_three: 6.0`, reported per record as `creative_all_three`): it is unpre-registered,
its rate swung **5.4–36.1%** across thresholds 5–7 on the PILOT and **46.4–56.0%** on the canonical
run 040653Z, and 13.6% of that run's records sit exactly on 6.00 on some axis (34/250). Adding
Surprising to a two-axis gate removes **1 of 250** records at t = 6 and **3** at t = 7. Earlier
figures on these lines came from runs since deleted; see `result/superseded_runs.json`.

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
  **48% of `known_answers` entries carry an explicit year** file-wide (340/708), and just
  **17% (`_3x`) / 16% (`_4x`)** in the back half of the file, so for those items "dated prior-art
  set" overstates what is shipped (`doc/misc/audit_live_C4_remainder.md` §2).

## Useful (viability / soundness / appropriateness) — 1–10
- Is the idea sound, workable, and appropriate to the challenge, **on its merits**?
- **Hard rules do NOT cap this axis** (changed in judge prompt v3, 2026-07-31). They are scored
  independently as `rule_compliance` (0–10). Under the old `≤3` cap the two were welded together:
  `corr(min(N,U,S), Useful)` ran 0.976 / 0.957, the composite *equalled* Useful in 190 of 250
  records, and Useful was ~85% explained by the single binary "did any judge cite a violation"
  (clean judge rows averaged 8.63, citing rows 2.84). The creativity endpoint was the compliance
  gate. Reporting them separately makes their correlation a result rather than an artifact.
- Useful is scored on the idea's merit, **not** on citations. *(Grounding is a separate gate — see
  below.)*
- Hard rules are checked **by the judge, in-prompt** — there is no deterministic pre-filter. The
  only programmatic rule checking that ships is `analysis/validate_items.py`, which tests items
  against *themselves* (it currently reports 2 BLOCKING contradictions, both in
  `C1_materials_chemistry_01`), not answers against rules.
- *Not a judge instruction:* "Useful gates New" is an **aggregation** property, delivered by the
  `min` endpoint, not a clause in the prompt. The prompt's only anti-nonsense instruction is "Do
  NOT reward nonsense", attached to Surprising.

## Surprising — 1–10, a PRIMARY axis (weakly anchored)
- Non-obviousness conditioned on correctness, judged against the judge's own sense of expert
  expectation. **Deliberately unanchored:** `expert_baseline` was supplied here until 2026-07-30 and
  an ablation showed it moved this axis by −0.02. In 7 items it also carried the author's enumeration
  of the intended surprises (58%, 59% and 64% of the field in three of them), making Surprising graded
  recall against a key rather than expectation-violation. That enumeration now lives in the
  judge-hidden `author_expected_surprises` field; `question/quarantine.yaml` tracks the three items.
- It is reported for continuity and because Boden's surprise criterion motivates the design, but it
  tracks New closely (r = 0.883; see the header note — that figure is prompt-v1-contaminated) and
  adding it to a two-axis gate eliminates only 1 of 250 records at t = 6. **Do not treat it as
  independent evidence.**

## Grounding gate (applied before scoring, not part of the axes)
`judge/score.py::grounding_gate`. **What ships is a PILOT proxy, not the FACT-precision gate this
section used to describe.** It counts *citation-worthy cues* (dated facts, statistics, currency,
named studies) with a regex, and:

- an empty answer **fails** as `empty_answer`; a non-empty answer under `_MIN_SUBSTANTIVE_CHARS`
  (**1000**, raised from 40 after 10 truncated-adapter preambles of 90–349 chars were scored 1/1/1)
  fails as `too_short`;
- a pure-invention answer making ≤2 uncited verifiable factual claims **passes** with zero citations
  (the old `>= min_citations` floor wrongly zeroed the invent tasks, C1/C5);
- otherwise it needs ≥1 citation **and** a claims-per-citation ratio ≤ `_MAX_CLAIMS_PER_CITATION`
  (**20**). This is a ratio, not an OR: the earlier "has ≥1 citation" disjunct let a single URL carry
  60 fabricated dated statistics.

There is **no frozen snapshot**, no per-claim entailment check, and no FACT precision threshold. The
stronger `metric: fact_precision, threshold: 0.8` gate exists only as design intent in
`doc/judge_protocol_intent.md`, marked `[NOT IMPLEMENTED]` there, and must not be cited as a shipped
control.

**Fail ⇒ the answer is UNSCORED (`creativity: null`), not zero.** A fake 0 folded into results was
explicitly rejected; a failing record carries `scoring_status` ∈ {`empty_answer`, `too_short`, `grounding_fail`}.

**Measured contribution: none, so far.** Across 245 records (superseded run 2026-07-31T020425Z, since
deleted — `result/superseded_runs.json`) the anti-fabrication clause fired **zero** times; all 11
rejections were **empty strings** from one entrant (`claude_shallow`, an adapter failure), which is
why `empty_answer` is a *separate* `scoring_status` from `grounding_fail` — conflating them
mislabelled an adapter bug as Claude being ungrounded. On the canonical run 040653Z the gate never
fires at all: 250/250 scored, shortest answer 2,495 chars. The gate is retained as a cheap guard
against an untooled or confabulating entrant, but **the paper must not claim it as a working control
on this field of entrants.**

## Reporting
Report the axes **separately per category** (a profile, not one number).

- **Implemented:** inter-judge reliability — Krippendorff's α (interval) and ICC(1,1)/ICC(1,k), plus
  the per-judge severity table, in `analysis/stats.py::reliability_report`. On the canonical run the
  full-panel ICC(1,k) is **0.0 / 0.618 / 0.0** (New / Useful / Surprising) against a 0.80 bar: the
  panel misses it on every axis, and by the most on Surprising. That one-way model absorbs judge
  severity into error, so it is a **floor**; removing the judge effect two-way gives ICC(3,k)
  **0.736 / 0.807 / 0.759**, which is the ceiling and clears the bar on Useful only. Report both, and
  recompute per run — never quote a fixed figure. Severity is reported alongside α by design: it
  varies by **3.32 / 3.20 / 3.74** points per axis on a 1–10 scale, exceeding the between-agent
  spread (2.06 on the composite), so α alone would hide the effect that decided the leaderboard.
- **Not implemented:** length bins — length is logged per record (`output_len_tokens`) but no
  analysis stratifies or adjusts for it, so "per category × length bin" is not something this repo
  currently produces.
- **Not implemented:** judge↔human agreement. There is no human panel, no human scores, and no
  human-agreement threshold anywhere in the code — `human_validation_required_categories` survives
  only as design intent in `doc/judge_protocol_intent.md`, read by nothing. Any claim that C1/C5 are
  human-anchored, or that the panel is "authoritative on C2/C3/C4", is unsupported by the shipped
  artifact.
- **No ranking claim is made** (`analysis/preregistration.yaml: ranking_claims: none`), because
  judge severity exceeded the between-agent spread.
