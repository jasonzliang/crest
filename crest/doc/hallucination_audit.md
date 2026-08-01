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

## Residual low-confidence notes — **all but two closed by the live-web pass**
The live-web audit (`docs/notes/audit_live_*.md`, 2026-07-30) resolved these and the resulting item
edits are recorded machine-readably in `docs/notes/hallucination_audit_live_log.jsonl` — that file,
not this list, is the auditable record of what changed. Dispositions:

- **CORRECTED in the item file** (see the log): `C1_economics_business_02` (Milgrom-Segal 2014, not
  2017), `C1_law_policy_03` (PNAS issue date), `C4_arts_humanities_23` (CARE 2019; Dutch report
  2020), `C5_economics_business_46` (Case-Shiller / Baltic Dry brand vs lineage dates),
  `C5_law_policy_47` (Kemeny 1959 + Young's later MLE characterization),
  `C2_engineering_10` (Hubble-class payload descriptor), `C5_engineering_48` (Sarrus is a *spatial*
  linkage under a planar-framed query).
- **THIS PASS WAS WRONG:** `C5_engineering_48`'s Hart's inversor date (1874-5 is correct), and
  `C1_materials_chemistry_01`'s Cs₂TiI₆ band gap was **not** overstated — 1.56 eV direct measured.
- **STILL OPEN:** the post-cutoff 2025/2026 restitution events in `C4_arts_humanities_23` are
  unverifiable by design (it is the file's only `post_cutoff` item).

## Standing recommendation
The live-web per-citation pass this section asked for **was run** across all 50 items
(`docs/notes/audit_live_*.md`, ~610 claims). What it did not deliver, and what release still needs:
per-answer provenance in the datasheet, and a resolvable DOI per `known_answers` entry — about half
of them still carry no year at all (`docs/datasheet.md` §2, "Prior-art dating").
