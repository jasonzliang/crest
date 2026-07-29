# CREST question audit — do the questions, count, and detail make sense?

Audit of `questions/crest_challenges.jsonl` against the CREST design, the related-work research,
and the Caesar reference (arXiv:2604.20855). **Verdict: the questions are high quality and
well-formed; the *detail* is excellent; the *count* (30) is a strong v1 but underpowered for the
paper's confirmatory statistics — scale to ~10/category before claiming the finding.**

## 1. Structure (verified programmatically)
- **30 challenges**, balanced: **6 per category** (C1–C5) × **5 per domain** (6 domains:
  bio/medicine, materials/chemistry, econ/business, law/policy, engineering, arts/humanities).
- **All metadata present** (0 missing across all 30): `known_answers`, `hard_rules`,
  `expert_baseline`, `axis_isolated`, `time_sensitivity`, `rationale`, `query`.
- Query length **627–3390 chars** (median 2185) — substantial, self-contained prompts.
- `known_answers` lists: **8–33 entries** (median 13), each **dated to the ~Jan-2026 cutoff**.
- Predicted directions: 12 predicted-null, 12 favored, 6 parity — matches the pre-registered
  mechanistic hypothesis.

## 2. Content quality (sampled one item per category, read in full)
Exemplary on the dimensions ICLR reviewers scrutinize:
- **Axis isolation is real, not nominal.** C1 (CRAB antibiotic) pins *Useful* with 7 checkable
  hard rules (novel target, essentiality dataset named, resistome durability, selectivity,
  permeability, non-duplication, one falsifying experiment); C3 (gauge-theory→translation) pins
  *New* with a novelty gate listing the already-claimed correspondences; C2 (no-perspective
  counterfactual) pins *Surprising* by pre-claiming the obvious first-order effects.
- **Contamination-aware novelty.** "New" is judged against a *dated known-answers list*, not the
  open web — the correct design (avoids penalizing grounding; matches the Caesar spec).
- **Calibrated surprise.** Each item ships an `expert_baseline` (the convergent expected answer);
  matching it scores low surprise. This operationalizes surprise as expectation-violation.
- **Checkable usefulness.** Hard rules are graders' checklists (named datasets, falsifiable tests),
  not vibes — this is stronger than most published creativity benchmarks.
- **Mechanistic rationale per item** ties each to the predicted direction, supporting
  pre-registration.

## 3. Alignment with the Caesar reference
- The **5 categories = Caesar's 5 pilot task types**; the **N/U/S rubric** matches; the
  **predicted directions match the pilot pattern** (C2/C3 favored 18–5, 20–2; C1/C5 null 5–18,
  7–15; C4 parity 13–9). CREST faithfully productionizes the Caesar seeds (1/category → 6/category,
  6×) while adding dated known-answers, hard rules, and expert baselines the pilot lacked.

## 4. Does the COUNT make sense?
- **30 is a coherent, high-quality v1**, but it is **underpowered for the confirmatory claims**.
  The headline is a *crossover interaction* (agent × category) plus *TOST equivalence* on the
  predicted-null/parity cells — both are power-hungry, and at **~6 items/cell** the paper itself
  (and the reviewer panel) flags them as hypothesis-generating, not confirmatory.
- **Recommendation: scale to ≥10 items/category (≥50 total)** before claiming the finding — this
  is exactly what the P3 draft states ("50 questions") and what the benchmark-track reviewers
  asked for. Keep the current 30 as the pre-registered core; add fresh held-out items for the
  confirmatory run.

## 5. Does the DETAIL make sense?
- **Yes — arguably more detailed than necessary, in a good way.** Each item is effectively a
  mini-rubric. Two cautions: (i) very long, highly-specified prompts can *steer* the answer (less
  room for open creativity) — acceptable for C1–C4 (which isolate an axis) but keep C5 lighter to
  preserve open-endedness; (ii) detail this specific must be **red-teamed per item** for a single
  unintended "intended answer."

## 6. Required fixes before release
1. **Run the committed adversarial item-vetting pass** (contamination / synthesis-required /
   axis-isolation / headroom / metadata) and log per-item dispositions in `datasheet.md`
   (§ appendix, currently a placeholder).
2. **Neutralize author-identifying labels for double-blind**: `predicted_direction: "caesar_win"`
   → `"favored"`; scrub the string "Caesar" from `rationale` fields in the *released* dataset
   (keep the mechanism language internal).
3. **Scale to ~10/category** (couple with the C6 decision in `category_coverage.md` if adding a
   category).
4. **Lighten C5 prompts** slightly so open-endedness is not over-constrained.

## One-line verdict
Right questions, right evaluations, excellent detail; the only substantive gap is **count/power** —
grow from 6 to ~10 items per category before the finding is claimed as confirmatory.
