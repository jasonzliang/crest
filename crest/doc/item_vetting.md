# CREST Item Vetting — Adversarial Red-Team

> ## ⚠ PARTLY SUPERSEDED (2026-07-29 pass; annotated 2026-07-31)
>
> This was a **desk review**: every grade below was assigned by reading the item, with **no web
> access and no execution**. Two later passes contradict it, and where they do, **they win**:
>
> 1. **Live-web citation audit of all 50 items** (~610 claims, `docs/notes/audit_live_*.md`,
>    2026-07-30). It found real defects in items this pass graded PASS, and it **overturns the
>    headline G5 finding**: the claim below that "all `known_answers` are dated & non-empty" is
>    false — most entries carry no year at all. The measured rates and the counting convention are
>    in `datasheet.md` §2 ("Prior-art dating"), which is authoritative for them; they are
>    deliberately not restated here, because they were restated in four files and went stale in
>    three. The dating error direction is one-sided: prior art is consistently made to look
>    *younger* than it is, which inflates novelty.
> 2. **Mechanical self-consistency checking** (`analysis/validate_items.py`, wired into
>    `analysis/ci_check.sh`). It reports **2 BLOCKING contradictions, both in
>    `C1_materials_chemistry_01`** — an earlier count of 4 across 3 items included two validator
>    false positives, since fixed. The pre-release gate currently FAILS on them. `_01` was graded
>    REVISE below; the two false positives (`_07`, `_43`) were graded PASS/KEEP.
>
> **Field drift.** The Method paragraph below describes reading `predicted_direction` and the
> designer `rationale` on each item. **Neither field exists any more:** `predicted_direction` and
> `category_name` were removed in schema v2.0.0 (predictions moved to
> `analysis/preregistration.yaml`), and `rationale` moved to `questions/item_design.jsonl` in v3.0.0.
> A judge-hidden `author_expected_surprises` field was added. Items now ship ten fields, not twelve.
>
> **What still stands.** The per-item table is retained as the historical record of the desk pass;
> rows contradicted by a later pass are marked inline with **`→ SUPERSEDED`**. The zero-fabrication
> finding was *confirmed* by the live audit across all five categories. The REVISE dispositions were
> acted on.
>
> **Not re-graded here.** This annotation corrects statements known to be false; it does not re-run
> the five gates against the current file. Treat an unannotated PASS as "not contradicted yet", not
> as verified.

## Method

This is an adversarial item-vetting pass over all 50 CREST challenges in
`questions/crest_challenges.jsonl` (ids ending `00`–`29` are the 30 original items;
`30`–`49` are the 20 newly-added items). Each item was read in full — `query`,
`hard_rules`, `known_answers`, `expert_baseline`, and (at the time) the per-item
`predicted_direction` and designer `rationale` — and stress-tested against five gates.
The goal is not to re-grade a model's answer but to ask whether each *item* actually
measures what it claims to. Gates are marked **PASS / WEAK / FAIL**; each item gets a
disposition (**KEEP / REVISE / CUT**) with a one-line reason. This report does **not**
modify the dataset.

**The five gates:**

1. **G1 Contamination-resistance** — is the answer NOT memorizable / not sitting on a
   single indexed page (genuinely multi-hop)? All items are invention or
   counterfactual tasks with no canonical published answer, and each `known_answers`
   list deliberately pre-claims the memorizable/first-order content, forcing work
   beyond recall. *(→ SUPERSEDED in strength: this was judged by reading. The
   decisive test — a tool-ablation check, scoring a no-web model and cutting anything
   it answers — has never been run, and runs are live-web, not contamination-controlled.
   Read every G1 PASS as "no memorizable answer was apparent", not as measured.)*
2. **G2 Synthesis-required** — does answering truly need multi-source synthesis rather
   than a single lookup?
3. **G3 Axis-isolation** — does it genuinely exercise its labeled isolated axis
   (C1 usefulness, C2 surprise, C3 novelty, C4 balanced, C5 novelty) rather than a
   confound?
4. **G4 Headroom** — is it hard enough not to be saturated by a strong agent
   (not trivially answerable)?
5. **G5 Metadata** — `known_answers` dated & non-empty, `hard_rules` checkable,
   `expert_baseline` present. *(→ SUPERSEDED: the "dated" half of this gate was graded
   by inspection and is wrong at file scale — see the header and `datasheet.md` §2. Every G5 PASS
   below should be read as "non-empty and present", never as "dated".)*

## Per-item assessment

`n/12`-style dating counts below are over an item's **substantive** `known_answers` entries,
excluding its leading `Dated as of …` header entry — the same convention as `datasheet.md` §2.

| id | cat | domain | G1 | G2 | G3 | G4 | G5 | disp. | reason |
|----|-----|--------|----|----|----|----|----|-------|--------|
| C1_biology_medicine_00 | C1 | bio_med | PASS | PASS | PASS | PASS | ~~PASS~~ **→ SUPERSEDED** | KEEP | CRAB novel-MOA; 7 checkable rules + falsifiable experiment cleanly isolate usefulness. **Live audit: 2 WRONG `known_answers` entries** ("dynobactin N" does not exist — it is dynobactin A; "RG6114" is inavolisib, not the LepB inhibitor G0775). Both corrected in the shipped file 2026-07-30 |
| C1_materials_chemistry_01 | C1 | mat_chem | PASS | PASS | PASS | PASS | ~~WEAK~~ **→ FAIL** | **REVISE** | Perovskite top-cell; 12 parametric rules isolate usefulness; KA band-gaps self-flagged unverified. **2 BLOCKING self-contradictions** (`validate_items.py`): R4 requires mu ∈ [0.40, 0.90] but the item's own `expert_baseline` reports mu ≈ 0.39; R6 permits a chalcogenide (S, Se) while R9 bans Se. The rules exclude the class they were written to admit |
| C1_economics_business_02 | C1 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | GPU spot-market mechanism; formal IC/budget-balance rules make usefulness provable |
| C1_law_policy_03 | C1 | law | PASS | PASS | PASS | PASS | PASS | KEEP | LEO-debris instrument; treaty-article + incentive-compat constraints isolate legal-operability |
| C1_engineering_04 | C1 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | FDM energy-absorber; strict SEA/plateau/reusability envelope; usefulness fully checkable |
| C1_arts_humanities_05 | C1 | arts | PASS | PASS | PASS | PASS | WEAK | KEEP | Mnemonic fixed form; usefulness = order-recall efficacy grounded in serial-recall science; KA self-flagged unverified |
| C1_biology_medicine_30 | C1 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Molecular-glue triple; ternary-geometry/lysine/E3-coexpression feasibility isolates usefulness (lighter rule-set) |
| C1_materials_chemistry_31 | C1 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Li superionic conductor; quantitative barrier/window/abundance targets isolate usefulness |
| C1_engineering_32 | C1 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | Daytime radiative cooler; radiative-balance inequality gives checkable usefulness |
| C1_arts_humanities_33 | C1 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | Novel tuning; cents-error/pitch-count arithmetic makes usefulness directly checkable |
| C2_biology_medicine_06 | C2 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | No-adaptive-immunity world; first-order pre-claimed, surprise via cross-field 2nd-order + coherence lock |
| C2_materials_chemistry_07 | C2 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | No-crystallinity world; six-arena scaffold, surprise via inverted/net-benefit consequences. A "1 BLOCKING self-contradiction: one hard rule permits 'Si' while another bans it" verdict was recorded here and was a **validator FALSE POSITIVE**, since fixed — `validate_items.py` reports nothing against this item |
| C2_economics_business_08 | C2 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | No limited liability; partial-counterfactual record anchors surprising-but-true cascades |
| C2_law_policy_09 | C2 | law | PASS | PASS | PASS | PASS | ~~FAIL~~ **→ FIXED** | ~~REVISE~~ **KEEP** | Statute-of-limitations world; design strong. The placeholder `expert_baseline` stub was **replaced with the real 818-char convergent-expectation text**; its enumeration of intended surprises was split into the judge-hidden `author_expected_surprises` field |
| C2_engineering_10 | C2 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | 1.5g world; scaling-law scaffold, surprise via gravity-invariants and direction-reversals |
| C2_arts_humanities_11 | C2 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | No linear perspective; canon pre-claimed, surprise via distant knock-ons + self-undermining test |
| C2_biology_medicine_34 | C2 | bio_med | PASS | PASS | PASS | PASS | ~~PASS~~ **→ SUPERSEDED** | KEEP (conditional) | Non-enucleated RBCs; anti-obvious rule isolates surprise — but the "concrete baseline" was not one. **64% of `expert_baseline` was an answer key**; the residue was 156 chars, failing schema `minLength(200)`, so the item was **quarantined 2026-07-30**. **Restored 2026-07-31** with a 1,620-char baseline (measured on the shipped file) that is explicitly **model-drafted, not expert-written, and still needs physiologist review** |
| C2_materials_chemistry_35 | C2 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Non-protective Al oxide; industrial-chain 2nd-order beyond substitute-metal baseline |
| C2_economics_business_36 | C2 | econ | PASS | PASS | PASS | PASS | ~~PASS~~ **→ WATCH** | KEEP | No shipping container; landed-cost/port-geography 2nd-order surprise. **58% of `expert_baseline` was answer key** (230 chars remain); on the quarantine watch-list |
| C2_law_policy_37 | C2 | law | PASS | PASS | PASS | PASS | ~~PASS~~ **→ WATCH** | KEEP | No plea bargaining; prosecutorial-incentive 2nd-order surprise; multi-source rule. **59% of `expert_baseline` was answer key** (210 chars remain); on the quarantine watch-list |
| C3_biology_medicine_12 | C3 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Category theory→differentiation; novelty gate blocks Rosen/MES; structural-fidelity rules |
| C3_materials_chemistry_13 | C3 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | Pop-gen→solid-state; trivial mappings banned; novelty on deeper terms + disanalogy |
| C3_economics_business_14 | C3 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | Knot theory→ownership networks; unoccupied niche; invariance proof required |
| C3_law_policy_15 | C3 | law | PASS | PASS | PASS | PASS | ~~WEAK~~ **→ CLEARED** | KEEP | RG→federalism; Galam-gated; novelty on competence-allocation dictionary. **Live audit verified all 10 prior-art entries and the RG mathematics; its central negative claim survived ten independent query forms** — the auditor's best-constructed item in the set. The self-flagged-unverified caveat is discharged |
| C3_engineering_16 | C3 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | Pop-gen→software evolution; Lehman-gated; equation-level correspondences + predictions |
| C3_arts_humanities_17 | C3 | arts | PASS | PASS | ~~PASS~~ **→ SUPERSEDED** | PASS | PASS | **REVISE** | Gauge theory→translation; shallow "meaning=invariant" gated; holonomy/curvature layer required. **Live audit: the novelty gate is materially wrong, not merely loose.** The item asserts existing work carries "the invariance HEADLINE only — no connection, no curvature, no Wilson loop"; Coda et al., arXiv:2203.08189 (2022) already builds fiber bundles whose fibers are admissible interpretations, motivated by linguistic ambiguity. **Still missing from `known_answers`** — the gate over-rewards |
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
| C4_biology_medicine_42 | C4 | bio_med | PASS | PASS | ~~PASS~~ **→ WEAK** | PASS | ~~PASS~~ **→ FAIL** | **REVISE** | Preclinical-model selection method; ≥3 traditions + new variable + 2 hard cases bind all three. **Live audit: 0/12 `known_answers` entries dated**, and the two literatures that would refute its flagship novelty claim are absent (Belzung & Lemoine 2011 mechanistic/homological validity; Wehling/Wendler translatability scoring, 2009–2017). Milder version of `_45`'s defect |
| C4_materials_chemistry_43 | C4 | mat_chem | PASS | PASS | ~~PASS~~ **→ SUPERSEDED** | PASS | ~~PASS~~ **→ FAIL** | **REVISE** | Synthesis-route ranking; discriminating hard cases invert green-metrics baseline. A "1 BLOCKING self-contradiction: the rules offer 'atom economy' as a genuinely NEW mechanism while it already appears in this item's own `known_answers`" verdict was a **validator FALSE POSITIVE**, since fixed. Still standing: **0 of its 12 substantive entries dated**; four existing aggregators (GREENSCOPE, EATOS, DOZN, Andraos) and the criticality methodology (Graedel 2012) are missing |
| C4_economics_business_44 | C4 | econ | PASS | PASS | PASS | PASS | ~~PASS~~ **→ WEAK** | KEEP | Killer-acquisition screen; below-threshold/zero-overlap hard cases invert concentration-test baseline. Only 2/12 entries dated (the best of the `_4x` batch); the Art. 22 entry is stale in a way that breaks its own H1 premise |
| C4_engineering_45 | C4 | eng | PASS | PASS | ~~PASS~~ **→ FAIL** | ~~PASS~~ **→ FAIL** | ~~PASS~~ **→ FAIL** | ~~KEEP~~ **DO NOT RELEASE** | Reparability/upgradeability index. **The novelty gate is INVERTED, not merely loose.** Hard rule (d) offers "a software-lock/parts-pairing penalty as a hard multiplier" as its example of a genuinely NEW mechanism, but `known_answers[1]` is the iFixit Repairability Score, whose published rubric already applies a **global** parts-pairing penalty (up to −100%). `expert_baseline` asserts the opposite ("the convergent baseline rarely penalizes software parts-pairing"), so a judge reading the item would *confirm* the false positive rather than catch it. Also 0/12 entries dated, one flatly wrong attribution (Martin & Ishii — **still unfixed in the shipped file**), and the only operative EU repairability score (Reg (EU) 2023/1669) is absent. On the quarantine watch-list |
| C5_biology_medicine_24 | C5 | bio_med | PASS | PASS | PASS | PASS | PASS | KEEP | Categorically-new modality; 26-entry KA + undruggable-biology reasoning; high headroom |
| C5_materials_chemistry_25 | C5 | mat_chem | PASS | PASS | PASS | PASS | PASS | KEEP | New solid-state class; 33-entry KA; single-organizing-principle bar; high headroom |
| C5_economics_business_26 | C5 | econ | PASS | PASS | PASS | PASS | PASS | KEEP | New market for a missing market; IC argument + buildable-now floor keep it hard |
| C5_law_policy_27 | C5 | law | PASS | PASS | PASS | PASS | PASS | KEEP | New future-generations instrument; open-world non-existence proof across many jurisdictions |
| C5_engineering_28 | C5 | eng | PASS | PASS | PASS | PASS | PASS | KEEP | New engineering device; 3-corpus white-space map; no off-the-shelf integration allowed |
| C5_arts_humanities_29 | C5 | arts | PASS | PASS | PASS | PASS | PASS | KEEP | New poetic form; 33-entry cross-lingual catalogue + collision rule; high headroom |
| C5_economics_business_46 | C5 | econ | PASS | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | PASS | **REVISED** | "Invent an economic index"; was negative-verify only and saturable. **Fix applied:** 5 hard rules (was 3) incl. a multi-source absence proof and a non-saturation guard; 21-entry prior-art catalogue |
| C5_law_policy_47 | C5 | law | PASS | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | ~~PASS~~ **→ WEAK** | **REVISED** | "Invent a voting method". **Fix applied** (5 rules, absence proof, non-saturation guard, 20-method catalogue) — but the suggested named social-choice property was not added, and the catalogue is **still incomplete**: Phragmén 1894, Nanson 1882 and random ballot are absent, and Bucklin is dated 1909 when the method is Condorcet 1793 |
| C5_engineering_48 | C5 | eng | PASS | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | PASS | **REVISED** | "Invent a planar linkage". **Fix applied:** 5 rules incl. a determinate Grübler–Kutzbach mobility bar, absence proof and non-saturation guard; 21-entry catalogue |
| C5_arts_humanities_49 | C5 | arts | PASS | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | ~~WEAK~~ **→ REVISED** | ~~PASS~~ **→ FAIL** | **REVISED** | "Invent a musical form". **Fix applied** (5 rules, absence proof, non-saturation guard, 21-entry catalogue), but the suggested fully-worked realized example was not required, and the catalogue is **bare and undated** — confirmed by two independent audit passes |

## Summary

**Dispositions (as graded 2026-07-29):** KEEP = 45 · REVISE = 5 · CUT = 0.
*(The table below no longer reproduces that split: four rows -- `01`, `17`, `42`, `43` -- had their
disposition cell overwritten with **REVISE** without a strikethrough, unlike `45`
(`~~KEEP~~ **DO NOT RELEASE**`). Parsing the table as it stands gives KEEP 40 / REVISE 5 /
REVISED 4 / DO-NOT-RELEASE 1. The 45/5/0 line is the ORIGINAL 2026-07-29 grading; the table records
the state after later revisions.)*

**→ SUPERSEDED.** After the live-web audit and mechanical validation, the standing count is:
5 REVISE items **fixed or acted on** (09's baseline restored; 46–49 hardened to 5 rules with
absence-proof and non-saturation guards), and **6 items newly flagged** that this pass graded
KEEP — `01` (the only item with BLOCKING self-contradictions), `00` (2 wrong prior-art entries,
since corrected), `17` (over-permissive novelty gate, unfixed), `42`/`44` (undated / pruned prior
art), and `45` (**inverted novelty gate — "do not release"**). Plus `34`, quarantined and then
restored on a model-drafted baseline. `07` and `43` were flagged here too and were **validator
false positives, since fixed** — they are not part of the count. The pre-release gate
(`analysis/ci_check.sh`) fails on `01`'s two blocking contradictions.

### REVISE items and the specific fix

> **Status 2026-07-31: all five were acted on.** 09's baseline was restored in full. 46–49 were
> hardened — each now carries **5 hard rules** (was 3) including a multi-source absence proof and an
> explicit non-saturation guard, plus a ~21-entry prior-art catalogue. The *generic* hardening
> landed; two of the *item-specific* bars proposed below did not (47's named social-choice property,
> 49's fully-worked realized example), and 47's and 49's catalogues remain incomplete/undated.

- **C2_law_policy_09** (G5 FAIL — **now FIXED**) — `expert_baseline` was a placeholder stub
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
  - *G1 (contamination):* uniformly strong **on inspection**. The invention/counterfactual format
    plus `known_answers` lists that pre-claim the memorizable and first-order content make
    the whole set look genuinely multi-hop; no item was found answerable from a single indexed
    page. **→ SUPERSEDED as a measurement:** no tool-ablation check was run, and runs use live web
    search with no frozen index, so search-time contamination is uncontrolled and unmeasured.
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
    **→ SUPERSEDED twice over.** (a) The "handled by … expert baselines" mitigation no longer
    operates: `expert_baseline` is judge-hidden as of 2026-07-30 because ablating it barely moved
    Surprising, and New and Surprising correlate hard in the run data. That correlation is
    **CONTAMINATED** — the v1 judge prompt stated it to the judge — so it does **not** license the
    conclusion "the axes do not dissociate", which an earlier version of this line drew. Figures
    and caveat: `design.md` §0. (b) The axis labels were measured against judge verdicts and
    mostly do not bind: valid for C1/usefulness only, wrong-signed for novelty. Rates: `design.md`
    §0. The 56% / 21% / 15% previously quoted here came from superseded run `111856Z` (n=196).
  - *G4 (headroom):* C1/C3/C4 are the hardest tiers and clearly unsaturated; only
    46–49 are saturable.
  - *G5 (metadata):* ~~all `known_answers` are dated & non-empty~~ **→ FALSE, see header.**
    `known_answers` is non-empty everywhere (8–33 entries per item) and `hard_rules` are checkable
    (5–12 rules per item in the shipped file), but most prior-art entries carry no year, and the
    `_3x`/`_4x` half of the file is far worse than the first half — rates in `datasheet.md` §2.
    One hard FAIL at the time (09, broken `expert_baseline`) — since fixed; a second (34) was
    found later by schema enforcement.
- ~~**Missing `category_name` in every new item.**~~ **→ MOOT.** `category_name` was removed from
  *all* 50 items in schema v2.0.0 (it was derivable from `category`, and one item shipped a
  long-form value that made `groupby` yield six categories). There is nothing to backfill.
- **Self-flagged unverified `known_answers`.** Three items (01, 05, 15) noted that the web-search
  budget was exhausted before verification. **→ Now resolved by the live audit:** `15` is fully
  verified (all 10 prior-art entries check out); `05` and `33` and `32` came back clean; `01`'s
  Cs₂TiI₆ band gap is half-corroborated (the 1.56 eV direct figure holds; the indirect figure does
  not reproduce) and it retains two IMPRECISE entries plus the two blocking rule contradictions
  above.
- **Weakest category = C5.** Its open-ended novelty framing makes synthesis thin and
  headroom fragile; the originals hold up only because of large `known_answers` sets
  and heavy deliverables. **Strongest = C3** (equation/theorem-level fidelity, highest
  headroom) and ~~**C4**~~ **→ SUPERSEDED on C4.** The live audit rates C4-new the *weakest*
  block in the file: `_45`'s novelty gate is inverted, `_42`'s is close behind, and 46 of 48
  substantive prior-art entries across `_42`–`_45` carry no year at all. C3's own
  standing is also qualified — the audit found five mathematical errors in C3 hard rules and one
  materially wrong novelty gate (`_17`), though it confirmed zero fabrications across ~155 checked
  claims.

### Do the newly-added items (30–49) hold up as well as the originals?

**→ SUPERSEDED. The answer measured by the live audit is: no.** The desk pass concluded "mostly
yes", reasoning that the new C1 (30–33), C2 (34–37), C3 (38–41) and C4 (42–45) items reuse the
originals' isolation logic — checkable feasibility envelopes, anti-obvious coherence rules,
well-anchored expert baselines, novelty gates — and graded them PASS on all five gates. Two things
that reading could not see turned out to separate the halves of the file:

1. **The citation cliff.** Prior-art dating collapses from the `_1x` block to the `_3x`/`_4x`
   blocks (rates: `datasheet.md` §2). Whoever wrote the back half of the file stopped citing, and
   an undated bare name cannot gate novelty at all — a judge cannot ask "absent as of date D" when
   D is unstated.
2. **Gate inversion.** `_45`'s hard rule offers as its example of a new mechanism something its own
   prior-art list already implements, and its baseline asserts the opposite of the truth, so the
   gate awards novelty for reproducing published prior art. `_42` and `_43` have milder versions.

The **C5 lightweight subset (46–49)** — the one weakness this pass did catch — has since been
hardened. The metadata regressions it named have both closed: `category_name` no longer exists on
any item, and 09's placeholder baseline was replaced. They were replaced by different ones: 34's
baseline is model-drafted, and `_3x`/`_4x` prior art is largely undated.
