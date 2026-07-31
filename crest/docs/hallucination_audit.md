> **SUPERSEDED (2026-07-30).** This pass was *knowledge-based triage* — it says so in its own
> method note: live web search was unavailable. A subsequent live-web audit of all 50 items
> (~610 claims, `docs/notes/audit_live_*.md`) found this pass produced **both a false positive and a
> false negative**: it wrongly flagged Hart's inversor (1874-5 is correct) and wrongly suspected the
> Cs2TiI6 band gap was ~1.0-1.5 eV (measured ~1.56 eV). Its applied corrections stand (11 claimed, 10 transcribed below) and are
> retained below for provenance, but its *conclusions* — including "no fabricated sources" — cannot
> be relied on, because that finding is not obtainable without web access. Use the live reports.

# CREST hallucination audit (queries + judge-side metadata)

Fact-check of every factual claim in `query`, `known_answers`, and `expert_baseline` across all 50
items, run by 5 domain agents (one per category). **Method caveat:** live web search was
unavailable this session, so this is *knowledge-based triage* — agents flagged implausible,
mis-attributed, or mis-dated claims from domain knowledge and marked genuinely-uncertain specifics
"unverifiable". A full per-citation web verification remains a pre-release step.

## Headline
No fabricated sources and no source-mathematics errors were found (RG β-function, Cheeger
inequality, Kantorovich duality, sheaf H¹ obstruction, Kingman/Little, knot invariants,
quasispecies↔Ising, fixation≈2s, cent values 701.955/386.314/315.641 — all stated correctly). The
set is unusually well-sourced. Only citation date/venue/attribution slips were found; **2
high-confidence, 8 medium/low**. All actionable ones were corrected.

## Corrections applied (10 listed)
*The prose above says 11; the table below has 10 rows. One correction was applied but never
transcribed here — the count and the table disagree, and the table is the auditable record.*
| Item | Field | Fix | Conf |
|---|---|---|---|
| C4_economics_business_20 | known_answers | *Radical Markets* (2018): "Lanier–Weyl" → **Posner & Weyl** | HIGH |
| C3_arts_humanities_17 | known_answers | "Morphologie du sens" → **"Morphogenèse du sens"**; author → Petitot (in Thom's lineage) | HIGH |
| C2_biology_medicine_06 | known_answers | immunoediting "(Science, 2002-2011)" → "(Nature Immunology 2002; Science 2011)" | med |
| C2_arts_humanities_11 | known_answers | point-at-infinity: "Kepler and Desargues (c.1639)" → "Kepler (1604) and Desargues (c.1639)" | med |
| C2_economics_business_08 | known_answers | removed likely-fabricated "5–20% of U.S. GDP" stat + unconfirmed "Edward Cox 1855" bookend | med |
| C4_economics_business_20 | known_answers | "Dawex (founded 2012)" → "(founded 2015)" | med |
| C1_biology_medicine_00 | known_answers | dynobactin "Nature 2022" → "Nature Microbiology 2022" | med |
| C3_biology_medicine_12 | known_answers | Rashevsky "organismic sets … (~1954)" → "(organismic sets ~1967; relational biology ~1954)" | med |
| C1_engineering_04 | known_answers | Restrepo et al. *Extreme Mechanics Letters* "2016" → "2015" | low-med |
| C4_biology_medicine_18 | known_answers | ICLAC Register "(2010 onward)" → "(2012 onward)" | low |

## Residual low-confidence notes — web-verify before release (not corrected)
- C1_materials_chemistry_01: Cs₂TiI₆ band gap "~1.6–2.0 eV" may be overstated (lit often ~1.0–1.5 eV).
- C1_economics_business_02: Milgrom-Segal deferred-acceptance "2017" (paper 2014 WP / 2020 JPE; 2017 = FCC auction).
- C1_law_policy_03: PNAS Rao et al. "May 2020" (print issue ≈ June 2020).
- C2_engineering_10: "Hubble-class payload" descriptor on Hippke's ~400,000 t example (figure/citation sound).
- C4_arts_humanities_23: CARE Principles "2020" (launched 2019); Dutch "Colonial Collections (2021)" (report 2020); the post-cutoff 2025/2026 restitution events are unverifiable by design (post_cutoff item).
- C5_economics_business_46: "Case-Shiller (1991)" and "Baltic Dry Index (1985)" are lineage-correct but the brand/name dates differ.
- C5_law_policy_47: "Kemeny-Young (1959)" compresses Kemeny 1959 + Young's later MLE characterization.
- C5_engineering_48: "Hart's inversor / A-frame (1874-75)" — A-frame usually dated 1877; Sarrus is a *spatial* linkage listed under a planar-framed query (internal-consistency nit).

## Standing recommendation
Before public release, run a live-web per-citation pass (the deep-research API agents retain web
access even when the top-level search budget is exhausted) to confirm the residual notes and every
"unverifiable" citation, and record per-answer provenance in the datasheet.
