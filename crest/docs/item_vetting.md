# CREST Item Vetting — Adversarial Red-Team

## Method

This is an adversarial item-vetting pass over all 50 CREST challenges in
`questions/crest_challenges.jsonl` (ids ending `00`–`29` are the 30 original items;
`30`–`49` are the 20 newly-added items). Each item was read in full — `query`,
`hard_rules`, `known_answers`, `expert_baseline`, `predicted_direction`, and the
designer `rationale` — and stress-tested against five gates. The goal is not to
re-grade a model's answer but to ask whether each *item* actually measures what it
claims to. Gates are marked **PASS / WEAK / FAIL**; each item gets a disposition
(**KEEP / REVISE / CUT**) with a one-line reason. This report does **not** modify
the dataset.

**The five gates:**

1. **G1 Contamination-resistance** — is the answer NOT memorizable / not sitting on a
   single indexed page (genuinely multi-hop)? All items are invention or
   counterfactual tasks with no canonical published answer, and each `known_answers`
   list deliberately pre-claims the memorizable/first-order content, forcing work
   beyond recall.
2. **G2 Synthesis-required** — does answering truly need multi-source synthesis rather
   than a single lookup?
3. **G3 Axis-isolation** — does it genuinely exercise its labeled isolated axis
   (C1 usefulness, C2 surprise, C3 novelty, C4 balanced, C5 novelty) rather than a
   confound?
4. **G4 Headroom** — is it hard enough not to be saturated by a strong agent
   (not trivially answerable)?
5. **G5 Metadata** — `known_answers` dated & non-empty, `hard_rules` checkable,
   `expert_baseline` present.

## Per-item assessment

| id | cat | domain | G1 | G2 | G3 | G4 | G5 | disp. | reason |
|----|-----|--------|----|----|----|----|----|-------|--------|
| C1_biology_medicine_00 | C1 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | CRAB novel-MOA; 7 checkable rules + falsifiable experiment cleanly isolate usefulness |
| C1_materials_chemistry_01 | C1 | mat_chem | PASS | PASS | PASS | PASS | WEAK | KEEP | Perovskite top-cell; 12 parametric rules isolate usefulness; KA band-gaps self-flagged unverified |
| C1_economics_business_02 | C1 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | GPU spot-market mechanism; formal IC/budget-balance rules make usefulness provable |
| C1_law_policy_03 | C1 | law | PASS | PASS | PASS | PASS | PASS | KEEP | LEO-debris instrument; treaty-article + incentive-compat constraints isolate legal-operability |
| C1_engineering_04 | C1 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | FDM energy-absorber; strict SEA/plateau/reusability envelope; usefulness fully checkable |
| C1_arts_humanities_05 | C1 | arts | PASS | PASS | PASS | PASS | WEAK | KEEP | Mnemonic fixed form; usefulness = order-recall efficacy grounded in serial-recall science; KA self-flagged unverified |
| C1_biology_medicine_30 | C1 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Molecular-glue triple; ternary-geometry/lysine/E3-coexpression feasibility isolates usefulness (lighter rule-set) |
| C1_materials_chemistry_31 | C1 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Li superionic conductor; quantitative barrier/window/abundance targets isolate usefulness |
| C1_engineering_32 | C1 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | Daytime radiative cooler; radiative-balance inequality gives checkable usefulness |
| C1_arts_humanities_33 | C1 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | Novel tuning; cents-error/pitch-count arithmetic makes usefulness directly checkable |
| C2_biology_medicine_06 | C2 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | No-adaptive-immunity world; first-order pre-claimed, surprise via cross-field 2nd-order + coherence lock |
| C2_materials_chemistry_07 | C2 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | No-crystallinity world; six-arena scaffold, surprise via inverted/net-benefit consequences |
| C2_economics_business_08 | C2 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | No limited liability; partial-counterfactual record anchors surprising-but-true cascades |
| C2_law_policy_09 | C2 | law | PASS | PASS | PASS | PASS | FAIL | REVISE | Statute-of-limitations world; design strong but `expert_baseline` is a placeholder stub ("See ... above.") |
| C2_engineering_10 | C2 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | 1.5g world; scaling-law scaffold, surprise via gravity-invariants and direction-reversals |
| C2_arts_humanities_11 | C2 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | No linear perspective; canon pre-claimed, surprise via distant knock-ons + self-undermining test |
| C2_biology_medicine_34 | C2 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Non-enucleated RBCs; anti-obvious rule + concrete baseline isolate surprise |
| C2_materials_chemistry_35 | C2 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Non-protective Al oxide; industrial-chain 2nd-order beyond substitute-metal baseline |
| C2_economics_business_36 | C2 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | No shipping container; landed-cost/port-geography 2nd-order surprise |
| C2_law_policy_37 | C2 | law | PASS | PASS | PASS | PASS | PASS | KEEP | No plea bargaining; prosecutorial-incentive 2nd-order surprise; multi-source rule |
| C3_biology_medicine_12 | C3 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Category theory→differentiation; novelty gate blocks Rosen/MES; structural-fidelity rules |
| C3_materials_chemistry_13 | C3 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Pop-gen→solid-state; trivial mappings banned; novelty on deeper terms + disanalogy |
| C3_economics_business_14 | C3 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | Knot theory→ownership networks; unoccupied niche; invariance proof required |
| C3_law_policy_15 | C3 | law | PASS | PASS | PASS | PASS | WEAK | KEEP | RG→federalism; Galam-gated; novelty on competence-allocation dictionary; prior-art self-flagged unverified |
| C3_engineering_16 | C3 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | Pop-gen→software evolution; Lehman-gated; equation-level correspondences + predictions |
| C3_arts_humanities_17 | C3 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | Gauge theory→translation; shallow "meaning=invariant" gated; holonomy/curvature layer required |
| C3_biology_medicine_38 | C3 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Optimal transport→non-transport biology; homonym/trajectory uses gated; novelty on duality/slackness |
| C3_materials_chemistry_39 | C3 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Sheaf cohomology→materials; TDA/K-theory gated; H^1 obstruction needs a lab referent |
| C3_law_policy_40 | C3 | law | PASS | PASS | PASS | PASS | PASS | KEEP | Queueing→non-backlog law; M/M/c gated; variability-amplification/feedback novelty |
| C3_arts_humanities_41 | C3 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | Spectral graph→humanities; character-networks gated; Cheeger-coupling novelty |
| C4_biology_medicine_18 | C4 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Replication-propensity score; forbidden-signal constraint forces New+Useful+Surprise to bind |
| C4_materials_chemistry_19 | C4 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Discovery-value metric; all three axes jointly gated; anti-remoteness requirement |
| C4_economics_business_20 | C4 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | Data-capital valuation; four break-properties + auditability force balance |
| C4_law_policy_21 | C4 | law | PASS | PASS | PASS | PASS | PASS | KEEP | Regulator-capture metric; banned-proxy constraint forces balanced invention |
| C4_engineering_22 | C4 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | Cross-domain margin-efficiency index; prior-art + invariance + falsifiability bind all three |
| C4_arts_humanities_23 | C4 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | Restitution adjudication framework; hard cases + new-mechanism force balance; post-cutoff grounding |
| C4_biology_medicine_42 | C4 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Preclinical-model selection method; ≥3 traditions + new variable + 2 hard cases bind all three |
| C4_materials_chemistry_43 | C4 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Synthesis-route ranking; discriminating hard cases invert green-metrics baseline |
| C4_economics_business_44 | C4 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | Killer-acquisition screen; below-threshold/zero-overlap hard cases invert concentration-test baseline |
| C4_engineering_45 | C4 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | Reparability/upgradeability index; software-lock inversion hard case; balanced |
| C5_biology_medicine_24 | C5 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Categorically-new modality; 26-entry KA + undruggable-biology reasoning; high headroom |
| C5_materials_chemistry_25 | C5 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | New solid-state class; 33-entry KA; single-organizing-principle bar; high headroom |
| C5_economics_business_26 | C5 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | New market for a missing market; IC argument + buildable-now floor keep it hard |
| C5_law_policy_27 | C5 | law | PASS | PASS | PASS | PASS | PASS | KEEP | New future-generations instrument; open-world non-existence proof across many jurisdictions |
| C5_engineering_28 | C5 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | New engineering device; 3-corpus white-space map; no off-the-shelf integration allowed |
| C5_arts_humanities_29 | C5 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | New poetic form; 33-entry cross-lingual catalogue + collision rule; high headroom |
| C5_economics_business_46 | C5 | econ | PASS | WEAK | WEAK | WEAK | PASS | REVISE | "Invent an economic index"; synthesis is negative-verify only, saturable, can't separate genuine vs arbitrary novelty |
| C5_law_policy_47 | C5 | law | PASS | WEAK | WEAK | WEAK | PASS | REVISE | "Invent a voting method"; thin synthesis + low headroom; a strong agent trivially clears it |
| C5_engineering_48 | C5 | eng | PASS | WEAK | WEAK | WEAK | PASS | REVISE | "Invent a planar linkage"; only a mobility floor; low headroom, thin synthesis |
| C5_arts_humanities_49 | C5 | arts | PASS | WEAK | WEAK | WEAK | PASS | REVISE | "Invent a musical form"; thin synthesis, easily saturated novelty |

## Summary

**Dispositions:** KEEP = 45 · REVISE = 5 · CUT = 0.

### REVISE items and the specific fix

- **C2_law_policy_09** (G5 FAIL) — `expert_baseline` is a placeholder stub
  (`"See expert-baseline field content above."`) instead of the real reference
  answer. For a C2 surprise item the baseline is load-bearing (Surprise is scored
  against it), so this must be fixed. **Fix:** restore the actual expert-baseline
  text (the convergent "evidentiary decay silently reconstitutes a de facto
  limitations period / archive-power migration / perpetual-reparations" narrative the
  rationale references). No other change needed — G1–G4 all pass.
- **C5_economics_business_46, C5_law_policy_47, C5_engineering_48, C5_arts_humanities_49**
  (G2/G3/G4 WEAK) — this lightweight C5 subset is a distinctly easier tier than the
  C5 originals: only 3 hard rules, short deliverables, and a novelty check that is
  pure negative-verification ("confirm no established X does this") rather than genuine
  multi-source synthesis. A strong agent saturates them, and the loose bar cannot
  distinguish real creative novelty from arbitrary novelty. **Fix (per item):** raise
  the difficulty and synthesis load — require the invention to be constructed from
  and contrasted against ≥3 named source families, add a quantitative/functional bar
  (46: combine ≥3 heterogeneous public datasets with a stated identification argument;
  47: satisfy a named social-choice property that a listed method fails, e.g.
  a specific monotonicity/participation criterion; 48: hit a quantified performance
  target with a first-order kinematic analysis; 49: supply a fully worked realized
  example and prove non-reduction to hybrids of catalogued forms), and expand the
  `hard_rules`/`known_answers` toward the depth of ids 24–29.

### Systematic patterns

- **By gate.**
  - *G1 (contamination):* uniformly strong. The invention/counterfactual format plus
    `known_answers` lists that pre-claim the memorizable and first-order content make
    the whole set genuinely multi-hop; nothing is answerable from a single indexed page.
  - *G2 (synthesis):* strong except the C5 lightweight subset (46–49). C5 as a category
    leans on "prove absence" negative-verification, which is thinner synthesis than the
    literature-fusion demanded by C1/C3/C4; the C5 *originals* (24–29) compensate with
    rich prior-art surveys, but 46–49 do not.
  - *G3 (axis-isolation):* solid across the board. Note two inherent (well-mitigated)
    entanglements: C3's "novelty" overlaps "surprise" (a novel structural mapping is
    also surprising) — handled by explicit novelty gates + expert baselines; and the
    C1 arts/invention items (05, 33) lean novelty-adjacent — handled by concrete
    functional/usefulness checks. Only 46–49 are genuinely WEAK (novelty labeled but
    the bar can't separate genuine from arbitrary novelty).
  - *G4 (headroom):* C1/C3/C4 are the hardest tiers and clearly unsaturated; only
    46–49 are saturable.
  - *G5 (metadata):* all `known_answers` are dated & non-empty and all `hard_rules`
    (min 3) are checkable. One hard FAIL (09, broken `expert_baseline`). Two softer
    systematic issues below.
- **Missing `category_name` in every new item.** All 20 newly-added items (30–49) omit
  the `category_name` field that all 30 originals carry — a metadata regression worth
  backfilling (does not affect gradeability).
- **Self-flagged unverified `known_answers`.** Three items (01, 05, 15) note in their
  rationale that the web-search budget was exhausted before verification, so their
  `known_answers`/prior-art (perovskite band-gaps; quenine/krama facts; RG-on-voting
  prior art) should be spot-checked against live sources before deployment.
- **Weakest category = C5.** Its open-ended novelty framing makes synthesis thin and
  headroom fragile; the originals hold up only because of large `known_answers` sets
  and heavy deliverables. **Strongest = C3** (equation/theorem-level fidelity, highest
  headroom) and **C4** (each hard rule pins a distinct axis, cleanly balanced).

### Do the newly-added items (30–49) hold up as well as the originals?

Mostly yes. The new C1 (30–33), C2 (34–37), C3 (38–41), and C4 (42–45) items reuse the
same isolation logic as the originals — checkable feasibility envelopes, anti-obvious
coherence rules, well-anchored expert baselines, and novelty gates — and are graded
PASS on all five gates. The C3-new (38–41, clean Gentner structure-mapping with novelty
gates) and C4-new (42–45, balanced with discriminating hard cases) are arguably as
strong as any originals. The one exception is the **C5 lightweight subset (46–49)**,
which is a visibly weaker tier than the C5 originals (24–29) and accounts for 4 of the
5 REVISE items. Two metadata regressions accompany the new batch: the missing
`category_name` field across all of 30–49, and the placeholder `expert_baseline` in the
one *original* item 09 (unrelated to the new batch, but the only G5 FAIL).
