# CREST — Benchmark Design Spec (P2)

Productionizes `documentation/caesar/caesar_creativity_eval_spec.md` into the
released benchmark, under the **P2 framing**: CREST is the hero; Caesar is one
cited entrant (arXiv:2604.20855); the finding is cross-agent and axis-dependent.

## 1. The claim (mechanistic scope, not a blanket win)
Do **not** claim "Caesar is more creative than SOTA." The Caesar human data are a
null overall (63/112, 95% CI [0.47, 0.65], p=0.22) and reverse the LLM judge on
C1/C5. Claim instead a **scope** result, theory-grounded (Gentner structure-mapping;
Byrne counterfactual): architectures that improve **cross-domain (C3)** and
**counterfactual (C2)** synthesis, **parity** on meta-creativity (C4), with
**predicted nulls** on constrained (C1) and open-ended (C5). The nulls confirm the
mechanism and defuse "self-serving benchmark."

## 2. Categories × domains (the spine)
- **5 categories** (C1–C5) as the failure-mode axes (see README table).
- **≥6 domains**: biology/medicine, materials/chemistry, economics/business,
  law/policy, engineering, arts/humanities.
- **~30 challenges** (20 min), ~5–6 per category so per-cell n ≥ 5 supports
  mixed-effects (challenge as random effect), retiring n=5 Cliff's-Delta.
- **Dual-label** every item: isolated N/U/S axis, domain, pre/post-training-cutoff.
- Include **axis-isolating** items (novelty-dominant, usefulness-dominant,
  surprise-dominant) so the aggregate cannot hide a weak axis.

## 3. Per-item contents
Each challenge ships with: dated **known-answers** list (baseline for "New"),
**hard rules** to check (constrained items), and an **expert-baseline** answer
(baseline for "Surprising"). Every query must require **deep multi-source web
synthesis**, never a single-fact lookup.

## 4. Contamination & length controls
- **Post-cutoff subset** (events/facts after baseline models' cutoffs) + a
  **frozen dated corpus snapshot** served through **one shared search index**
  (every agent searches the same frozen corpus — fair + reproducible). Report
  results split pre/post-cutoff.
- **Length/verbosity confound** (Caesar paper r=0.47): pre-register **≥3 length
  bins**; report **length-matched** comparisons for every category.

## 5. Judge design (bound it; don't "validate" a biased judge)
- Multi-vendor panel + **≥1 open-weight** judge.
- **Leave-one-family-out** as the DEFAULT reported number (drop the judge sharing
  an entrant's model family; Caesar uses GPT-5.x ⇒ drop the GPT judge; the Caesar
  paper showed +2.47 same-family bias).
- Report **inter-judge agreement** (Krippendorff α / ICC), blinded, answer-order
  randomized.
- Scope: reliable on **C2/C3/C4**, **unreliable on C1/C5** — stated, not hidden.
- **Humans own the New/Surprising axes.**

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
  the gate ⇒ creativity score = 0. Defuses novelty-by-hallucination; run on ALL
  entrants' CREST outputs (cross-agent, not a Caesar showcase).
- Optional capability control: DeepResearch Bench RACE or LiveResearchBench —
  reported as capability, NEVER as creativity, NEVER a coverage leaderboard.

## 9. Report a profile, not one number
Per category × length bin: New + Useful + Surprising + coherence + grounding +
diversity. Show wins (C2, C3) AND predicted nulls (C1, C5) transparently.

## 10. Release & reproducibility
Release benchmark + prompts + frozen snapshots + judge configs + human labels +
all transcripts publicly (defuses "self-serving benchmark"; enables re-scoring).
Datasheet in `datasheet.md`. Version + leaderboard.

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
- [ ] Self-preference + contamination control (leave-one-family-out; post-cutoff).
- [ ] Adequate N + correct significance (per-item; mixed-effects; correction).
- [ ] Novelty tied to usefulness/soundness (grounding gate).

## 13. P2 framing constraints (from the P2/P3 decision)
- Caesar is CITED (arXiv:2604.20855), not described in-paper (IP/anonymity + COI).
- The grounding gate is cross-agent, not a Caesar-well-sourced showcase.
- A Caesar ablation is an OPTIONAL, IP-gated secondary module, added only if all
  five decision triggers are green (see `crest_p2_iclr2027_outline.md`).
