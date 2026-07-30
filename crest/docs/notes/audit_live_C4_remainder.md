# Live-web citation audit — C4 remainder (items _42 … _45)

Auditor pass: live WebSearch/WebFetch, 2026-07-30.
Scope: `C4_biology_medicine_42`, `C4_materials_chemistry_43`, `C4_economics_business_44`, `C4_engineering_45`
Source under audit: `/Users/jason/Desktop/rome/crest/questions/crest_challenges.audit.jsonl` (working copy, **not edited**).
Fields examined: `known_answers`, `expert_baseline`, `hard_rules`, `rationale`, `query`.

---

## 0. Headline

1. **Zero fabrications in 48 entries.** Every named metric, method, standard, statute, case and paper resolves to a real artifact. The prior auditor's "low fabrication risk" read is **confirmed**.
2. **The prior auditor's "bare undated name list" observation is confirmed and is worse than stated.** 46 of 48 substantive `known_answers` entries across these four items carry **no year at all** (95.8%). Both dated entries are in `_44`. See §2 for the file-wide comparison — `_1x` is 88.4% dated, `_4x` is 15.8%.
3. **The dating bias is one-directional, as predicted.** Every brand-vs-concept slip found makes prior art look *younger* / less specified than it is (OECD AOP, EN 45554, ESPR, French durability index, ISO 14044). No error was found in the opposite direction.
4. **One hard WRONG:** `Modularity index (Martin & Ishii)` in `_45`. Martin & Ishii's Design-for-Variety method produces the **Generational Variety Index** and the **Coupling Index**, not a "modularity index."
5. **One materially stale legal claim:** `EU Merger Regulation Article 22 referral practice` in `_44`, gutted for below-threshold deals by the CJEU on 3 Sept 2024 — well inside the list's own stated ~Jan 2026 currency.
6. **The most serious defect is not a citation error — `_45`'s novelty gate is void.** Its own worked example of a "genuinely new" mechanism (a parts-pairing/software-lock penalty as a hard multiplier) is **already implemented by the first entry in its own `known_answers` list**: iFixit's current Repairability Scoring Rubric applies a *global* parts-pairing penalty of **up to −100%**. A submission that proposes precisely the mechanism the item suggests would be scored as novel while reproducing published prior art. `_45`'s `expert_baseline` asserts the opposite of the truth here.

---

## 1. Summary table

Verdict key: **C** = CONFIRMED · **I** = IMPRECISE · **W** = WRONG · **U** = UNVERIFIABLE · **F** = FABRICATED (none found)

### C4_biology_medicine_42

| # | Claim (as written) | V | Correct / precise value | Source |
|---|---|---|---|---|
| 1 | `Willner's validity triad: face, construct, predictive validity` | C | Willner 1984, *Psychopharmacology* 83:1–16 | https://link.springer.com/article/10.1007/BF00427414 |
| 2 | `FDA Drug Development Tool (DDT) and Animal Model Qualification Program` | **I** | AMQP is scoped **only to the Animal Rule** (efficacy where human trials are unethical/infeasible) — not general translational model selection. As of 1 Jan 2026: 5 projects, **1 qualified DDT ever**. The pathway for organoid/MPS/in-silico tools is **ISTAND**, which the list omits. | https://www.fda.gov/drugs/animal-model-qualification-program-amqp/overview-animal-model-qualification-program · https://www.fda.gov/drugs/drug-development-tool-ddt-qualification-programs/innovative-science-and-technology-approaches-new-drugs-istand-program |
| 3 | `Biomarker/model 'Context of Use' (COU) qualification concept` | C | Real FDA concept, central to the DDT qualification framework (21st Century Cures Act, 2016). Undated bare name. | https://www.fda.gov/drugs/development-approval-process-drugs/drug-development-tool-ddt-qualification-programs |
| 4 | `ARRIVE 2.0 preclinical reporting guidelines` | C | Percie du Sert et al. 2020, *PLoS Biol* 18(7):e3000410 (pub. 14 Jul 2020); original ARRIVE = Kilkenny et al. 2010 | https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.3000410 |
| 5 | `SYRCLE risk-of-bias tool for animal studies` | C | Hooijmans, Rovers, de Vries et al. 2014, *BMC Med Res Methodol* 14:43 | https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/1471-2288-14-43 |
| 6 | `GRADE evidence-certainty framework` | C | GRADE Working Group (Atkins et al.) 2004, *BMJ* 328:1490 | https://pubmed.ncbi.nlm.nih.gov/15205295/ |
| 7 | `Bradford Hill viewpoints for causal inference` | C | Hill 1965, *Proc R Soc Med* 58:295–300; nine viewpoints | https://journals.sagepub.com/doi/10.1177/003591576505800503 |
| 8 | `3Rs framework (Replacement, Reduction, Refinement)` | C | Russell & Burch 1959, *The Principles of Humane Experimental Technique*, Methuen | https://norecopa.no/textbase/the-principles-of-humane-experimental-technique |
| 9 | `CAMARADES preclinical systematic-review ... methods` | C | Founded **2004** by Macleod & Howells, Edinburgh | https://clinical-brain-sciences.ed.ac.uk/camarades/about-camarades |
| 10 | `OECD Adverse Outcome Pathway (AOP) framework` | **I** | **Brand-vs-concept.** OECD AOP Development Programme launched **2012**; the concept is **Ankley et al. 2010**, *Environ Toxicol Chem* 29:730–741. Crediting "OECD AOP" alone dates the prior art 2 years young. | https://academic.oup.com/etc/article/38/6/1152/7737077 |
| 11 | `WHO/IPCS mode-of-action human-relevance framework` | C | Meek et al. 2003 (ILSI-RSI); Boobis et al. 2006 (cancer), 2008 (non-cancer); Meek et al. 2014 update | https://pubmed.ncbi.nlm.nih.gov/18259981/ |
| 12 | `Microphysiological systems qualification efforts (e.g., IQ MPS)` | C | IQ MPS **Affiliate formed June 2018**, from an IQ working group created 2014 at NCATS' request | https://www.iqmps.org/ |

### C4_materials_chemistry_43

| # | Claim | V | Correct / precise value | Source |
|---|---|---|---|---|
| 1 | `E-factor (Sheldon)` | C | Sheldon **1992**, *Chem. Ind.* (London), 7 Dec 1992, 903 ("Organic Synthesis — Past, Present and Future"); EQ hazard-weighted variant shortly after. Confirmed independently by Sheldon's own 30-year retrospective (2023). | https://pubs.rsc.org/en/content/articlelanding/2023/gc/d2gc04747k |
| 2 | `Atom economy (Trost)` | C | Trost **1991**, *Science* 254(5037):1471–1477 | https://www.science.org/doi/10.1126/science.1962206 |
| 3 | `12 Principles of Green Chemistry (Anastas & Warner)` | C | 1998, *Green Chemistry: Theory and Practice*, OUP | https://global.oup.com/academic/product/green-chemistry-9780198506980 |
| 4 | `EcoScale route-assessment score` | C | Van Aken, Strekowski & Patiny **2006**, *Beilstein J. Org. Chem.* 2:3; 6 parameters, 0–100 scale | https://www.beilstein-journals.org/bjoc/articles/2/3 |
| 5 | `Process Mass Intensity (PMI); ACS GCI Pharmaceutical Roundtable metrics` | C | PMI selected as the Roundtable's key metric **2011**; Jimenez-Gonzalez, Ponder, Broxterman & Manley 2011, *Org. Process Res. Dev.* 15(4):912–917 | https://pubs.acs.org/doi/10.1021/op200097d |
| 6 | `CHEM21 unified green-metrics toolkit` | C | McElroy, Constantinou, Jones, Summerton & Clark **2015**, *Green Chem.* 17:3111–3121 | https://pubs.rsc.org/en/content/articlelanding/2015/gc/c5gc00340g |
| 7 | `Reaction Mass Efficiency (RME)` | C | Constable, Curzons & Cunningham **2002**, *Green Chem.* 4(6):521–527 | https://pubs.rsc.org/en/content/articlelanding/2002/gc/b206169b |
| 8 | `Solvent selection guides (GSK, Pfizer, CHEM21)` | C | Pfizer: Alfonsi et al. 2008; GSK: Henderson et al. 2011; CHEM21: Prat et al. 2016 — all *Green Chem.* | https://learning.acsgcipr.org/guides-and-metrics/solvent-selection-guides/solvent-selection-guides-summary-and-further-reading/ |
| 9 | `Life Cycle Assessment (ISO 14040/14044)` | **I** | **ISO 14040:2006** and **ISO 14044:2006** (+ Amd 1:2017, Amd 2:2020); the 2006 pair consolidated first editions issued 1997–2000. Both still current as of 2026 — no newer edition. Undated citation of a versioned standard with amendments is not usable as a dated baseline. | https://www.iso.org/standard/38498.html |
| 10 | `Green Aspiration Level / Relative Process Greenness` | C | Roschangar, **Sheldon** & Senanayake **2015**, *Green Chem.* 17:752–768. Sheldon is a genuine co-author — **no "right paper / wrong famous name" failure here** despite the prominent name. | https://pubs.rsc.org/en/content/articlelanding/2015/gc/c4gc01563k |
| 11 | `Element criticality assessments (USGS, EU Critical Raw Materials list)` | **I** | Both are **re-issued lists**, so undated citation is unusable. USGS: final **2025** list = **60** commodities (Fed. Reg. 7 Nov 2025), up from 50 in 2022. EU: **2023** CRM list (34 CRMs / 17 SRMs); Critical Raw Materials Act in force **23 May 2024**, review every 4 years. The *methodology* (needed for H1) is Graedel et al. 2012 — omitted, see §5. | https://www.federalregister.gov/documents/2025/11/07/2025-19813/final-2025-list-of-critical-minerals · https://www.iea.org/policies/17662-european-critical-raw-materials-act |
| 12 | `Techno-economic analysis (TEA) and anticipatory LCA` | C | Anticipatory LCA: Wender et al. **2014**, *Environ. Sci. Technol.* 48(18):10531–10538 | https://pubs.acs.org/doi/10.1021/es5016923 |

### C4_economics_business_44

| # | Claim | V | Correct / precise value | Source |
|---|---|---|---|---|
| 1 | `Herfindahl-Hirschman Index (HHI)` | C | Hirschman 1945 (*National Power and the Structure of Foreign Trade*); Herfindahl 1950 (dissertation, US steel); adopted in the 1982 US Merger Guidelines | https://www.justice.gov/archives/atr/1982-merger-guidelines-and-ascent-hypothetical-monopolist-paradigm |
| 2 | `US DOJ/FTC Merger Guidelines (2010 horizontal; 2023 update)` | **I** | "2023 update" understates: the joint **2023 Merger Guidelines (18 Dec 2023) superseded and replaced** both the 2010 Horizontal Merger Guidelines *and* the 2020 Vertical Merger Guidelines with a single unified set. Confirmed still in effect: retained by FTC (Ferguson memo) and DOJ, **18 Feb 2025**. | https://www.ftc.gov/system/files/ftc_gov/pdf/ferguson-memo-re-merger-guidelines.pdf · https://www.justice.gov/atr/media/1389861/dl |
| 3 | `GUPPI (Gross Upward Pricing Pressure Index)` | **I** | Unattributed. GUPPI is **Salop & Moresi 2009** (extending a working-paper version of Farrell & Shapiro) and **Moresi 2010**; entered the 2010 HMG. Listing GUPPI unattributed next to an attributed UPP entry invites the reader to credit both to Farrell–Shapiro, which is wrong. | https://media.crai.com/wp-content/uploads/2020/09/16163618/the-use-of-UPPIs-in-merger-analysis-Moresi-Feb-2010.pdf |
| 4 | `Upward Pricing Pressure (UPP), Farrell-Shapiro` | C | Farrell & Shapiro **2010**, *B.E. J. Theor. Econ.* 10(1) art. 9 | https://faculty.haas.berkeley.edu/shapiro/alternative.pdf |
| 5 | `SSNIP / hypothetical-monopolist market definition` | C | **1982** US DOJ Merger Guidelines (paradigm predates by ~2 decades but 1982 is the canonical adoption) | https://www.justice.gov/archives/atr/1982-merger-guidelines-and-ascent-hypothetical-monopolist-paradigm |
| 6 | `Cunningham, Ederer & Ma, 'Killer Acquisitions' (2021)` | C | **Exact:** Colleen Cunningham, Florian Ederer, Song Ma, *J. Polit. Econ.* **129(3):649–702 (2021)**. Not fabricated, no author substitution. Note scope limit worth stating: the evidence base is **pharmaceutical only**. | https://www.journals.uchicago.edu/doi/abs/10.1086/712506 · https://lbsresearch.london.edu/id/eprint/1632/1/cem_jpe.pdf |
| 7 | `EU Merger Regulation Article 22 referral practice` | **W** | **Materially stale.** CJEU, **3 Sept 2024**, joined cases **C-611/22 P and C-625/22 P (Illumina/GRAIL)**: set aside the General Court and annulled the Commission's acceptance decisions, holding the Commission **may not encourage or accept Art. 22 referrals from NCAs that themselves lack jurisdiction** under national law. The Commission's March 2021 Art. 22 policy for below-threshold deals is dead; the live route is **national call-in powers**. A list claiming currency to ~Jan 2026 must say this — otherwise `_44`'s central below-threshold hook (H1) points at a defunct instrument. | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex:62022CJ0611 · https://curia.europa.eu/site/upload/docs/application/pdf/2024-09/cp240127en.pdf |
| 8 | `EU Digital Markets Act gatekeeper-designation criteria` | **I** | Regulation **(EU) 2022/1925** (14 Sept 2022). The killer-acquisition-relevant provision is not the designation criteria but **Article 14**: gatekeepers must inform the Commission of *any* intended concentration involving digital-sector services or data collection, **irrespective of whether it is notifiable** under the EUMR or national rules. That is the operative below-threshold visibility mechanism and the entry misses it. | https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32022R1925 |
| 9 | `UK CMA theories of harm, incl. loss of dynamic/potential competition` | C | **Merger Assessment Guidelines, CMA129, 18 March 2021** — explicit "loss of dynamic competition" ToH (2010 guidelines had only "perceived potential competition"); also covers **reverse** killer acquisitions | https://assets.publishing.service.gov.uk/media/61f952dd8fa8f5388690df76/MAGs_for_publication_2021_--_.pdf |
| 10 | `Potential-competition doctrine (actual and perceived potential entrant)` | C | Actual potential entrant = *FTC v. Procter & Gamble*, 386 U.S. 568 (**1967**); perceived potential entrant = *United States v. Falstaff Brewing*, 410 U.S. 526 (**1973**); refined in *United States v. Marine Bancorporation*, 418 U.S. 602 (**1974**) | https://supreme.justia.com/cases/federal/us/418/602/ |
| 11 | `Contestable-markets theory (Baumol, Panzar, Willig)` | C | **1982**, *Contestable Markets and the Theory of Industry Structure*, Harcourt Brace Jovanovich | https://archive.org/details/contestablemarke0000baum |
| 12 | `Innovation-competition analysis (EU Dow/DuPont, Bayer/Monsanto)` | C | Dow/DuPont **M.7932, 27 March 2017**; Bayer/Monsanto **M.8084, 21 March 2018** (C(2018) 1709 final) | https://ec.europa.eu/competition/mergers/cases1/202150/M_8084_8063752_13335_9.pdf |

### C4_engineering_45

| # | Claim | V | Correct / precise value | Source |
|---|---|---|---|---|
| 1 | `iFixit Repairability Score` | C (but see §3) | Real; **0–10**, introduced **2011**. Current *Repairability Scoring Rubric v2.x*: Design for Repair **80%**, Service Manual **10%**, Parts Availability & Cost **10%**; Unique Product Identifier = gate; **Parts Pairing = penalty only, global, up to −100%**. Software-update duration explicitly *not yet* included. | https://www.ifixit.com/Wiki/Repairability_Scoring_Rubric_v2.2 · https://www.ifixit.com/News/75533/how-ifixit-scores-repairability |
| 2 | `French Indice de Reparabilite / Indice de Durabilite` | **I** | Two distinct instruments needing separate dates. *Réparabilité*: loi AGEC 2020-105 (10 Feb 2020), décret **2020-1757** (29 Dec 2020), in force **1 Jan 2021**, 1–10. *Durabilité*: décret **2024-316 of 5 April 2024**; applies to **TVs from 8 Jan 2025** and **washing machines from 8 April 2025**; adds reliability sub-criteria on top of the repairability criteria; 1–10 over 7 sub-criteria. | https://www.ecologie.gouv.fr/politiques-publiques/indice-durabilite · https://www.economie.gouv.fr/particuliers/mes-droits-conso/bien-consommer/tout-savoir-sur-lindice-de-durabilite |
| 3 | `EU Ecodesign for Sustainable Products Regulation repairability scoring` | **I** | **Brand-vs-concept, and wrong instrument for an operative score.** ESPR = Regulation **(EU) 2024/1781**, published 28 June 2024, in force **18 July 2024** — an *enabling framework*; repairability scoring arrives only via delegated acts. The **operative** EU repairability score today is the **A–E repairability class on the smartphone/slate-tablet energy label**, Regulation **(EU) 2023/1669** (16 June 2023), applying from **20 June 2025**, with companion ecodesign Reg. **(EU) 2023/1670**. Citing ESPR alone dates the operative score ~2 years young and omits the only one in force. | https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401781 · https://eur-lex.europa.eu/eli/reg_del/2023/1669/oj/eng · https://single-market-economy.ec.europa.eu/news/new-eu-rules-durable-energy-efficient-and-repairable-smartphones-and-tablets-start-applying-2025-06-20_en |
| 4 | `EN 45554 (assessing repair, reuse, upgrade of energy-related products)` | **I** | **EN 45554:2020**, exact title *"General methods for the assessment of the ability to repair, reuse and upgrade energy-related products"*; ratified by CENELEC **2 Dec 2019**, published Feb 2020 (BS EN 45554:2020 dated 30 Apr 2020); fulfils standardisation request **M/543**. **Brand-vs-concept:** its scoring/aggregation framework was built on the **JRC Repair Scoring System (Cordella, Alfieri & Sanfelix 2019, JRC114337)** and its disassembly index on the **eDiM** metric (Vanegas et al. 2016; Peeters et al. 2018, JRC107773) — i.e. the method is 2016–2019, not 2020. Also: EN 45554 covers **product-related *and* support-related** criteria and deliberately **excludes spare-part price** as too volatile to score. | https://www.en-standard.eu/bs-en-45554-2020-general-methods-for-the-assessment-of-the-ability-to-repair-reuse-and-upgrade-energy-related-products/ · https://publications.jrc.ec.europa.eu/repository/bitstream/JRC114337/jrc114337_report_repair_scoring_system_final_report_v3.2_pubsy_clean.pdf · https://ecostandard.org/news_events/en-45554-a-standard-that-works-for-the-environment/ |
| 5 | `FMEA / FMECA` | C | US **MIL-P-1629 (1949)** first description; MIL-STD-1629 (1974); **MIL-STD-1629A, 24 Nov 1980**; MIL-STD-1629A **cancelled without replacement 24 Aug 1998** | https://everyspec.com/MIL-STD/MIL-STD-1600-1699/MIL_STD_1629A_1556/ |
| 6 | `MTTR and maintainability engineering (MIL-HDBK-470A)` | C | **MIL-HDBK-470A, 4 Aug 1997**, *Designing and Developing Maintainable Products and Systems*, Vols I & II; status **active** | https://acqnotes.com/Attachments/MIL-HDBK-470A.pdf |
| 7 | `Design for Disassembly (DfD)` | **U** | Bare generic term with no year and no attribution; no single canonical dated source located in this pass. Cannot function as a dated baseline. It *is* operationalised by a datable metric — eDiM (2016/2018) — which the list omits. Recommend anchoring or deleting. | https://publications.jrc.ec.europa.eu/repository/bitstream/JRC107773/jrc107773_20180302_-_edim_2_clean_-_online.pdf |
| 8 | `Design for Serviceability metrics` | C | Gershenson & Ishii, *"Life-Cycle Serviceability Design"*, ASME 1991 Design Technical Conferences / 3rd Int. Conf. on Design Theory & Methodology, Miami, 22–25 Sept **1991**; *"Design for Serviceability"* in Kusiak (ed.), *Concurrent Engineering*, **1992** | https://asmedigitalcollection.asme.org/IDETC-CIE/proceedings-abstract/DETC91/07477/127/1107344 |
| 9 | `Right-to-Repair legislative criteria (US state laws; EU right-to-repair directive)` | **I** | EU: **Directive (EU) 2024/1799 of 13 June 2024**, in force **30 July 2024**, applies from **31 July 2026**. US: Oregon **SB 1596**, signed **28 March 2024**, effective **1 Jan 2025** — the **first US law banning parts pairing**, and therefore directly determinative for H1, yet unnamed. | https://eur-lex.europa.eu/eli/dir/2024/1799/oj/eng · https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2024orLaw0069.pdf |
| 10 | `Material Circularity Indicator (Ellen MacArthur Foundation)` | C | EMF with **Granta Design**, **2015**, LIFE-co-funded; 0–1 scale; methodology updated **2019** for biological materials. Scope caveat: MCI measures **material-flow circularity**, not reparability — a weak "tradition" for this gate. | https://www.ellenmacarthurfoundation.org/material-circularity-indicator · https://content.ellenmacarthurfoundation.org/m/77e62bc9924c20d0/original/Circularity-Indicators-Methodology.pdf |
| 11 | `Modularity index (Martin & Ishii)` | **WRONG** | Martin & Ishii's *Design for Variety* method yields **two indices: the Generational Variety Index (GVI)** — redesign effort for future generations — **and the Coupling Index (CI)** — coupling among components. Neither is a "modularity index." Martin & Ishii 2002, *Research in Engineering Design* 13(4); earlier ASME IDETC 2000. Actual product-**modularity** measures belong to others: Gershenson et al. 1999 (additive intra-/inter-module similarity+dependency ratios); Mikkola & Gassmann **modularization function** (2000/2001, IEEE TEM 2003). | https://link.springer.com/article/10.1007/s00163-002-0020-2 · https://www.semanticscholar.org/paper/DESIGN-FOR-VARIETY:-A-METHODOLOGY-FOR-DEVELOPING-Martin-Ishii/8cd2c70bdd95497c379e1bd5000dcf89ce7a44eb |
| 12 | `Total Cost of Ownership / life-cycle cost analysis` | **U** | Bare generic term, no year, no attribution, no standard number. Not traceable to a dated artifact; cannot serve as a novelty baseline. Recommend dating (to a specific LCC standard the authors verify) or deleting. | — |

### Non-`known_answers` claims (`expert_baseline`, `hard_rules`, `rationale`)

| Item | Claim | V | Correction | Source |
|---|---|---|---|---|
| `_45` `expert_baseline` | "The convergent baseline **rarely penalizes software parts-pairing or digital locks**" | **WRONG** | The reference baseline for this item — iFixit, listed first in its own `known_answers` — applies a **global scorecard penalty of up to −100%** for parts pairing, and treats software-calibration lockout as a complete repair failure. iFixit's own words: *"Our scoring penalty for this repair-stopper is severe, and it's a global scorecard penalty."* | https://www.ifixit.com/News/75533/how-ifixit-scores-repairability · https://www.ifixit.com/Wiki/Repairability_Scoring_Rubric_v2.2 |
| `_45` `hard_rules` (d) | worked example of a NEW mechanism: "a software-lock/parts-pairing penalty **as a hard multiplier**" | **WRONG as a novelty example** | Already prior art in entry #1 of the same item. A global penalty "up to −100%" is functionally a hard multiplier that can zero the score. | as above |
| `_45` `rationale` | "no standard repairability index fuses … with a **software-lock hard multiplier** and an intrinsic-vs-institutional reparability split" | **WRONG** (first clause) | iFixit's rubric does exactly the first half. On the second half: EN 45554 already separates **product-related** from **support-related** criteria, which is close to the proposed intrinsic-vs-institutional split. | https://ecostandard.org/news_events/en-45554-a-standard-that-works-for-the-environment/ |
| `_45` `hard_rules` (d) | second example: "a stage separating **intrinsic hardware reparability from institutional/legal reparability**" | **I** (weakly novel) | EN 45554's product-related vs support-related parameter split, and the JRC RSS's separation of design vs commercial-practice parameters, already do most of this work. Not disqualifying, but not clean-novel either. | https://publications.jrc.ec.europa.eu/repository/bitstream/JRC114337/jrc114337_report_repair_scoring_system_final_report_v3.2_pubsy_clean.pdf |
| `_45` `expert_baseline` | "into a roughly 0-10 score derived mainly from a physical teardown, **following EN 45554**" | **I** | 0–10 is the **iFixit** and **French** scale. EN 45554 does **not** prescribe a 0–10 scale; it defines parameters and classification bands and leaves weighting/aggregation to implementing measures, and it explicitly excludes spare-part price. Attributing the 0–10 teardown score to EN 45554 conflates three instruments. | https://standards.iteh.ai/catalog/standards/clc/ed9b48c0-a4a9-421a-a14f-4ff341199918/en-45554-2020 |

---

## 2. Counts

### By verdict

| Verdict | `known_answers` entries | + baseline/rule claims | Total |
|---|---|---|---|
| CONFIRMED | 33 | 0 | **33** |
| IMPRECISE | 11 | 2 | **13** |
| WRONG | 2 | 3 | **5** |
| UNVERIFIABLE | 2 | 0 | **2** |
| **FABRICATED** | **0** | **0** | **0** |
| Total | 48 | 5 | **53** |

Per item (`known_answers` only):

| Item | C | I | W | U | F |
|---|---|---|---|---|---|
| `_42` | 10 | 2 | 0 | 0 | 0 |
| `_43` | 10 | 2 | 0 | 0 | 0 |
| `_44` | 8 | 3 | 1 | 0 | 0 |
| `_45` | 5 | 4 | 1 | 2 | 0 |

### Undated / uncited bare names

Definitions: **dated** = entry contains an explicit year. **fully bare** = no year *and* no personal-name/institution/document-number anchor of any kind.

| Item | entries | dated | undated | **fully bare** | fully-bare entries |
|---|---|---|---|---|---|
| `_42` | 12 | 0 | 12 (100%) | **5** | COU concept · ARRIVE 2.0 · SYRCLE · GRADE · 3Rs framework |
| `_43` | 12 | 0 | 12 (100%) | **4** | EcoScale · RME · Green Aspiration Level / RPG · TEA + anticipatory LCA |
| `_44` | 12 | 2 | 10 (83%) | **4** | HHI · GUPPI · SSNIP · potential-competition doctrine |
| `_45` | 12 | 0 | 12 (100%) | **4** (5 if the un-named statutes count) | FMEA/FMECA · Design for Disassembly · Design for Serviceability metrics · TCO/LCC — *plus* "Right-to-Repair legislative criteria," which names no statute |
| **Total** | **48** | **2 (4.2%)** | **46 (95.8%)** | **17 (35.4%)** | |

An undated bare name cannot function as a dated novelty baseline at all: a judge cannot ask "is the submission's mechanism absent from every listed framework as of date D" when D is unstated. 17 entries fail even the weaker test of being traceable to a specific artifact without an external search.

### File-wide comparison — testing the prior auditor's observation

Fraction of `known_answers` entries containing an explicit year, by item-number decade (all 50 items, dating preamble excluded):

| group | items | entries | dated | % dated |
|---|---|---|---|---|
| `_0x` | 10 | 140 | 62 | 44.3% |
| `_1x` | 10 | 112 | 99 | **88.4%** |
| `_2x` | 10 | 211 | 139 | 65.9% |
| `_3x` | 10 | 99 | 17 | 17.2% |
| `_4x` | 10 | 146 | 23 | **15.8%** |
| whole file | 50 | 708 | 340 | 48.0% |

**Verdict on the observation: CONFIRMED, and it generalises.** `_4x` is ~5.6× less dated than `_1x`. The four items in scope are the extreme: 2/48 = 4.2%. Note `_3x` (17.2%) is essentially as bad as `_4x` — the citation-density cliff is not `_4x`-specific, it is a `_3x`+`_4x` phenomenon. Whoever wrote the back half of the file stopped citing.

### Direction of the dating bias

Every date-related defect found points the same way — prior art appears **younger or vaguer** than reality, so a submission looks **more novel**:

| Item | Credited to | Actually | Understatement |
|---|---|---|---|
| `_42` | "OECD AOP framework" (programme 2012) | concept Ankley et al. 2010 | 2 yr |
| `_45` | EN 45554 (2020 brand) | JRC RSS 2019, eDiM 2016/2018 | 1–4 yr |
| `_45` | ESPR 2024/1781 "repairability scoring" | operative score is Reg 2023/1669, applying 2025 | wrong instrument |
| `_45` | "Indice de durabilité" (2024/2025) | supersedes indice de réparabilité, in force 2021 | 3–4 yr |
| `_43` | "ISO 14040/14044" undated | 2006 editions consolidating 1997–2000 first editions | up to 9 yr |
| `_44` | "2023 update" to 2010 HMG | 2023 Guidelines *replaced* 2010 HMG + 2020 VMG | scope, not date |

**Zero counter-examples.** The bias is systematic, not random noise — consistent with the pattern already confirmed elsewhere in this dataset.

---

## 3. The `_45` novelty gate is void — expanded

This is the finding that should block release of `_45` in its current form, and it is not a citation error.

- `hard_rules` (d) requires "≥1 decision variable, aggregation rule, or stage **absent from every listed framework**", and offers as its worked example *"a software-lock/parts-pairing penalty as a hard multiplier."*
- `known_answers[1]` is `iFixit Repairability Score`.
- iFixit's current rubric (v2.x) lists **Parts Pairing** as: *"Penalty only, global, up to −100%."* iFixit's explainer: *"Our scoring penalty for this repair-stopper is severe, and it's a global scorecard penalty."*
- `expert_baseline` asserts the opposite: *"The convergent baseline rarely penalizes software parts-pairing or digital locks."*
- H1 — "fully modular, unglued hardware but parts-pairing/software locks that block third-party repair" — is precisely the case iFixit's rubric is built to handle, and precisely the case Oregon SB 1596 (eff. 1 Jan 2025) legislates against.

Consequence: a model that proposes exactly the mechanism the item suggests satisfies (d) and is scored **novel**, while in fact reproducing the reference implementation named in the item's own prior-art list. The gate produces a false positive by construction. And because `expert_baseline` states the false claim, a judge reading only the item would confirm the false positive rather than catch it.

`_42`'s gate has a milder version of the same problem: its example new mechanism is "a quantified mechanism-divergence penalty," but **Belzung & Lemoine (2011)** already formalise *homological* validity (species/strain) and *mechanistic* validity as first-class criteria — and **Wehling/Wendler translatability scoring (2009–2017)** is already a weighted, aggregated, retrospectively validated (Spearman r = 0.91) fitness-for-purpose scoring procedure with disease-area-specific weights. Neither is listed.

---

## 4. Exact replacement strings

Each `old` below was verified by script to occur **exactly once** in `questions/crest_challenges.audit.jsonl` (48/48 `known_answers` strings + 5 prose strings, all unique). No `.jsonl` file was modified. Apply to the live `crest_challenges.jsonl` after confirming the same uniqueness there.

Priority: **P0** = must fix before release (wrong/void gate) · **P1** = stale or misleading · **P2** = add missing date/citation.

### P0

```
# _45 — WRONG attribution
old: Modularity index (Martin & Ishii)
new: Design for Variety indices - Generational Variety Index (GVI) and Coupling Index (CI) (Martin & Ishii 2002, Research in Engineering Design 13(4)); product-modularity measures proper (Gershenson et al. 1999; Mikkola & Gassmann modularization function, 2001/2003)

# _45 — expert_baseline states the opposite of the truth
old: The convergent baseline rarely penalizes software parts-pairing or digital locks, and gives little explicit credit for open diagnostic access when hardware is hard to open.
new: The convergent baseline already penalizes parts pairing: iFixit's current rubric (v2.x) applies a global scorecard penalty of up to -100% for parts pairing, and Oregon SB 1596 (effective 1 Jan 2025) bans it outright. What the convergent baseline still lacks is explicit credit for open diagnostic access and published schematics when hardware is hard to open, and any principled rule for trading the two off.

# _45 — hard_rule (d) worked examples are both prior art
old: (e.g., a software-lock/parts-pairing penalty as a hard multiplier, or a stage separating intrinsic hardware reparability from institutional/legal reparability)
new: (note: a parts-pairing penalty is NOT novel - iFixit v2.x already applies a global penalty up to -100%, and EN 45554 already separates product-related from support-related criteria; a qualifying new mechanism must go beyond both, e.g. a scale-invariant tradeoff rule that lets verified diagnostic-bus access and published schematics offset disassembly difficulty, with a stated exchange rate)

# _45 — rationale repeats the false novelty claim
old: New: no standard repairability index fuses physical-teardown scoring, maintainability engineering, and modularity metrics with a software-lock hard multiplier and an intrinsic-vs-institutional reparability split.
new: New: no standard repairability index fuses physical-teardown scoring, maintainability engineering, and modularity metrics into a single graded index with an explicit, stated exchange rate between physical disassembly difficulty and institutional openness (diagnostic access, schematics, indefinite spare supply). Parts-pairing penalties are prior art (iFixit v2.x) and do not count toward hard_rule (d).

# _44 — stale legal instrument
old: EU Merger Regulation Article 22 referral practice
new: EU Merger Regulation Article 22 referral practice (2021 Commission Guidance; curtailed by CJEU Illumina/GRAIL, C-611/22 P and C-625/22 P, 3 Sept 2024 - no referral where the referring Member State itself lacks jurisdiction), and the national below-threshold call-in powers that replaced it
```

### P1

```
# _45
old: EU Ecodesign for Sustainable Products Regulation repairability scoring
new: EU Ecodesign for Sustainable Products Regulation (Regulation (EU) 2024/1781, in force 18 July 2024) as an enabling framework for repairability scoring via delegated acts; the only operative EU repairability score to date is the A-E repairability class on the smartphone/slate-tablet energy label (Regulation (EU) 2023/1669, applying from 20 June 2025; companion ecodesign Regulation (EU) 2023/1670)

old: EN 45554 (assessing repair, reuse, upgrade of energy-related products)
new: EN 45554:2020, "General methods for the assessment of the ability to repair, reuse and upgrade energy-related products" (ratified by CENELEC 2 Dec 2019, published 2020, under standardisation request M/543; product-related and support-related criteria; spare-part price deliberately excluded as too volatile to score); its scoring/aggregation approach derives from the JRC Repair Scoring System (Cordella, Alfieri & Sanfelix 2019, JRC114337) and its disassembly index from the eDiM ease-of-disassembly metric (Vanegas et al. 2016; Peeters et al. 2018, JRC107773)

old: French Indice de Reparabilite / Indice de Durabilite
new: French Indice de reparabilite (loi AGEC 2020-105 of 10 Feb 2020; decret 2020-1757; in force 1 Jan 2021; scored 1-10) and Indice de durabilite (decret 2024-316 of 5 April 2024; televisions from 8 Jan 2025, washing machines from 8 April 2025; adds reliability sub-criteria)

old: Right-to-Repair legislative criteria (US state laws; EU right-to-repair directive)
new: Right-to-Repair legislative criteria (EU: Directive (EU) 2024/1799 of 13 June 2024, in force 30 July 2024, applying from 31 July 2026; US: Oregon SB 1596, signed 28 March 2024, effective 1 Jan 2025 - the first US statute banning parts pairing)

old: into a roughly 0-10 score derived mainly from a physical teardown, following EN 45554
new: into a roughly 0-10 score derived mainly from a physical teardown (the 0-10 scale is iFixit's and the French index's; EN 45554 itself defines parameters and classification bands and leaves weighting to implementing measures)

old: iFixit Repairability Score
new: iFixit Repairability Score (0-10; introduced 2011; current Repairability Scoring Rubric v2.x: Design for Repair 80%, service manual 10%, parts availability and cost 10%, unique product identifier as a gate, and a GLOBAL parts-pairing penalty of up to -100%; software-update duration not yet scored)

# _44
old: US DOJ/FTC Merger Guidelines (2010 horizontal; 2023 update)
new: US DOJ/FTC Merger Guidelines (2010 Horizontal Merger Guidelines, superseded by the joint 2023 Merger Guidelines of 18 Dec 2023, which replaced both the 2010 HMG and the 2020 Vertical Merger Guidelines; confirmed retained by FTC and DOJ on 18 Feb 2025)

old: GUPPI (Gross Upward Pricing Pressure Index)
new: GUPPI (Gross Upward Pricing Pressure Index; Salop & Moresi 2009, Moresi 2010 - not Farrell-Shapiro)

old: EU Digital Markets Act gatekeeper-designation criteria
new: EU Digital Markets Act (Regulation (EU) 2022/1925) gatekeeper-designation criteria, and the Article 14 duty on gatekeepers to inform the Commission of any intended digital-sector concentration irrespective of whether it is otherwise notifiable

# _43
old: Element criticality assessments (USGS, EU Critical Raw Materials list)
new: Element criticality assessments (USGS 2025 List of Critical Minerals, 60 commodities, final 7 Nov 2025; EU 2023 CRM list of 34 CRMs / 17 SRMs under the Critical Raw Materials Act, in force 23 May 2024, reviewed every 4 years; underlying methodology: Graedel et al. 2012, Environ. Sci. Technol. 46:1063 - supply risk, environmental implications, vulnerability to supply restriction)

old: Life Cycle Assessment (ISO 14040/14044)
new: Life Cycle Assessment (ISO 14040:2006 and ISO 14044:2006, incl. ISO 14044 Amd 1:2017 and Amd 2:2020; 2006 editions consolidated first editions issued 1997-2000; both still current)

# _42
old: FDA Drug Development Tool (DDT) and Animal Model Qualification Program
new: FDA Drug Development Tool (DDT) Qualification Programs (framework under the 21st Century Cures Act, 2016), comprising the Animal Model Qualification Program (AMQP - scoped to the Animal Rule; 1 qualified DDT as of Jan 2026) and the ISTAND pilot, which is the pathway for organoid, MPS and in-silico tools

old: OECD Adverse Outcome Pathway (AOP) framework
new: OECD Adverse Outcome Pathway (AOP) framework (concept: Ankley et al. 2010, Environ. Toxicol. Chem. 29:730-741; OECD AOP Development Programme launched 2012)
```

### P2 — date/citation only, no substantive change

```
# _42
old: Willner's validity triad: face, construct, predictive validity for disease models
new: Willner's validity triad: face, construct, predictive validity for disease models (Willner 1984, Psychopharmacology 83:1-16)

old: Biomarker/model 'Context of Use' (COU) qualification concept
new: Biomarker/model 'Context of Use' (COU) qualification concept (FDA DDT qualification framework, 21st Century Cures Act 2016)

old: ARRIVE 2.0 preclinical reporting guidelines
new: ARRIVE 2.0 preclinical reporting guidelines (Percie du Sert et al. 2020, PLoS Biol 18(7):e3000410; original ARRIVE: Kilkenny et al. 2010)

old: SYRCLE risk-of-bias tool for animal studies
new: SYRCLE risk-of-bias tool for animal studies (Hooijmans et al. 2014, BMC Med Res Methodol 14:43)

old: GRADE evidence-certainty framework
new: GRADE evidence-certainty framework (GRADE Working Group / Atkins et al. 2004, BMJ 328:1490)

old: Bradford Hill viewpoints for causal inference
new: Bradford Hill viewpoints for causal inference (Hill 1965, Proc R Soc Med 58:295-300; nine viewpoints)

old: 3Rs framework (Replacement, Reduction, Refinement)
new: 3Rs framework (Replacement, Reduction, Refinement; Russell & Burch 1959, The Principles of Humane Experimental Technique)

old: CAMARADES preclinical systematic-review and meta-analysis methods
new: CAMARADES preclinical systematic-review and meta-analysis methods (founded 2004, Macleod & Howells, Edinburgh)

old: WHO/IPCS mode-of-action human-relevance framework
new: WHO/IPCS mode-of-action human-relevance framework (Meek et al. 2003; Boobis et al. 2006 cancer, 2008 non-cancer; Meek et al. 2014 update)

old: Microphysiological systems qualification efforts (e.g., IQ MPS)
new: Microphysiological systems qualification efforts (e.g., IQ MPS Affiliate, formed June 2018 from a 2014 IQ working group set up at NCATS' request)

# _43
old: E-factor (Sheldon)
new: E-factor (Sheldon 1992, Chem. Ind. (London), 7 Dec 1992, 903; hazard-weighted EQ variant shortly after)

old: Atom economy (Trost)
new: Atom economy (Trost 1991, Science 254(5037):1471-1477)

old: 12 Principles of Green Chemistry (Anastas & Warner)
new: 12 Principles of Green Chemistry (Anastas & Warner 1998, Green Chemistry: Theory and Practice, OUP)

old: EcoScale route-assessment score
new: EcoScale route-assessment score (Van Aken, Strekowski & Patiny 2006, Beilstein J. Org. Chem. 2:3; six parameters, 0-100)

old: Process Mass Intensity (PMI); ACS GCI Pharmaceutical Roundtable metrics
new: Process Mass Intensity (PMI), adopted as the ACS GCI Pharmaceutical Roundtable's key metric in 2011 (Jimenez-Gonzalez, Ponder, Broxterman & Manley 2011, Org. Process Res. Dev. 15:912-917)

old: CHEM21 unified green-metrics toolkit
new: CHEM21 unified green-metrics toolkit (McElroy, Constantinou, Jones, Summerton & Clark 2015, Green Chem. 17:3111-3121)

old: Reaction Mass Efficiency (RME)
new: Reaction Mass Efficiency (RME) (Constable, Curzons & Cunningham 2002, Green Chem. 4:521-527)

old: Solvent selection guides (GSK, Pfizer, CHEM21)
new: Solvent selection guides (Pfizer: Alfonsi et al. 2008; GSK: Henderson et al. 2011; CHEM21: Prat et al. 2016 - all Green Chem.)

old: Green Aspiration Level / Relative Process Greenness
new: Green Aspiration Level / Relative Process Greenness (Roschangar, Sheldon & Senanayake 2015, Green Chem. 17:752-768)

old: Techno-economic analysis (TEA) and anticipatory LCA
new: Techno-economic analysis (TEA) and anticipatory LCA (Wender et al. 2014, Environ. Sci. Technol. 48:10531-10538)

# _44
old: Herfindahl-Hirschman Index (HHI)
new: Herfindahl-Hirschman Index (HHI; Hirschman 1945, Herfindahl 1950; adopted in the 1982 US Merger Guidelines)

old: Upward Pricing Pressure (UPP), Farrell-Shapiro
new: Upward Pricing Pressure (UPP), Farrell & Shapiro 2010, B.E. J. Theor. Econ. 10(1)

old: SSNIP / hypothetical-monopolist market definition
new: SSNIP / hypothetical-monopolist market definition (1982 US DOJ Merger Guidelines)

old: Cunningham, Ederer & Ma, 'Killer Acquisitions' (2021)
new: Cunningham, Ederer & Ma, 'Killer Acquisitions' (2021), J. Polit. Econ. 129(3):649-702 - evidence base is pharmaceutical-sector only

old: UK CMA theories of harm, incl. loss of dynamic/potential competition
new: UK CMA theories of harm, incl. loss of dynamic/potential competition and reverse killer acquisitions (Merger Assessment Guidelines, CMA129, 18 March 2021)

old: Potential-competition doctrine (actual and perceived potential entrant)
new: Potential-competition doctrine (actual potential entrant: FTC v. Procter & Gamble, 386 U.S. 568 (1967); perceived potential entrant: United States v. Falstaff Brewing, 410 U.S. 526 (1973); refined in United States v. Marine Bancorporation, 418 U.S. 602 (1974))

old: Contestable-markets theory (Baumol, Panzar, Willig)
new: Contestable-markets theory (Baumol, Panzar & Willig 1982, Contestable Markets and the Theory of Industry Structure, Harcourt Brace Jovanovich)

old: Innovation-competition analysis (EU Dow/DuPont, Bayer/Monsanto)
new: Innovation-competition analysis (EU Dow/DuPont, M.7932, 27 March 2017; Bayer/Monsanto, M.8084, 21 March 2018)

# _45
old: FMEA / FMECA
new: FMEA / FMECA (US MIL-P-1629, 1949; MIL-STD-1629A, 24 Nov 1980, cancelled without replacement 1998)

old: MTTR and maintainability engineering (MIL-HDBK-470A)
new: MTTR and maintainability engineering (MIL-HDBK-470A, 4 Aug 1997, Designing and Developing Maintainable Products and Systems; active)

old: Design for Disassembly (DfD)
new: Design for Disassembly (DfD), operationalised by disassembly-time metrics (eDiM: Vanegas et al. 2016; Peeters et al. 2018, JRC107773 - MOST-based)

old: Design for Serviceability metrics
new: Design for Serviceability metrics (Gershenson & Ishii, 'Life-Cycle Serviceability Design', ASME DTM 1991; 'Design for Serviceability', in Kusiak (ed.), Concurrent Engineering, 1992)

old: Material Circularity Indicator (Ellen MacArthur Foundation)
new: Material Circularity Indicator (Ellen MacArthur Foundation with Granta Design, 2015; updated 2019; 0-1 scale; measures material-flow circularity, not reparability)
```

**`Total Cost of Ownership / life-cycle cost analysis`** — no verified dated anchor found. Either date it to a specific LCC standard the authors verify, or delete it: as written it is an undatable generic term that cannot gate anything.

---

## 5. MISSING prior art (omission = gate failure)

### `_42` preclinical-model selection — 4 material omissions

1. **Wehling/Wendler translatability score** — Wehling 2009, *Nat Rev Drug Discov*; Wendler & Wehling 2012, *J Transl Med* 10:39; disease-area-specific version 2017, *J Transl Med*. **This is the most damaging omission in the whole audit.** It is already a reusable, weighted, aggregated scoring procedure for exactly this decision — availability/quality of in-vitro and in-vivo results, clinical data, biomarkers, personalisation, with disease-area-specific weights, a bounded output, a stated go/no-go threshold (sum > 4), and retrospective validation at Spearman r = 0.91. `_42` asks the model to invent this. https://link.springer.com/article/10.1186/1479-5876-10-39 · https://link.springer.com/article/10.1186/s12967-017-1329-y
2. **Belzung & Lemoine 2011**, *Biol Mood Anxiety Disord* 1:9 — five-criterion extension of Willner: homological (species + strain), pathogenic (onto- + triggering), mechanistic, face (ethological + biomarker), predictive (induction + remission). The item anchors on Willner's *triad* and then proposes a "mechanism-divergence penalty" as new — but homological + mechanistic validity is close to that, and 15 years old. https://biolmoodanxietydisord.biomedcentral.com/articles/10.1186/2045-5380-1-9
3. **FDA ISTAND pilot** (Innovative Science and Technology Approaches for New Drugs) — the actual DDT qualification pathway for organoids, MPS and in-silico tools. The item's `query` explicitly names organoids, organ-on-chip and in-silico models but its only regulatory qualification entry (AMQP) is Animal-Rule-scoped. https://www.fda.gov/drugs/drug-development-tool-ddt-qualification-programs/innovative-science-and-technology-approaches-new-drugs-istand-program
4. **ASME V&V 40-2018** + **FDA 2023 guidance, "Assessing the Credibility of Computational Modeling and Simulation in Medical Device Submissions"** — risk-informed model-credibility framework, where credibility must be commensurate with the weight placed on the model. The item admits in-silico models to scope but supplies no credibility framework for them. https://www.asme.org/codes-standards/find-codes-standards/assessing-credibility-of-computational-modeling-through-verification-and-validation-application-to-medical-devices · https://www.fda.gov/media/154985/download

### `_43` synthesis-route ranking — 5 material omissions

1. **GREENSCOPE** (US EPA; Ruiz-Mercado et al., ~2003 onward) — multi-criteria process sustainability aggregator, **139 indicators** across mass efficiency / environment / energy / economy. An existing instance of the artifact the item asks to invent. https://www.epa.gov/chemical-research/assessing-chemical-process-sustainability-greenscope
2. **EATOS** (Eissen & Metzger 2002) — Environmental Assessment Tool for Organic Syntheses; mass index S⁻¹ + environmental factor E with hazard weighting on input *and* output. Predates and prefigures weighted aggregation of green metrics. https://pubmed.ncbi.nlm.nih.gov/12203284/
3. **DOZN 2.0 / 2.1 / 3.0** (Merck/MilliporeSigma, 2017 →) — quantitative 12-principles evaluator producing per-principle scores and a single aggregate. https://www.sciencedirect.com/science/article/pii/S0022328X22001152
4. **Andraos, unified reaction metrics + global material-efficiency algorithm** — *Org. Process Res. Dev.* 2005 (Parts I & II) and the 2009 global algorithm applied to competing Tamiflu synthesis plans. An existing algorithm for ranking *whole routes* of arbitrary complexity, i.e. exactly hard_rule (a). https://pubs.acs.org/doi/10.1021/op049803n · https://pubs.acs.org/doi/10.1021/op800157z
5. **Graedel et al. 2012**, *Environ. Sci. Technol.* 46:1063 — three-dimensional metal criticality methodology (supply risk / environmental implications / vulnerability to supply restriction), Yale. The item lists the USGS and EU criticality *lists* (outputs) but not the quantitative *method*, which is what H1's PGM-vs-earth-abundant tradeoff actually needs. https://pubs.acs.org/doi/10.1021/es203534z

Consequence for the gate: the "supply-criticality-weighted atom economy" composite may still be new as a specific formula, but hard_rule (d) as written — "absent from *every* listed framework" — is trivially satisfiable when the four strongest existing aggregators are not listed.

### `_44` killer-acquisition screen — 4 material omissions

1. **FTC 6(b) study of non-HSR-reported acquisitions by five tech platforms, 2010–2019** (15 Sept 2021) — 616 non-reportable transactions over $1M; 94 above threshold but exempt. The empirical foundation for H1's below-threshold premise, and **non-pharma**, which matters because the only cited empirical study (Cunningham et al.) is pharma-only. https://www.ftc.gov/system/files/documents/reports/non-hsr-reported-acquisitions-select-technology-platforms-2010-2019-ftc-study/p201201technologyplatformstudy2021.pdf
2. **The three 2019 policy reports** that actually proposed the reforms this item asks a model to reinvent: **Furman Review, "Unlocking digital competition"** (March 2019); **Crémer / de Montjoye / Schweitzer, "Competition policy for the digital era"** (April 2019, for DG COMP — burden-shifting for acquisitions by dominant platforms); **Stigler Center Committee on Digital Platforms** (Sept 2019 — recommends transaction-value HSR thresholds because turnover-only screens miss nascent firms). https://assets.publishing.service.gov.uk/media/5c88150ee5274a230219c35f/unlocking_digital_competition_furman_review_web.pdf · https://euagenda.eu/upload/publications/untitled-257961-ea.pdf · https://publicknowledge.org/wp-content/uploads/2021/11/Stigler-Committee-on-Digital-Platforms-Final-Report.pdf
3. **HSR premerger notification regime, current state** — the query names "filing-threshold status" as an input, so this is load-bearing. FTC 2024 Final Rule published 12 Nov 2024, effective **10 Feb 2025**, expanded disclosure of overlaps and minority holdings — then **vacated by the US District Court for the Eastern District of Texas on 12 Feb 2026**. Neither the rule nor its vacatur appears in the list. https://www.federalregister.gov/documents/2024/11/12/2024-25024/premerger-notification-reporting-and-waiting-period-requirements · https://www.bakerbotts.com/thought-leadership/publications/2026/february/new-hsr-rules-overturned-by-federal-court-what-filers-need-to-know
4. **National below-threshold call-in powers** (Italy, Ireland, Denmark, Sweden, Hungary, Latvia and others) — post-Illumina, this is the *only* live EU route to a below-threshold review, and it is the mechanism the Commission itself now points to. The list's Art. 22 entry is a dead end without it. https://www.crowell.com/en/insights/client-alerts/one-year-after-illuminagrail-how-are-eu-competition-authorities-now-dealing-with-below-threshold-mergers

### `_45` reparability/upgradeability index — 6 material omissions

1. **Regulation (EU) 2023/1669** (energy labelling, smartphones/slate tablets, **A–E repairability class**, applying from **20 June 2025**) and **Regulation (EU) 2023/1670** (companion ecodesign). The only operative EU repairability score in existence, entirely absent — while the list instead cites the ESPR framework, which has not yet produced one. https://eur-lex.europa.eu/eli/reg_del/2023/1669/oj/eng
2. **JRC Repair Scoring System** — Cordella, Alfieri & Sanfelix 2019, *Analysis and development of a scoring system for repair and upgrade of products*, JRC114337; plus **JRC128672** (2022, smartphones/slate tablets application). This is the actual source of the EU scoring and aggregation method the item credits to EN 45554 / ESPR: prioritise parts → select criteria → assign classification scores → aggregate. https://publications.jrc.ec.europa.eu/repository/bitstream/JRC114337/jrc114337_report_repair_scoring_system_final_report_v3.2_pubsy_clean.pdf
3. **eDiM (ease of Disassembly Metric)** — Vanegas et al. 2016; Peeters, Tecchio, Ardente, Vanegas, Coughlan & Duflou 2018, JRC107773. MOST-based disassembly-time calculation underpinning EN 45554's disassembly index. The item's whole `query` turns on "teardown data, fastener/joint types" but supplies no disassembly-time primitive. https://publications.jrc.ec.europa.eu/repository/bitstream/JRC107773/jrc107773_20180302_-_edim_2_clean_-_online.pdf
4. **EN 45552** (durability) and **EN 45553** (remanufacture) — EN 45554's sibling standards from the same M/543 series. Citing one of a coordinated family without the family understates the standardisation prior art.
5. **IEEE 1874-2013**, *Documentation Schema for Repair and Assembly of Electronic Devices* (oManual) — machine-readable repair-documentation standard. The item lists "documentation" as an input with no standard behind it. https://standards.ieee.org/ieee/1874/5739/
6. **Oregon SB 1596** (signed 28 March 2024, effective **1 Jan 2025**) — the first US statute banning parts pairing. Absent even though the item's entire claimed novelty and its H1 case are about parts pairing. https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2024orLaw0069.pdf

---

## 6. Overall judgement — are these four gates strong enough to score novelty against?

**No, not as written.** Ranked by remaining usability after the P0/P1 fixes above:

| Item | Gate strength | Assessment |
|---|---|---|
| `_44` economics | **Adequate after fixes** | The only item with any dated entries (2/12), and its two proposed new mechanisms — a pipeline shelving-incentive index and a dynamic-contestability score for bottleneck-input control independent of current overlap — were not found in the published literature in this pass. But the Art. 22 entry is stale in a way that breaks H1's premise, and four significant literatures (FTC 6(b), the three 2019 reports, HSR current state, national call-in powers) are missing. Fix those and this gate holds. |
| `_43` chemistry | **Weak but repairable** | Attributions are all correct — best-attributed of the four. But every entry is undated, and the four strongest existing *aggregators* (GREENSCOPE, EATOS, DOZN, Andraos) plus the actual criticality *methodology* (Graedel 2012) are missing. "Absent from every listed framework" is far too easy to satisfy against this list. Adding the five omissions and dating all twelve entries makes it serviceable. |
| `_42` biology | **Weak** | Zero dated entries. One regulatory scope error (AMQP ≠ general model selection). Critically, an existing weighted-and-validated translatability *scoring procedure* (Wehling/Wendler) and an existing mechanistic/homological validity framework (Belzung & Lemoine 2011) are both absent — so the item's two flagship novelty claims are gated against a list that has been pruned of exactly the prior art that would refute them. Needs the four omissions plus dates before it can score novelty. |
| `_45` engineering | **Broken — do not release** | Not a citation problem. The item's own worked example of a novel mechanism is implemented by the first entry in its own prior-art list (iFixit's global parts-pairing penalty, up to −100%), its second example is close to EN 45554's product-related/support-related split, its `expert_baseline` asserts the opposite of the truth on the decisive point, one attribution is flatly wrong (Martin & Ishii), two entries are undatable generics, and the single most on-point regulatory instrument in the world (Reg (EU) 2023/1669's A–E repairability class) is absent. The gate will systematically award novelty credit for reproducing published prior art. Requires the P0 rewrite of `hard_rules` (d), `expert_baseline` and `rationale`, not just citation patching. |

**On the fabrication question:** the prior auditor's prediction was right — 0 fabrications in 48 entries, 0 "right paper / wrong famous name" substitutions. Notably, the one place where a famous-name substitution would have been easy to make and easy to miss — `Green Aspiration Level (Roschangar, Sheldon & Senanayake 2015)`, where Sheldon is also the E-factor's author — checks out: Sheldon is a genuine co-author.

**On the novelty question:** the prior auditor's framing — "low fabrication risk but weak novelty gates" — understates the second half. The problem is not merely that these gates are weak; it is that `_45`'s gate is *inverted*, and `_42`'s is close behind. Both would reward a submission for re-deriving prior art, and both contain `expert_baseline` prose that would lead a judge to confirm rather than catch the error. Undated entries make a novelty gate unenforceable; a wrong `expert_baseline` makes it actively misleading. The second failure mode is worse and is not fixed by adding years.

**Minimum before public release:**
1. Apply all five P0 replacements (the four `_45` prose/attribution fixes and the `_44` Art. 22 fix).
2. Date all 48 entries (P1 + P2 blocks give verified text for 47 of them; `Total Cost of Ownership / life-cycle cost analysis` needs a decision).
3. Add the 19 named missing prior-art items in §5 to the relevant `known_answers` lists.
4. Re-run the same audit against `_3x`, which is statistically as under-cited as `_4x` (17.2% vs 15.8% dated) and was not covered by either pass.
