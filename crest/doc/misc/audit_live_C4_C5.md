# Live-Web Citation Audit — C4 / C5 items

**Scope:** the 20 items with `id` starting `C4_` or `C5_` in `questions/crest_challenges.audit.jsonl`
**Date of audit:** 2026-07-30
**Method:** live WebSearch + WebFetch (Wikipedia, primary institutional pages, Crossref API, PubMed, press releases). No `.jsonl` file was modified.
**Fields examined:** `known_answers`, `expert_baseline`, `query`, `hard_rules`.

> **Headline: zero fabrications.** Every named index, metric, method, paper, institution, standard, and
> instrument I was able to check exists and is attributed to the right people. The defects are all
> *date-precision* defects of one recurring type (see "Systemic pattern") plus **one genuine
> internal-consistency error** (Sarrus, `C5_engineering_48`).

---

## 1. Summary table

### 1a. Priority claims flagged by the prior offline audit

| Item | Claim | Verdict | Correct value | Source |
|---|---|---|---|---|
| `C4_arts_humanities_23` #15 | "Dutch 'Colonial Collections' advisory committee framework (2021) enabling unconditional returns" | **IMPRECISE** | Three distinct events conflated: (a) Gonçalves-Ho Kang You committee report *Colonial Collections and a Recognition of Injustice*, published **7 Oct 2020** by the Raad voor Cultuur; (b) government **policy vision** (*Beleidsvisie collecties uit een koloniale context*) adopting it, incl. unconditional return, **Jan 2021**; (c) the standing advisory committee itself (*Adviescommissie teruggave cultuurgoederen uit koloniale context* / Commissie Koloniale Collecties) established by decree of the State Secretary for OCW on **6 Sept 2022**. The prior audit was right that the *report* is 2020. | https://nltimes.nl/2020/10/07/netherlands-advised-return-art-looted-colonial-era · https://english.cultureelerfgoed.nl/topics/c/cultural-goods-from-a-colonial-context/policy-in-the-netherlands · https://commissie.kolonialecollecties.nl/over-de-commissie |
| `C4_economics_business_20` #2 | "Dawex (founded 2015)" | **CONFIRMED** | Founded 2015 in Lyon by Fabrice Tocco and Laurent Lafaye. Nuance only: the *Dawex Global Data Marketplace* product launched **2017**; 2015 is company founding. | https://www.dawex.com/en/about/our-story/ · https://www.cbinsights.com/company/dawex |
| `C4_economics_business_20` #10 | "Posner & Weyl 'Radical Markets' (2018)" | **CONFIRMED** | Eric A. Posner & E. Glen Weyl, *Radical Markets: Uprooting Capitalism and Democracy for a Just Society*, Princeton UP, 2018. The prior pass's correction away from "Lanier-Weyl" was **correct**. See §3 for a surviving inconsistency in `C5_economics_business_26`. | https://press.princeton.edu/books/hardcover/9780691177502/radical-markets |
| `C4_biology_medicine_18` #14 | "ICLAC Register of Misidentified Cell Lines (2012 onward)" | **IMPRECISE** | The **Register predates ICLAC**. It was "originally developed by Amanda Capes-Davis and Ian Freshney, and published in 2010" (Capes-Davis et al., *Int J Cancer* 2010;127:1-8, PMID 20143388). **ICLAC was formed in 2012**, following ANSI/ATCC ASN-0002-2011, and now curates the Register (latest: v14, 15 Feb 2026). | https://iclac.org/databases/cross-contaminations/ · https://iclac.org/about-iclac/ |
| `C5_economics_business_46` #16 | "S&P/Case-Shiller Home Price Index (1991)" | **IMPRECISE** (lineage-correct, brand-date wrong) | Methodology: Case & Shiller weighted-repeat-sales, late 1980s. **Case Shiller Weiss, Inc. founded 1991** (Allan Weiss with Case & Shiller); CSW produced the US indices 1991-2002. **Fiserv acquired CSW in 2002, when Standard & Poor's began publishing → the "S&P/Case-Shiller" brand dates to 2002.** CoreLogic acquired the business Apr 2013 ("S&P CoreLogic Case-Shiller"); now "S&P Cotality Case-Shiller". | https://en.wikipedia.org/wiki/Case%E2%80%93Shiller_index · https://en.wikipedia.org/wiki/Allan_Weiss |
| `C5_economics_business_46` #19 | "Baltic Dry Index (1985)" | **IMPRECISE** (lineage-correct, brand-date wrong) | The Baltic Exchange first published the **Baltic Freight Index (BFI) on 4 Jan 1985** (13 voyage routes, settlement mechanism for the BIFFEX futures contract). The **Baltic Dry Index launched 1 Nov 1999**, replacing the BFI and switching from spot voyage rates to timecharter averages for Capesize/Panamax/Handysize. | https://en.wikipedia.org/wiki/Baltic_Dry_Index · https://transportgeography.org/contents/chapter3/transport-costs/baltic-dry-index/ |
| `C5_law_policy_47` #17 | "Kemeny-Young method (1959) — maximum-likelihood ranking" | **IMPRECISE** (the year+gloss pairing is strictly wrong) | Prior audit confirmed. Three separate contributions: **Kemeny 1959** (*Mathematics without numbers*, Daedalus 88:577-591) gives the Kendall-tau **distance-minimizing** rule — *not* an MLE claim. **Young & Levenglick 1978** (*A Consistent Extension of Condorcet's Election Principle*, SIAM J. Appl. Math. 35(2):285-300) give the axiomatic characterization — this is where the "Young" in the name comes from. **Young 1988** (*Condorcet's Theory of Voting*, APSR 82(4):1231-1244; also *Optimal Voting Rules*, JEP 9(1), 1995) supplies the **maximum-likelihood-estimator** interpretation. | https://en.wikipedia.org/wiki/Kemeny_method |
| `C5_engineering_48` #10 | "Sarrus linkage — rotation to rectilinear translation", listed as prior art for a **planar**-linkage invention query | **WRONG — internal-consistency error** | Sarrus (Pierre Frédéric Sarrus, **1853**) is a **spatial** single-loop overconstrained **6R** mechanism, a "space crank". Wikipedia, verbatim: *"The Sarrus linkage is of a three-dimensional class sometimes known as a space crank, unlike the Peaucellier–Lipkin linkage which is a planar mechanism."* The motion description ("rotation to rectilinear translation") is correct; the **classification as in-scope planar prior art is not**. See §4 for why this is a scoring bug, not a citation slip. | https://en.wikipedia.org/wiki/Sarrus_linkage |

### 1b. `C4_arts_humanities_23` post-cutoff assessment (the item is labelled `post_cutoff`)

The 2025/2026 restitution events in `known_answers` #16 are **real and independently verifiable on the
live web** — they are *not* unverifiable-by-design, and they are unusually accurate.

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| "Netherlands returning 119 bronzes (Feb and June 2025)" | **CONFIRMED** | Transfer agreement signed **19 Feb 2025** at the Wereldmuseum Leiden (Dutch culture minister Eppo Bruins + NCMM DG Olugbile Holloway); formal handover **21 June 2025** (Lagos/Edo State, received by Oba Ewuare II). Largest single return of Benin material tied to the 1897 expedition. | https://www.aljazeera.com/amp/news/2025/6/21/the-netherlands-returns-119-stolen-sculptures-to-nigeria · https://www.npr.org/2025/02/21/g-s1-50111/benin-bronze-netherlands-nigeria |
| "three Swiss museums agreeing to transfer 28 bronzes with some remaining on long-term loan … (2026-03)" | **CONFIRMED** (date exact) | Transfer of ownership of **28 objects**, signed **20 March 2026**; handover ceremony National Museum Lagos **29 June 2026**. Three museums: Ethnographic Museum, University of Zurich (14 returned), Museum Rietberg Zurich (2), Musée d'Ethnographie de Genève (2) = 18 physically returned; **9 remain on long-term loan at Rietberg + 1 at MEG** = 10. 18 + 10 = 28 ✓. (5 further objects seized by Swiss authorities returned under separate proceedings.) | https://www.musethno.uzh.ch/en/About-us/News/260629-media-release-benin-artefacts.html · https://www.euronews.com/culture/2026/06/30/switzerland-returns-18-looted-benin-bronzes-to-nigeria |
| "…at Nigeria's request" (the Swiss loan-back) | **UNVERIFIABLE** | The UZH media release documents the loan arrangement but does **not** attribute the request to Nigeria. The Swiss federal release (admin.ch) returned HTTP 403 to automated fetch. Recommend softening to "with some remaining on long-term loan". | https://www.musethno.uzh.ch/en/About-us/News/260629-media-release-benin-artefacts.html (loans stated, attribution absent) |
| "Germany's transfer of ~1,100 Benin Bronzes (2022, first physical returns 2022-12)" | **IMPRECISE** | Joint political declaration **1 July 2022** covering **1,130** objects — "~1,100" is fine. But **two objects (an Oba head and a 16th-c. plaque) were physically handed to Nigerian representatives at the 1 July 2022 Berlin signing**; the first delivery *on Nigerian soil* was **20 objects in Abuja, 20 Dec 2022**. "First physical returns 2022-12" needs qualifying. | https://kulturstaatsminister.de/fileadmin/user_upload/Downloads/Aufarbeiten/2022-07-01-Joint-Declaration-Benin-Bronzes.pdf · https://www.theartnewspaper.com/2022/07/04/the-benin-bronzes-are-returning-home-germany-and-nigeria-sign-historic-restitution-agreement |
| "Nigeria's designation of the Oba as private royal custodian (2023-03)" | **CONFIRMED** | Decree/gazette issued by outgoing President Buhari **23 March 2023**, vesting repatriated Benin Expedition objects (incl. future returns) in the Oba of Benin / the Royal Family in Benin City. | https://en.wikipedia.org/wiki/Benin_Bronzes |
| "Digital Benin database launched 2022-11 (5,000+ objects across 130+ institutions)" | **CONFIRMED** | Launched **4 Nov 2022**; 5,240+ objects; **131** museums/institutions across 20 countries; hosted by MARKK Hamburg. | https://www.museumsassociation.org/museums-journal/news/2022/11/digital-benin-project-unveils-online-platform/ · https://digitalbenin.org/documentation/introduction |
| #7 "Declaration on the Importance and Value of Universal Museums (2002) … ~18 major museums" | **CONFIRMED** | Issued **December 2002** by the directors of **18** European and US museums (Art Institute of Chicago, Staatliche Museen zu Berlin, Cleveland, Getty, Guggenheim, Louvre, Met, MFA Boston, MoMA, …). | https://www.elginism.com/similar-cases/declaration-on-the-importance-of-the-universal-museum/20021211/4620/ |

**Verdict on the `post_cutoff` label:** correct and well-used. The item's post-cutoff content is
*genuinely* checkable rather than a hedge. **But it creates a maintenance liability**: `known_answers`
#16 hard-codes a March 2026 event, and the Benin restitution timeline is still moving (the Swiss
handover on 29 June 2026 already post-dates the entry's framing). A benchmark shipping publicly needs
either a dated snapshot marker on this entry or a policy of re-verifying it per release.

### 1c. Other claims verified live (second tier)

| Item | Claim | Verdict | Note / source |
|---|---|---|---|
| `C4_economics_business_20` #2 | "AWS Data Exchange (launched Nov 2019)" | **CONFIRMED** | GA announced **13 Nov 2019**, 1,000+ products / 80+ providers. https://aws.amazon.com/about-aws/whats-new/2019/11/introducing-aws-data-exchange |
| `C4_economics_business_20` #4 | "IAS 38 effective 2004, ongoing" (attributed to "IASB") | **IMPRECISE** | IAS 38 was **issued September 1998 by the IASC** (not the IASB), adopted by the IASB April 2001, and **revised March 2004** (revised version effective for annual periods beginning on/after 31 Mar 2004). https://www.iasplus.com/en/standards/ias/ias38 · https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/ |
| `C4_economics_business_20` #11 | OECD "Measuring the Economic Value of Data and Cross-Border Data Flows" (2020) | **CONFIRMED** | Nguyen, D. & Paczos, M. (2020), *OECD Digital Economy Papers* **No. 297**, Aug 2020. https://www.oecd.org/en/publications/measuring-the-economic-value-of-data-and-cross-border-data-flows_6345995e-en.html |
| `C4_biology_medicine_18` #2 | "Begley & Ellis (2012, Nature, 'Amgen', 6/53 preclinical oncology studies reproduced)" | **CONFIRMED** | *Drug development: Raise standards for preclinical cancer research*, Nature 483(7391):531-533, 28 Mar 2012. (The 6-of-53 figure is in the commentary body/Table 1; PubMed carries no abstract.) https://pubmed.ncbi.nlm.nih.gov/22460880/ |
| `C4_biology_medicine_18` #11 | "Alipourfard et al. (2021, preprint) — 'Systematizing Confidence in Open Research and Evidence'" | **CONFIRMED** | Crossref: *Systematizing Confidence in Open Research and Evidence (SCORE)*, Alipourfard et al., 2021, DOI **10.31235/osf.io/46mnb** (SocArXiv). https://doi.org/10.31235/osf.io/46mnb |
| `C4_biology_medicine_18` #14 | "Cellosaurus (Bairoch, 2018, Journal of Biomolecular Techniques)" | **CONFIRMED** | Bairoch A., *The Cellosaurus, a Cell-Line Knowledge Resource*, J Biomol Tech 2018;**29(2):25-38**, PMID 29805321, DOI 10.7171/jbt.18-2902-002. https://pubmed.ncbi.nlm.nih.gov/29805321/ |
| `C4_biology_medicine_18` #16 | "SciScore and the Rigor-and-Transparency Index (Menke, Bandrowski et al., 2020, iScience)" | **CONFIRMED** | Menke, Roelandse, Ozyurt, Martone, Bandrowski, iScience 2020, DOI 10.1016/j.isci.2020.101698. |
| `C4_engineering_22` #4 | "Process-capability indices Cp/Cpk (Victor Kane, J. Quality Technology, 1986)" | **CONFIRMED** | Kane, V.E., *Process Capability Indices*, JQT 1986, DOI 10.1080/00224065.1986.11978984. |
| `C4_engineering_22` #4 | "Cpm (Chan–Cheng–Spiring, 1988)" | **CONFIRMED** | Chan, Cheng & Spiring, *A New Measure of Process Capability: Cpm*, JQT 1988, DOI 10.1080/00224065.1988.11979102. |
| `C4_law_policy_21` #8 | "Libgober (2020, 'Meetings, Comments, and the Distributive Politics of Rulemaking', QJPS)" | **CONFIRMED** | Quarterly Journal of Political Science **vol. 15**, 2020, DOI 10.1561/100.00018135. |
| `C4_materials_chemistry_19` #3 | "Krivovichev structural-complexity (Acta Cryst. A, 2012)" | **CONFIRMED** | *Topological complexity of crystal structures: quantitative approach*, Acta Cryst A 2012, DOI 10.1107/S0108767312012044. |
| `C5_economics_business_46` #18 | "Herfindahl-Hirschman Index (1945/1950)" | **CONFIRMED** | The dual dating is the standard and correct one: Hirschman, *National Power and the Structure of Foreign Trade* (1945); Herfindahl, *Concentration in the Steel Industry* dissertation (1950); Hirschman's own priority note *The Paternity of an Index* (1964). https://en.wikipedia.org/wiki/Herfindahl%E2%80%93Hirschman_index |
| `C5_law_policy_47` #18 | "STAR voting (Score-Then-Automatic-Runoff, ~2014)" | **IMPRECISE** (same brand-vs-concept pattern) | Proposed **October 2014** by **Mark Frohnmayer** as **Score Runoff Voting (SRV)**; the "STAR / Score Then Automatic Runoff" name came later (2017-18). The *method* date ~2014 is right; the *name* is not from 2014. https://en.wikipedia.org/wiki/STAR_voting |
| `C5_law_policy_47` #15 | "Bucklin voting (~1909) — sequential rank accumulation" | **IMPRECISE — and it matters for novelty gating** | 1909 = first US use, Grand Junction, Colorado; named for Georgist politician James W. Bucklin. But **the method was proposed by Condorcet in 1793** and reportedly used by the Republic of Geneva that same year. The effective prior-art date is **1793**, not 1909. https://en.wikipedia.org/wiki/Bucklin_voting |
| `C5_law_policy_27` #1 | "Finland — Committee for the Future: **permanent standing committee** … established 1993" | **IMPRECISE** | Established **1993 as a temporary committee**; the Eduskunta granted it **permanent standing-committee status in 2000**. The parenthetical "(the first standing parliamentary future-generations body)" therefore attaches to the wrong year. https://unu.edu/cpr/blog-post/parliamentary-committees-future-legislative-movement-overcome-political-myopia · https://eptanetwork.org/static-html/comparative-table/countryreport/finland.html |
| `C5_engineering_48` #10 | Sarrus, 1853, Pierre Frédéric Sarrus, "space crank", pre-dates Peaucellier | **CONFIRMED** (confirms the error in 1a) | https://en.wikipedia.org/wiki/Sarrus_linkage |

### 1d. `expert_baseline` fields

Checked all 20. They contain **essentially no falsifiable dated claims** — they are prose descriptions
of the convergent expert answer and the surprise threshold. The only embedded factual references are
"NAGPRA 2024" (`C4_arts_humanities_23`, consistent with `known_answers` #10 and correct),
"Shiller (2003)" (`C5_economics_business_26`, *The New Financial Order*, 2003 — correct), and
"RFdiffusion/AlphaFold3 era" (`C5_biology_medicine_24` — RFdiffusion 2023, AlphaFold 3 May 2024, correct).
**No defects found in `expert_baseline`.**

---

## 2. Counts by verdict

Counted at the level of *discrete checkable claims verified against a live source*, not per item.

| Verdict | Count |
|---|---|
| **CONFIRMED** | **19** |
| **IMPRECISE** | **11** |
| **WRONG** | **1** (Sarrus placement, `C5_engineering_48` #10) |
| **UNVERIFIABLE** | **2** |
| **FABRICATED** | **0** |
| Total live claim-checks | **33** |

UNVERIFIABLE detail:
1. `C4_arts_humanities_23` #16 — "at Nigeria's request" (Swiss loan-back). Tried: admin.ch federal
   press release (**HTTP 403**), UZH Ethnographic Museum release (loans documented, attribution
   absent), Euronews/swissinfo/artnet coverage (no attribution). Recommend removing the attribution.
2. `C5_biology_medicine_24` #19 — "Oncolytic viruses … approvals since 2015". Flagged but **not
   live-verified** (WebSearch budget exhausted at 200/200). To my knowledge this is US/EU-centric:
   Rigvir was approved in Latvia in 2004 and Oncorine (H101) in China in 2005; T-VEC/Imlygic (FDA Oct
   2015, EMA Dec 2015) is the first *Western* approval. **Needs a live check before release.**

---

## 3. Exact old → new replacements

Recommended text edits. **No `.jsonl` file was modified by this audit.**

**`C4_arts_humanities_23`, `known_answers` #15**
- old: `Dutch 'Colonial Collections' advisory committee framework (2021) enabling unconditional returns`
- new: `Dutch colonial-collections framework: Gonçalves Committee report 'Colonial Collections and a Recognition of Injustice' (Council for Culture, Oct 2020); government policy vision adopting it, incl. unconditional return (Jan 2021); standing Colonial Collections Committee (Adviescommissie teruggave cultuurgoederen uit koloniale context) established Sept 2022`

**`C4_arts_humanities_23`, `known_answers` #16**
- old: `Germany's transfer of ~1,100 Benin Bronzes (2022, first physical returns 2022-12)`
- new: `Germany's transfer of 1,130 Benin Bronzes (joint declaration 1 July 2022, with 2 objects handed over at the Berlin signing; first delivery in Nigeria 20 Dec 2022, 20 objects)`
- old: `three Swiss museums agreeing to transfer 28 bronzes with some remaining on long-term loan at Nigeria's request (2026-03)`
- new: `three Swiss museums (Ethnographic Museum UZH, Museum Rietberg Zurich, MEG Geneva) transferring ownership of 28 objects (signed 2026-03-20), 18 physically returned and 10 remaining on long-term loan in Switzerland (handover 2026-06-29)`

**`C4_economics_business_20`, `known_answers` #4**
- old: `IAS 38 effective 2004, ongoing`
- new: `IAS 38 issued Sept 1998 by the IASC, adopted by the IASB 2001, revised March 2004, ongoing`

**`C4_biology_medicine_18`, `known_answers` #14**
- old: `ICLAC Register of Misidentified Cell Lines (2012 onward)`
- new: `ICLAC Register of Misidentified Cell Lines (register first published 2010 by Capes-Davis & Freshney, Int J Cancer 127:1-8; curated by ICLAC since its formation in 2012; v14, 2026)`

**`C5_economics_business_46`, `known_answers` #16**
- old: `S&P/Case-Shiller Home Price Index (1991) — repeat-sales housing prices.`
- new: `Case-Shiller repeat-sales home price index — methodology Case & Shiller (late 1980s); produced by Case Shiller Weiss Inc. from 1991; published under the S&P/Case-Shiller brand from 2002; now S&P Cotality Case-Shiller.`

**`C5_economics_business_46`, `known_answers` #19**
- old: `Baltic Dry Index (1985) — dry-bulk shipping freight cost.`
- new: `Baltic Dry Index — dry-bulk shipping freight cost; predecessor Baltic Freight Index published from 4 Jan 1985, reconstituted and renamed as the BDI on 1 Nov 1999.`

**`C5_law_policy_47`, `known_answers` #17**
- old: `Kemeny-Young method (1959) — maximum-likelihood ranking.`
- new: `Kemeny-Young method — Kemeny (1959, Daedalus) distance-minimizing (Kendall-tau) ranking; Young & Levenglick (1978, SIAM J. Appl. Math.) axiomatic characterization; Young (1988, APSR) maximum-likelihood interpretation.`

**`C5_law_policy_47`, `known_answers` #18**
- old: `STAR voting (Score-Then-Automatic-Runoff, ~2014).`
- new: `STAR voting (Score Then Automatic Runoff) — proposed Oct 2014 by Mark Frohnmayer as Score Runoff Voting (SRV); renamed STAR ~2018.`

**`C5_law_policy_47`, `known_answers` #15**
- old: `Bucklin voting (~1909) — sequential rank accumulation.`
- new: `Bucklin voting / Grand Junction system — sequential rank accumulation; proposed by Condorcet (1793) and reportedly used by the Republic of Geneva the same year; re-invented and first used in the US at Grand Junction, Colorado (1909).`

**`C5_engineering_48`, `known_answers` #10** — pick one:
- (preferred) **delete the entry**, since a spatial mechanism is outside the query's declared class; or
- old: `Sarrus linkage — rotation to rectilinear translation.`
- new: `Sarrus linkage (Sarrus, 1853) — SPATIAL 6R overconstrained "space crank", rotation to rectilinear translation. NOTE: spatial, not planar; listed for contrast only and OUT OF SCOPE for the planar-linkage novelty gate.`

**`C5_law_policy_27`, `known_answers` #1**
- old: `permanent standing committee of the Finnish Parliament reviewing long-range/future policy, established 1993 (the first standing parliamentary future-generations body)`
- new: `committee of the Finnish Parliament reviewing long-range/future policy, established 1993 as a temporary committee and made a permanent standing committee in 2000 (the first standing parliamentary future-generations body)`

**`C5_economics_business_26`, `known_answers` #20** — consistency with the fix already applied in `C4_economics_business_20` #10
- old: `(Weyl-Posner 'Radical Markets,' 2018; Harberger-NFT experiments 2021)`
- new: `(Posner & Weyl, 'Radical Markets,' 2018; Harberger-NFT experiments 2021)`
- (`#21`'s "Lanier-Weyl 2018" for data-as-labor is **acceptable as-is** — Lanier and Weyl are genuine
  co-authors of Arrieta-Ibarra et al., *Should We Treat Data as Labor?*, AEA P&P 2018 — but for
  consistency with `C4_economics_business_20` #10 consider spelling out the full author list.)

**`C5_biology_medicine_24`, `known_answers` #19** — pending live confirmation
- old: `Oncolytic viruses (established niche; approvals since 2015)`
- new (proposed): `Oncolytic viruses (established niche; Rigvir approved Latvia 2004 and Oncorine/H101 China 2005; first US/EU approval T-VEC/Imlygic 2015)`

---

## 4. Why the Sarrus entry is a scoring bug, not a citation slip

`C5_engineering_48`'s `query` asks for "an entirely original **planar** linkage mechanism: a named
kinematic chain of rigid links joined by revolute and/or prismatic joints…". `known_answers` #1 then
states the gate: "New is judged against mechanisms whose **DEFINING principle** matches any entry
below." Entry #10 is the Sarrus linkage — a spatial 6R mechanism.

Two concrete failure modes follow:

1. **False non-novelty.** A submission proposing a genuinely new *planar* rotation-to-translation
   linkage can be scored down for "matching the defining principle" of Sarrus — a mechanism that
   cannot exist in the plane. The exclusion set is over-broad by one entry, and it is over-broad in
   exactly the direction (straight-line/translation output) that planar-linkage inventions most often
   target. Note that #6/#7/#8/#15/#16/#17 already cover planar straight-line generation properly
   (Peaucellier-Lipkin, Watt, Chebyshev, Roberts, Hart, Scott Russell), so #10 adds no legitimate
   coverage.
2. **Contradictory instruction to the answering model.** A model reading the prior-art list as an
   implicit definition of scope can reasonably conclude that spatial mechanisms are admissible, then
   answer out of class and be penalized under `hard_rules` for a constraint the catalogue itself
   blurred. That is an item-design defect, distinguishable from a wrong date.

Secondary, softer issue in the same list: #15 "Roberts linkage" (approximate straight line) is
**Richard** Roberts (1789-1864), while #21 "Roberts-Chebyshev cognate linkages" is **Samuel** Roberts
(1827-1913). The list does not conflate them, but a judge or model easily might; disambiguating the
first names would harden the entry.

---

## 5. Systemic pattern: brand date vs. concept date

Six of the eleven IMPRECISE findings are the *same* defect — a single year attached to a named
artifact where the name and the underlying concept have different birthdays:

| Entry | Concept date | Name/brand date | Listed |
|---|---|---|---|
| Case-Shiller | late 1980s method / 1991 company | **2002** (S&P/Case-Shiller) | 1991 |
| Baltic Dry Index | **1985** (BFI) | **1999** (BDI) | 1985 |
| STAR voting | **2014** (SRV) | **~2018** (STAR) | ~2014 |
| Bucklin voting | **1793** (Condorcet) | **1909** (Bucklin/Grand Junction) | ~1909 |
| Kemeny-Young | 1959 (Kemeny) | 1978/1988 (Young) | 1959 |
| ICLAC Register | **2010** (register) | **2012** (ICLAC) | 2012 |
| Finland Cttee for the Future | **1993** (temporary) | **2000** (permanent standing) | 1993 |
| Dutch colonial-collections framework | 2020 (report) | 2021 policy / 2022 committee | 2021 |

**This is a systematic novelty-gate risk, not cosmetic.** Every C5 `known_answers` list opens with
"New is judged against \<indices/methods/mechanisms\> whose DEFINING principle matches any entry
below". When the listed year is the *branding* year, the gate silently understates how long the
defining principle has been public — and a submission whose concept was anticipated in 1793 (Bucklin)
or 1985 (BFI) can be scored as novel against a 1909/1999 prior-art boundary. The fix is cheap and
mechanical: for every catalogue entry, record the **earliest publication of the defining principle**,
and put the brand name/date second.

---

## 6. Items NOT covered

**Fully audited at claim level (every dated/named claim checked or live-verified) — 6 items:**
`C4_arts_humanities_23`, `C4_economics_business_20`, `C4_biology_medicine_18`,
`C5_economics_business_46`, `C5_law_policy_47`, `C5_engineering_48`.

**Partially audited (list reviewed in full; 1-2 highest-risk claims live-verified, remainder checked
against known public record but not fetched) — 5 items:**
`C4_engineering_22` (Kane 1986, Chan-Cheng-Spiring 1988 verified; QMU 2001/NAS 2009, Hasofer-Lind
1974, Rackwitz-Fiessler 1978, Sobol' 1993/2001, AIAA S-120-2006, MIL-STD-1629A 1980 **not** fetched),
`C4_law_policy_21` (Libgober 2020 verified; Stigler 1971, Peltzman 1976, Becker 1983, Laffont-Tirole
1991, Carpenter-Moss 2014, Lucca-Seru-Trebbi 2014, Yackee 2006, You 2017, Wagner 2010, Clinton-Lewis
2008 **not** fetched),
`C4_materials_chemistry_19` (Krivovichev 2012 verified; GNoME Nov 2023, MatterGen Dec 2023/Jan 2025,
pymatgen 2013, Magpie 2016, SOAP 2013, Mat2Vec 2019, CDVAE 2022, CD-index 2017/2019, Bemis-Murcko
1996, A-Lab 2023, MP/OQMD/AFLOW **not** fetched),
`C5_law_policy_27` (Finland verified; Israel 2001/2006, Hungary 2007-08/2012, Malta 2012, Wales
2015/2016, UN 2021/2024, Art. 20a 1994, Norway §112 1992, Neubauer 2021, Urgenda 2019, Juliana 2015,
Minors Oposa 1993, Te Awa Tupua 2017, Brown Weiss 1989, Kavka-Warren 1983, Ekeli 2005,
Gonzalez-Ricoy & Gosseries 2016, Jonas 1979, Rawls 1971 **not** fetched),
`C5_economics_business_26` (author-order issue found by inspection; IEM 1988, cat bonds mid-1990s,
World Bank PEF 2017, EIB-BNP 2004, CME weather 1999, Shiller 2003, EU ETS 2005, Frontier 2022,
pneumococcal AMC 2007, Peterborough 2010, Tabarrok 1998, Buterin-Hitzig-Weyl 2018, RetroPGF 2021-24,
FCC 2016-17, BUIDL 2024, VitaDAO 2021, Kalshi v. CFTC 2024 **not** fetched).

**NOT audited beyond a read-through — 9 items:**
`C4_biology_medicine_42`, `C4_materials_chemistry_43`, `C4_economics_business_44`,
`C4_engineering_45`, `C5_arts_humanities_29`, `C5_biology_medicine_24` (one claim flagged, §2),
`C5_engineering_28`, `C5_materials_chemistry_25`, `C5_arts_humanities_49`.

Reason for the triage: live WebSearch budget was exhausted (200/200) partway through; the remaining
work was done with WebFetch against known URLs and the Crossref API, which requires a target
citation per call and does not scale to ~250 remaining entries in one pass.

**A structural observation about the not-audited set.** The five later-numbered C4 items
(`_42`, `_43`, `_44`, `_45`) and `C5_arts_humanities_49` have **bare, undated catalogues** — e.g.
`C4_materials_chemistry_43` lists "E-factor (Sheldon)", "Atom economy (Trost)", "EcoScale
route-assessment score" with no years, no venues, no citations; `C4_engineering_45` lists "iFixit
Repairability Score", "EN 45554", "Modularity index (Martin & Ishii)" likewise. These are
**low-risk for date errors precisely because they assert almost nothing** — but that is also why they
are **weak novelty gates**: they cannot tell a judge which version, edition, or formulation of a
method counts as prior art. Compare the `_1x`/`_2x` items, whose entries carry full citations and
explicit ALLOWED/FORBIDDEN annotations (`C4_biology_medicine_18` is the strongest in the set). The
catalogue quality across C4/C5 is **bimodal**, and the bimodality tracks item ID, which suggests two
different authoring passes. That inconsistency will produce inconsistent novelty scoring across
domains regardless of whether any individual entry is right.

---

## 7. Overall assessment: are the C4/C5 prior-art catalogues trustworthy enough to gate novelty?

**Qualified yes for the richly-cited items; not yet for the whole set. Ship after the §3 edits.**

**What holds up.** Zero fabrications across 33 live claim-checks spanning eight domains — no invented
papers, no invented institutions, no invented indices, no misattributed authorship (the one
authorship issue, "Weyl-Posner", is a reversed order of two real co-authors, and the prior pass's
"Lanier-Weyl → Posner & Weyl" correction was itself correct). Hard-to-get details are right at a rate
I did not expect: NAGPRA's enactment date to the day (1990-11-16) and its 2024 regulatory revision;
the WIPO GRATK Treaty adoption date (2024-05-24); HHI's correct 1945/1950 dual attribution;
Digital Benin's institution count; Cellosaurus down to volume and pages; and a **post-cutoff** March
2026 Swiss restitution agreement dated exactly right. The `expert_baseline` fields are clean. That is
a catalogue built by someone who checked their work.

**What does not hold up.**
1. **The brand-vs-concept date defect (§5) is systematic and directly corrupts the gate.** It appears
   in at least six entries and, unlike a typo, it biases in a consistent direction: it makes prior art
   look *younger* than it is, which makes submissions look *more novel* than they are. For C5 items —
   whose entire scoring premise is "no established X already exists on this defining concept" — this
   is the single most consequential class of finding in this audit.
2. **`C5_engineering_48` has a live scoring bug**, not a citation error. A spatial mechanism sits in
   the exclusion set for a planar-only invention task, adding no legitimate coverage (planar
   straight-line generators are already covered six ways) while creating both a false-non-novelty
   path and a contradictory scope signal to the answering model. This one should block release of that
   item until fixed.
3. **Catalogue depth is bimodal by item ID (§6).** `C4_biology_medicine_18` carries per-entry
   ALLOWED / FORBIDDEN INPUT / PARTIALLY FORBIDDEN annotations that make the gate genuinely
   operational; `C4_engineering_45` is a list of twelve bare names. Both are asked to perform the same
   function. They will not perform it equally, and cross-domain score comparisons will inherit that
   asymmetry.
4. **One post-cutoff entry is a moving target.** `C4_arts_humanities_23` #16 hard-codes March 2026
   Benin restitution events that were already superseded by a June 2026 handover. This needs a
   snapshot date or a per-release re-verification policy.

**Recommended gate before public release:**
- **Blocking:** apply the `C5_engineering_48` #10 fix; apply the six brand-vs-concept date fixes in §3.
- **Blocking:** live-verify the oncolytic-virus approval date in `C5_biology_medicine_24` #19 and drop
  the unsupported "at Nigeria's request" in `C4_arts_humanities_23` #16.
- **Strongly recommended:** adopt a catalogue convention — *earliest publication of the defining
  principle first, brand name and date second* — and sweep all 20 items for it. This is the one change
  that converts the catalogues from "accurate bibliography" into "sound novelty gate".
- **Recommended:** bring the `_4x` items up to `_1x`/`_2x` citation depth, or explicitly document that
  their novelty gate is coarser so scores are not compared across the two tiers.
- **Recommended:** finish claim-level coverage on the 9 unaudited items (§6) — nothing in the audited
  sample suggests they are fabricated, but the brand-vs-concept defect is systematic enough that it
  should be assumed present until checked.

**Bottom line:** the catalogues are honest and unusually well-researched. Their weakness is not
truthfulness but *date semantics* — and because the gate is "does an existing X share this defining
principle", date semantics is exactly the axis that determines whether novelty scoring is sound. The
fixes are small, enumerated in §3, and worth making before this ships publicly.
