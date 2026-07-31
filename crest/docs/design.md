# CREST — Benchmark Design Spec (P2)

Productionizes `documentation/caesar/caesar_creativity_eval_spec.md` (external —
that path is in the `science_moonshot` tree, not this repo) into the released
benchmark, under the **P2 framing**: CREST is the hero; Caesar is one cited
entrant (arXiv:2604.20855); the finding is cross-agent and axis-dependent.

## 1. The claim (mechanistic scope, not a blanket win)
Do **not** claim "Caesar is more creative than SOTA." The Caesar human data are a
null overall (63/112, 95% CI [0.47, 0.65], p=0.22) and reverse the LLM judge on
C1/C5. Claim instead a **scope** result, theory-grounded (Gentner structure-mapping;
Byrne counterfactual): architectures that improve **cross-domain (C3)** and
**counterfactual (C2)** synthesis, **parity** on meta-creativity (C4), with
**predicted nulls** on constrained (C1) and open-ended (C5). The nulls confirm the
mechanism and defuse "self-serving benchmark."

These per-category directions now live in `analysis/preregistration.yaml` (they
were removed from the item file, where a `predicted_direction` field could be
edited after seeing results). That registration is **not externally timestamped**,
so describe it as "the authors' stated prior expectation, recorded in the
repository" — never as pre-registered. Note also that only C2/C3 are entailed by
the mechanistic account; parity on C4 and nulls on C1/C5 are free parameters.

## 2. Categories × domains (the spine)
- **5 categories** (C1–C5) as the failure-mode axes (see README table).
- **≥6 domains**: biology/medicine, materials/chemistry, economics/business,
  law/policy, engineering, arts/humanities.
- **50 challenges** (10 per category) so per-cell n = 10 supports
  mixed-effects (challenge as random effect), retiring n=5 Cliff's-Delta.
- **Dual-label** every item: isolated N/U/S axis, domain, pre/post-training-cutoff.
- Include **axis-isolating** items (novelty-dominant, usefulness-dominant,
  surprise-dominant) so the aggregate cannot hide a weak axis (MEASURED 2026-07-30: this holds for C1/usefulness only -- 56% binding vs 33% chance; the novelty label is wrong-signed at 21%, i.e. those items are novelty-EASY, and surprise is 15%. Narrow the claim accordingly.).

## 3. Per-item contents
Each challenge ships with: dated **known-answers** list (the prior-art set
**novelty** is scored against — the axis formerly called "New") and
**hard rules** to check (constrained items). Every query must require **deep
multi-source web synthesis**, never a single-fact lookup.
- **`expert_baseline` is JUDGE-HIDDEN since 2026-07-30.** It was the "Surprising"
  anchor until an ablation showed withholding it moved that axis by **−0.02**,
  while in 7 items it doubled as the author's enumeration of the intended
  surprises (turning Surprising into graded recall against a key). Retained in
  the dataset for provenance; `judge/score.py::_judge_prompt` no longer sends it.
  Its answer-key content was split into a second judge-hidden field,
  **`author_expected_surprises`**.
- Fields REMOVED from `questions/crest_challenges.jsonl` (schema
  `crest-challenge/3.1.0`): `predicted_direction` → `analysis/preregistration.yaml`
  (it was a 5-row lookup on `category` sitting in editable data, so it could
  evidence no ordering); `rationale` → `questions/item_design.jsonl`;
  `category_name` (derivable from `category`).
- `questions/schema.json` is now **enforced on load** by
  `harness/run_crest.load_challenges`. It previously shipped unapplied — no
  `jsonschema` import existed anywhere in the repo — so `required` was decorative.
- Items with a defect that makes their scores uninterpretable are listed in
  `questions/quarantine.yaml` and dropped from runs with a loud notice.

## 4. Contamination & length controls
- **Post-cutoff subset** (events/facts after baseline models' cutoffs) + a
  **frozen dated corpus snapshot** served through **one shared search index**
  (every agent searches the same frozen corpus — fair + reproducible). Report
  results split pre/post-cutoff.
  [NOT BUILT: `harness/agents.FrozenIndex` deliberately raises. Every run to date
  used LIVE provider-native web search and is **not** contamination-controlled;
  the manifest records that caveat per run. `time_sensitivity` is now written to
  `records.jsonl`, so the pre/post-cutoff split is at least computable.]
- **Length/verbosity confound** (Caesar paper r=0.47): pre-register **≥3 length
  bins**; report **length-matched** comparisons for every category.

## 5. Judge design (bound it; don't "validate" a biased judge)
- Multi-vendor panel + **≥1 open-weight** judge. [NOT YET: the live panel is
  Anthropic + OpenAI + Google only; a genuinely third-party-hosted open-weight
  judge is the outstanding gap — see `judge/judge_config.live.yaml`.]
- **REVERSED 2026-07-30: the FULL PANEL scores every entrant**
  (`leave_one_family_out: false`). With exactly 3 vendors, LOFO made judge
  identity perfectly confounded with entrant family: `judge_google` is a severity
  outlier (+2.04 vs OpenAI, +3.24 vs Anthropic on min(N,U,S)), LOFO removed it
  deterministically for exactly the Google entrants, no judge scored all five
  entrants, and ~60% of the observed spread tracked panel composition. The
  anti-self-preference control introduced a larger bias than the one it removed.
  LOFO is **demoted to a robustness check**: every judge row is stamped
  `same_family`, so the LOFO subset is recoverable post-hoc and self-preference
  enters the model as a covariate (`analysis/stats.py` MixedLM).
- **Primary endpoint: `min(New, Useful)`.** Surprising is reported but
  EXPLORATORY (r ≈ 0.95 with novelty; its anchor field moved it by −0.02).
  The thresholded "all three ≥ 6" indicator is retained only for backward
  comparability — its rate swings 5.4–36.1% across thresholds 5–7.
- Report **inter-judge agreement** (Krippendorff α / ICC, implemented in
  `analysis/stats.py::reliability_report`) plus **per-judge severity**, blinded.
  ~~answer-order randomized~~ — VACUOUS and removed: scoring is single-answer,
  not pairwise, so there is no answer order to randomize.
- Scope: reliable on **C2/C3/C4**, **unreliable on C1/C5** — stated, not hidden.
- **Humans own the New/Surprising axes.** [FUTURE WORK: no human validation has
  been run; see §7.]

## 6. Objective, judge-free signals
- **Distributional diversity** across repeated generations (embedding-dispersion;
  anti-mode-collapse), especially for C5.
- **Citation faithfulness** (grounding gate; see §8).
- **Do NOT** use corpus-/training-novelty metrics (NovAScore, Creativity Index,
  etc.) as headline signals — they penalize grounded citation (a grounded agent
  scores below an ungrounded confabulator). Backfire.

## 7. Human validation (cheap + native)
- Re-analyze the existing 112 Caesar comparisons correctly: mixed-effects
  (rater + item random effects), Krippendorff α, per-item unit, multiplicity
  correction.
- Small native-artifact re-run: ~200–300 pairwise comparisons on **real long-form
  cited outputs** (not LLM-normalized), ~10–15 domain-qualified raters, focused on
  C2/C3/C4. ~$3–8K, weeks, likely IRB-exempt. Power the categories actually
  claimed (~100/arm for a ~65% effect); do NOT power the pooled claim.
- Use human data to **bound** (not certify) the judge.

## 8. External anchors (capability/grounding only — never creativity)
- **Grounding GATE:** DeepResearch Bench **FACT** (citation faithfulness). Fail
  the gate ⇒ the record is UNSCORED (`creativity: null`, `scoring_status`
  `grounding_fail` or `empty_answer`) — never a fake 0 folded into the results.
  Defuses novelty-by-hallucination; run on ALL entrants' CREST outputs
  (cross-agent, not a Caesar showcase).
  [SHIPPED VERSION IS A PILOT PROXY, not FACT: `judge/score.py::grounding_gate` is
  a regex cue-counter. MEASURED 2026-07-31 over 245 records, its anti-fabrication
  clause fired **zero** times — all 11 rejections were empty strings — so on a
  field of entrants that all use provider-native search it contributes nothing
  beyond an empty-answer check and must not be claimed as a working control.
  `judge/judge_config.yaml`'s `grounding_gate.metric: fact_precision` declares a
  materially stronger gate than the one that runs.]
- Optional capability control: DeepResearch Bench RACE or LiveResearchBench —
  reported as capability, NEVER as creativity, NEVER a coverage leaderboard.

## 9. Report a profile, not one number
Per category × length bin: New + Useful + Surprising + coherence + grounding +
diversity. Show wins (C2, C3) AND predicted nulls (C1, C5) transparently.

## 10. Release & reproducibility
Release benchmark + prompts + frozen snapshots + judge configs + human labels +
all transcripts publicly (defuses "self-serving benchmark"; enables re-scoring).
Datasheet in `datasheet.md`. Version + leaderboard. `analysis/ci_check.sh` is the
pre-release gate that mechanically enforces this list; it is currently **RED**
(4 item self-contradictions) and no leaderboard has been promoted, because judge
severity exceeded the between-agent spread and no ranking claim is supportable.

## 11. DO-NOT list (from the audits/sweep)
- No LiveIdeaBench / AGC-Bench / CreativityPrism / SerenQA as a RUN venue
  (retrieval-neutralizing or wrong world). Borrow rubrics only.
- No NoveltyBench headline (intra-model diversity; backfire).
- No coverage/reference benchmarks (ResearcherBench coverage, DeepScholar,
  ResearchRubrics, ReportBench, DEER) as a creativity signal — anti-Surprise.
- No corpus-novelty metrics as headline (penalize grounding).
- No fiction/EQ/tool-affordance benchmarks (wrong domain).

## 12. Reviewer-defense checklist (the 5 bars)
- [ ] Human validation of the judge (agreement + IRR).
- [ ] An external axis the authors did not design (FACT faithfulness).
- [ ] Self-preference + contamination control (`same_family` as a covariate with
      leave-one-family-out as a robustness check — see §5; post-cutoff. Neither a
      frozen index nor a contamination control exists yet).
- [ ] Adequate N + correct significance (per-item; mixed-effects; correction).
- [ ] Novelty tied to usefulness/soundness (grounding gate).

## 13. P2 framing constraints (from the P2/P3 decision)
- Caesar is CITED (arXiv:2604.20855), not described in-paper (IP/anonymity + COI).
- The grounding gate is cross-agent, not a Caesar-well-sourced showcase.
- A Caesar ablation is an OPTIONAL, IP-gated secondary module, added only if all
  five decision triggers are green (see `paper/p2_benchmark_only/crest_paper_outline.md`;
  the file was previously cited here as `crest_p2_iclr2027_outline.md`, which does
  not exist in this repo).
