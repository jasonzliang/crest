# CREST C1 — live-web citation audit

**Scope:** the 10 items with `id` prefix `C1_` in `question/crest_challenges.audit.jsonl`.
**Fields audited:** `known_answers` (highest weight — it is the novelty yardstick), `expert_baseline`, `query`.
**Date of audit:** 2026-07-30. **No `.jsonl` file was modified.**

**Method.** WebSearch (until session budget exhausted at 200 calls), then WebFetch and direct HTTPS
fetches against primary sources and literature APIs (Europe PMC REST, Crossref, OpenAlex, Semantic
Scholar, PubChem, USENIX/NeurIPS proceedings, publisher and agency pages). Unfalsifiable prose,
scoring-rubric language, and textbook common knowledge (Vickrey 1961, 12-TET, "villanelle is 19
lines") were not re-litigated.

---

## Headline

**Zero fabrications.** Every paper, compound, statute, standard, mission and product named across
all 10 items exists. That is the single most important result: the C1 prior-art lists were built
from real literature, not hallucinated.

**5 WRONG, 9 IMPRECISE, 2 UNVERIFIABLE, ~80 CONFIRMED.** Of the 5 WRONG, **3 sit inside
`known_answers`** and are the ones that actually matter:

1. `C1_biology_medicine_00` — **"dynobactin N"** does not exist; the compound is **dynobactin A**.
2. `C1_biology_medicine_00` — **"RG6114"** is *not* the LepB inhibitor G0775. RG6114 is
   **inavolisib** (GDC-0077 / Itovebi), a PI3Kα inhibitor for breast cancer. Wrong drug entirely.
3. `C1_materials_chemistry_31` — **LAGP** is given the LATP formula, erasing the germanium
   dependence that the item's own baseline argument turns on.

The other 2 WRONG are both inside a single citation in `C1_engineering_04` (a phantom co-author and
a wrong companion journal).

**The four prior-pass corrections:** 3 of 4 fully re-verify (AWS Spot timeline + <5% interruption;
Rao/Burgess/Kaffine PNAS volume-issue-pages; FCC 22-74 date). The fourth (Cs2TiI6 band gap) is
**half-corroborated** — the 1.56 eV direct figure holds, the 1.58 eV indirect figure does not
reproduce from any source I could reach.

---

## Verdict counts

| Verdict | Count |
|---|---|
| CONFIRMED | ~80 |
| WRONG | 5 |
| IMPRECISE | 9 |
| UNVERIFIABLE | 2 |
| **FABRICATED** | **0** |

By item (defects only): bio_00 = 2 WRONG + 1 IMPRECISE + 1 UNVERIFIABLE · eng_04 = 2 WRONG +
2 IMPRECISE · mat_31 = 1 WRONG · law_03 = 2 IMPRECISE · mat_01 = 2 IMPRECISE + 1 UNVERIFIABLE ·
econ_02 = 1 IMPRECISE · bio_30 = 1 IMPRECISE · **arts_05, arts_33, eng_32 = clean**.

---

## Summary table

### C1_biology_medicine_00 (CRAB antibacterial MoA)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| Zosurabalpin = RG6006 (Roche), tethered macrocyclic peptide, traps LptB2FGC, CRAB-selective; Nature 2024 (Zampaloni; Pahil) | CONFIRMED | Zampaloni et al., *Nature* 625:566–571, online 3 Jan 2024; Pahil et al. companion | https://www.nature.com/articles/s41586-023-06873-0 · https://pubmed.ncbi.nlm.nih.gov/38172634/ |
| LpxC inhibitors ACHN-975, LPC-233; UDP-3-O-acyl-GlcNAc deacetylase | CONFIRMED | both compounds real | https://doi.org/10.3389/fmicb.2025.1541379 |
| **"Darobactin and dynobactin N"** bind BamA | **WRONG** | The compound is **dynobactin A** (from *Photorhabdus australis*). Miller et al. name only dynobactin A; no "dynobactin N" exists in the literature. ("N–C crosslink" in that paper is a bond type, not a variant.) | https://www.nature.com/articles/s41564-022-01227-4 · https://www.rcsb.org/structure/7R1W |
| Darobactin: Nature 2019 (Imai et al.); dynobactin: Nat Microbiol 2022 (Miller et al.) | CONFIRMED | Imai et al. *Nature* 576:459 (2019); Miller RD, Iinishi A, … Hiller S, Lewis K, *Nat Microbiol* 2022 | https://www.nature.com/articles/s41586-019-1791-1 · https://doi.org/10.1038/s41564-022-01227-4 |
| Murepavadin (POL7080) peptidomimetic LptD inhibitor, Pseudomonas-focused | CONFIRMED | *Drugs of the Future* 2018 monograph titles it exactly this | https://doi.org/10.1358/dof.2018.043.03.2774450 |
| Thanatin binds LptA (Vetterli et al. 2018–2019) | CONFIRMED | Vetterli et al., *Sci Adv* 4:eaau2634 (2018) | https://doi.org/10.1126/sciadv.aau2634 |
| Cefiderocol: siderophore-cephalosporin, TonB-dependent uptake, inhibits PBP3 | CONFIRMED | — | https://doi.org/10.1021/acsinfecdis.4c00218 |
| "next-gen analogs SPR206, **SPR741/MRX-8**" | **IMPRECISE** | Three distinct programs, not two. SPR741 (Spero) is a **non-bactericidal polymyxin-B-derived potentiator** with no useful intrinsic Gram-negative activity; MRX-8 (MicuRx) is a separate direct-acting next-gen polymyxin. The `/` implies equivalence. | https://doi.org/10.3390/antibiotics11091251 · https://doi.org/10.1128/aac.01912-24 |
| Sulbactam-durlobactam (XACDURO) FDA-approved May 2023 for CRAB | CONFIRMED | approved **23 May 2023**, HABP/VABP due to *A. baumannii-calcoaceticus* complex | https://www.drugs.com/history/xacduro.html |
| PDF inhibitors actinonin, LBM415/GSK1322322 | CONFIRMED | — | https://doi.org/10.1021/acsinfecdis.4c00218 |
| LepB inhibitors: arylomycins, **G0775/RG6114** | **WRONG** | G0775 is correct (Smith PA et al., *Nature* 561:189–194, 2018). **RG6114 = inavolisib / GDC-0077 / RO-7113755**, a PI3Kα inhibitor-degrader (Itovebi) — an unrelated oncology drug. Delete `/RG6114`. | https://www.nature.com/articles/s41586-018-0483-6 · PubChem synonyms for inavolisib list `RG6114`, `RG-6114` |
| LolCDE inhibitors, pyridineimidazole G0507 series | CONFIRMED | G0507 real (Nickerson et al., LolCDE inhibitor) | https://doi.org/10.1002/asia.202500350 |
| FabI: fabimycin (Gram-negative-active), afabicin | CONFIRMED | fabimycin real, FabI-targeting, Gram-negative-selective | https://doi.org/10.64898/2026.04.05.716606 |
| Epetraborole = LeuRS inhibitor, boron/oxaborole editing-site trap | CONFIRMED | OBORT mechanism: boron binds cis-diols of tRNA-Leu terminal adenosine, traps it in the LeuRS editing site | https://doi.org/10.1371/journal.pntd.0011795 |
| trans-translation inhibitors KKL-35, acylaminooxadiazoles | CONFIRMED | — | https://doi.org/10.1021/acsinfecdis.4c00218 |
| Riboswitch: ribocil (Merck), roseoflavin | CONFIRMED | Howe JA et al. (Merck Research Labs), *Nature* 526:672–677 (2015) | https://doi.org/10.1038/nature15542 |
| FtsZ: PC190723, TXA709/TXA707 | CONFIRMED | TXA709 is the prodrug of active benzamide TXA707 | https://doi.org/10.3390/antibiotics9020069 |
| MurA/fosfomycin; NBTIs gepotidacin, zoliflodacin; taniborbactam/xeruborbactam/avibactam/zidebactam (zidebactam also a PBP2 binder); MsbA G907; PPMOs vs *acpP*/*rpsH*; phage/endolysin/CRISPR/efflux-inhibitor modalities | CONFIRMED | all real and correctly characterised | https://doi.org/10.1021/acsinfecdis.4c00218 |
| **EB:** MurJ (MviN) = MOP-superfamily lipid II flippase; solved *Thermosipho*/*E. coli* structures; alternating-access cavity; MTSES-accessibility probing | CONFIRMED | Kuk ACY, Hao A, Lee SY, *Annu Rev Biochem* 91:705–729 (2022) | https://doi.org/10.1146/annurev-biochem-040320-105145 |
| **EB:** "*murJ* is called essential in A. baumannii Tn-seq essential-gene sets (ATCC 17978 / AB5075)" | **UNVERIFIABLE** | A. baumannii essential-gene resources exist (Ward RD et al., *mBio* 15:e02051-23, 2024, CRISPRi essential-gene knockdowns; Gallagher et al. Tn-seq in AB5075) but I could not confirm *murJ* appears in **both** the ATCC 17978 and AB5075 essential sets as stated. Directionally sound (*murJ* is essential in *E. coli* and broadly conserved-essential in Gram-negatives). | https://doi.org/10.1128/mbio.02051-23 |
| **EB:** humans have no MurJ ortholog | CONFIRMED | — | — |

### C1_economics_business_02 (GPU market mechanism)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| Green-Laffont 1979; Myerson-Satterthwaite 1983 | CONFIRMED | Green & Laffont, *Incentives in Public Decision-Making*, North-Holland 1979 (reviewed *Econ J* 90:407, 1980); Myerson & Satterthwaite, *JET* 29:265–281 (1983) | https://doi.org/10.2307/2231809 · https://doi.org/10.1016/0022-0531(83)90048-0 |
| GSP: Edelman-Ostrovsky-Schwarz 2007; Varian 2007 | CONFIRMED | *AER* 97(1):242–259 (2007); *IJIO* 25:1163–1178 (2007) | https://doi.org/10.1257/aer.97.1.242 · https://doi.org/10.1016/j.ijindorg.2006.10.002 |
| **AWS EC2 Spot: 2009-2017 bid-based; changed at re:Invent 2017, rolled out ~March 2018; no bidding; <5% average interruption** *(prior-pass correction)* | CONFIRMED | AWS Compute Blog post dated **13 March 2018**, verbatim: "The typical frequency of interruption for Spot Instances in the last 30 days was **less than 5% on average**." Announced at re:Invent Nov 2017. | https://aws.amazon.com/blogs/compute/new-amazon-ec2-spot-pricing/ |
| "Google Cloud Spot/Preemptible VMs (… **~24h max life**, ~30s preemption notice)" | **IMPRECISE** | The 24-hour hard cap is a property of legacy **Preemptible VMs only**. **Spot VMs** (GA Oct 2021) have **no maximum runtime**. The ~30 s ACPI shutdown warning applies to both. | https://docs.cloud.google.com/compute/docs/instances/spot · https://docs.cloud.google.com/compute/docs/instances/preemptible |
| Azure Spot VMs: user max-price cap, eviction on price OR capacity | CONFIRMED | — | https://docs.cloud.google.com/compute/docs/instances/spot (contrast) |
| Vast.ai: open marketplace, host-set prices + interruptible bid-based tier | CONFIRMED | Vast.ai docs: on-demand = "Fixed pricing set by the host"; "Interruptible instances use a bidding system … higher bids get priority … May be paused if outbid" | https://docs.vast.ai/instances/instance-types |
| Nisan-Ronen 1999/2001 | CONFIRMED | *GEB* 35:166–196 (2001); STOC 1999 | https://doi.org/10.1006/game.1999.0790 |
| Lehmann-O'Callaghan-Shoham 2002; Lavi-Swamy 2005; Dobzinski-Nisan-Schapira 2005 | CONFIRMED | *JACM* 49:577–602 (2002); FOCS 2005:595–604; STOC 2005:610–618 | https://doi.org/10.1145/585265.585266 · https://doi.org/10.1109/sfcs.2005.76 · https://doi.org/10.1145/1060590.1060681 |
| online VCG (Parkes-Singh 2003); Hajiaghayi et al. 2004 | CONFIRMED | Parkes & Singh, "An MDP-Based Approach to Online Mechanism Design," NeurIPS **2003** proceedings; Hajiaghayi/Kleinberg/Parkes, EC'04:71–80 | https://proceedings.neurips.cc/paper_files/paper/2003 · https://doi.org/10.1145/988772.988784 |
| Milgrom-Segal deferred-acceptance auctions (paper 2014; FCC incentive auction); Li 2017 OSP | CONFIRMED | Milgrom & Segal, EC'14 (Stanford, June 2014); Li, *AER* 107:3257–3287 (2017) | https://netecon.seas.harvard.edu/NetEcon14/Papers/Milgrom_netecon14.pdf · https://doi.org/10.1257/aer.20160425 |
| Ghodsi et al. 2011 DRF; Ben-Yehuda et al. 2013 | CONFIRMED | DRF = NSDI'11; Agmon Ben-Yehuda et al., *ACM TEAC* 1(3) (2013), earlier CloudCom 2011 | https://www.usenix.org/legacy/events/nsdi11/tech/full_papers/Ghodsi.pdf · https://doi.org/10.1145/2509413.2509416 |
| VCG NP-hard winner determination; Vickrey/Clarke/Groves 1961/1971/1973; Myerson 1981; multi-unit uniform-price & pay-as-bid | CONFIRMED (common knowledge) | — | — |

### C1_engineering_04 (reusable FDM energy absorber)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| **"Correa, Klatt, Spadaccini, Seepersad et al., 'Negative stiffness honeycombs for recoverable shock isolation,' Rapid Prototyping Journal, 2015"** | **WRONG (author)** | **Spadaccini is not an author.** Actual: **Correa DM, Klatt T, Cortes S, Haberman M, Kovar D, Seepersad C**, *Rapid Prototyping Journal* **21(2):193–200 (2015)** | https://doi.org/10.1108/RPJ-12-2014-0182 |
| **"(and companion work in Additive Manufacturing, 2015)"** | **WRONG (venue)** | The companion paper is Correa DM, Seepersad CC, Haberman MR, "Mechanical design of negative stiffness honeycomb materials," ***Integrating Materials and Manufacturing Innovation* 4:10 (2015)** — not *Additive Manufacturing*. | https://doi.org/10.1186/s40192-015-0038-8 |
| Frenzel, Findeisen, Kadic, Gumbsch, Wegener, *Adv Mater* 2016 | CONFIRMED | *Adv Mater* 28:5865–5870 (2016); author list exact | https://doi.org/10.1002/adma.201600610 |
| Shan, Kang, Raney, Wang, Fang, Candido, Lewis, Bertoldi, *Adv Mater* 2015 | CONFIRMED | *Adv Mater* 27:4296–4301 (2015); author list exact | https://doi.org/10.1002/adma.201501708 |
| Restrepo, Mankame, Zavattieri, *Extreme Mechanics Letters* 2015 | CONFIRMED | *EML* 4:52–60 (2015) | https://doi.org/10.1016/j.eml.2015.08.001 |
| "Bertoldi, Reis, Shim, Mullin et al., **~2008-2017**" (holey sheets, buckliball) | **IMPRECISE** | Buckliball = Shim, Perdigou, Chen, Bertoldi, Reis, *PNAS* 109(16):5978–5983 (2012) ✓. But Mullin, Willshaw, Box, Mahadevan, *PRL* 99:084301 is **2007** — the range should open at ~2007. | https://doi.org/10.1073/pnas.1115674109 |
| "TPMS lattices … printed in **TPU/elastomer** … e.g. **Maskery, Ashcroft, Hague** et al." | **IMPRECISE** | Maskery/Ashcroft/Hague TPMS work is **laser-sintered polyamide (nylon-12) and metal**, not TPU (e.g. Maskery et al., *Polymer* 152:62–71, 2018). TPU-gyroid recoverable-cushioning studies exist but are from other groups. Named attribution is misplaced. | https://doi.org/10.1016/j.polymer.2017.11.049 |
| Carbon/Adidas 4D & 4DFWD ~2017-2021; EOS/HP + nTopology TPU lattice insoles | CONFIRMED (secondary sources only) | Futurecraft 4D unveiled 2017 with Carbon; 4DFWD 2021. adidas's own press-release URL now 404s. | https://en.wikipedia.org/wiki/Carbon_(company) |
| Constant-force compliant mechanisms (Howell and collaborators, ~2000-2019) | CONFIRMED (common knowledge) | — | — |
| **EB:** FDM TPU ~95A Shore, density ~1.20 g/cc | CONFIRMED | standard FDM TPU-95A datasheets: 1.20–1.22 g/cm³ | — |

### C1_law_policy_03 (LEO debris instrument)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| **Rao, Burgess & Kaffine, PNAS 117(23):12756-12762, issue 9 June 2020 (online-first 26 May 2020)** *(prior-pass correction)* | CONFIRMED | Volume 117, issue 23, pp. 12756–12762; PubMed records Epub 2020 May 26; PNAS vol 117 no 23 = 9 June 2020 issue | https://www.pnas.org/content/117/23/12756/tab-article-info · https://pubmed.ncbi.nlm.nih.gov/32457138/ |
| Adilov, Alexander & Cunningham, *Environmental and Resource Economics* (2015) | CONFIRMED | ERE **60(1):81–98** (2015) | https://doi.org/10.1007/s10640-013-9758-4 |
| "Deposit-refund schemes and performance (deorbit) bonds — **Molly Macauley (Resources for the Future)** and OECD space-economy analyses" | **IMPRECISE (misattribution)** | Macauley/RFF is real and published on orbital-debris economics (*Resources* 1993; *Acta Astronautica* 115:160–164, 2015) but **no publication of hers on deposit-refund or performance bonds for orbit** could be found — her deposit-refund work is municipal solid waste. The **OECD leg is correct**: Undseth, Jolly & Olivari, "Space sustainability: the economics of space debris in perspective," OECD STI Policy Paper, 8 Apr 2020. Real bond/deposit-refund citations: Bullock & Johanson, *MIT Sci Policy Rev* (2021). | https://doi.org/10.1787/a339de43-en · https://doi.org/10.1016/j.actaastro.2015.05.006 · https://doi.org/10.38105/spr.16gdw8z5d4 |
| 51 U.S.C. ch. 509 financial-responsibility / MPL | CONFIRMED | §50914 uses the statutory phrase "maximum probable loss"; $500M third-party / $100M gov-property caps | https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title51-section50914&num=0&edition=prelim |
| **FCC 22-74, adopted 29 September 2022, 5-year rule** *(prior-pass correction)* | CONFIRMED | Second Report and Order, adopted 29 Sep 2022, IB Dockets 18-313 / 22-271 | https://docs.fcc.gov/public/attachments/FCC-22-74A1.pdf |
| ESA Zero Debris Charter drafted 2023, first signatories 2024, net-zero by 2030 | CONFIRMED | "draft zero" July 2023, launched Nov 2023; **12 countries signed 22 May 2024** | https://www.esa.int/Space_Safety/Space_Debris/Twelve_countries_sign_the_Zero_Debris_Charter |
| COPUOS LTS: 21 guidelines adopted 2019 | CONFIRMED | UNIS/OS/518, 22 June 2019: "a preamble and 21 guidelines" | https://www.unoosa.org/oosa/en/informationfor/media/2019-unis-os-518.html |
| IADC Space Debris Mitigation Guidelines 2002, rev. 2007/2020 | CONFIRMED | IADC-02-01 Rev.0 = 2002-10-15, Rev.1 = 2007-09-01, Rev.2 = 2020-03-01 (current) | https://orbitaldebris.jsc.nasa.gov/library/iadc-space-debris-guidelines-revision-2.pdf |
| "Space Sustainability Rating — WEF concept (**~2019-2021**), operational home at eSpace/EPFL **from ~2022**" | **IMPRECISE** | Per SSR's own history: concept initiated by the WEF Global Future Council on Space **in 2016**; WEF appointed the design consortium (ESA/MIT/BryceTech/UT Austin) 2019; **eSpace–EPFL selected May 2021**; SSR **went live June 2022**; independent SSR Association formed Jan 2023. | https://spacesustainabilityrating.org/about/ |
| ESA ClearSpace-1 contracted to ClearSpace SA, 2020; Astroscale ELSA-d launched March 2021 | CONFIRMED | €86M service contract signed **26 Nov 2020** (mission commissioned Dec 2019); ELSA-d launched **22 March 2021 UTC**. Side note: ClearSpace-1's target changed VESPA → PROBA-1 and launch slipped to ~2028/29. | https://www.esa.int/Newsroom/Press_Releases/Call_for_Media_ESA_and_ClearSpace_SA_sign_contract_for_world_s_first_debris_removal_mission · https://astroscale.com/missions/elsa-d/ |
| SPD-3 (June 2018) + OSC TraCSS | CONFIRMED | SPD-3 signed **18 June 2018**; TraCSS is an Office of Space Commerce program, operational 2026. **Live-status caveat:** the FY2026 President's Budget proposed terminating TraCSS; Senate appropriators rejected the termination (July 2025). A 2026-dated item should reflect that its funding was contested. | https://trumpwhitehouse.archives.gov/presidential-actions/space-policy-directive-3-national-space-traffic-management-policy/ · https://www.space.commerce.gov/traffic-coordination-system-for-space-tracss/ |
| **EB:** OST Art. II (no appropriation), Art. VI ("authorization and continuing supervision"), Art. VIII (jurisdiction & control); Liability Convention Art. III (fault, elsewhere than on the surface of the Earth); Japan Space Activities Act | CONFIRMED | All verified verbatim. Japan = "Act on Launching Spacecraft and Launch Vehicle and Control of Spacecraft," **Act No. 76 of 2016**. | https://www.unoosa.org/oosa/en/ourwork/spacelaw/treaties/outerspacetreaty.html · https://www.unoosa.org/oosa/en/ourwork/spacelaw/treaties/liability-convention.html · https://www8.cao.go.jp/space/english/activity/application.html |

### C1_materials_chemistry_01 (wide-gap tandem top cell)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| BaZrS3 orthorhombic Pnma, DIRECT gap ~1.7-1.85 eV | CONFIRMED | distorted Pnma perovskite; measured direct gaps 1.74–1.85 eV | https://doi.org/10.1021/acsaem.9b02428 · https://doi.org/10.1021/acsami.3c00618 |
| BaHfS3 ~1.9-2.0 eV | CONFIRMED (literature consensus) | standard reported range in the chalcogenide-perovskite literature; no single primary abstract reachable this session | https://doi.org/10.1021/acsami.3c00618 |
| SrZrS3 (perovskite + needle-like polymorphs, ~1.5-2.05 eV); CaZrS3 (~1.9-2.05 eV) | CONFIRMED | α needle-like and β distorted-perovskite polymorphs with gaps spanning ~1.5–2.05 eV | https://doi.org/10.1021/acsomega.0c00740 |
| BaZrSe3 ~1.3-1.5 eV | CONFIRMED | — | https://doi.org/10.1021/acsami.3c00618 |
| Ruddlesden-Popper Ba(n+1)Zr(n)S(3n+1) (Ba3Zr2S7, Ba2ZrS4), ~1.25-1.8 eV | CONFIRMED | dimensional tuning across that range is the standard result | https://doi.org/10.1021/acsami.3c00618 |
| Cs2AgBiBr6 INDIRECT gap ~1.95-2.2 eV | CONFIRMED | Slavney et al. 1.95 eV indirect; McClure et al. 2.19 eV; PL at 1.9–2.0 eV from self-trapped excitons | https://doi.org/10.1021/jacs.5b13294 · https://doi.org/10.1021/acs.chemmater.5b04231 |
| Cs2AgBiCl6, Cs2AgInCl6, Cs2AgSbBr6, Cs2NaBiI6, Cs2AgSbCl6 — mostly indirect / too wide | CONFIRMED | — | https://doi.org/10.1021/jacs.6c07190 |
| **"Cs2TiBr6 and Cs2TiI6 … ~1.55-2.0 eV (Cs2TiI6 measured 1.56 eV direct / 1.58 eV indirect)"** *(prior-pass correction)* | **IMPRECISE (half-corroborated)** | The source is Aslam S, Bakhsh S, Yusof Y, Abd. Rahman MY, Ibrahim A, Samsuri S, "Structural and optical properties of vacancy-ordered double halide perovskites, Cs2TiI6 films," *Mater Sci Eng B* **296:116645** (Oct 2023). Every accessible rendering of that paper reports **"direct and indirect band gaps of 1.56 eV"** — i.e. 1.56 eV for *both*. The **1.58 eV indirect** figure does not reproduce. Full text unreachable (ScienceDirect 403, academia.edu 403, jina proxy 403; Crossref/OpenAlex/Semantic Scholar hold no abstract). | https://doi.org/10.1016/j.mseb.2023.116645 |
| Cs2SnI6 ~1.3 eV; CsSnI3/FASnI3/MASnI3 ~1.3-1.4 eV (Sn²⁺→Sn⁴⁺); CsGeI3/MAGeI3 ~1.6 eV (Ge²⁺); Cs3Bi2I9/MA3Bi2I9/Cs3Sb2I9 ~1.9-2.1 eV; AgBiI4/Ag2BiI5 ~1.8-1.9 eV; BiSI/BiSeI/SbSI ~1.5-1.9 eV quasi-1D | CONFIRMED | all values within the standard reported ranges | https://doi.org/10.1002/adma.202105844 |
| Oxynitrides SrTaO2N ~2.1, BaTaO2N ~1.8-2.0, CaTaO2N, LaTaON2 ~2.0 eV; studied as photocatalysts | CONFIRMED | — | https://doi.org/10.1126/sciadv.aav0693 (stability); oxynitride photocatalysis literature |
| Reference incumbent Cs/FA-Pb(I,Br)3 ~1.68-1.75 eV; Hoke-effect segregation | CONFIRMED | — | — |
| **EB:** Bartel tolerance factor threshold **tau < 4.18** | CONFIRMED (verbatim) | Bartel et al., *Sci Adv* 5:eaav0693 (2019): "τ < 4.18 indicates perovskite"; 92% accuracy on 576 ABX3 solids. (Same paper: optimal Goldschmidt bounds 0.825 < t < 1.059, 74% accuracy.) | https://doi.org/10.1126/sciadv.aav0693 · https://pmc.ncbi.nlm.nih.gov/articles/PMC6368436/ |
| **EB:** "Zr ~193 ppm, Hf ~5.3 ppm, Ba ~628 ppm, S ~350 ppm crust" | **IMPRECISE (mixed datasets)** | Zr 193 / Hf 5.3 / Ba 628 ppm are **Rudnick & Gao (2003) upper-continental-crust** values; S ~350 ppm is the CRC/whole-crust figure. On one consistent whole-crust dataset: **Zr 165, Hf 3.0, Ba 425, S 350 ppm**. The qualitative claim (abundant, Hf scarcest) survives either way. | https://en.wikipedia.org/wiki/Abundance_of_elements_in_Earth%27s_crust |
| **EB:** Goldschmidt t~0.95, octahedral mu~0.39-0.42 for Ba(Zr0.5Hf0.5)S3 (Shannon radii) | **UNVERIFIABLE** | Not independently recomputed; plausible for 12-coord Ba²⁺ / 6-coord Zr⁴⁺-Hf⁴⁺ / S²⁻ but I did not evaluate the Shannon-radii arithmetic. | — |

### C1_arts_humanities_05 (mnemonic poetic form) — **clean**

| Claim | Verdict | Source |
|---|---|---|
| Sestina: Arnaut Daniel c. 1180s; 39 lines = 6×6 + 3-line envoi; retrogradatio cruciata 6-1-5-2-4-3 | CONFIRMED — schema ABCDEF → FAEBDC → CFDABE → ECBFAD → DEACFB → BDFECA is exactly the 6,1,5,2,4,3 spiral; Arnaut Daniel active c. 1180–1200 | https://en.wikipedia.org/wiki/Sestina · https://www.treccani.it/enciclopedia/sestina_(Enciclopedia-dell'Italiano)/ |
| Quenine / N-ine (Queneau, formalised by Roubaud/Oulipo); Queneau numbers "related to 2 being a primitive root mod 2N+1" | CONFIRMED — precise criterion: n is a Queneau number iff p = 2n+1 is prime and either 2 has order 2n in Z/pZ (2 a primitive root mod p) or n is odd. The "related to" hedge is accurate. | https://oeis.org/A054639 · https://www.ams.org/notices/201105/rtx110500682p.pdf |
| Vedic vikriti-patha: krama / jata (ab/ba/ab) / ghana (ab/ba/abc/cba/abc) | CONFIRMED — standard descriptions of jaṭā- and ghana-pāṭha | https://en.wikipedia.org/wiki/Vedic_chant |
| Villanelle 19 lines, 5 tercets + quatrain, A1/A2 refrains; Pantoum (Malay-derived, 2&4 → 1&3); Ghazal radif + qafiya | CONFIRMED (common knowledge) | — |
| Cisiojanus: medieval Latin calendar mnemonic, **12th c.**, syllable-index → feast day | CONFIRMED — "originated in the late twelfth century"; 365 syllables in 12 hexameter couplets; name from *CIrcumcISIO JANUarius* | https://sites.utexas.edu/ransomcentermagazine/2014/01/20/cisiojanus/ · https://ciphermysteries.com/2018/11/23/the-linguistic-diffusion-of-cisiojanus-mnemonics |
| Dróttkvætt: 8 lines of 6 syllables, obligatory alliteration + hendingar | CONFIRMED — skaldic.org: "stanzas of eight six-syllable lines, regular alliteration and hendingar (skothending in odd lines and aðalhending in even ones)" | https://skaldic.org/m.php?p=doc&i=621 |
| Ars memoriae / *Rhetorica ad Herennium* / Frances Yates *The Art of Memory*; Major & Dominic systems; Oulipo N+7, snowball, *Cent mille milliards de poèmes*, *morale élémentaire* | CONFIRMED (common knowledge) | — |

### C1_biology_medicine_30 (molecular-glue degrader)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| CRBN glues thalidomide/lenalidomide/pomalidomide → IKZF1/IKZF3; lenalidomide also CK1α | CONFIRMED | Krönke et al., *Nature* 2015: lenalidomide induces CRL4(CRBN)-dependent CK1α degradation | https://doi.org/10.1038/nature14610 |
| CC-885 → GSPT1 | CONFIRMED | Matyskiela et al., *Nature* 535:252 (2016) | https://doi.org/10.1038/nature18611 |
| Indisulam/E7820 → DCAF15 → RBM39 | CONFIRMED | Han et al., *Science* 356:eaal3755 (2017) | https://doi.org/10.1126/science.aal3755 |
| BI-3802 → BCL6 polymerization and degradation | CONFIRMED | Słabicki et al., *Nature* 588:164–168 (2020); ligase = **SIAH1** (naming it would strengthen the entry) | https://doi.org/10.1038/s41586-020-2925-1 |
| Cyclin K glues (CR8, dCeMM2/3/4) via DDB1-CUL4 (CDK12) | CONFIRMED | CR8: Słabicki et al., *Nature* 585:293 (2020). dCeMM2/3/4 real: Mayor-Ruiz et al., *Nat Chem Biol* 16:1199–1207 (2020) — substrate-receptor-**independent**, DDB1-CUL4 core, so "via DDB1-CUL4" is the right phrasing | https://doi.org/10.1038/s41586-020-2374-x · https://doi.org/10.1038/s41589-020-0594-x |
| "Covalent glue recruiters using RNF114 (nimbolide), KEAP1, DCAF11, or DCAF16 **to degrade BRD4** and others" | **IMPRECISE** | Two fixes. (a) BRD4 is **not** from the nimbolide paper — Spradlin et al., *Nat Chem Biol* 2019 demonstrates RNF114 recruitment only; BRD4/BCR-ABL degradation via RNF114 is Luo et al., *Cell Chem Biol* 2021. (b) DCAF16/DCAF11/KEAP1 were introduced as **covalent bifunctional (electrophilic PROTAC)** recruiters, not monovalent glues — calling them "glue recruiters" muddies the very glue-vs-PROTAC distinction the query asks the answer to respect. | https://doi.org/10.1038/s41589-019-0304-8 · https://doi.org/10.1038/s41589-019-0279-5 |
| IAP-recruiting SNIPERs; MDM2-based degraders | CONFIRMED | SNIPER = "Specific and Non-genetic IAP-dependent Protein ERaser," recruits cIAP1/XIAP | https://doi.org/10.1080/14756366.2022.2074414 |
| SMARCA2/4 VHL/CRBN degraders; classic VHL/CRBN PROTACs (contrast case) | CONFIRMED | — | — |
| 14-3-3 stabilizer glues (fusicoccin/cotylenin) | CONFIRMED | fusicoccin A explicitly described as a 14-3-3 PPI-stabilizing molecular glue | https://doi.org/10.1002/advs.202508543 · https://doi.org/10.1039/d4sc05963h |
| KRAS G12C/G12D and STAT3 degraders as formerly-undruggable examples | CONFIRMED | G12C: LC-2 (Bond et al., *ACS Cent Sci* 2020). G12D: ASP3082. STAT3: SD-36 (Bai et al., *Cancer Cell* 2019) | https://doi.org/10.1021/acscentsci.0c00411 · https://doi.org/10.1016/j.ccell.2019.10.002 |
| FBXO22-based glue degraders | CONFIRMED (with precision note) | Real, 2025 wave: SMARCA2/4 (Villemure et al., *Nat Commun* 16:9679, 2025, cpd G-6599), NSD2/CDK12, TEAD (FBXO22 **C326**). Mechanism is **covalent cysteine engagement**, so "glue" is loose. | https://doi.org/10.1038/s41467-025-64669-4 |

### C1_materials_chemistry_31 (Li superionic conductor)

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| Li10GeP2S12 and Li9.54Si1.74P1.44S11.7Cl0.3 | CONFIRMED — every subscript exact | Kamaya et al., *Nat Mater* 2011; Kato et al., *Nat Energy* 1:16030 (2016) | https://doi.org/10.1038/nmat3066 · https://doi.org/10.1038/nenergy.2016.30 |
| Argyrodites Li6PS5X (X = Cl, Br, I) | CONFIRMED — correct general formula | — | https://doi.org/10.1038/s41467-025-64357-3 |
| Garnet LLZO Li7La3Zr2O12 with Ta/Al doping | CONFIRMED | — | https://doi.org/10.3390/ijms241612905 |
| **"NASICON LATP/LAGP Li1+xAlxTi2-x(PO4)3"** | **WRONG** | That formula is **LATP only** (typ. Li1.3Al0.3Ti1.7(PO4)3). **LAGP is germanium-based: Li1+xAlxGe2-x(PO4)3** (typ. Li1.5Al0.5Ge1.5(PO4)3). Two formulas are needed. **This one bites:** the item's `expert_baseline` argues the field is forced onto "Ge/rare-earth-bearing oxides," and the query's hard constraint is "avoid scarce or costly constraining elements" — collapsing LAGP into the Ti formula deletes the exact Ge dependence the novelty argument rests on. | https://doi.org/10.1021/acsomega.0c01826 · https://doi.org/10.3390/molecules28248029 |
| Perovskite LLTO Li3xLa(2/3-x)TiO3 | CONFIRMED — notation variant only | — | https://doi.org/10.3390/ma16227088 |
| Halides Li3YCl6, Li3InCl6, Li3ScCl6, Li2ZrCl6 | CONFIRMED — all four real | — | https://doi.org/10.1021/acs.chemmater.5c02303 · https://doi.org/10.1016/j.cej.2022.135413 |
| Anti-perovskites Li3OCl and Li3OCl0.5Br0.5 | CONFIRMED — Li3OCl is the standard ordering | — | https://doi.org/10.1002/advs.201500359 · https://doi.org/10.1021/acsmaterialsau.1c00026 |
| Thin-film LiPON | CONFIRMED | Bates et al., *Solid State Ionics* 2000 | https://doi.org/10.1016/S0167-2738(00)00327-1 |
| Thio-LISICON Li3.25Ge0.25P0.75S4; glass-ceramic Li7P3S11 | CONFIRMED — both stoichiometries appear verbatim | Kanno & Murayama, *JES* 2001 | https://doi.org/10.1149/1.1379028 · https://doi.org/10.1016/j.electacta.2017.09.156 |
| LiBH4, Li2B12H12, Li(CB11H12) | CONFIRMED — all three real | 0.7Li(CB9H10)–0.3Li(CB11H12) reaches 6.7 mS/cm at 25 °C | https://doi.org/10.1038/s41467-019-09061-9 · https://doi.org/10.1039/c5ee02941d |
| Li3N and lithium nitride-halides; Na3Zr2Si2PO12 (context) | CONFIRMED | — | https://doi.org/10.3390/ma14143790 |

### C1_engineering_32 (radiative cooling) — **clean**

| Claim | Verdict | Source |
|---|---|---|
| Raman et al. 2014 photonic multilayer (HfO2/SiO2 on Ag) | CONFIRMED — Raman AP, Anoma MA, Zhu L, Rephaeli E, Fan S, *Nature* 515:540–544 (27 Nov 2014) | https://pubmed.ncbi.nlm.nih.gov/25428501/ |
| Zhai et al. 2017 glass-polymer hybrid metamaterial (SiO2 microspheres in polymer, Ag backing) | CONFIRMED — *Science* 355:1062–1066 (2017); SiO2 microspheres in polymethylpentene (TPX) over 200 nm Ag; ~96% solar reflectance, IR emissivity >0.93, 93 W/m² noon cooling | https://doi.org/10.1126/science.aai7899 |
| Mandal et al. 2018 hierarchically porous P(VdF-HFP) | CONFIRMED — *Science* 362:315–319 (2018); R_solar 0.96±0.03, LWIR ε 0.97±0.02, ~6 °C sub-ambient, ~96 W/m² | https://doi.org/10.1126/science.aat9513 |
| Purdue ultra-white BaSO4-acrylic paint (Ruan group) | CONFIRMED — Ruan-group BaSO4 paint/film line (Li/Peoples/Felicelli/Ruan) | https://doi.org/10.1515/nanoph-2023-0567 |
| Purdue CaCO3-acrylic white paint | CONFIRMED — Ruan-group CaCO3-acrylic paint | https://doi.org/10.1016/j.xcrp.2020.100221 |
| Delignified nanowood / cellulose cooler (Hu group) | CONFIRMED — Li T et al., *Science* 364:760–763 (2019), "A radiative cooling structural material" | https://doi.org/10.1126/science.aau9101 |
| Silica aerogel & anodized-aluminium coolers; PDMS-on-metal emitters; TiO2/ZnO baseline paints; hBN coatings; SiC/SiO2 metasurface selective emitters; colored/structural-color coolers | CONFIRMED at family level — all real, well-represented device classes | https://doi.org/10.1515/nanoph-2024-0489 |

### C1_arts_humanities_33 (tuning system) — **clean**

| Claim | Verdict | Source |
|---|---|---|
| 12-TET, Pythagorean, meantone (1/4- and 1/6-comma), 5-limit JI diatonic | CONFIRMED (common knowledge) | — |
| Well temperaments Werckmeister III, Kirnberger III, **Vallotti**, Young | CONFIRMED — Vallotti temperament, invented by Francesco Antonio Vallotti | https://en.wikipedia.org/wiki/Well_temperament |
| 19-TET; 22-TET and **Indian shruti** systems; 31-TET (Huygens/Fokker); 53-TET | CONFIRMED — the 22-śruti division of the octave is attested from the *Nāṭyaśāstra* onward | https://en.wikipedia.org/wiki/Shruti_(music) |
| Bohlen-Pierce: tritave (3:1) divided into **13 equal steps** | CONFIRMED — approximates the 3:5:7 wide triad at steps 0/6/10 | https://microtonal.miraheze.org/wiki/Bohlen%E2%80%93Pierce_scale |
| Wendy Carlos Alpha / Beta / Gamma | CONFIRMED — steps 77.965 c / 63.8 c / 35.1 c; introduced on *Beauty in the Beast* (1986) | https://en.wikipedia.org/wiki/Wendy_Carlos_scales |
| Harry Partch 43-tone JI | CONFIRMED (common knowledge) | — |
| Named regular temperaments: meantone, porcupine, **miracle**, **magic**, **pajara** | CONFIRMED — miracle discovered by George Secor (eponym of the *secor*); magic = regular temperament with generator ≈ 5/4; pajara first defined by Paul Erlich. Porcupine is standard in regular-temperament theory but verified only indirectly (en.xen.wiki is Cloudflare-blocked to automated fetches). | https://en.wikipedia.org/wiki/George_Secor · https://en.wikipedia.org/wiki/Magic_temperament · https://en.wikipedia.org/wiki/Paul_Erlich |
| Erv Wilson MOS and combination-product-set scales | CONFIRMED — Wilson coined both | https://en.wikipedia.org/wiki/Erv_Wilson |

---

## Recommended mechanical replacements

Apply to `question/crest_challenges.jsonl` (and the audit copy). Each is an exact substring
replacement; the surrounding entry text is unchanged unless shown.

### WRONG — fix before release

**1. `C1_biology_medicine_00` / `known_answers` — nonexistent compound**
```
OLD: Darobactin and dynobactin N: bind BamA of the BAM
NEW: Darobactin and dynobactin A: bind BamA of the BAM
```

**2. `C1_biology_medicine_00` / `known_answers` — wrong drug code**
```
OLD: Type I signal peptidase (LepB) inhibitors: arylomycins, G0775/RG6114. => LepB KNOWN.
NEW: Type I signal peptidase (LepB) inhibitors: arylomycins, G0775 (Genentech; Smith et al., Nature 2018). => LepB KNOWN.
```
(`RG6114` is inavolisib/GDC-0077, an unrelated PI3Kα drug — delete, do not "correct" to another code.)

**3. `C1_engineering_04` / `known_answers` — phantom co-author + wrong companion journal**
```
OLD: Correa, Klatt, Spadaccini, Seepersad et al., 'Negative stiffness honeycombs for recoverable shock isolation,' Rapid Prototyping Journal, 2015 (and companion work in Additive Manufacturing, 2015).
NEW: Correa, Klatt, Cortes, Haberman, Kovar, Seepersad, 'Negative stiffness honeycombs for recoverable shock isolation,' Rapid Prototyping Journal 21(2):193-200, 2015 (and companion work: Correa, Seepersad, Haberman, 'Mechanical design of negative stiffness honeycomb materials,' Integrating Materials and Manufacturing Innovation 4:10, 2015).
```

**4. `C1_materials_chemistry_31` / `known_answers` — LAGP given the LATP formula**
```
OLD: NASICON LATP/LAGP Li1+xAlxTi2-x(PO4)3
NEW: NASICON LATP Li1+xAlxTi2-x(PO4)3 and LAGP Li1+xAlxGe2-x(PO4)3
```

### IMPRECISE — recommended

**5. `C1_biology_medicine_00` / `known_answers` — polymyxin programs conflated**
```
OLD: Polymyxins/colistin and next-gen analogs SPR206, SPR741/MRX-8: bind lipid A / permeabilize the outer membrane.
NEW: Polymyxins/colistin and next-gen analogs SPR206 (Spero, direct-acting) and MRX-8 (MicuRx, direct-acting), plus the non-bactericidal potentiator SPR741 (Spero): bind lipid A / permeabilize the outer membrane.
```

**6. `C1_economics_business_02` / `known_answers` — 24h cap applies only to Preemptible VMs**
```
OLD: Google Cloud Spot/Preemptible VMs (fixed or percentage discount, no bidding, ~24h max life, ~30s preemption notice)
NEW: Google Cloud Spot VMs (fixed or percentage discount, no bidding, no maximum runtime, ~30s preemption notice) and their legacy Preemptible-VM predecessor (~24h max life, ~30s notice)
```

**7. `C1_engineering_04` / `known_answers` — range should open at 2007 (Mullin et al., PRL 2007)**
```
OLD: Bertoldi, Reis, Shim, Mullin et al., ~2008-2017.
NEW: Mullin, Bertoldi, Reis, Shim et al., ~2007-2017 (Mullin et al., PRL 2007; buckliball: Shim et al., PNAS 2012).
```

**8. `C1_engineering_04` / `known_answers` — Maskery TPMS work is not TPU**
```
OLD: Triply periodic minimal surface (TPMS) lattices (gyroid, Schwarz-P) printed in TPU/elastomer for recoverable cushioning — e.g., Maskery, Ashcroft, Hague et al. and related TPU-gyroid energy-absorption studies, ~2017-2021.
NEW: Triply periodic minimal surface (TPMS) lattices (gyroid, Schwarz-P) as energy absorbers — Maskery, Ashcroft, Hague et al. in laser-sintered polyamide (~2017-2018) plus a separate body of TPU/elastomer-gyroid recoverable-cushioning studies, ~2018-2021.
```

**9. `C1_law_policy_03` / `known_answers` — Macauley did not publish on orbital deposit-refund/bonds**
```
OLD: Deposit-refund schemes and performance (deorbit) bonds — Molly Macauley (Resources for the Future) and OECD space-economy analyses: operators post a refundable bond returned only on verified end-of-life disposal. KNOWN.
NEW: Deposit-refund schemes and performance (deorbit) bonds — OECD space-economy analysis (Undseth, Jolly & Olivari, 'Space sustainability: the economics of space debris in perspective,' OECD STI Policy Paper, Apr 2020) and academic bond proposals (e.g. Bullock & Johanson, MIT Science Policy Review 2021); background orbital-debris economics from Molly Macauley (Resources for the Future, Acta Astronautica 2015): operators post a refundable bond returned only on verified end-of-life disposal. KNOWN.
```

**10. `C1_law_policy_03` / `known_answers` — SSR dates**
```
OLD: Space Sustainability Rating — World Economic Forum concept (~2019-2021), operational home at eSpace/EPFL from ~2022
NEW: Space Sustainability Rating — World Economic Forum concept (Global Future Council on Space, 2016; design consortium appointed 2019), eSpace/EPFL selected as operator May 2021, went live June 2022, independent SSR Association from Jan 2023
```

**11. `C1_materials_chemistry_01` / `known_answers` — Cs2TiI6 indirect-gap figure not reproducible**
```
OLD: (Cs2TiI6 measured 1.56 eV direct / 1.58 eV indirect)
NEW: (Cs2TiI6 films: direct and indirect gaps both reported ~1.56 eV, Aslam et al., Mater Sci Eng B 296:116645, 2023)
```

**12. `C1_materials_chemistry_01` / `expert_baseline` — abundances mix two crustal datasets**
```
OLD: (Zr ~193 ppm, Hf ~5.3 ppm, Ba ~628 ppm, S ~350 ppm crust)
NEW: (upper continental crust, Rudnick & Gao 2003: Zr ~193 ppm, Hf ~5.3 ppm, Ba ~628 ppm, S ~62 ppm; whole-crust CRC values: Zr ~165, Hf ~3.0, Ba ~425, S ~350 ppm)
```
*If a single number per element is wanted, use one consistent dataset — the current mix silently
swaps reference frames mid-sentence.*

**13. `C1_biology_medicine_30` / `known_answers` — glue-vs-PROTAC conflation and misattributed BRD4**
```
OLD: Covalent glue recruiters using RNF114 (nimbolide), KEAP1, DCAF11, or DCAF16 to degrade BRD4 and others
NEW: Covalent E3 recruiters using RNF114 (nimbolide; Spradlin et al. 2019 - BRD4/BCR-ABL degradation via RNF114 from Luo et al. 2021), KEAP1, DCAF11, or DCAF16 (introduced as electrophilic bifunctional PROTACs, with monovalent versions only more recently)
```

### Optional strengthening (no verdict against the text)

- `C1_biology_medicine_30`: name **SIAH1** as the BI-3802/BCL6 ligase, and cite Słabicki 2020 /
  Mayor-Ruiz 2020 explicitly. Reframe FBXO22 as **covalent cysteine-engaging** degraders (real
  targets: SMARCA2/4, NSD2, CDK12, TEAD; 2025).
- `C1_biology_medicine_00` `expert_baseline`: either cite a specific A. baumannii essential-gene
  source for *murJ* (Ward et al., *mBio* 2024 is the best current one) or soften "is called
  essential in … Tn-seq essential-gene sets (ATCC 17978 / AB5075)" to "is essential or
  near-essential in Gram-negative essential-gene datasets."
- `C1_law_policy_03`: TraCSS's FY2026 funding was proposed for termination and restored by Senate
  appropriators (July 2025). A 2026-dated item that treats TraCSS as a settled fixture is
  optimistic; one sentence of hedging would future-proof it.
- `C1_law_policy_03`: ClearSpace-1 has re-targeted from VESPA to PROBA-1 with launch slipped to
  ~2028/29 — worth a parenthetical if answers might be scored on mission status.

---

## Overall assessment: are C1's novelty baselines trustworthy enough to score against?

**Yes, after the four `known_answers` fixes (items 1, 2, 4 above plus the engineering citation).**

The reasoning:

1. **Nothing is fabricated.** Across ~95 checkable claims spanning ten disciplines, every named
   paper, compound, statute, standard, mission and commercial product turned out to exist. This is
   the property that matters most for a novelty yardstick: a hallucinated prior-art entry would
   penalise a genuinely novel answer for "restating" something that was never published. That
   failure mode is absent from C1.

2. **The error rate is low and the errors are shallow.** 5 WRONG out of ~95 (~5%), and four of
   the five are *labelling* errors — a wrong compound suffix, a wrong internal drug code, a phantom
   co-author, a wrong journal. In every one of those cases the **underlying target/mechanism/prior
   art is correctly identified**, so the novelty boundary the entry draws is still in the right
   place. An agent proposing BamA would still be correctly marked not-new; an agent proposing LepB
   would still be correctly marked not-new.

3. **One error has real semantic bite.** `C1_materials_chemistry_31`'s LAGP formula is the
   exception. That item's whole novelty framing is "you can't get >1 mS/cm plus Li-metal stability
   without sulfides or **Ge**/rare-earth oxides," and the prior-art list as written contains no
   germanium NASICON at all — LAGP is spelled with the titanium formula. An answer that proposed a
   Ge-free NASICON could be scored as more novel than it is, or a judge could get confused about
   what the excluded-element constraint even covers. **Fix this one before release.**

4. **The `expert_baseline` fields are in better shape than expected.** These are prose arguments,
   mostly unfalsifiable by design, but where they make hard checkable claims they hold up: Bartel
   τ < 4.18 is verbatim correct, MurJ's structural and superfamily characterisation is correct, the
   OST/Liability-Convention article mapping is verbatim correct, and the TPU material data is
   right. The two soft spots (mixed crustal-abundance datasets, the unverified *murJ* Tn-seq
   citation) affect the *decoration* of the argument, not its logic.

5. **Three items are fully clean:** `C1_arts_humanities_05`, `C1_arts_humanities_33`, and
   `C1_engineering_32`. The two humanities items are notably strong — the sestina permutation, the
   Queneau-number criterion, the dróttkvætt line/syllable count, and the Cisiojanus dating all
   check out exactly, which is not the norm for humanities prior-art lists in AI-authored
   benchmarks.

6. **Residual risk to be aware of.** (a) The IMPRECISE cluster in `C1_law_policy_03` and
   `C1_materials_chemistry_01` consists of dates and numbers that a strong answer might itself get
   *more* right than the baseline does — a judge scoring "agrees with known_answers" rather than
   "agrees with reality" would punish accuracy. Worth a rubric note. (b) Two items
   (`C1_law_policy_03`, `C1_economics_business_02`) reference fast-moving operational facts (TraCSS
   funding, cloud spot-market terms) that will drift; they need a re-check on any future release,
   not a fix now.

**Verdict: release-ready for 6 of 10 items as-is, and for all 10 after applying the four WRONG
fixes. The nine IMPRECISE fixes are strongly recommended but not blocking.**

---

## Sourcing limitations to disclose

- The session's WebSearch budget (200 calls) was exhausted partway through; the remainder of the
  audit was done via WebFetch and direct HTTPS against primary sources and literature APIs
  (Europe PMC, Crossref, OpenAlex, Semantic Scholar, PubChem, USENIX/NeurIPS proceedings).
- Three sources were unreachable to automated fetching and forced fallbacks:
  **ScienceDirect** (403, blocked the Cs2TiI6 full text — hence that verdict's low confidence),
  **science.org** (Cloudflare, worked around via PMC), and **en.xen.wiki** (Cloudflare, so
  "porcupine temperament" is confirmed only indirectly).
- `C1_engineering_04`'s adidas 4DFWD primary press release now returns 404/202; that date rests on
  secondary sources.
