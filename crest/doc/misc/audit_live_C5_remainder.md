# Live-web citation audit — C5 remainder (5 items)

Scope: `C5_arts_humanities_29`, `C5_materials_chemistry_25`, `C5_biology_medicine_24`,
`C5_engineering_28`, `C5_arts_humanities_49` in `questions/crest_challenges.audit.jsonl`.
Audited live-web against primary sources (publisher DOI pages, Crossref, official
registries, regulator press releases, university-press books). Wikipedia was not
used as the sole basis for any verdict.

**No `.jsonl` file was edited.** Replacement strings below are proposals only; each has
been verified to occur EXACTLY ONCE in the raw file text.

**Continuity.** These five items are precisely the set that `docs/notes/audit_live_C4_C5.md` §6
listed as "NOT audited beyond a read-through" when its WebSearch budget ran out at 200/200, minus
the four C4 items since closed by `audit_live_C4_remainder.md`. With this pass, claim-level live
audit coverage of the 50-item file is complete. Two prior conclusions are refined here:

- The earlier pass called catalogue quality **bimodal by item ID**, with the densely-cited `_1x`/`_2x`
  items the strong end. That is half right: `C5_engineering_28` (a `_2x`) is indeed the most densely
  dated item in this batch at 95%, **but its dates are the most systematically wrong of any item
  audited so far** (§0b). Citation density was being read as a proxy for reliability; it is not one.
- The earlier pass flagged `C5_arts_humanities_49` as having a bare, undated catalogue. Confirmed
  and quantified: 17 of its 20 entries carry no date whatsoever, and all 20 are Western (§5.1).

---

## Headline findings

0. **Single most exposed error, found in the largest baseline:** `C5_materials_chemistry_25` `[5]`
   credits metal-organic frameworks to "**Yaghi/Kitagawa, late 1990s**" — omitting **Richard
   Robson**, who shared the **2025 Nobel Prize in Chemistry** for MOFs and whom the Nobel committee
   names as the originator ("It was Robson who first reasoned it would be possible to make these
   frameworks in the **1980s**"). Robson & Hoskins published in *JACS* **1989/1990**. A publicly
   released 2026 benchmark carrying this will be noticed on sight by any materials reviewer (§3.2).
1. **The open lead is confirmed and the pattern holds.** `C5_biology_medicine_24` dates
   oncolytic-virus approvals to "since 2015". The real first approvals are **Latvia 2004
   (Rigvir)** and **China 2005 (Oncorine/H101)**; 2015 is only the first *FDA* approval. Same
   defect as found elsewhere: prior art dated younger than reality, inflating apparent novelty.
2. **The same defect is epidemic in the two most densely dated items, and it is strictly
   one-directional.** `C5_engineering_28`: **13 of 23** claim units date prior art to a brand launch
   or research boom rather than first publication — by up to **85 years** (electroadhesion:
   Johnsen-Rahbek 1923, listed as "SRI ~2008") and 51 years (electropermanent magnets: US 3,089,064
   filed 1959, listed as "Knaian 2010"). Only 2 of 23 survive unamended.
   `C5_materials_chemistry_25`: **13 of ~39** dated claims defective — carbon nanotubes **−39 yr**
   (Radushkevich & Lukyanovich 1952), halide perovskites **−31 to −116 yr** (Weber 1978; Wells 1893),
   amorphous metals −26, zeotypes −30, MOPs −14. **Across all five items and ~130 claim units, not
   one date error runs in the direction that would make a submission look *less* novel.**
3. **A defect class that the earlier passes largely missed: `expert_baseline` fields point
   graders at white space that is already occupied.** (`audit_live_C4_remainder.md` caught one
   instance in `C4_engineering_45`; `audit_live_C4_C5.md` §1d checked all 20 baselines and
   concluded "no defects" because it tested only for dated citations.) **Four more instances here,
   giving a base rate of 5 for 5 on items actually tested for it.** The worst is
   `C5_materials_chemistry_25`, whose baseline nominates knot/entanglement order and non-atomic
   lattices as the winning territory — the former named and formalised by **Robson himself in 1998**
   and instantiated by woven COF-505 *which the same item lists as prior art in entry `[6]`*, the
   latter occupied since the Abrikosov vortex lattice of **1957**. In
   `C5_biology_medicine_24` the baseline nominates "phase behavior/condensate control,
   mechanical/rheological state" as the genuinely-novel territory — but condensate modulators
   are clinical-stage and **histotripsy has FDA authorisation (Oct 2023)** and **Tumor Treating
   Fields since 2011**. In `C5_arts_humanities_29` the baseline's two worked examples of a
   "new constraint TYPE" are the defining principles of Occitan *partimen* / Japanese *mondōka*
   and of 4th-century Chinese *huiwen* grid poetry respectively. Because `hard_rule` R5/R3 say
   novelty is voided if the principle already exists, these items instruct the grader to reward
   what the rules require them to zero.
4. **One "right thing, wrong famous name" instance found** (`C5_arts_humanities_29` `[15]`):
   Agha Shahid Ali is listed as a practitioner of the "looser American ghazal" when he was its
   most prominent *opponent*, who edited *Ravishing DisUnities: **Real** Ghazals in English*
   (2000) specifically to insist on strict *radif* + *qafia*. Notably, the engineering item
   contains **no** name-substitution errors — its two attribution faults are an author credited
   on a paper he is not on (Aizenberg) and a control theorist read as a hardware paper's author
   (Skelton).
5. **The non-Western blind spot is real, load-bearing, and sharper than "some forms are
   missing."** `C5_arts_humanities_49`'s catalogue is, by inspection of all 20 forms, **entirely
   Western** (European art music plus Anglo-American popular song) — and, more diagnostically,
   its 20 entries are almost all **thematic-return** schemes. An entire axis of formal
   organisation is absent: form built primarily by **metric/temporal transformation**, which is
   how Javanese *irama*, Japanese *jo-ha-kyū* and Korean *sanjo* each organise large-scale
   structure (§5.2). A submission inventing "form as hierarchical metric-density expansion"
   collides with nothing on the list. `C5_arts_humanities_29` is genuinely cross-lingual but
   dates its non-Western and ancient prior art too young — most sharply at `[23]`, which credits
   visual/pattern poetry to Herbert (1633) when Greek *technopaegnia* (c. 300 BCE) and Sanskrit
   *citrakāvya* (6th-7th c. CE) precede it by 1,000-1,900 years.

---

## 0a. Why these defects are not recoverable at judge time

From `judge/score.py` (`_judge_prompt`), the judge is instructed:

> *"**New**: novelty vs the DATED KNOWN ANSWERS below. **Judge ONLY against that list, NOT
> against the web or your own background knowledge** — an idea absent from the list is new FOR
> THIS BENCHMARK even if you believe you have seen it, and an idea present in the list is not
> new even if it looks fresh."*

and

> *"**Surprising**: expectation-violation vs the EXPERT BASELINE …"*

Three consequences that set the severity of everything below:

1. **A missing entry is an unrecoverable false-novelty award.** The judge is explicitly barred
   from using background knowledge to catch omitted prior art. So the MISSING-prior-art lists in
   this audit are not a nice-to-have — they are the *only* defence the scoring pipeline has.
   Every family listed in §1.4, §2.3, §3.5, §4.4 and §5.4 is a guaranteed New = 7-10 for an agent
   that rediscovers it.
2. **`expert_baseline` is piped in as the Surprise reference.** So an `expert_baseline` that
   nominates already-occupied territory as the "genuinely surprising" answer does active harm:
   an agent that lands on histotripsy-like tissue mechanics, condensate control, or a
   *partimen*/*huiwen*-style reading-path rule collects a *high* Surprise score for reproducing
   FDA-authorised or 4th-century prior art — and the judge is forbidden from correcting it.
3. Date errors bite indirectly rather than directly: the judge compares against list *contents*,
   but the `hard_rules` shown alongside it (and the agent's own prompt) reference "the **dated**
   known-answers list" and dated prior-art cutoffs, so a wrongly-young date shifts the horizon
   an agent must argue past. The `_MAX_KNOWN_ANSWERS = 40` cap does not fire at 33.

---

## 0b. Dating density vs dating accuracy — and continuity with the earlier passes

The prior passes (`docs/notes/audit_live_C4_C5.md` §5, `audit_live_C4_remainder.md` §2) established
two things: (i) a systematic **brand-date vs concept-date** defect with *zero counter-examples*, and
(ii) a citation-density cliff in the back half of the file. Both hold here, and this pass adds a
third observation: **density and accuracy are independent failures.**

| Item | real entries | carry a date | bare (no date at all) |
|---|---|---|---|
| `C5_engineering_28` | 22 | **21 (95%)** | 1 |
| `C5_arts_humanities_29` | 32 | 24 (75%) | 8 |
| `C5_biology_medicine_24` | 26 | 13 (50%) | 13 |
| `C5_materials_chemistry_25` | 32 | 16 (50%) | 16 |
| `C5_arts_humanities_49` | 20 | **3 (15%)** | **17** |

- `C5_engineering_28` is the **most densely dated** item of the five — and it is also the most
  systematically **mis**-dated: 13 of 23 claim units credit prior art to a brand launch or research
  boom rather than first publication, every one in the novelty-inflating direction, with gaps of 5
  to 85 years. Compare the earlier passes, where the same defect ran only 1-9 years. **The pattern
  does not merely hold; it is an order of magnitude worse in this item.** Dating something is not
  the same as dating it right.
- `C5_arts_humanities_49` fails the opposite way: 17 of 20 entries are completely bare
  ("Ternary form (ABA).", "Rondo (ABACA...).", "Ritornello form."). There is no date to be wrong
  about, and therefore no auditable prior-art boundary at all.
- Several entries use **non-dates that read like dates**: "(established)" appears throughout
  `C5_biology_medicine_24`; `C5_engineering_28` `[21]` says "(established automotive prior art)"
  for a principle patented in **1877**; `C5_arts_humanities_29` `[22]` says "ancient through John
  Cage". These are unfalsifiable and should be replaced with an earliest-publication year.

**Zero counter-examples in this pass either.** Across all date defects found in these five items,
not one runs in the direction that would make a submission look *less* novel.

---

## 0c. NEW SYSTEMIC DEFECT CLASS: `expert_baseline` nominating occupied white space

This is the most transferable finding of this pass, and it needs work outside my five items.

`audit_live_C4_C5.md` §1d checked all 20 `expert_baseline` fields and concluded **"No defects found
in `expert_baseline`"** — but it tested only for *falsifiable dated citations*, of which these prose
fields contain almost none. It did not test the thing that actually matters: **whether the territory
the baseline nominates as "genuinely novel" is already occupied.** `audit_live_C4_remainder.md` then
found exactly that defect in `C4_engineering_45`, where both the `expert_baseline` and the
`hard_rules` worked examples turned out to be prior art already sitting in the item's own
`known_answers` entry #1.

This pass confirms the same defect in **four** more items:

| Item | Nominated as the novel/winning territory | Actually |
|---|---|---|
| `C5_materials_chemistry_25` | (i) "long-range order defined by a conserved topological/knot invariant of interwoven covalent strands"; (ii) "lattice sites are an ordered, kinetically trapped array of non-atomic entities" | (i) an established sub-discipline: Batten & **Robson**, "Interpenetrating Nets: Ordered, Periodic **Entanglement**" (1998); entanglement invariants formalised in *Acta Cryst. A* 2012/2020; and **woven COF-505, which this item lists as prior art in its own entry `[6]`**. (ii) Abrikosov vortex lattice **1957**; skyrmion lattices 2009 incl. metastable/quenched; **Wigner crystals** — lattice sites literally made of electrons; **artificial spin ice** — an engineered, frustrated, kinetically trapped array. Even the baseline's *fallback* answer is published (§3.4) |
| `C5_biology_medicine_24` | "a physical state variable of tissue (phase behavior/condensate control, mechanical/rheological state, or spatial organization)" | condensate modulators clinical-stage; **histotripsy FDA-authorised Oct 2023**; **TTFields FDA-approved 2011** (§1.3) |
| `C5_arts_humanities_29` | "each line must be a valid answer to the question posed by the previous line"; "a 'branching' form with two legal reading-paths" | Occitan *partimen* / Japanese *mondōka* (*Kojiki*, 712 CE) — and *katauta*, whose paired use IS question-and-answer, is **already in the item's own entry `[12]`**; Su Hui's *Xuanji tu*, 4th c. CE (§2.2) |
| `C5_engineering_28` | the reference-floor device itself (bistable flexure + EPM tool-changer) | already granted art: **US 10,335,958 / US 10,414,055 (2019)**, absent from the list; and its force estimate breaks the B²/2μ₀ ceiling by 1-2 orders of magnitude (§4.1) |

Because `judge/score.py` pipes `expert_baseline` in as the **Surprise** reference (§0a), this defect
does not merely fail to help — it *inverts* the axis. An agent that lands on the nominated territory
is reproducing prior art while collecting a high Surprise score, and the judge is explicitly
forbidden from using its own knowledge to notice.

**Recommended follow-up beyond this audit's scope.** Seven C5 items have an `expert_baseline` that
nominates specific "genuinely novel" territory rather than merely describing the convergent expert
answer:

`C5_arts_humanities_29` ✓defect found · `C5_biology_medicine_24` ✓defect found ·
`C5_materials_chemistry_25` ✓defect found (§3.4) · **`C5_economics_business_26`** ·
**`C5_law_policy_27`** · **`C5_economics_business_46`** · **`C5_law_policy_47`**

(`C5_engineering_28`'s baseline does not use the "here is what would be genuinely novel" phrasing the
scan keyed on, yet carries the same defect — so the four bold items are a floor, not a ceiling.
Running base rate: **5 of 5 items tested for this defect have it**, counting `C4_engineering_45`.)

The four in bold were covered by the earlier pass **under the test that missed this defect**, so they
are effectively unverified against it. Each should be re-checked with one question: *is the thing the
baseline calls novel already published, approved, or productised?* On a base rate of 4 of 4 items so
far, the prior should be that at least some of them are.

---

## 0d. Baseline-size correction (affects the framing of this whole audit)

The two "33-entry" baselines are not 33 real entries.

| Item | `known_answers` length | Actual catalogued items | Non-item overhead |
|---|---|---|---|
| C5_arts_humanities_29 | 33 | **32** | `[0]` is a dating/instructions note |
| C5_materials_chemistry_25 | 33 | **32** | `[32]` is a dating/instructions note |
| C5_arts_humanities_49 | 21 | **20** | `[0]` is a dating/instructions note |
| C5_biology_medicine_24 | 26 | 26 | — |
| C5_engineering_28 | 22 | 22 | — |

Additionally `C5_arts_humanities_29` **double-counts the nonet**: it appears as a named
form in entry `[10]` ("Nonet (nine lines counting DOWN 9->1 syllables)") and again in
entry `[32]` ("bref double, glose/glosa, pleiades, **nonet**, tanka-sequence"). Real
distinct forms in that catalogue: **31**.

---

## 1. C5_biology_medicine_24 — therapeutic modalities (26 entries)

### 1.1 The open lead: "oncolytic virus approvals since 2015" — **the pattern HOLDS**

Entry `[18]` reads: *"Oncolytic viruses (established niche; approvals since 2015)"*.
This is **WRONG**, and wrong in exactly the direction previously found elsewhere in this
dataset: prior art dated ~11 years YOUNGER than reality, which inflates apparent novelty.

Actual approval timeline, as of the item's own 28 July 2026 floor:

| Product | Jurisdiction | Approval | Note |
|---|---|---|---|
| **Rigvir** (unmodified ECHO-7 picornavirus) | **Latvia, 2004** | first oncolytic virus approved anywhere | later also Georgia (2015), Armenia (2016); Latvian marketing authorisation **suspended 30/31 May 2019** on quality grounds |
| **Oncorine / H101** (E1B-55K-deleted Ad5) | **China, Nov 2005** | first *recombinant* oncolytic virus approved anywhere | nasopharyngeal carcinoma + chemo |
| **T-VEC / Imlygic** (HSV-1 + GM-CSF) | USA, 2015 (then EU) | first **FDA/Western** approval — this is what "2015" actually refers to | unresectable metastatic melanoma |
| **Delytact / teserpaturev (G47Δ)** | Japan, **June 2021** (conditional, time-limited, 7 yr) | first oncolytic virus for a primary brain cancer | launched Nov 2021 |

Sources:
- Rigvir 2004 + Georgia/Armenia: https://pmc.ncbi.nlm.nih.gov/articles/PMC6557159/ ; https://pmc.ncbi.nlm.nih.gov/articles/PMC4560272/
- Rigvir suspension 2019 (regulator, primary): https://www.zva.gov.lv/en/news-and-publications/news/rigvir-marketing-authorisation-suspended-information-current-patients
- Oncorine/H101 China 2005: https://pmc.ncbi.nlm.nih.gov/articles/PMC6557159/ ; https://www.genetherapynet.com/oncorine.html
- T-VEC 2015: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5029010/
- Delytact 2021 (company primary): https://www.daiichisankyo.com/files/news/pressrelease/pdf/202106/20210611_E_47.pdf and launch https://www.daiichisankyo.com/files/news/pressrelease/pdf/202111/20211101_E.pdf

**Verdict: WRONG.** This is the same systematic defect: the entry silently adopts the
*FDA* milestone as the *class* milestone. An agent proposing "regionally-approved
unmodified enterovirus virotherapy" or "E1B-deleted adenoviral oncolysis" would, under
the current entry, look like it was clearing a 2015 floor rather than a 2004/2005 one.

Also verified for completeness: **no** new oncolytic approval lands before the 28 July 2026
floor. Replimune's RP1 (vusolimogene oderparepvec) had FDA CRLs in July 2025 and April
2026; the accepted resubmission carries a goal date of **2 August 2026** — five days after
the item's cutoff. https://ir.replimune.com/news-releases/news-release-details/replimune-announces-fda-acceptance-rp1-biologics-license

### 1.2 Other verdicts

| Claim | Verdict | Correct value | Source |
|---|---|---|---|
| `[18]` "approvals since 2015" | **WRONG** | first approvals 2004 (Rigvir, Latvia) and 2005 (Oncorine, China); 2015 = first FDA | see 1.1 |
| `[19]` phage therapy "compassionate-use/clinical-trial stage in 2026" | **IMPRECISE** | true for the US/EU only. Phage preparations are **registered medicines sold in pharmacies** in Russia (NPO Microgen, 14 licensed phage products) and Georgia (Eliava PYO/Intesti), continuously for decades | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10135294/ ; https://phage.ge/en ; https://www.scfh.ru/en/papers/phages-attack/ |
| `[5]` "mRNA vaccines validated 2020-2021" | CONFIRMED | BNT162b2 EUA 11 Dec 2020; mRNA-1273 EUA 18 Dec 2020 | https://www.federalregister.gov/documents/2021/01/19/2021-01022/authorizations-of-emergency-use-of-two-biological-products-during-the-covid-19-pandemic-availability |
| `[12]` "first CRISPR therapy approved 2023" | CONFIRMED | Casgevy (exa-cel): MHRA Nov 2023, **FDA 8 Dec 2023** (SCD); beta-thal 16 Jan 2024 | https://news.vrtx.com/news-releases/news-release-details/vertex-and-crispr-therapeutics-announce-us-fda-approval |
| `[12]` "base/prime editors in clinic by 2025-2026" | CONFIRMED | in vivo CRISPR still pre-approval at the cutoff: Intellia began a rolling BLA for lonvo-z (NTLA-2002) in Apr 2026 | https://ir.intelliatx.com/news-releases/news-release-details/intellia-therapeutics-initiates-rolling-submission-biologics |
| `[20]` "FMT-derived approvals 2022-2023" | CONFIRMED | Rebyota (fecal microbiota, live-jslm) 30 Nov 2022; Vowst (spores, live-brpk) 26 Apr 2023 | https://www.ferring.com/ferring-receives-u-s-fda-approval-for-rebyota-fecal-microbiota-live-jslm-a-novel-first-in-class-microbiota-based-live-biotherapeutic/ ; https://www.fda.gov/media/168002/download |
| `[10]` RNA editing "AIMer/RESTORE-type... early clinical ~2024-2026" | CONFIRMED | RESTORE = Merkle, Merz, Reautschnig et al., *Nat Biotechnol* 37:133 (2019); first-ever human RNA editing = Wave WVE-006 (AIMer), announced 16 Oct 2024 | https://www.nature.com/articles/s41587-019-0013-6 ; https://ir.wavelifesciences.com/node/11731 |
| `[16]` in vivo CAR "preclinical to early clinical ~2024-2026" | CONFIRMED (conservative) | by the cutoff there is published first-in-human in vivo CAR-T data (Capstan CPTX2309 Ph1 dosed Jun 2025; Kelonia KLN-1010 at ASH 2025; MagicRNA HN2301 in *NEJM*) | https://www.businesswire.com/news/home/20250611668181/en/ ; https://keloniatx.com/kelonia-therapeutics-presents-first-in-human-data-from-phase-1-inmmycar-study-of-kln-1010-in-vivo-bcma-car-t-therapy-at-the-american-society-of-hematology-ash-2025-annual-meeting/ |
| `[14]` degrader zoo (PROTAC/LYTAC/AbTAC/MoDE/AUTAC/ATTEC) | CONFIRMED | no dates asserted, all six named classes are real and correctly grouped | — |
| `[25]` de novo binders "RFdiffusion/AlphaFold-era" | CONFIRMED | Watson et al., *Nature* 620:1089 (2023) | https://www.nature.com/articles/s41586-023-06415-8 |

### 1.3 The `expert_baseline`'s designated white space is ALREADY OCCUPIED — **critical**

`expert_baseline` closes by telling the grader what a genuinely rule-clearing answer looks
like: *"a modality acting through a physical state variable of tissue (phase behavior/
condensate control, mechanical/rheological state, or spatial organization) rather than
through molecular occupancy or genetic sequence."*

All three of those are occupied, two of them by **regulator-authorised** products:

| Suggested white space | Occupying prior art | Status | Source |
|---|---|---|---|
| phase behaviour / condensate control | **Condensate-modulating drugs (c-mods)**. Mechanistic foundation: Klein et al., "Partitioning of cancer therapeutics in nuclear condensates," *Science* 368:1386 (2020). Dewpoint Therapeutics' DPTX3186 (β-catenin c-mod) works by *forcing β-catenin into an inactive condensate* — i.e. the therapeutic act is a phase-behaviour change, not occupancy | clinical-stage by end-2025 | https://www.science.org/doi/10.1126/science.aaz4427 ; https://dewpointx.com/dewpoint-therapeutics-closes-series-d-financing-to-advance-first-in-class-condensate-modulator-c-mod-into-clinical-development-for-gastric-cancer/ |
| mechanical / rheological state | **Histotripsy** — focused-ultrasound acoustic cavitation that *mechanically liquefies* tissue with no heating and no molecular target | **FDA De Novo marketing authorisation, 9 Oct 2023** (HistoSonics Edison) | https://histosonics.com/fda-awards-histosonics-clearance-of-its-first-of-a-kind-edison-histotripsy-system-2/ ; https://ascopost.com/news/october-2023/fda-grants-marketing-authorization-to-edison-histotripsy-system-for-treatment-of-liver-tumors/ |
| spatial organisation / physical state variable | **Tumor Treating Fields (Optune)** — alternating electric fields that act on mitotic-spindle physics, not on a receptor | **FDA approved 2011** (recurrent GBM), 2015 (newly diagnosed GBM) | https://www.accessdata.fda.gov/cdrh_docs/pdf10/p100034s013b.pdf ; https://www.healio.com/news/hematology-oncology/20151006/fda-approves-optune-for-newly-diagnosed-glioblastoma-multiforme |

**Consequence:** the `expert_baseline` is not merely a "reference floor" here — it actively
points the grader at territory that R5 (genuine prior-art check) should void. An agent that
follows the baseline's own hint and proposes a condensate-phase or tissue-mechanics modality
would be scored *Surprising and New* by a grader reading only this item, while in fact
reproducing an FDA-authorised device class and a clinical-stage small-molecule class.

### 1.4 MISSING prior art — C5_biology_medicine_24

The catalogue is strong on molecular/genetic modalities and structurally blind to
**physically-mediated** ones, which is precisely where the item invites answers. Absent
classes, each with a distinct mechanism of action and each already authorised or in humans:

1. **Histotripsy / non-thermal mechanical ablation** — FDA De Novo Oct 2023 (see above).
2. **Tumor Treating Fields** — FDA 2011; also approved for pleural mesothelioma (2019) and locally advanced pancreatic cancer. https://www.targetedonc.com/view/tumor-treating-fields-therapy-garners-fda-approval-in-locally-advanced-pancreatic-cancer
3. **Condensate modulators (c-mods)** — clinical stage 2025. Mechanistically orthogonal to entry `[0]` small molecules (they act on the *phase state* of the target, not its active site).
4. **Boron neutron capture therapy** — a *binary nuclear* mechanism (¹⁰B + thermal neutron → α + ⁷Li in-cell). Steboronine (borofalan-¹⁰B) + NeuCure approved by Japan's MHLW **25 March 2020**; national insurance coverage June 2020. Not reducible to entry `[21]` radioligand therapy, which relies on the radionuclide's own decay. https://academic.oup.com/oncolo/article/26/7/e1250/6510477
5. **Magnetic hyperthermia / alternating-field nanoparticle thermoablation** — NanoTherm + NanoActivator, **CE mark 2010** for recurrent GBM. Entry `[24]` covers only *light*-activated agents. https://pmc.ncbi.nlm.nih.gov/articles/PMC6078833/
6. **Irreversible electroporation / electrochemotherapy** — non-thermal cell death by high-voltage-pulse membrane permeabilisation. NanoKnife received FDA 510(k) clearance **K102329, 24 Oct 2011**, for surgical ablation of soft tissue (prostate-specific clearance later). Not covered by `[23]`, which is specifically about neuromodulation interfaces. https://www.aetna.com/cpb/medical/data/800_899/0828.html ; https://investors.angiodynamics.com/news-releases/news-release-details/angiodynamics-receives-fda-clearance-nanoknifer-system-prostate
7. **Mitochondrial replacement / donation** — organelle substitution as therapy. UK regulations 2015; Newcastle licensed 2017; **eight live births reported July 2025**. Neither gene addition `[11]` nor editing `[12]` nor cell therapy `[15]`. https://www.ncl.ac.uk/press/articles/archive/2025/07/mitochondrialdonationtreatment/
8. **Prescription digital therapeutics** — mechanism is a targeted sensory/behavioural stimulus, no molecule and no device-tissue interface. EndeavorRx FDA-authorised **15 June 2020**. https://www.akiliinteractive.com/news-collection/akili-announces-endeavortm-attention-treatment-is-now-available-for-children-with-attention-deficit-hyperactivity-disorder-adhd-al3pw
9. **Gene-edited xenotransplantation** — whole-organ replacement from a multi-edited donor species (United Therapeutics UKidney, 10 edits; eGenesis, 69 edits). FDA cleared the **first human trials in 2025** after a 3-patient study approved Dec 2024. Distinct from `[17]` (stem-cell/tissue-engineered) and from `[11]`/`[12]` (the editing is in the *donor animal*, not the patient). https://www.statnews.com/2025/09/08/pig-organ-transplant-egenesis-revivicor-human-trials-fda/ ; https://nyulangone.org/news/first-gene-edited-pig-kidney-transplant-clinical-trial-begins-nyu-langone-health
10. **External-beam / particle radiotherapy (proton, carbon-ion, FLASH)** — the single largest physical modality in oncology, entirely absent; only *targeted radioligand* `[21]` appears. (Uncontroversial enough not to need a citation; flagged because an agent proposing a spatially- or temporally-structured energy-deposition modality has no listed class to collide with.)
11. **Focused-ultrasound blood-brain-barrier opening** as a therapeutic act in its own right — microbubble oscillation transiently opens a physiological barrier; the mechanism *is* mechanical modulation of tissue state, not molecular occupancy. Exablate Neuro holds **FDA Breakthrough Device designation** for BBB disruption, with trials in glioblastoma, Alzheimer's and Parkinson's. https://insightec.com/global/news-global/fda-approves-1st-study-of-exablate-neuro-to-open-the-bbb-in-glioblastoma-patients/ ; https://www.neurotherapeuticsjournal.org/article/S1878-7479(24)00038-2/fulltext
12. **Allergen immunotherapy / antigen-specific tolerance induction** — the mechanism is *deletion* of an existing immune response (Treg induction, IgE→IgG4/IgA isotype switch via tolerogenic mucosal dendritic cells), the mechanistic inverse of the prophylactic immunisation in `[5]`. FDA-approved sublingual tablets: Oralair, Grastek, Ragwitek (all **2014**), Odactra (**2017**). https://academic.oup.com/cei/article/209/3/262/6670504 ; https://www.westernhealth.com/provider/prior-authorization-archive/allergen-immunotherapy-agents-grastek-odactra-oralair-ragwitek/

---

## 2. C5_arts_humanities_29 — poetic forms (33 entries → 31 distinct forms)

### 2.1 Dated/attributed claims

| # | Claim | Verdict | Correct value | Source |
|---|---|---|---|---|
| `[31]` | Bop — "Afaa Michael Weaver, Cave Canem, **early 2000s**" | **WRONG** | **spring 1997**, at a Cave Canem summer retreat, as a workshop exercise (students included Terrance Hayes, Honorée Fanonne Jeffers, Vincent Woodard). Weaver in his own words: *"In inventing the bop that spring in 1997 while teaching at Cave Canem..."*. Inspired by Hughes's blues poems + the triadic Pindaric ode. Cave Canem itself was founded 1996, so "early 2000s" cannot be right. | https://www.theartsection.com/afaa-weaver (inventor, first person) ; structure: https://poets.org/glossary/bop ; https://cavecanempoets.org/about/ |
| `[29]` | Duplex — "Jericho Brown, **~2018**, in *The Tradition*" | **IMPRECISE** | *The Tradition* is **2019** (Copper Canyon Press; Pulitzer 2020). Individual duplexes circulated in journals from 2018, so "~2018" is defensible for first appearance but is attached to the wrong book year. Precise rule: 14 lines / 7 couplets, 9–11 syllables per line, the second line of each couplet returning (mutated) as the first line of the next, final line echoing the first. | https://poets.org/glossary/duplex ; https://www.poetrynw.org/radical-stasis-jericho-browns-duplex-form/ |
| `[23]` | Concrete/visual/pattern poetry — "**from George Herbert's 'Easter Wings'** to 20th c. concretism" | **WRONG (concept-date)** | Shaped/pattern poetry begins ~1,900 years earlier: Greek *technopaegnia* of **Simias of Rhodes, c. 300 BCE** ("Wings", "Axe", "Egg"); Latin *carmina figurata* of **Optatianus Porfyrius, 317–326 CE**; Sanskrit *citrakāvya/bandha* shape-verse in **Bhāravi and Māgha, 6th–7th c. CE**. Herbert (1633) is a late instance, not an origin. | https://www.loebclassics.com/view/simias-pattern_poems/2015/pb_LCL028.561.xml ; https://www.classicalstudies.org/text-and-image-time-and-space-reading-simias%E2%80%99-wings-and-axe ; https://www.brepolsonline.net/doi/10.1484/J.GIF.5.101962 ; https://journals.uc.edu/index.php/vl/article/view/5431 |
| `[26]` | Erasure — "20th–21st c. (Ronald Johnson's *Radi os*, Mary Ruefle, Austin Kleon)" | **IMPRECISE** | The foundational work is **Tom Phillips, *A Humument*, begun 1966** (source: W. H. Mallock, *A Human Document*), first published in book form 1980 — it predates Johnson's *Radi os* (1977) and is described in the literature as the founding text of literary erasurism, which Johnson drew on. | https://archipelagobooks.org/2013/08/celebrating-erasure-ii-tom-phillips/ ; https://www.thehistoryofblackoutpoetry.org/tom-phillips |
| `[26]` | "Austin Kleon" | CONFIRMED | spelling and attribution correct — *Newspaper Blackout*, HarperCollins, 2010 | https://austinkleon.com/newspaperblackout/ |
| `[0]` | reference works named as the novelty authority: "Princeton Encyclopedia of Poetry and Poetics; Poetry Foundation and Academy of American Poets glossaries; Lewis Turco's 'The Book of Forms'" | CONFIRMED — **nothing fabricated** | All real and correctly titled: *The Princeton Encyclopedia of Poetry and Poetics*, 4th ed. 2012, ed. Roland Greene with Cushman, Cavanagh, Ramazani, Rouzer, Princeton UP; Lewis Turco, *The Book of Forms: A Handbook of Poetics, Including Odd and Invented Forms*, rev. & expanded 4th ed. 2012, University Press of New England | https://www.jstor.org/stable/j.ctt2tt8jz ; https://english.stanford.edu/publications/princeton-encyclopedia-poetry-and-poetics-fourth-edition ; https://www.pw.org/content/the_book_of_forms |
| `[15]` | Ghazal — "and the looser 'American ghazal' (**Adrienne Rich, Agha Shahid Ali**, 20th c.)" | **WRONG** — this is the "right movement, wrong famous name" failure mode | **Agha Shahid Ali was the loose American ghazal's leading opponent, not a practitioner of it.** He attacked it in "The Ghazal in America: May I?" and edited *Ravishing DisUnities: **Real** Ghazals in English* (Wesleyan UP, 2000) precisely to insist that without strict *radif* + *qafia* the poem "is not a ghazal." The loose line is Rich's *Homage to Ghalib* (1968) / *The Blue Ghazals* and the Aijaz Ahmad *Ghazals of Ghalib* circle (1971: Rich, Merwin, Stafford). Ali belongs in the **strict** clause of the same entry. | https://archive.org/details/ravishingdisunit0000unse ; https://poetryschool.com/theblog/unreal-ghazals-in-english/ ; https://dialog.puchd.ac.in/wp-content/uploads/2022/01/8.-WritingAdapting-Ghazal-in-English-A-Select-Study-of-Agha-Shahid-Alis-Call-Me-Ishmael-Tonight.pdf |
| `[9]` | Cinquain — "Adelaide Crapsey, **~1911**" | **IMPRECISE** | composed in her final years, **c. 1911–1913**; 28 cinquains published posthumously in *Verse* (1915); Crapsey died Oct 1914. Standard references date the form's development to ~1913 rather than 1911. | https://www.britannica.com/biography/Adelaide-Crapsey ; https://cinquain.org/theory.html |
| `[27]` | Fib — "Gregory K. Pincus, 2006... 1/1/2/3/5/8" | CONFIRMED (but see 2.3) | posted on gottabook.blogspot.com **1 April 2006**; *NYT* coverage 14 April 2006 | https://www.poetryfoundation.org/articles/68971/1-1-2-3-5-8-fun |
| `[5]` | Villanelle — "19 lines... **codified 19th c. France/England**" | **CONFIRMED** (notably better than the popular account) | This matches current scholarship (Amanda French; Julie Kane): Passerat's *"J'ay perdu ma tourterelle"* (written 1574, published 1606) is the **only** Renaissance example of the 19-line form; the fixed form was constructed by Wilhelm Ténint (*Prosodie de l'école moderne*, 1844), Banville (1845) and Gosse (1877). The dataset avoided the widespread "Renaissance fixed form" error here. | https://amandafrench.net/files/Dissertation.pdf ; https://amandafrench.net/files/FirstVillanelle.pdf |
| `[28]` | Golden shovel — "Terrance Hayes, 2010, honoring Gwendolyn Brooks" | CONFIRMED | "The Golden Shovel," in *Lighthead* (2010, National Book Award); source poem Brooks's "We Real Cool" (1959) | https://www.britannica.com/art/golden-shovel-poetry ; https://poets.org/glossary/goldenshovel |
| `[10]` | Nonet 9→1; etheree 1→10, "20th c. American" | CONFIRMED | etheree named for **Etheree Taylor Armstrong (1918–1994)**, Arkansas; 10 lines 1→10 syllables | https://www.poetrysoup.com/dictionary/etheree |
| `[10]` + `[32]` | nonet listed twice | **defect (duplication)** | inflates the catalogue count; see §0d | — |
| `[14]` | lüshi/jueju tonal patterning + "ci (lyrics to fixed tune-patterns). **Tang dynasty.**" | **IMPRECISE** | regulated verse (*jintishi*) was codified in the **early Tang (7th c.)**; *ci* emerged in the **late Tang**, took shape in the Five Dynasties, and is the characteristic form of the **Song**. One date cannot cover both, and the *cipai* template (stanza/line/character counts + level-oblique tonal pattern + rhyme) is what the entry is actually describing. | https://www.britannica.com/art/ci ; https://www.berkshirepublishing.com/ecph-china/2017/12/27/ci-poetry/ |
| `[4]` | Sestina — Arnaut Daniel, 12th c., six sestets + tercet, *retrogradatio cruciata* | CONFIRMED | late 12th c. Provençal troubadour; six six-line stanzas + three-line envoi; end-words rotated, unrhymed | https://poets.org/glossary/sestina ; https://poets.org/poet/arnaut-daniel |
| `[24]` | Queneau, *Cent mille milliards de poèmes*, 1961, 10 sonnets → 10^14 | CONFIRMED (arithmetically self-verifying: 10 interchangeable alternatives × 14 line positions = 10^14) | — | claim not separately fetched; no discrepancy found in any source consulted |
| `[1]`–`[3]`, `[6]`–`[8]`, `[11]`–`[13]`, `[15]`–`[22]`, `[25]`, `[30]`, `[32]` | sonnet/da Lentini, terza rima/Dante, ottava rima–rhyme royal–Spenserian, French refrain forms + Swinburne's *A Century of Roundels* (1883), ballade/chant royal, Romance minor forms, limerick + clerihew (Bentley 1905), Japanese syllabic set, sijo, ghazal (radif/qafia/maqta; Rich 1968, Ali), rubaʿi/qasida, pantoum ← Malay *pantun berkait*, landay (9+13), Welsh cynghanedd metres, dróttkvætt, Sapphic/Alcaic quantitative stanzas, acrostic/abecedarian/mesostic (Cage), cento (Ausonius), contrapuntal, Turco's minor forms | CONFIRMED | no date or attribution errors found. Two specific date claims verified individually: **sijo** — emerged 14th c. at the end of Goryeo, 3 lines averaging 14–16 syllables (42–48 total), countertheme/twist in L3 ✓; **dróttkvætt** — 9th–13th c., syllable/position count + alliteration + internal rhyme (*hending*) ✓ | https://pressto.amu.edu.pl/index.php/kr/article/download/6506/6523 ; https://skaldic.org/m.php?p=doc&i=730 ; https://www.britannica.com/art/skaldic-poetry ; remainder spot-checked against poets.org / Poetry Foundation glossaries |

### 2.2 The `hard_rules` and `expert_baseline` designate white space that is ALREADY OCCUPIED — **critical**

`hard_rule[4]` ("NEW CONSTRAINT-TYPE REQUIRED") names four constraint types as
*not central to any documented form*: **semantic/relational**, **inter-line logical
dependency**, **reader-path/topological**, **cross-modal or generative**. The
`expert_baseline` then gives two worked examples of a winning answer: *"a rule where each
line must be a valid answer to the question posed by the previous line"* and *"a 'branching'
form with two legal reading-paths whose fork is fixed by a stated rule."*

Every one of these is the defining principle of a documented form — and the occupying prior
art is overwhelmingly **non-Western**, which is exactly the blind spot the catalogue has.

| Designated "new type" | Occupying documented form | Source |
|---|---|---|
| semantic / double-meaning constraint | **Amharic/Geʿez *qene* — *sem-enna-werq* ("wax and gold")**: the form's *defining* requirement is that the verse carry a surface meaning and a concealed second meaning simultaneously. Tradition traced to the 14th c., taught formally in the Ethiopian Orthodox church schools. | https://journal.themissingslate.com/2016/03/28/the-secret-world-of-ethiopian-poetry/ ; https://dictionary.abyssinica.com/qnies.aspx |
| semantic constraint, epic scale | **Sanskrit *śleṣa* / *dvisandhāna kāvya***: Kavirāja's *Rāghavapāṇḍavīya* (12th c.) narrates the *Rāmāyaṇa* and the *Mahābhārata* **at the same time**, every verse legible as both. A ~1,000-year South Asian movement, monographed by Yigal Bronner, *Extreme Poetry: The South Asian Movement of Simultaneous Narration* (Columbia UP, 2010). *Trisandhāna* works carry three narratives. | https://cup.columbia.edu/book/extreme-poetry/9780231151603/ ; https://ebooks.inflibnet.ac.in/icp04/chapter/types-of-literature-kavyas-poetry-2/ |
| **"two legal reading-paths whose fork is fixed by a stated rule"** (the baseline's own example of a winning answer) | **Chinese *huiwen* reversible poetry — Su Hui's *Xuanji tu* ("Star Gauge"), 4th c. CE**: an 841-character 29×29 woven grid with rule-governed reading paths yielding ~3,000 (by some counts up to 12,000) distinct poems. Definitive study: Michèle Métail, *Wild Geese Returning: Chinese Reversible Poems* (NYRB/Calligrams, 2017). | https://www.nyrb.com/products/wild-geese-returning ; https://marianchristiepoetry.net/routes-through-a-poem/ |
| **"each line must be a valid answer to the question posed by the previous line"** (the baseline's other example) | **Occitan *tenso* / *partimen* and Old French *jeu-parti***: the *partimen*'s defining rule is that one poet poses a dilemma and the reply must take the opposing horn, in alternating stanzas. ~120 partimens + ~75 tensos in Occitan and ~200 *jeux-partis* in Old French survive. | https://scholarworks.iu.edu/journals/index.php/tmr/article/view/17102/23220 ; https://www.academia.edu/66394443/Thats_debatable_Genre_issues_in_troubadour_tensos_and_partimens |
| same, and **already inside the catalogue's own text** | **Japanese *mondōka* 問答歌 ("dialogue song") / *sedōka* 旋頭歌 / *sōmonka* 相聞歌** — *mondōka* are traced to the *Kojiki* (**712 CE**); *sedōka* is classified in Man'yōshū scholarship precisely as the "question and answer poem," built as a pair of *katauta* (5-7-7) where the first poses and the second answers, typically by a second author; *sōmonka* (corresponsive exchange poems) is one of the *Man'yōshū*'s three top-level categories. The catalogue's entry `[12]` **names *katauta* but omits that its defining paired use is question-and-answer** — so the `expert_baseline`'s headline example of a "new constraint type" is the documented function of a form the item already lists. | https://www.enotes.com/topics/manyoshu/criticism/criticism-1/edward-putzar-essay-date-1973 ; http://www.wakapoetry.net/poems/anthologies/manyoshu-%E4%B8%87%E8%91%89%E9%9B%86/ ; https://www.britannica.com/topic/Manyo-shu |
| reader-path / topological (again) | already partly self-refuted: the catalogue's own `[30]` contrapuntal/two-column entry is a reader-path rule | — |
| cross-modal | already self-refuted: the catalogue's own `[14]` *ci* (lyrics composed to fixed pre-existing tune-patterns, *cipai*) is a cross-modal constraint | — |
| generative / algorithmic | **Jackson Mac Low's *diastic* text-selection method (1963)** — a deterministic algorithm that reads words out of a source text by rule-driven correspondence with a seed text. Also Oulipo (`[24]`) and Cage's chance operations. | https://direct.mit.edu/books/oa-monograph/6011/The-Complete-Stein-Poems-1998-2003 ; https://jacket2.org/commentary/mac-low-writing-through-stein |

So `hard_rule[4]` and the `expert_baseline` jointly instruct the grader to reward answers
that `hard_rule[5]` ("if the grader locates the proposed principle as the defining principle
of any existing named form **in any language/tradition**, New = 1") would set to New = 1.
The item is internally contradictory, and the contradiction resolves against the agent only
if the grader happens to know the non-Western canon.

### 2.3 MISSING prior art — C5_arts_humanities_29

The catalogue is genuinely cross-lingual (better than `_49`) but its non-Western coverage is
thin and, where present, mis-dated. Absent occupied principles, ordered by likelihood that
an inventing agent rediscovers them:

1. **Sanskrit *śleṣa* / *dvisandhāna* bitextual verse** — simultaneous narration, 12th c. and a millennium-long movement. (Occupies the "semantic constraint" and "two readings" space.) Bronner, Columbia UP 2010.
2. **Chinese *huiwen* / Su Hui's *Xuanji tu*, 4th c.** — grid with rule-governed multiple reading paths. (Occupies both "reader-path/topological" and the Queneau-style combinatorial space, 1,600 years before Queneau.)
3. **Amharic *qene* / *sem-enna-werq*** — obligatory concealed second meaning. (Occupies "semantic/relational".)
4. **Occitan *tenso*/*partimen*, Old French *jeu-parti*** — obligatory dialogic dilemma-and-answer. (Occupies "inter-line logical dependency".)
5. **Sanskrit *citrakāvya* / *bandha*** — shape-verse (lotus, wheel, sword, plough patterns), palindromic and magic-square verse; Bhāravi, Māgha (6th–7th c.). Predates `[23]`'s Herbert by ~1,000 years, and Greek technopaegnia predate it by ~900 more.
6. **Tamil *antādi*** (≈6th c. CE, Kāraikkāl Ammaiyār; then the Āḻvār *prabandham*s) — the last word or syllable of each verse must open the next, and in the 100-verse "garland" variant the final verse loops back to the opening word, closing the chain. Distinct from pantoum-style whole-line reuse (word/syllable-level, plus circular closure). https://www.uveda.org/dictionary/antadi ; https://cswr.hds.harvard.edu/news/2025/08/04/until-one-immersed-journey-through-early-tamil-devotional-poetry
7. **Somali *gabay*** — poem-wide obligatory monoalliteration: a single chosen consonant must alliterate in **every line** of a poem that may exceed 100 lines. A lipogram-family constraint applied at whole-poem scale; not the same as intra-line cynghanedd or Norse alliteration. https://wardheernews.com/paramountcy-of-alliteration-in-somali-literature/
8. **Sanskrit *yamaka*** — a *śabdālaṅkāra* requiring sequential repetition of whole syllable-strings at fixed positions (line-initial, medial or final) where each recurrence must carry a *different* meaning; theorised by Bhāmaha and Vāmana. A distinct phonological-plus-semantic constraint type, not the intra-line consonant braiding of cynghanedd. https://www.wisdomlib.org/hinduism/essay/alamkaras-mentioned-by-vamana/d/doc1143409.html
9. **Vietnamese *lục bát*** — alternating 6/8 lines with a *chaining internal rhyme* (syllable 6 of the 8-line rhymes back to syllable 6 of the previous line, whose syllable 8 seeds the next). https://www.languageisavirus.com/poetry-guide/luc-bat.php
10. **Jackson Mac Low's diastic method (1963)** — algorithmic generation from a seed text; the closest ancestor of any "generative rule" proposal.
11. **Tom Phillips, *A Humument* (1966)** — erasure's founding work (see `[26]`).
12. **Irish *dán díreach*** (12th-17th c.) — a *second*, independent strict-metre system alongside the Welsh one the catalogue does list at `[19]`. Its species (*deibhidhe*, *séadna*, *rannaigheacht mhór/bheag*, *casbhairn*) impose syllable count plus *comhardadh* rhyme requiring vowel identity **and** agreement of consonant class and quality (hard/soft/light/rough/strong), with alliteration in every line often linking one line's final word to the next line's first stressed word. The consonant-*class* equivalence rule has no counterpart in cynghanedd. https://people.stfx.ca/mlinklet/CELT341BardicMetres.htm ; https://www.scoilgaeilge.org/academics/mairead/EarlyIrishLiterature/TheLanguageofPoetry.htm
13. Also absent: Hebrew *piyyut* alphabetic/name acrostics (Yannai, 6th c.); Kalevala metre (trochaic tetrameter + obligatory parallelism); Filipino *tanaga*; Swahili *utenzi*; Tamil *veṇpā* and *Kuṟaḷ*; Nahuatl *difrasismo*.

---

### 2.4 Proposed replacement strings — C5_biology_medicine_24 and C5_arts_humanities_29

Every `old` string below was checked with `python3` against the raw file text and occurs
**exactly once**. Nothing has been applied.

**C5_biology_medicine_24**

```
old: Oncolytic viruses (established niche; approvals since 2015)
new: Oncolytic viruses (established niche; first national approvals 2004 — Rigvir/ECHO-7,
     Latvia, marketing authorisation suspended 2019 — and 2005 — Oncorine/H101, China;
     first FDA approval T-VEC/Imlygic 2015; Delytact/teserpaturev conditionally approved
     in Japan 2021)
```

```
old: Bacteriophage therapy (compassionate-use/clinical-trial stage in 2026)
new: Bacteriophage therapy (registered pharmacy medicines in Russia — NPO Microgen — and
     Georgia — Eliava PYO/Intesti — for decades; compassionate-use and clinical-trial stage
     in the US/EU in 2026)
```

**C5_arts_humanities_29**

```
old: Bop (Afaa Michael Weaver, Cave Canem, early 2000s)
new: Bop (Afaa Michael Weaver, invented spring 1997 at the Cave Canem summer retreat)
```

```
old: Duplex (Jericho Brown, ~2018, in 'The Tradition')
new: Duplex (Jericho Brown; individual duplexes in journals from 2018, collected in 'The
     Tradition', 2019)
```

```
old: from George Herbert's 'Easter Wings' to 20th c. concretism
new: from Greek technopaegnia (Simias of Rhodes, c. 300 BCE) and Latin carmina figurata
     (Optatian, 317-326 CE) through Sanskrit citrakavya/bandha shape-verse (Bharavi, Magha,
     6th-7th c. CE) and George Herbert's 'Easter Wings' (1633) to 20th c. concretism
```

```
old: (Ronald Johnson's 'Radi os', Mary Ruefle, Austin Kleon)
new: (Tom Phillips's 'A Humument', begun 1966; Ronald Johnson's 'Radi os', 1977;
     Mary Ruefle; Austin Kleon)
```

```
old: Cinquain (Adelaide Crapsey, ~1911; syllabic 2-4-6-8-2)
new: Cinquain (Adelaide Crapsey, composed c. 1911-1913, published posthumously in 'Verse',
     1915; syllabic 2-4-6-8-2)
```

```
old: and the looser 'American ghazal' (Adrienne Rich, Agha Shahid Ali, 20th c.)
new: and the looser 'American ghazal' (Adrienne Rich's 'Homage to Ghalib', 1968; the Aijaz
     Ahmad 'Ghazals of Ghalib' circle, 1971), which Agha Shahid Ali repudiated in favour of
     strict radif+qafia ('Ravishing DisUnities: Real Ghazals in English', 2000)
```

```
old: NOTE: mathematical-sequence syllable counting is an occupied principle.
new: NOTE: mathematical-sequence syllable counting is an occupied principle, and far older
     than the Fib — the Fibonacci series itself was derived by Sanskrit prosodists (Virahanka
     c. 600-800 CE, Gopala, Hemachandra c. 1150) from enumerating matra-vrtta metres.
```

```
old: ci (lyrics to fixed tune-patterns). Tang dynasty.
new: ci (lyrics composed to fixed tune-patterns, cipai). Regulated verse codified in the
     early Tang; ci emerged in the late Tang and flourished in the Song.
```

Also recommended (no single-substring fix; requires editing two entries): remove the
duplicate **nonet** from entry `[32]`, since it is already a named form in `[10]`.

---

## 3. C5_materials_chemistry_25 — solid-state material classes (33 entries → 32 families)

### 3.1 Structural observations (by inspection, independent of the citation verdicts)

- Entry `[32]` is a dating/instruction note, not a family, so the real count is **32**.
- **Five entries bundle two or three distinct dated discoveries each**, which matters because the
  judge is told to match a submission against list *entries*:

  | entry | bundled dated discoveries |
  |---|---|
  | `[4]` | fullerenes (1985), carbon nanotubes (1991), graphene (2004) |
  | `[6]` | COFs (2005) + woven/interlocked COFs (2016) |
  | `[12]` | high-entropy alloys (2004) + high-entropy oxides/ceramics/carbides (2015) |
  | `[17]` | biphenylene network (2021), monolayer C60 polymer/graphullerene (2022), monolayer amorphous carbon (undated) |
  | `[19]` | organic electrides (1980s), C12A7:e⁻ (2003), 2D Ca₂N/Y₂C (2013) |

  A judge scanning for a collision will match on the headline family and can easily miss a buried
  one — "monolayer amorphous carbon" and "woven COFs" are the two most exposed, since both are
  plausible targets for an "interwoven/aperiodic covalent network" proposal, which is precisely
  the direction the `expert_baseline` points agents in.
- **16 of the 32 families carry no date at all** (HOFs/halogen-bonded frameworks, CTFs/CMPs,
  Ruddlesden-Popper/Aurivillius, MAX/MAB/MBenes, vdW 2D crystals, LDHs, Prussian blue analogues,
  superionic electrolytes, clathrates, Heusler/caloric alloys, plastic/barocaloric crystals,
  single-atom catalysts, metal-organic chalcogenolates, DNA/colloidal superlattices, hyperuniform
  disordered solids, supramolecular/vitrimer networks). For those, there is no prior-art boundary
  a judge could apply even in principle.

### 3.2 The single worst finding: the MOF entry omits a 2025 Nobel laureate

Entry `[5]` reads *"Metal-organic frameworks (MOFs) — metal-node + organic-linker porous crystals
(**Yaghi/Kitagawa, late 1990s**)"*. Both the attribution and the date are **WRONG**.

- **Richard Robson is omitted.** Designed metal-organic/coordination frameworks originate with
  **Hoskins & Robson, *JACS* 1989, 111, 5962** and ***JACS* 1990, 112, 1546** — the latter titled
  "Design and construction of a **new class** of scaffolding-like materials."
- The **2025 Nobel Prize in Chemistry** went to **Susumu Kitagawa, Richard Robson and Omar M.
  Yaghi** *"for the development of metal-organic frameworks"* — and the Nobel committee's own
  account states: *"It was **Robson** who first reasoned it would be possible to make these
  frameworks in the **1980s**."*
- The date is ~10 years young. Timeline: Robson 1989/1990 → term "metal-organic framework" coined
  by **Yaghi & Li, *JACS* 1995**, 117, 10401 → **Kitagawa** (Kondo et al., *Angew. Chem.* 1997, 36,
  1725) → **MOF-5** (Li, Eddaoudi, O'Keeffe, Yaghi, *Nature* 1999, 402, 276). Earlier still:
  Kinoshita et al., *BCSJ* 1959, 32, 1221 (Cu(I)-adiponitrile 3D net).

I verified the Nobel citation and the Robson attribution independently.
https://www.kva.se/en/news/the-nobel-prize-in-chemistry-2025/ ;
https://www.chemistryworld.com/news/2025-chemistry-nobel-prize-goes-to-the-scientists-behind-metal-organic-frameworks/4022287.article ;
https://api.crossref.org/works/10.1021/ja00160a038 ; https://api.crossref.org/works/10.1021/ja00146a033

**This is the one defect in the whole audit with reputational as well as scoring consequences.**
A benchmark released publicly in 2026 that credits MOFs to "Yaghi/Kitagawa, late 1990s" — omitting
the laureate the committee names as the originator — will be noticed immediately by any materials
reviewer.

### 3.3 Other verdicts

| # | Claim | Verdict | Correct value | Source |
|---|---|---|---|---|
| `[5]` | MOFs "Yaghi/Kitagawa, late 1990s" | **WRONG** | see §3.2 | as above |
| `[17]` | "graphullerene (qHP-/qTP-C60, **2022**)" | **WRONG — two materials fused into one date** | qHP-/qTP-C60 = Hou et al., *Nature* 2022, 606, 507 (15 Jun 2022). **Graphullerene is a different material from a different lab in a different year**: Meirzadeh et al., *Nature* **2023**, 613, 71 (4 Jan 2023, Columbia) | https://api.crossref.org/works/10.1038/s41586-022-04771-5 ; https://api.crossref.org/works/10.1038/s41586-022-05401-w |
| `[19]` | "2D Ca2N/**Y2C** (2013)" | **WRONG** | Ca₂N is 2013 (Lee et al., *Nature* 494, 336) but **Y₂C is 2014**: Zhang, Xiao, Lei, Toda, Matsuishi, Kamiya, Ueda, Hosono, *Chem. Mater.* 2014, **26**(22), 6638-6643, online 10 Nov 2014. I fetched the Crossref record to confirm. A date-filtered Crossref sweep to 2014-06 returns no Y₂C electride paper. | https://api.crossref.org/works/10.1021/cm503512h |
| `[10]` | halide perovskites "photovoltaic boom post-2009" | **IMPRECISE — 31 to 116 yr young; the worst gate risk in the item** | Kojima 2009 is right for the PV boom, but the *class* is far older: **Wells, *Z. Anorg. Chem.* 1893, 3, 195** (CsPbX₃); **Møller, *Nature* 1958, 182, 1436** (perovskite structure **plus photoconductivity**); **Weber 1978** (CH₃NH₃PbX₃ *and* CH₃NH₃SnBrₓI₃₋ₓ); Mitzi 1994/1995 (layered hybrids) | https://api.crossref.org/works/10.1002/zaac.18930030124 ; https://api.crossref.org/works/10.1038/1821436a0 ; https://api.crossref.org/works/10.1515/znb-1978-1214 |
| `[4]` | carbon nanotubes "(1991)" | **IMPRECISE — 39 yr young** | Iijima 1991 confirmed but not first: **Radushkevich & Lukyanovich, *Zh. Fiz. Khim.* 1952, 26, 88** (clear TEM of ~50 nm carbon tubes); **Oberlin, Endo & Koyama, *J. Cryst. Growth* 1976, 32, 335**. Settled in the literature by Monthioux & Kuznetsov, *Carbon* 2006, 44, 1621, "Who should be given the credit for the discovery of carbon nanotubes?" | https://api.crossref.org/works/10.1016/0022-0248(76)90115-9 ; https://api.crossref.org/works/10.1016/j.carbon.2006.03.019 |
| `[1]` | "Au-Si, **Duwez** 1960" | **IMPRECISE — first author displaced by the famous PI** | **Klement W. Jr., Willens R. H., Duwez Pol**, *Nature* 1960, 187, 869. Duwez is *third* author (the Caltech PI). This is the closest thing in the item to the "wrong famous name" mode — a real paper with the prominent name standing in for the actual first author. | https://api.crossref.org/works/10.1038/187869b0 |
| `[1]` | 1960 as the amorphous-alloy class date | **IMPRECISE — 26 yr young** | Kramer, *Ann. Phys.* 1934, 411, 37; **Brenner, Couch & Williams, *J. Res. NBS* 1950, 44, 109** (electrodeposited amorphous Ni-P — **1950**, not 1947); Buckel & Hilsch, *Z. Phys.* 1954, 138, 109 | https://api.crossref.org/works/10.6028/jres.044.009 |
| `[1]` | "bulk metallic glasses 1990s" | **IMPRECISE — 6 to 21 yr young** | cm-scale BMG: **Kui, Greer & Turnbull, *APL* 1984, 45, 615**; mm-scale Chen 1974. The 1990s anchors are right only for *processable multicomponent* BMGs (Inoue 1989-90; Peker & Johnson, *APL* 1993, 63, 2342) | https://api.crossref.org/works/10.1063/1.95330 ; https://api.crossref.org/works/10.1063/1.110520 |
| `[9]` | "MOPs and porous organic cages (Cooper, **~2009**)" | **IMPRECISE — MOPs are 14 yr older** | Porous organic cages confirmed (Tozawa … Cooper, *Nat. Mater.* 2009, 8, 973), but **MOPs/coordination cages = Fujita et al., *Nature* 1995, 378, 469** and Moulton … Zaworotko, *Chem. Commun.* 2001, 863 ("nanoballs"). One date misdates half the entry. | https://api.crossref.org/works/10.1038/378469a0 ; https://api.crossref.org/works/10.1039/b102714j |
| `[12]` | "high-entropy oxides/**ceramics/carbides** (2015)" | **IMPRECISE** | Entropy-stabilized *oxides* 2015 is correct (Rost et al., *Nat. Commun.* 6, 8485). But high-entropy **nitride films are 2004** (Chen, Shun, Yeh, Wong, *Surf. Coat. Technol.* 188-189, 193); borides 2016; carbides 2018. | https://api.crossref.org/works/10.1016/j.surfcoat.2004.08.023 ; https://api.crossref.org/works/10.1038/ncomms9485 |
| `[26]` | MOF glasses "~2015+" | **IMPRECISE** | melt-quenched ZIF glass 2015 correct (Bennett et al., *Nat. Commun.* 6, 8079), but **amorphous MOFs are 2010** (Bennett, Goodwin, Dove, Keen et al., *PRL* 104, 115503); MOF liquids 2017 | https://api.crossref.org/works/10.1103/physrevlett.104.115503 |
| `[18]` | goldene "(2024)" | **CONFIRMED for the material; IMPRECISE for the name** | Kashiwaya et al., *Nature Synthesis* 2024, 3, 744 confirmed for free-standing goldene. But the **name was published in 2022** (Sharma et al., *ACS AMI* 14, 54992) and there is a **live priority dispute**: Matters Arising, *Nat. Synth.* 2026, 5, 330, plus an Author Correction 2024, 3, 1577 | https://api.crossref.org/works/10.1021/acsami.2c19743 ; https://api.crossref.org/works/10.1038/s44160-025-00959-5 |
| `[0]` | zeolites "synthetic since the 1940s-50s" | **CONFIRMED for zeolites; IMPRECISE for zeotypes** | Barrer 1948; Milton/Union Carbide US2882243A + US2882244A both filed 24 Dec 1953. But **AlPO₄ zeotypes are 1982** (Wilson, Lok, Messina, Cannan, Flanigen, *JACS* 104, 1146) — the entry's own second noun is 30 years later than its date | https://patents.google.com/patent/US2882243A/en ; https://api.crossref.org/works/10.1021/ja00368a062 |
| `[13]` | MXenes "(Gogotsi/Barsoum, 2011)" | **CONFIRMED (acceptable shorthand)** | Naguib et al., *Adv. Mater.* 2011, 23, 4248. Gogotsi and Barsoum are the two corresponding PIs, so unlike the Duwez case this is legitimate shorthand; name "MXene" coined 2011-12 | https://api.crossref.org/works/10.1002/adma.201102306 |
| `[2]` | quasicrystals "(Shechtman, 1982/84)" | **CONFIRMED — the split is correct** | Discovery **8 April 1982** at NBS Gaithersburg (melt-spun Al-14 at.% Mn, sample 1725, notebook entry "(10 fold ???)"); paper Shechtman, Blech, Gratias, Cahn, *PRL* 53, 1951, **12 Nov 1984**. The *term* "quasicrystal" is later still (Levine & Steinhardt, *PRL* 53, 2477, 24 Dec 1984). | https://www.nist.gov/nist-and-nobel/dan-shechtman/nobel-moment-dan-shechtman |
| `[3]`,`[6]`,`[12]` Yeh/Cantor, `[16]`,`[17]` biphenylene + MAC, `[19]` Dye 1983/C12A7 2003/Ca₂N 2013, `[4]` fullerenes + graphene, and the anchor citations behind `[22]`-`[31]` | | **CONFIRMED** | Kistler *Nature* 1931, 127, 741; COF 2005 + COF-505 2016; Yeh and Cantor genuinely independent 2004 papers (Cantor's is the Aug 2002 RQ11 proceedings); borophene Mannix *Science* 2015, 350, 1513; biphenylene Fan *Science* 2021, 372, 852; monolayer amorphous carbon Toh *Nature* 2020, 577, 199; Ellaboudy/Dye/Smith *JACS* 1983, 105, 6490; fullerenes *Nature* 1985, 318, 162; graphene *Science* 2004, 306, 666 | Crossref records for each, verified by the parallel audit |

**Counts:** CONFIRMED 26 · **WRONG 3** · **IMPRECISE 10** · UNVERIFIABLE 0 · **FABRICATED 0**.
14 further entries are undated; that is judged *acceptable* here, because each names an unambiguous
family an expert can gate on ("NASICON", "LDHs", "Prussian blue analogues") — an agent cannot
plausibly "invent" NASICON and pass. Missing dates cost recall; **wrong** dates cost correctness.

**Direction of the bias: all 13 defective claims date prior art YOUNGER than reality.** Carbon
nanotubes −39 yr · halide perovskites −31 to −116 · amorphous metals −26 · MOPs −14 · high-entropy
ceramics −11 · MOFs −10 · BMGs −6 · amorphous MOFs −5 · zeotypes −30 · Y₂C and graphullerene −1
each. Zero counter-examples, matching every prior pass.

### 3.4 The `expert_baseline`'s white space is OCCUPIED — both targets

The `expert_baseline` tells the grader that a New-axis-winning answer would need either (i) "long-range
order defined by a conserved topological/knot invariant of interwoven covalent strands" or (ii) "a
material whose 'lattice sites' are an ordered, kinetically trapped array of non-atomic entities."
Neither is white space.

**(i) Topological/knot order in extended solids — occupied, and it is a named sub-discipline.**

| Prior art | Citation |
|---|---|
| **"Interpenetrating Nets: Ordered, Periodic *Entanglement*"** — the title is almost the baseline's own phrasing, and the author is **Robson** | Batten & Robson, *Angew. Chem. Int. Ed.* 1998, 37, 1460 |
| Formal **topological invariants** (Hopf ring net, isotopy classes) used to *classify* crystal entanglements | Alexandrov, Blatov & Proserpio, *Acta Cryst. A* 2012, 68, 484; Power, Baburin & Proserpio, *Acta Cryst. A* 2020, 76, 275 |
| **"The geometry of periodic knots, polycatenanes and weaving from a chemical perspective"** — by Yaghi's own group | Liu, O'Keeffe, Treacy & Yaghi, *Chem. Soc. Rev.* 2018, 47, 4642 |
| Woven covalent crystal | COF-505, *Science* 2016, 351, 365 — **already listed in this item's own entry `[6]`** |
| Molecular knots and Borromean links | Dietrich-Buchecker & Sauvage 1989; Chichak … Stoddart, *Science* 2004, 304, 1308 |
| Catenated extended solids | poly[n]catenanes *Science* 2017, 358, 1434; densely catenated MOF *Nature* 2021, 598, 298; **mechanically interlocked 2D polymers *Science* 2025, 387, 264**; **3D polycatenated architected materials *Science* 2025, 387, 269** |

**(ii) Non-atomic lattice sites — occupied for 69 years, including the "kinetically trapped" qualifier.**
Abrikosov vortex lattice (1957; imaged Essmann & Träuble 1967) · **skyrmion lattice** (Mühlbauer et al.,
*Science* 2009, 323, 915; real-space Yu et al., *Nature* 2010, 465, 901; metastable/quenched skyrmion
lattices are an established sub-topic) · polar skyrmions (*Nature* 2019, 568, 368) · **Wigner electron
crystal — literally a crystal whose lattice sites are electrons** (Smoleński et al., *Nature* 2021, 595,
53; moiré generalized Wigner crystals *Nature* 2020, 579, 359) · **artificial spin ice — a
lithographically *engineered*, frustrated, kinetically trapped array** (Wang et al., *Nature* 2006, 439,
303) · charge-density waves (Wilson, Di Salvo & Mahajan 1975) · time crystals (2017).

**And the baseline's own fallback answer is already published.** The "porous ordered electride
framework" it offers as the merely-competent answer is not just a two-family superposition — C12A7:e⁻
*is* a nanoporous cage-framework electride, and framework-electride design by anion-site removal has
been published for sodalites (Kang, Parrish & Zhu, *J. Phys. Chem. C* 2023, 127, 18745; Liu, Mukta,
Kang & Zhu, *ACS Omega* 2025, 10, 1635, "Semiconducting Electrides Derived from Sodalite"). So the
baseline should score low on **New** as well as on Surprising — it understates its own problem.

**Net effect:** this item's `expert_baseline` directs agents toward two territories that are decades
occupied, one of which (woven COFs) the item *itself* lists as prior art in entry `[6]`. That is a
self-contradiction inside a single item, and per §0a the judge cannot correct it.

### 3.5 MISSING families — 21 verified gaps

Ranked by how likely an agent is to land there. **The first four sit exactly where the
`expert_baseline` points**, which is the compounding risk.

1. **Chalcogenide phase-change / ovonic amorphous semiconductors** — reversible field-driven amorphous↔crystalline switching as the functional state. Ovshinsky, *PRL* 1968, 21, 1450.
2. **Superatomic / cluster-assembled crystals** — lattice sites are molecular clusters acting as pseudo-atoms with tunable superatomic valence. Roy … Nuckolls, *Science* 2013, 341, 157, "Nanoscale Atoms in Solid-State Chemistry"; theory Khanna & Jena, *PRL* 1992, 69, 1664.
3. **Incommensurately modulated and composite (host-guest) crystals** — aperiodic long-range order needing (3+d)-dimensional superspace, **distinct from quasicrystals**, which is the item's only aperiodic family. de Wolff, *Acta Cryst. A* 1974, 30, 777; misfit layer compounds Wiegers 1996.
4. **Topological insulators / Weyl semimetals** — the order parameter is *bulk band topology*, i.e. exactly the kind of non-structural organizing principle the baseline asks for. Bernevig, Hughes & Zhang, *Science* 2006, 314, 1757; Hsieh et al., *Nature* 2008, 452, 970.
5. **Oxide / network glasses (continuous random network)** — the item has *metallic* glasses and *MOF* glasses but not the parent class. Zachariasen, *JACS* 1932, 54, 3841.
6. **Glass-ceramics** — controlled internal nucleation of a glass to crystal-in-glass. Stookey, US2920971A, filed 1956.
7. **Intercalation / staging hosts** — reversible guest insertion with discrete staging order. Whittingham, *Science* 1976, 192, 1126; Mizushima/Goodenough 1980.
8. **Ordered mesoporous solids** — periodicity in the *pore* lattice with amorphous walls; orthogonal to zeolites. Kresge, Leonowicz, Roth, Vartuli, Beck, *Nature* 1992, 359, 710.
9. **Mechanically interlocked polymers / polycatenanes / polyrotaxanes** — topological rather than covalent bonds as the network connector. *Science* 2017, 358, 1434; *Science* 2025, 387, 264 and 269.
10. **Charge-density-wave materials** — self-generated electronic superlattice. Wilson, Di Salvo & Mahajan, *Adv. Phys.* 1975, 24, 117.
11. **Multiferroics / magnetoelectrics** — coexisting coupled ferroic order parameters. Schmid 1994; Kimura *Nature* 2003, 426, 55.
12. **Zintl phases** — polyanionic covalent clusters charge-balanced by electropositive cations. Schäfer, Eisenmann & Müller, *Angew. Chem. IE* 1973, 12, 694.
13. **Chevrel phases** — condensed Mo₆X₈ metal-cluster units. Chevrel, Sergent & Prigent, *JSSC* 1971, 3, 515.
14. **Kagome / geometrically frustrated metals** — lattice topology as the organizing principle. Ortiz et al., *PRM* 2019, 3, 094407.
15. **Single-molecule magnets** — magnetic bistability on an isolated molecule. Sessoli, Gatteschi, Caneschi & Novak, *Nature* 1993, 365, 141.
16. **Conducting polymers / organic charge-transfer superconductors.** Shirakawa … Heeger, *JCS Chem. Commun.* 1977, 578.
17. **Spin-crossover frameworks** — bistable local spin state as a switchable order parameter. Cambi & Szegö 1931; Real et al., *Science* 1995, 268, 265.
18. **Nanoporous dealloyed metals** — bicontinuous porosity by spinodal dealloying, not templating. Erlebacher et al., *Nature* 2001, 410, 450; Raney US1563587A (1924/1925).
19. **Metal hydrides / interstitial alloys and superhydrides** — H on interstitial sites as a stoichiometric sublattice; H-clathrate cages at pressure. Drozdov et al., *Nature* 2019, 569, 528.
20. **Polymer-derived ceramics** — preceramic polymer pyrolysed to an amorphous covalent network. Yajima, Hayashi & Omori, *Chem. Lett.* 1975, 4, 931.
21. **Relaxor/MPB ferroelectrics and "phonon-glass electron-crystal" rattler cages.** Sales, Mandrus & Williams, *Science* 1996, 272, 1325.

Also worth adding: **graphdiyne/graphyne** (Li et al., *Chem. Commun.* 2010, 46, 3256) — a conspicuous
omission from `[17]`'s carbon-allotrope list — and **porphene/porphite** (*Nat. Commun.* 2023, 14).
⚠️ **Do not add "holey graphyne" (*Matter* 2022, 5, 2306): it is RETRACTED** (Crossref `update-to:
retraction`).

**2025-H1 2026 recency scan** (required by entry `[32]`): no single dominant newly named class, but
three 2025 items bear directly on this item — 3D polycatenated architected materials (*Science* 387,
269), mechanically interlocked 2D polymers (*Science* 387, 264), and sodalite-derived electrides
(*ACS Omega* 10, 1635). The first two occupy white space (i); the third occupies the baseline's own
fallback answer.

### 3.6 Proposed replacement strings — all 13 verified by me to occur exactly once

The file stores **literal UTF-8 em-dashes** (573 present, zero `—` escapes), so replacements must
use `—`.

```
[5]  old: Metal-organic frameworks (MOFs) — metal-node + organic-linker porous crystals (Yaghi/Kitagawa, late 1990s)
     new: Metal-organic frameworks (MOFs) / designed coordination polymers — metal-node + organic-
          linker porous crystals (originating "node-and-spacer" design: Hoskins & Robson, JACS
          1989/1990; term "metal-organic framework" coined by Yaghi 1995; Kitagawa 1997; MOF-5,
          Yaghi 1999; 2025 Nobel Prize in Chemistry: Kitagawa, Robson, Yaghi)
[17] old: long-range-ordered monolayer C60 polymer / graphullerene (qHP-/qTP-C60, 2022)
     new: long-range-ordered monolayer C60 polymer (qHP-/qTP-C60, Hou et al. 2022) and graphullerene,
          a distinct few-layer covalent fullerene network (Meirzadeh et al. 2023)
[19] old: organic electrides (Dye, 1980s), inorganic C12A7:e- (2003), 2D Ca2N/Y2C (2013)
     new: organic electrides (Ellaboudy, Dye & Smith 1983), inorganic C12A7:e- (Matsuishi et al.
          2003), 2D Ca2N (Lee et al. 2013) and 2D Y2C (Zhang et al. 2014)
[1]  old: Metallic glasses / bulk amorphous alloys — quenched atomic disorder (Au-Si, Duwez 1960; bulk metallic glasses 1990s)
     new: Metallic glasses / bulk amorphous alloys — quenched atomic disorder (amorphous metal films,
          Kramer 1934 and Buckel & Hilsch 1954; electrodeposited amorphous Ni-P, Brenner et al. 1950;
          melt-quenched Au-Si, Klement, Willens & Duwez 1960; centimetre-scale bulk metallic glass,
          Kui, Greer & Turnbull 1984; processable multicomponent BMGs, Inoue 1989-90 and Peker &
          Johnson 1993)
[4]  old: Carbon nanomaterials — fullerenes (1985), carbon nanotubes (1991), graphene (2004)
     new: Carbon nanomaterials — fullerenes (1985), carbon nanotubes (first TEM observation
          Radushkevich & Lukyanovich 1952; Oberlin, Endo & Koyama 1976; Iijima 1991), graphene (2004)
[10] old: Halide perovskites — ABX3 hybrid organic-inorganic semiconductors (photovoltaic boom post-2009), plus double perovskites and antiperovskites
     new: Halide perovskites — ABX3 inorganic and hybrid organic-inorganic semiconductors (CsPbX3
          since Wells 1893; perovskite structure plus photoconductivity, Moller 1958; CH3NH3PbX3 and
          CH3NH3SnX3, Weber 1978; layered hybrids, Mitzi 1994-95; photovoltaic boom post-2009,
          Kojima et al. 2009), plus double perovskites (Cs2AgBiBr6, 2016) and antiperovskites
          (Li3OCl, 2012)
[12] old: High-entropy alloys (Yeh/Cantor, 2004) and high-entropy oxides/ceramics/carbides (2015)
     new: High-entropy alloys (Yeh 2004; Cantor, Chang, Knight & Vincent 2004; earlier equiatomic
          multicomponent work, Vincent/Cantor 1981) and high-entropy ceramics (nitride films 2004;
          entropy-stabilized oxides, Rost et al. 2015; borides 2016; carbides 2018)
[9]  old: Porous molecular crystals — metal-organic polyhedra (MOPs) and porous organic cages (Cooper, ~2009)
     new: Porous molecular crystals — metal-organic polyhedra/coordination cages (Fujita 1995;
          Zaworotko "nanoballs" 2001) and porous organic cages (Tozawa/Cooper 2009)
[26] old: MOF glasses / amorphous melt-quenched MOFs (ZIF glasses, ~2015+)
     new: MOF glasses / amorphous MOFs (ball-milled amorphous ZIFs, Bennett et al. 2010; MOF liquids
          2017; melt-quenched ZIF glasses, Bennett et al. 2015+)
[18] old: Goldene — free-standing 2D monolayer gold (2024)
     new: Goldene — free-standing 2D monolayer gold (name first published for self-assembled single-
          atomic-layer Au crystals, Sharma et al. 2022; free-standing goldene by Ti3C2 etching,
          Kashiwaya et al. 2024; priority contested in Nature Synthesis 2026)
[0]  old: Zeolites and zeotypes — crystalline microporous aluminosilicate/phosphate frameworks (synthetic since the 1940s-50s)
     new: Zeolites and zeotypes — crystalline microporous aluminosilicate/phosphate frameworks
          (synthetic zeolites: Barrer 1948, Milton/Union Carbide zeolites A and X filed 1953;
          AlPO4 zeotypes: Wilson, Lok & Flanigen 1982)
[22] old: Superionic solid electrolytes — garnets (LLZO), argyrodites, NASICON, Li-thiophosphates
     new: Superionic solid electrolytes — AgI (1914), Na beta-alumina (1967), NASICON (Hong;
          Goodenough, Hong & Kafalas 1976), garnets (LLZO, Murugan/Weppner 2007), argyrodites
          (Deiseroth 2008), Li-thiophosphates (LGPS, Kamaya 2011)      [optional]
[13] old: MXenes — 2D transition-metal carbides/nitrides from MAX-phase etching (Gogotsi/Barsoum, 2011)
     new: MXenes — 2D transition-metal carbides/nitrides from MAX-phase etching (Naguib et al.,
          Gogotsi/Barsoum groups, 2011; name "MXene" coined 2011-12)                   [optional]
```

## 4. C5_engineering_28 — engineering mechanisms (22 entries + expert_baseline = 23 claim units)

**Nothing fabricated — every cited work exists.** But the list is systematically mis-dated in
a single direction. I independently re-verified the four most consequential findings against
primary documents and all four hold:

- **US 3,089,064** (Cotton de Bennetot, filed 3 Feb 1959, granted 7 May 1963), "Combined permanent magnet and electromagnet" — is a genuine electropermanent magnet: *"substantially no power supply for its operation except during the short intervals of time when it is energized or de-energized."* So `[2]`'s 2010 date is ~51 years late.
- **US 3,456,134** (Wen H. Ko, filed 5 Oct 1967, granted 15 Jul 1969), "Piezoelectric Energy Converter for Electronic Implants" — claims *"a piezoelectric crystal in the form of a cantilevered beam … a weight mounted on said free end,"* operating *"in its resonant mode."* That is exactly `[15]`'s device, ~35 years early.
- **US 2,575,360** (Jacob Rabinow, filed 31 Oct 1947, granted 20 Nov 1951), "Magnetic fluid torque and force transmitting device" — carbonyl-iron-in-oil MR fluid. `[16]`'s "Lord Corp, 1990s-2000s" is ~50 years late and credits the wrong originator.
- **SUPERball authorship** — Bruce, Caluwaerts, Iscen, Sabelhaus, SunSpiral (NASA Ames), 2014. **Skelton is not an author.** `[12]` is wrong on both name and year.

### 4.1 Verdicts

| # | Claim | Verdict | Correct value | Source |
|---|---|---|---|---|
| `[0]` | radiative cooling "Raman, Zhu, Rephaeli, Fan — Nature 2014" | **WRONG** (author dropped) | **Raman, Abou Anoma, Zhu, Rephaeli, Fan**, *Nature* 515:540 (2014). Second author Marc Abou Anoma omitted. Venue/year correct. | https://api.crossref.org/works/10.1038/nature13883 |
| `[1]` | jamming gripper author list | IMPRECISE | 8 authors: Brown, Rodenberg, Amend, **Mozeika, Steltz, Zakin**, Lipson, Jaeger; *PNAS* 107:18809 | https://api.crossref.org/works/10.1073/pnas.1003250107 |
| `[2]` | EPM "(Knaian, MIT, 2010)" | **WRONG — concept ~51 yr too young** | Thesis is real, but the electropermanent magnet is **Cotton de Bennetot, US 3,089,064, filed 3 Feb 1959, granted 7 May 1963** — I fetched the patent: it explicitly claims pulse-switched operation with "substantially no power supply … except during the short intervals when it is energized or de-energized." Term "electropermanent magnet" in Braillon, US 4,075,589 (1976/1978). | https://patents.google.com/patent/US3089064A/en ; https://patents.google.com/patent/US4075589A/en ; https://cba.mit.edu/docs/theses/10.06.knaian.pdf |
| `[3]` | vitrimers Science 2011 | IMPRECISE | citation correct; **"vitrimer" coined 2012** (Capelot, Unterlass, Tournilhac, Leibler, *ACS Macro Lett.* 1:789); "covalent adaptable networks" = Kloxin, Scott, Adzima, Bowman, *Macromolecules* 43:2643 (2010) | https://pubs.acs.org/doi/10.1021/mz300239f ; https://api.crossref.org/works/10.1021/ma902596s |
| `[4]` | TENG Fan/Tian/Z.L. Wang, *Nano Energy* 2012 | **CONFIRMED** | complete 3-author list, correct | https://doi.org/10.1016/j.nanoen.2012.01.004 |
| `[5]` | auxetics Lakes 1987 | IMPRECISE | Lakes correct, but earlier NPR: Gibson, Ashby, Schajer, Robertson, *Proc. R. Soc. A* 382:25 (**1982**); Almgren (1985). "Auxetic" coined Evans et al., *Nature* 353:124 (1991) | https://doi.org/10.1098/rspa.1982.0087 ; https://doi.org/10.1038/353124a0 |
| `[6]` | 4D printing Tibbits 2013 | IMPRECISE | 2013 = a **TED talk**, not a publication. First peer-reviewed: Ge, Qi, Dunn, *APL* 103:131901 (2013) — **no Boyce**. Self-folding sheets already Hawkes et al., *PNAS* 107:12441 (2010) | https://doi.org/10.1063/1.4819837 ; https://doi.org/10.1073/pnas.0914069107 |
| `[7]` | kirigami "Blees et al., 2014-2017" | **WRONG (year)** | Blees … McEuen, "Graphene kirigami," *Nature* 524:204, **2015**. Engineering kirigami prior art: Nojima & Saito (2006); Saito, Agnese, Scarpa (2011) | https://api.crossref.org/works/10.1038/nature14588 |
| `[8]` | TPMS/gyroid AM heat exchangers "2018-2022" | IMPRECISE (3-48 yr) | first AM-TPMS transfer study Femmer, Kuehne, Wessling, *Chem. Eng. J.* 273:438 (**2015**); patent US 9,440,216 priority **2012**; gyroid itself Schoen, NASA TN D-5541 (**1970**) | https://api.crossref.org/works/10.1016/j.cej.2015.03.029 ; https://patents.google.com/patent/US9440216B2/en ; https://ntrs.nasa.gov/api/citations/19700020472 |
| `[9]` | fog harvesting "Park, **Aizenberg** et al., 2013-2016" | **WRONG — conflation + 12-22 yr too young** | Two different papers bundled under one attribution. 2013 = K.-C. Park, Chhatre, Srinivasan, **Cohen, McKinley**, *Langmuir* 29:13269 — **Aizenberg is not an author**. 2016 = Park, Kim, Grinthal, … **Aizenberg**, *Nature* 531:78. Namib-beetle origin = **Parker & Lawrence, *Nature* 414:33 (2001)**; wettability-patterned mimic = Zhai … Rubner, Cohen, *Nano Lett.* 6:1213 (2006). (Same Kyoo-Chul Park moved MIT→Harvard, so this is an attribution error rather than a name substitution.) | https://www.nature.com/articles/35102108 ; https://pubs.acs.org/doi/10.1021/nl060644q ; https://www.nature.com/articles/nature16956 |
| `[10]` | electroadhesion "SRI ~2008; Grabit ~2015" | **WRONG (Grabit yr) + concept 85 yr too young** | SRI 2008 correct (Prahlad, Pelrine, Stanford, Marlow, Kornbluh, ICRA 2008; patent priority 2006). **Grabit Inc. founded 2013.** Concept = **Johnsen & Rahbek, *J. IEE* 61:713 (1923)**; electrostatic wall-climbing pre-SRI: Yamamoto, Nakashima, Higuchi, IEEE MHS 2007 | https://doi.org/10.1109/ROBOT.2008.4543670 ; https://patents.google.com/patent/US7872850B2/en |
| `[11]` | compliant bistables "Howell, BYU, 2000s" | IMPRECISE (6-10 yr) | Howell & Midha, *ASME JMD* 116:280 (**1994**); bistable specifically Jensen, Howell, Salmon, *JMD* 121:416 (1999); independent MEMS bistable Vangbo (1998); book *Compliant Mechanisms* 2001 | https://doi.org/10.1115/1.2919359 ; https://doi.org/10.1016/S0924-4247(98)00097-1 |
| `[12]` | tensegrity "**Skelton**; NASA SUPERball lander, 2015" | **WRONG — misattribution + year + 53-67 yr** | **Skelton is not an author on any SUPERball paper.** I verified the author list: Bruce, Caluwaerts, Iscen, Sabelhaus, SunSpiral (NASA Ames), ICRA/WCSCM **2014**. Skelton & de Oliveira, *Tensegrity Systems*, Springer **2009** is the control text. Concept: Snelson 1948; Fuller US 3,063,521 (1959/1962); Snelson US 3,169,611 (1960/1965) | https://ntrs.nasa.gov/api/citations/20140011157/downloads/20140011157.pdf ; https://patents.google.com/patent/US3063521A/en |
| `[13]` | metalens Khorasaninejad/Capasso Science 2016 | IMPRECISE (5-18 yr) | citation correct; the *method* is Yu … Capasso, *Science* 334:333 (**2011**); flat lens Aieta (2012); dielectric metasurface Lin, Fan, Hasman, Brongersma, *Science* 345:298 (2014); subwavelength phase Lalanne (1998) | https://doi.org/10.1126/science.1210713 ; https://doi.org/10.1021/nl302516v |
| `[14]` | PCM packs "commercialized through the 2010s" | **WRONG — 44-53 yr too young** | Bentilla, Sterrett, Karre, NASA-CR-75041 (**1966**); Hale, Hoover, O'Neill, *PCM Handbook*, NASA-CR-61363 (1971); electronics-specific Pal & Joshi (1995/96); Alawadhi & Amon (2003) | https://ntrs.nasa.gov/api/citations/19660017401 ; https://ntrs.nasa.gov/api/citations/19720012306 |
| `[15]` | piezo harvesters "established 2000s-2010s" | **WRONG — ~35 yr too young** | **Ko, US 3,456,134, filed 5 Oct 1967** — an end-mass piezo cantilever resonant harvester. First peer-reviewed analysis Umeda, Nakamura, Ueha, *JJAP* 35:3267 (1996) | https://patents.google.com/patent/US3456134A/en ; https://api.crossref.org/works/10.1143/JJAP.35.3267 |
| `[16]` | MR dampers "Lord Corp, 1990s-2000s" | **WRONG — 42-52 yr too young + wrong company** | MR fluid invented by **Jacob Rabinow, National Bureau of Standards**, *AIEE Trans.* 67:1308 (**1948**), US 2,575,360 filed 1947. Lord's first commercial MR product = Motion Master seat damper, 1998. **MagneRide was Delphi/GM** (2002.5 Cadillac Seville STS); Lord only supplied the fluid | https://patents.google.com/patent/US2575360A/en |
| `[17]` | PneuNets Ilievski/Whitesides 2011 | IMPRECISE (brand vs method) | citation correct; "PneuNet" is a 2011 *name* for a 1955-1991 method: Gaylord, US 2,844,126 (filed 1955); Suzumori, Iikura, Tanaka, IEEE MEMS **1991** multi-chamber pneumatic-network elastomer actuator | https://doi.org/10.1002/anie.201006464 ; https://patents.google.com/patent/US2844126A/en |
| `[18]` | regen shocks Levant 2009 / Audi eROT 2016 | IMPRECISE | both product dates hold, but no prior art given: Karnopp, *Veh. Syst. Dyn.* 18:187 (**1989**); Goldner & Zerigian, US 6,952,060 (2005) | https://news.mit.edu/2009/shock-absorbers-0209 ; https://www.tandfonline.com/doi/abs/10.1080/00423118908968918 |
| `[19]` | coiled polymer muscles Haines/Baughman Science 2014 | **CONFIRMED** | correct; same-group precursor Lima et al., *Science* 338:928 (2012) | https://doi.org/10.1126/science.1246906 |
| `[20]` | acoustic/elastic metamaterials "(2010s)" | **WRONG — 10-15 yr too young** | **Liu, Zhang, Mao, Zhu, Yang, Chan, Sheng, *Science* 289:1734 (2000)** locally resonant sonic materials; double-negative Li & Chan (2004); acoustic cloak theory Cummer & Schurig (2007); elastic-plate cloak Farhat (2009); pentamodes Milton & Cherkaev (1995). Only the first *experimental* broadband cloak is 2010s (Zhang, Xia, Fang, 2011) | https://www.science.org/doi/abs/10.1126/science.289.5485.1734 ; https://iopscience.iop.org/article/10.1088/1367-2630/9/3/045 |
| `[21]` | toroidal CVT "established automotive prior art" | IMPRECISE (undated, unfalsifiable) | Hunt, **US** 197,472 (1877); Hayes, US 1,698,229 (1925/1929), Austin production 1933; Perbury/Torotrak Fellows, US 4,756,211 (GB priority 1985); first volume-production half-toroidal = Nissan EXTROID, 1999 | https://patents.google.com/patent/US197472A/en ; https://patents.google.com/patent/US4756211A/en |
| `expert_baseline` | EPM + bistable-flexure tool-changer, "~50-200 N from a few-mm^3 stack" | **WRONG (3 defects)** | (a) inherits `[2]`'s EPM mis-dating; (b) **physics off by 1-2 orders of magnitude** — magnetic pressure ceiling B²/2μ₀ ≈ 0.4 MPa at 1 T, so 50-200 N needs ~125-500 mm² of pole face; a few-mm³ stack yields single-digit N (Knaian's own 12 mm Robot Pebbles latch at ~80× module weight). This matters because `hard_rule[5]` asks the judge to grade whether the submission's feasibility estimate is "order-of-magnitude correct" — the calibration reference itself is not; (c) the baseline device is **already granted art absent from the list**: switchable-magnet robot tool-changers US 10,335,958 / US 10,414,055 (2019) | https://patents.google.com/patent/US10335958B2/en ; http://cba.mit.edu/docs/papers/10.05.knaian.ICRA.pdf |

### 4.2 Counts

| Verdict | Count | Entries |
|---|---|---|
| CONFIRMED | **2** | `[4]`, `[19]` |
| WRONG | **11** | `[0]`, `[2]`, `[7]`, `[9]`, `[10]`, `[12]`, `[14]`, `[15]`, `[16]`, `[20]`, `expert_baseline` |
| IMPRECISE | **10** | `[1]`, `[3]`, `[5]`, `[6]`, `[8]`, `[11]`, `[13]`, `[17]`, `[18]`, `[21]` |
| UNVERIFIABLE | 0 | — |
| FABRICATED | **0** | — |

**Directional bias: 13 of 23 claim units date prior art to a product launch, brand name, or
research boom rather than to first publication — and in every single case the true date is
EARLIER than listed.** Gaps: `[10]` ≈ −85 yr · `[12]` ≈ −53 to −67 · `[2]` ≈ −51 · `[14]` ≈
−44 to −53 · `[16]` ≈ −42 to −52 · `[15]` ≈ −35 · `[17]` ≈ −20 to −56 · `[9]` ≈ −12 to −22 ·
`[20]` ≈ −11 to −15 · `[13]` ≈ −5 to −18 · `[11]` ≈ −6 to −10 · `[8]` ≈ −3 to −48 · `[5]` ≈ −5.
Not one error runs the other way.

Author-list defects: 2, **both omission** (`[0]`, `[1]`). **No "right paper, wrong famous
name" instance was found in this item** — Lipson, Jaeger, Z. L. Wang, McEuen, Capasso,
Whitesides, Baughman and Leibler are all genuine and correctly positioned. The two
attribution errors are `[9]` (Aizenberg credited on a paper he is not on) and `[12]`
(Skelton read as SUPERball's author).

### 4.3 Proposed replacements — all 22 verified by me to occur exactly once

```
[0]  old: Raman, Zhu, Rephaeli, Fan — Nature, 2014
     new: Raman, Abou Anoma, Zhu, Rephaeli, Fan — Nature 515:540, 2014
[1]  old: Brown, Rodenberg, Amend, Lipson, Jaeger et al. — PNAS, 2010
     new: Brown, Rodenberg, Amend, Mozeika, Steltz, Zakin, Lipson, Jaeger — PNAS 107:18809, 2010
[2]  old: (Knaian, MIT, 2010)
     new: (Knaian, MIT PhD thesis, 2010 — millimetre-scale EPM for programmable matter; the
          electropermanent magnet itself is prior art: Cotton de Bennetot, US 3,089,064,
          filed 1959/granted 1963; term used in Braillon, US 4,075,589, 1976/1978)
[3]  old: Montarnal, Capelot, Tournilhac, Leibler — Science, 2011
     new: Montarnal, Capelot, Tournilhac, Leibler — Science 334:965, 2011; term "vitrimer"
          coined in Capelot, Unterlass, Tournilhac, Leibler, ACS Macro Lett. 1:789, 2012;
          "covalent adaptable networks" named in Kloxin, Scott, Adzima, Bowman,
          Macromolecules 43:2643, 2010
[5]  old: Lakes — Science, 1987; re-emergent as programmable lattices 2014-2020
     new: Lakes — Science 235:1038, 1987 (first isotropic NPR foam); earlier NPR prior art:
          Gibson, Ashby, Schajer & Robertson, Proc. R. Soc. A 382:25, 1982 and Almgren,
          J. Elasticity 15:427, 1985; "auxetic" coined by Evans et al., Nature 353:124, 1991;
          re-emergent as programmable lattices 2014-2020
[6]  old: (Tibbits, MIT, 2013)
     new: (term coined in Tibbits' TED2013 talk, Feb 2013 — not a peer-reviewed source; first
          peer-reviewed demonstration Ge, Qi & Dunn, Appl. Phys. Lett. 103:131901, 2013;
          self-folding programmable sheets already in Hawkes et al., PNAS 107:12441, 2010)
[7]  old: (Blees et al. and others, 2014-2017)
     new: (Blees et al. — Nature 524:204, 2015; engineering-kirigami prior art: Nojima & Saito,
          JSME Int. J. A 49:38, 2006 and Saito, Agnese & Scarpa, JIMSS, 2011)
[8]  old: lattice heat exchangers and heat sinks (2018-2022)
     new: lattice heat exchangers and heat sinks (gyroid geometry: Schoen, NASA TN D-5541,
          1970; first AM-TPMS transfer study: Femmer, Kuehne & Wessling, Chem. Eng. J.
          273:438, 2015; patent US 9,440,216, priority 2012; metal-AM product wave 2018-2022)
[9]  old: (Park, Aizenberg et al., 2013-2016)
     new: (Namib-beetle water capture: Parker & Lawrence, Nature 414:33, 2001; wettability-
          patterned synthetic mimic: Zhai, Berg, Cebeci, Kim, Milwid, Rubner & Cohen, Nano
          Lett. 6:1213, 2006; mesh optimisation: K.-C. Park, Chhatre, Srinivasan, Cohen &
          McKinley, Langmuir 29:13269, 2013; slippery asymmetric bumps: Park, Kim, Grinthal,
          He, Fox, Weaver & Aizenberg, Nature 531:78, 2016; field fog-collector engineering:
          Schemenauer & Cereceda, J. Appl. Meteorol. 33:1313, 1994)
[10] old: (SRI International, ~2008; Grabit Inc., ~2015)
     new: (Johnsen-Rahbek effect, J. IEE 61:713, 1923; electrostatic wall-climbing: Yamamoto,
          Nakashima & Higuchi, IEEE MHS 2007; SRI: Prahlad, Pelrine, Stanford, Marlow &
          Kornbluh, IEEE ICRA 2008:3028, patent priority 2006; Grabit Inc. founded 2013)
[11] old: (Howell, BYU, 2000s)
     new: (Howell & Midha, ASME J. Mech. Des. 116:280, 1994; bistable compliant mechanisms:
          Jensen, Howell & Salmon, JMD 121:416, 1999; independent MEMS bistable flexure:
          Vangbo, Sens. Act. A 69:212, 1998; Howell, Compliant Mechanisms, Wiley, 2001)
[12] old: (Skelton; NASA SUPERball lander, 2015)
     new: (tensegrity concept: Snelson 1948, Fuller US 3,063,521 filed 1959/granted 1962,
          Snelson US 3,169,611 filed 1960/granted 1965; dynamics and control: Skelton &
          de Oliveira, Tensegrity Systems, Springer, 2009; NASA Ames SUPERball robot: Bruce,
          Caluwaerts, Iscen, Sabelhaus & SunSpiral, ICRA/WCSCM 2014 — Skelton is not an author)
[13] old: Khorasaninejad, Capasso et al. — Science, 2016
     new: Khorasaninejad, Chen, Devlin, Oh, Zhu, Capasso — Science 352:1190, 2016; metasurface
          phase-discontinuity method: Yu, Genevet, Kats, Aieta, Tetienne, Capasso & Gaburro,
          Science 334:333, 2011; flat lens Aieta et al., Nano Lett. 12:4932, 2012; dielectric
          metasurface Lin, Fan, Hasman & Brongersma, Science 345:298, 2014
[14] old: transient electronics cooling (commercialized through the 2010s)
     new: transient electronics cooling (NASA fusible-material thermal control: Bentilla,
          Sterrett & Karre, NASA-CR-75041, 1966; Hale, Hoover & O'Neill, PCM Handbook,
          NASA-CR-61363, 1971; electronics-package specific: Pal & Joshi, SEMI-THERM 1995;
          Alawadhi & Amon, IEEE TCAPT 26:116, 2003; consumer/EV product wave through the 2010s)
[15] old: Piezoelectric cantilever vibration energy harvesters (established 2000s-2010s)
     new: Piezoelectric cantilever vibration energy harvesters (end-mass piezo cantilever
          harvester patented by Ko, US 3,456,134, filed 1967/granted 1969; PVDF implant
          harvester Hasler, Stein & Harbauer, Ferroelectrics 60:277, 1984; first peer-reviewed
          analysis Umeda, Nakamura & Ueha, Jpn. J. Appl. Phys. 35:3267, 1996; WSN research
          boom Roundy, Wright & Rabaey 2003-2004)
[16] old: (Lord Corp MR dampers, 1990s-2000s)
     new: (MR fluid invented by Jacob Rabinow, National Bureau of Standards — AIEE Trans.
          67:1308, 1948, US 2,575,360 filed 1947/granted 1951; Lord Motion Master seat damper,
          first commercial MR product, 1998; Delphi MagneRide on the 2002.5 Cadillac Seville
          STS, with Lord supplying the fluid)
[17] old: Ilievski, Whitesides et al. — Angew. Chem., 2011
     new: Ilievski, Mazzeo, Shepherd, Chen, Whitesides — Angew. Chem. Int. Ed. 50:1890, 2011;
          "PneuNet" names a much older method: Gaylord, US 2,844,126, filed 1955/granted 1958
          (McKibben-type) and Suzumori, Iikura & Tanaka, IEEE MEMS 1991 (multi-chamber
          pneumatic-network elastomer actuator)
[18] old: (Levant Power GenShock, 2009; Audi eROT, 2016)
     new: (electrodynamic variable/regenerative damper analysis: Karnopp, Vehicle System
          Dynamics 18:187, 1989; Goldner & Zerigian, US 6,952,060, 2005; Levant Power
          GenShock, 2009; Audi eROT, 2016)
[20] old: for cloaking and negative-index wave steering (2010s)
     new: for cloaking and negative-index wave steering (locally resonant sonic materials:
          Liu, Zhang, Mao, Zhu, Yang, Chan & Sheng, Science 289:1734, 2000; double-negative:
          Li & Chan, Phys. Rev. E 70:055602, 2004; pentamode realizability: Milton & Cherkaev,
          ASME JEMT 117:483, 1995; acoustic cloaking theory: Cummer & Schurig, New J. Phys.
          9:45, 2007; elastic-plate cloak: Farhat, Guenneau & Enoch, PRL 103:024301, 2009;
          first experimental broadband acoustic cloak: Zhang, Xia & Fang, PRL 106:024301, 2011)
[21] old: traction-drive transmissions (established automotive prior art)
     new: traction-drive transmissions (concept patented by C. W. Hunt, US 197,472, 1877;
          automotive variator F. A. Hayes, US 1,698,229, filed 1925/granted 1929, Austin
          production 1933; Perbury/Torotrak toroidal-race variator Fellows, US 4,756,211,
          GB priority 1985; first volume-production half-toroidal automotive CVT: Nissan
          EXTROID, Cedric/Gloria Y34, 1999, NSK variator)
[eb] old: Knaian-style electropermanent magnet
     new: electropermanent magnet (Cotton de Bennetot, US 3,089,064, 1959/1963; miniaturised
          by Knaian, MIT, 2010)
[eb] old: order-of-magnitude holding force ~50-200 N from a few-mm^3 Alnico/NdFeB stack
     new: order-of-magnitude holding force ~50-200 N requiring ~125-500 mm^2 of pole-face area
          at the B^2/2mu0 ~ 0.4 MPa magnetic-pressure ceiling (a few-mm^3 magnet stack yields
          only single-digit N, as in Knaian's 12 mm Robot Pebbles)
```

`[4]` and `[19]` need no change.

### 4.4 MISSING prior art — C5_engineering_28

Twenty established mechanism families absent from the list, each of which a submission could
"invent" and clear `hard_rule[2]` by construction:

1. **Gecko-inspired fibrillar dry adhesives** — Autumn et al., *Nature* 405:681 (2000); synthetic Geim et al., *Nat. Mater.* 2:461 (2003). Different physics from `[10]` (van der Waals, not electrostatic). https://doi.org/10.1038/35015073
2. **Dielectric elastomer actuators** — Pelrine, Kornbluh, Pei, Joseph, *Science* 287:836 (2000); priority *Sens. Act. A* 64:77 (1998). https://doi.org/10.1016/s0924-4247(97)01657-9
3. **HASEL / electrohydraulic actuators** — Acome et al. (Keplinger), *Science* 359:61 (2018). https://doi.org/10.1126/science.aao6139
4. **Shape-memory-alloy (Nitinol) actuators** — Buehler & Wiley, US 3,174,851, filed 1961. `[6]` covers shape-memory *polymer* only. https://patents.google.com/patent/US3174851A/en
5. **Origami / Miura-ori deployables** — Miura, ISAS Report 618 (1985); Zirbel … Magleby, Howell, *ASME JMD* 135:111005 (2013). Fold, not cut — distinct from `[7]`.
6. **Negative-stiffness damping composites** — Lakes, Lee, Bersie, Wang, *Nature* 410:565 (2001). https://doi.org/10.1038/35069035
7. **Thermoacoustic / Stirling engines** — Stirling, Br. Pat. 4081 (1816); Ceperley, *JASA* 66:1508 (1979); Backhaus & Swift, *Nature* 399:335 (1999). **No heat-engine entry exists at all.** https://doi.org/10.1121/1.383505
8. **Elastocaloric / magnetocaloric solid-state cooling** — Brown, *JAP* 47:3673 (1976); Cui et al., *APL* 101:073904 (2012). https://doi.org/10.1063/1.323176
9. **Variable-stiffness low-melting-point-alloy composites** — Shan, Lu, Majidi, *SMS* 22:085005 (2013). Different physics from `[1]`'s granular jamming. https://doi.org/10.1088/0964-1726/22/8/085005
10. **Soft fluidic logic / pneumatic valves and oscillators** — Unger … Quake, *Science* 288:113 (2000); Preston et al., *Sci. Robot.* 4:eaaw5496 (2019). `[17]` is actuation, not control. https://doi.org/10.1126/science.288.5463.113
11. **EHD / ion-drag pumps and ionic-wind thrusters** — Stuetzer, *JAP* 30:984 (1959); Xu et al. (Barrett), *Nature* 563:532 (2018). https://doi.org/10.1063/1.1777003
12. **Mechanical metamaterial digital logic** — Ion, Wall, Kovacs, Baudisch, CHI '17:977 (2017); Song et al., *Nat. Commun.* 10:882 (2019). https://doi.org/10.1145/3025453.3025624
13. **Ultrasonic / travelling-wave piezo motors** — Sashida, US 4,562,374, priority 1982. Opposite transduction direction from `[15]`. https://patents.google.com/patent/US4562374A/en
14. **Magnetically actuated soft continuum robots** — Hu, Lum, Mastrangeli, Sitti, *Nature* 554:81 (2018); Kim, Parada, Liu, Zhao, *Sci. Robot.* 4:eaax7329 (2019). https://doi.org/10.1038/nature25443
15. **Capillary-wick heat pipes / loop heat pipes** — Grover, Cotter, Erickson, *JAP* 35:1990 (1964); Grover, US 3,229,759, filed 1963. **The largest thermal gap in the list.** https://doi.org/10.1063/1.1713792
16. **Electrostatic MEMS comb-drive actuators** — Tang, Nguyen, Howe, *Sens. Actuators* 20:25 (1989). https://doi.org/10.1016/0250-6874(89)87098-2
17. **Halbach arrays / flux-modulated magnetic gears** — Halbach, *NIM* 169:1 (1980); Atallah & Howe, *IEEE Trans. Magn.* 37:2844 (2001). https://doi.org/10.1016/0029-554X(80)90094-4
18. **Thermoelectric Peltier heating/cooling** — Goldsmid & Douglas, *Br. J. Appl. Phys.* 5:386 (1954). **No thermoelectric entry at all.** https://doi.org/10.1088/0508-3443/5/11/303
19. **Cable-driven parallel robots** — Albus, Bostelman, Dagalakis, NIST RoboCrane, *J. Robotic Syst.* 10:709 (1993). https://doi.org/10.1002/rob.4620100509
20. **Switchable-magnet robot tool-changers** — US 10,335,958 / US 10,414,055 (2019). This is the `expert_baseline` device's own closest prior art, and it is not on the list. https://patents.google.com/patent/US10335958B2/en

Partially covered (lower risk): metamaterial mechanisms (Ion et al., **UIST** 2016 — not CHI);
flexure nanopositioners (Paros & Weisbord, *Machine Design*, 1965 priority absent);
multistable energy-trapping lattices (Shan/Bertoldi, 2015).

## 5. C5_arts_humanities_49 — musical forms (21 entries → 20 forms)

### 5.1 The prior reviewer's "entirely Western" finding — **CONFIRMED by direct inspection**

I enumerated all 20 catalogued forms and classified each by tradition:

- **European art music (18):** binary/rounded binary, ternary, sonata-allegro, rondo, theme and variations, fugue and canon, ritornello, passacaglia/chaconne, strophic, through-composed, minuet-and-trio/scherzo, sonata-rondo, da capo aria, arch form, bar form, isorhythm, cyclic form, moment form/open form.
- **Anglo-American popular song (2):** verse-chorus and 32-bar AABA; twelve-bar blues (African-American in origin but operating wholly inside the Western tonal/harmonic-cycle system).
- **Everything else: zero.** No South Asian, no Arabic/Turkish/Persian, no Southeast Asian (gamelan), no East Asian (Chinese/Japanese/Korean), no Sub-Saharan African, no Latin American entry.

Given §0a — the judge is instructed to score New *only* against this list and explicitly **not**
against its own knowledge — this means an agent that reinvents, say, Javanese *irama*-level
metric expansion, Korean *sanjo*'s accelerating rhythmic-cycle suite, Japanese *jo-ha-kyū*,
Hindustani *ālāp–jor–jhālā*, Carnatic *rāgam–tānam–pallavi*, the Andalusian *nūba*'s accelerating
*mīzān* sections, or a West African bell-cycle interlock **will be scored New = 7-10 and cannot be
caught**. Each of these is a large-scale organizing principle for sectional succession and
return — exactly what the query asks the agent to invent — and none collides with any listed entry.

A second, smaller defect visible by inspection: entry `[20]` lumps **moment form** (Stockhausen's
*Momentform*) together with **open form** (the Brown/Cage/Boulez mobile-score principle). These are
distinct organizing principles — non-teleological self-sufficient moments in a fixed order versus a
performer-chosen ordering of fixed modules — so the effective catalogue is smaller than 20.

### 5.2 MISSING prior art — three verified directly by me, as a floor

These three are enough on their own to establish the gate failure, independent of the fuller list:

1. **Javanese *irama* levels + colotomic *gongan* structure.** *Irama* is a hierarchy of metric
   density in which each level **doubles** the number of elaborating strokes per *balungan* beat —
   *lancar* (1) → *tanggung* (2) → *dadi* (4) → *wilet* (8) → *rangkep* (16) — so a single composition
   can be stretched or compressed to different total lengths and different degrees of embellishment
   by planned irama changes (*tanggung → dadi → wilet → rangkep*). Orthogonally, colotomic structure
   defines the form: in *ladrang* the *gong ageng* marks a 32-beat *gongan* while the *kenong*
   subdivides every 8. **A large-scale scheme for organising sectional succession by hierarchical
   metric-density transformation is not any of the 20 listed forms** — it is not variation (the
   melody is fixed), not rondo/ternary (no thematic return pattern), and not moment form.
   Sumarsam (Wesleyan), "Temporal and Density Flow in Javanese Gamelan":
   https://sumarsam.faculty.wesleyan.edu/files/2023/01/4_Temporal_and_Density_Flow.pdf ;
   https://music.arts.uci.edu/abauer/6.2/readings/Short_primer_Javanese_Gamelan_Sri_Duhita.pdf
2. **Japanese *jo-ha-kyū* 序破急.** A three-phase temporal-proportion principle — *jo* (slow,
   unmeasured introduction), *ha* (measured, accelerating development), *kyū* (rapid conclusion) —
   originating in 8th-century *gagaku* and generalised by Zeami into the governing structural
   principle of *noh*, applied recursively at the level of the play, the scene, and the phrase. It is
   a proportional/temporal scheme, not a thematic-return scheme, so no listed entry covers it.
   https://db2.the-noh.com/edic/2009/06/johakyu_1.html
3. **Korean *sanjo*.** A 4-7 movement solo suite whose sections are defined and ordered *by their
   rhythmic cycle* (*jangdan*), progressing monotonically from the slow *jinyangjo* through
   *jungmori*, *jungjungmori* to the fast *jajinmori* and *hwimori* — i.e. the organizing principle
   of the whole form is a one-way acceleration through named metric cycles. Structurally distinct
   from every listed form. https://www.melodigging.com/genre/sanjo ;
   https://accesson.kr/kaa/v.2/0/54/42772 ; https://silo.tips/download/chapter-music-of-sanjo
   *(Caveat: sources conflict on jinyangjo's metre — popular summaries say 18/8, Korean musicology
   generally says 24 beats in four groups of six. I could not resolve this from primary sources, so
   no metre figure is asserted here. Do not propagate either number without checking.)*

Note the family resemblance: **three separate traditions organise large-scale form primarily by
metric/temporal transformation rather than by thematic return** — and the catalogue's 20 entries are
almost entirely thematic-return schemes. That is a whole axis of formal organisation missing from the
novelty gate, not a few stray omissions.

### 5.3 Per-entry verdicts

**This item is factually the cleanest of the five: zero WRONG, zero FABRICATED.** Every form named
is real and correctly named. The seven IMPRECISE findings are *compressions* — two distinct
principles fused into one entry — rather than errors. The failure is entirely one of coverage.

| # | Claim | Verdict | Precise version | Source |
|---|---|---|---|---|
| `[3]` | "Sonata-allegro (exposition–development–recapitulation)" | **IMPRECISE** | Describes Hepokoski-Darcy **Type 3 only**. Type 2 lacks a full recapitulation and substitutes a "tonal resolution"; Types 1 and 2 are double-rotational, Type 4 = sonata-rondo, Type 5 = concerto | https://academic.oup.com/book/4770/chapter/147034087 ; https://onlinelibrary.wiley.com/doi/full/10.1111/j.1468-2249.2008.00283.x |
| `[6]` | "Fugue **and** canon (imitative counterpoint)" | **IMPRECISE — two things fused, and the stated principle is a texture not a form** | Canon = *strict, continuous* imitation at a fixed offset. Fugue is a compositional **procedure** (Tovey), not a form; its principle is subject/answer + episode + tonal plan | https://www.britannica.com/art/fugue ; https://www.britannica.com/art/fugue/Varieties-of-the-fugue |
| `[8]` | "Passacaglia / chaconne (ground bass)" | **IMPRECISE on two counts** | (a) The equation is scholarly-**contested** — Silbiger: "many seventeenth- and eighteenth-century composers did indeed conceive the passacaglia and the ciaccona as different"; the entry silently adopts Bukofzer's opposing view. (b) "Ground bass" is wrong for much of the repertoire — Silbiger: "The sense of a 'theme' subjected to variations is not really present." These are repeating **harmonic/bass formulas**, not necessarily literal ostinati | https://sscm-jscm.org/jscm/v2/no1/silbiger.html ; https://www.oxfordbibliographies.com/display/document/obo-9780199757824/obo-9780199757824-0166.xml |
| `[11]` | "Verse–chorus **and** 32-bar AABA" | **IMPRECISE — distinct paradigms fused** | Summach: AABA uses repeated strophes with an internal refrain; verse-chorus alternates lyric-*variant* verses with lyric-*invariant* choruses. Lumping also hides the **prechorus** (mid-1960s) and the **post-chorus / drop** (2010s) | https://mtosmt.org/issues/mto.11.17.3/mto.11.17.3.summach.html |
| `[16]` | "Arch form (ABCBA) — symmetric **palindrome**" | **IMPRECISE** | It is a palindrome of *section order*, not a literal retrograde: returning sections play forwards and are usually varied. True retrograde form is a different thing (Machaut, *Ma fin est mon commencement*; Hindemith's *Ludus Tonalis* postlude). Bartók's own term was ***bridge form***; "arch form" is an Anglophone analytical coinage | https://www.chambermusicsociety.org/about-the-music/compositions/bartok-string-quartet-4 ; https://www.oxfordreference.com/display/10.1093/acref/9780199579037.001.0001/acref-9780199579037-e-365 |
| `[18]` | "Isorhythm (14th-15th c.) — repeating rhythmic-melodic layers" | **IMPRECISE (dates CONFIRMED)** | Dates fine (Earp: c. 1316 to Du Fay's late motets in the 1440s). But the definition misses the defining mechanism: a repeated durational pattern (**talea**) applied to a melodic tenor (**color**) of *unequal* period, so pitch and rhythm cycles run out of phase and realign only at their LCM. Also: "isorhythm" is a **modern coinage (Friedrich Ludwig, 1904)** — medieval theorists said *talea* and *color* | https://www.cambridge.org/core/books/abs/critical-companion-to-medieval-motets/isorhythm/19692497AAE8A2ACEEC0278D234F5244 |
| `[20]` | "Moment form / open form (Stockhausen, 20th c.)" | **IMPRECISE — two principles fused plus a mis-attribution** | Moment form is Stockhausen's (*Momentform*, described 1960, printed in *Texte* 1, 1963) — non-teleological discontinuity. **"Open form" is Earle Brown's term** (from Calder mobiles, 1952-53); Boulez's parallel is *mobile form*; Stockhausen's own word for permutable-order pieces (*Klavierstück XI*, 1956) was **polyvalent form**. The literature resists the conflation: Brown's procedures "achieve smooth transitions and long lines of connected material" | https://mtosmt.org/issues/mto.20.26.3/mto.20.26.3.andersen.html ; https://academic.oup.com/mq/article-abstract/LXIV/2/177/1013555 |
| `[1]`,`[2]`,`[4]`,`[5]`,`[7]`,`[9]`,`[10]`,`[12]`,`[13]`,`[14]`,`[15]`,`[17]`,`[19]` | binary/rounded binary, ternary, rondo, theme and variations, ritornello, strophic, through-composed, minuet-and-trio/scherzo, sonata-rondo, da capo aria, twelve-bar blues, bar form, cyclic form | **CONFIRMED** (13) | *Barform* = two **Stollen** (*Aufgesang*) + **Abgesang** confirmed; note `[17]` incidentally already covers the formes-fixes **ballade** (aabC), and `[12]` is compound ternary, i.e. a special case of `[2]` rather than an independent principle | Britannica / Open Music Theory / Oxford Reference entries per row |

**`hard_rules` citations:** Caplin, *Classical Form* (OUP **1998**) — CONFIRMED. Hepokoski & Darcy,
*Elements of Sonata Theory* (OUP **2006**) — CONFIRMED. "the Norton/Oxford form-and-analysis canon" —
**UNVERIFIABLE as written** (no title given; real referents exist, e.g. Rosen, *Sonata Forms*,
Norton 1980) — not a fabrication, just unfalsifiable as a rule.

**Two structural problems in the rules themselves:**

1. **The rules invoke Hepokoski-Darcy as the reference authority, but their theory's top-level
   category is missing from the gate.** **Rotational form** is absent — and it is not a footnote:
   in Sonata Theory "sonata form is reconstrued as a subcategory of an overarching rotational
   principle." **Sonata deformation** and **teleological genesis** are also absent. An agent that
   proposes "cyclic passes through an ordered module-series, each pass reworked" reinvents a 2006
   Oxford monograph and, per §0a, will be scored New 7-10.
   https://academic.oup.com/book/4770/chapter/147034087 ; https://mtosmt.org/issues/mto.22.28.2/mto.22.28.2.lee.pdf
2. **`hard_rule[3]` is unsatisfiable by the agent under test.** It requires an absence-proof against
   **Grove Music Online**, which is paywalled — every Grove URL returned **HTTP 403** to automated
   fetch. A live-web agent cannot comply, so the rule either fires spuriously or is ignored.

**Counts:** CONFIRMED 13 · IMPRECISE 7 · **WRONG 0** · UNVERIFIABLE 1 (a `hard_rules` reference) ·
**FABRICATED 0** · N/A 1 (framing note `[0]`).

### 5.4 MISSING prior art — the real defect

The Western-only finding was confirmed **mechanically**: the whole item (query, `known_answers`,
`hard_rules`, `expert_baseline`, `rationale`) was scanned against ~60 non-Western and non-canonical
form terms — **zero hits**. The `expert_baseline` is likewise purely Western ("sonata-rondo… a
theme-and-variations wrapped in an arch"). Meanwhile **Grove — the rules' own cited authority — has
entries for gamelan, Iranian dastgāh and rāga.** The gate omits what its own reference documents.

**Tier 1 — near-certain rediscovery. These will be certified falsely novel today.** (My three
independently verified in §5.2 are the first three; the rest come from the parallel audit.)

| Organizing principle | Tradition / date | Citation |
|---|---|---|
| **Metric-augmentation variation suite** — successively halve the structural pulse and multiply ornamentation of one skeletal tune, generating ever-longer versions | Chinese *fangman jiahua* 放慢加花 (*Lao liuban* → *Zhonghua liuban* → *Man liuban*); Thai **phleng thao** (*sam chan / song chan / chan diao*, c. 1840-60); Javanese **irama** | https://contemporary_chinese_culture.en-academic.com/390/Jiangnan_sizhu ; https://thesiamsociety.org/wp-content/uploads/1970/03/JSS_058_2b_Morton_ThaiTraditionalMusic.pdf ; https://sumarsam.faculty.wesleyan.edu/files/2023/01/4_Temporal_and_Density_Flow.pdf |
| **Recursive self-similar three-phase acceleration** — the same slow-break-fast shape governs every level from a single step to a whole day's programme | **jo-ha-kyū**: gagaku → Zeami, *Sandō* **1423**; noh's five-part play is literally *Jo, Ha-jo, Ha-ha, Ha-kyū, Kyū* | https://noh.stanford.edu/form ; https://db2.the-noh.com/edic/2009/06/johakyu_1.html |
| **Progressive-acceleration suite** — movements ordered by increasing tempo / faster metric cycle within one mode | Korean **sanjo**; Moroccan **nūba** (5 *mīzān*, each accelerating *muwassaʿ → mahzūz → inṣirāf*); Ottoman **fasıl**; Tang **daqu**; Javanese *mérong → inggah → sesegan*; Balinese *kawitan–pengawak–pengecet* | https://silo.tips/download/chapter-music-of-sanjo ; https://academic.oup.com/chicago-scholarship-online/book/14587/chapter/168703626 |
| **Audible gradual process as the form** — one perceptible process determines both surface and whole | Reich, *Piano Phase* 1967; essay "Music as a Gradual Process" **1968** | https://global.oup.com/academic/product/writings-on-music-1965-2000-9780195151152 |
| **Additive process** — a cell lengthened/shortened by one unit per repetition | Glass, *Two Pages* 1968; *Music in Twelve Parts* 1971-74 | https://philipglass.com/recordings/twelve_parts/ |
| **Module-drift form** — fixed module sequence, each repeated ad lib, players advancing independently | Riley, *In C*, 53 modules, 1964 | https://www.wisemusicclassical.com/work/46356/In-C--Terry-Riley/ |
| **Non-commensurate loop / tempo-ratio convergence** — layers of unequal period realigning only at their LCM or a computed convergence point | Eno, *Music for Airports* 1978; Nancarrow tempo canons | https://mtosmt.org/issues/mto.14.20.1/mto.14.20.1.nemire.pdf |
| **Cyclic form over an invariant timeline with additive accretion** — an unchanging asymmetric bell ostinato (12-pulse ⟨2212221⟩) frames all parts; form advances by *density*, not sectional return | West Africa (Ewe, Yoruba, Akan). "Standard pattern" = A. M. Jones; "time line" = Nketia 1963 | https://jams.ucpress.edu/content/59/1/1 ; https://academicworks.cuny.edu/gc_pubs/935/ |
| **Colotomic / gongan form** — form defined by nested periodic gong punctuation; the form-*names are* cycle lengths (*ketawang* 16, *ladrang* 32) | Java / Bali | https://gamelanbvg.com/gendhing/gamelanGlossary.pdf |
| **Rotational form** (+ sonata deformation, teleological genesis) | Hepokoski & Darcy 2006 — **cited by the rules, absent from the gate** | https://academic.oup.com/book/4770/chapter/147034087 |
| **Energy-curve form** — intro → riser → **drop** → breakdown → second buildup → second drop → outro; organised by textural/filter tension, not thematic return | EDM; Butler 2006; Osborn, *Intégral* 36 (2023) | https://theory.esm.rochester.edu/integral/36-2023/osborn/ |
| **Modal-itinerary form (*sayr*)** — form is a prescribed *route* through a mode's *ajnās* with *qafla* cadences and obligatory return | Arabic **taqsīm** | https://academic.oup.com/mts/article-abstract/35/2/235/1034751 |
| **Registral ascent → climax → formulaic descent** — ordered ascent through modal nuclei to a peak, then a codified cadential descent | Iranian **dastgāh/radīf**: *darāmad – gūsheh – ʿawj/owj – forūd* | https://www.iranicaonline.org/articles/dastgah/ ; https://ich.unesco.org/en/RL/radif-of-iranian-music-00279 |
| **Monotonic metrical emancipation** — unmetered → pulsed-but-unmetered → metered, tempo never decreasing, register expanding outward from the tonic | Hindustani **ālāp – joḍ – jhālā → gat** (dhrupad-derived; **vocal as well as instrumental**) | https://www.britannica.com/art/South-Asian-arts/Musical-forms-and-instruments ; https://autrimncpa.wordpress.com/genres/ |
| **Cumulative form** — the theme appears in fragments and arrives complete only near the END | Ives, c. 1902-08; term = Burkholder, *All Made of Tunes* (Yale UP 1995) | https://mtosmt.org/issues/mto.11.17.2/mto.11.17.2.iverson.html |
| **Interlocking / hocket** — the melody exists only in the composite of strictly alternating single-note streams | Ugandan **amadinda/akadinda** (Kubik's "inherent rhythm"); Shona mbira *kushaura/kutsinhira*; Aka yodel-hocket (Arom) | https://www.mtosmt.org/issues/mto.10.16.4/mto.10.16.4.scherzinger.html ; https://doi.org/10.1017/CBO9780511518317 |
| **Closed→open two-part design** — composed lyrical section, then an open-ended cyclic call-and-response vamp with progressive intensification, ended by cue not architecture | Cuban **son** (*largo → montuno*, coro vs sonero); salsa *mambo/moña* | https://academicworks.cuny.edu/jj_pubs/315/ ; https://tupress.temple.edu/book/0371 |
| **Threefold-repetition cadence** — one phrase stated exactly three times, timed so the last stroke lands on beat 1 of the cycle | Hindustani **tihāī** | https://www.oxfordreference.com/display/10.1093/oi/authority.20110803095455560 |
| **Mode-garland with link-back refrain**, and the exhaustive-enumeration cycle (one section per mode of the system) | Carnatic **rāgamālikā**; **72-Melarāgamālikā**, Mahā Vaidyanātha Iyer **1883** | https://archive.org/stream/HistoryOfIndianMusicBySambamoorthy/HistoryOfIndianMusicBySambamoorthy_djvu.txt |
| **Formula composition** — one melodic formula's intervals and durations projected onto every structural level from phrase to whole cycle; goal-directed and hierarchically derived, i.e. the **inverse** of moment form | Stockhausen, *Mantra* **1970**; *Licht* super-formula 1977-2003 | Kohl, *Perspectives of New Music* 28/2 (1990): 262-91 |

**Tier 2 — high risk.** Single-mode prescribed-genre-order suite (**waṣla**, **fasıl**) · **double-function
form** (Liszt 1853) · **equal-length superimposable sections** (Japanese *danmono*: every *dan* = 104
beats, enabling *dan-awase*, two dan played simultaneously) · **register-zone sectioning** (dhrupad
*sthāyī–antarā–sañcārī–ābhog*) · **three-stage metrical emancipation with the theme withheld to last**
(**rāgam–tānam–pallavi**) · **time-bracket form** (Cage number pieces 1987-92) ·
**game-piece/rule-protocol form** (Zorn, *Cobra* 1984) · **iterative-feedback form** (Lucier, *I Am
Sitting in a Room*, 1969) · **Ghost Trance Music** (Braxton 1995-2006) · **stochastic form** (Xenakis,
*Pithoprakta*) · **spectral process form** (Grisey, *Partiels* 1975) · **developing variation +
liquidation** (Schoenberg — explicitly *not* theme-and-variations) · **personnages rythmiques**
(Messiaen) · **kāydā + palta + tihāī** permutational variation set · **banqiangti vs qupaiti** (form as
a sequence over a fixed inventory of metrical types vs an ordered set of pre-existing labelled tunes) ·
**proportional/numeric form** (Dufay, *Nuper rosarum flores*, 6:4:2:3, 1436).

**Tier 3 — real prior art, lower rediscovery probability.** Mensuration/prolation canon cycle
(Ockeghem, *Missa prolationum*) · **formes fixes virelai (AbbaA) and rondeau (ABaAabAB)** — refrain-framed
recombination of only two musical phrases, **not** covered by bar form (which does cover the ballade) ·
paired-versicle sequence · *punctum* with *ouvert/clos* endings (estampie) · Byzantine **kanōn** ·
suite/partita ordered by dance type and the **variation suite** (Peuerl 1611; Schein 1617) ·
quodlibet/medley/potpourri · **la solita forma** (Basevi 1859) · cantus-firmus/parody mass cycle ·
chorale prelude/fantasia · French overture · prelude-and-fugue pairing · ricercar/canzona · ragtime
multi-strain march chain · **pathet** (modal region mapped to time of day across a nine-hour wayang) ·
Mevlevî **âyîn** · **pansori** (*aniri* vs *sori* over a jangdan inventory) · **incomplete-repetition
form** (Plains song) · noh **shōdan** (a modular grammar of ~100 conventional units with fixed
syntactic slots) · **prabandha** (*udgrāha–dhruva–melāpaka–ābhoga*) · **crippled symmetry** (Feldman
1981) · **chain form** (Lutosławski) · **collage form** (Berio, *Sinfonia* III) · version/riddim-family
form (Jamaican dub) · Mande *jaliya* (*donkilo/birimintingo/sataro* over a *kumbengo* ostinato) ·
meta-cycle of mode-suites (Shashmaqom, Uyghur Twelve Muqam, the twelve dastgāh).

### 5.5 Proposed replacement strings — all 7 verified by me to occur exactly once

```
[3]  old: Sonata-allegro (exposition–development–recapitulation).
     new: Sonata-allegro (exposition–development–recapitulation) — Hepokoski-Darcy Type 3; also
          Types 1, 2 (tonal resolution without full recapitulation), 4, 5.
[6]  old: Fugue and canon (imitative counterpoint).
     new: Fugue — subject/answer exposition, episodes, tonal plan (a procedure, not a fixed form).
          Canon — strict continuous imitation at a fixed offset (incl. mensuration/prolation and
          tempo canons).
[8]  old: Passacaglia / chaconne (ground bass).
     new: Passacaglia and chaconne — variation over a repeating bass or harmonic formula (their
          mutual distinction is scholarly-contested; not always a literal ground bass).
[11] old: Verse–chorus and 32-bar AABA popular-song forms.
     new: 32-bar AABA (strophe + bridge) and verse–chorus (lyric-variant verse vs lyric-invariant
          chorus) — distinct paradigms; incl. prechorus and post-chorus/drop modules.
[16] old: Arch form (ABCBA) — symmetric palindrome.
     new: Arch / bridge form (ABCBA) — symmetry of section ORDER (structural palindrome), distinct
          from literal retrograde/mirror forms.
[18] old: Isorhythm / isorhythmic motet (14th-15th c.) — repeating rhythmic-melodic layers.
     new: Isorhythm / isorhythmic motet (c. 1316-1440s) — a repeated durational pattern (talea)
          over a melodic tenor (color) of different period, so rhythm and pitch cycles run out of
          phase; term coined by Friedrich Ludwig, 1904.
[20] old: Moment form / open form (Stockhausen, 20th c.).
     new: Moment form (Stockhausen, "Momentform" 1960) — non-teleological mosaic of discontinuous
          self-contained moments. Open/mobile/polyvalent form (Brown, Boulez, Stockhausen
          Klavierstück XI) — performer- or conductor-chosen ordering; a separate principle.
```

### 5.6 Corrections to claims in my own audit brief (so they do not propagate)

The parallel audit caught several errors in the *instructions I wrote*, which is exactly what a good
audit should do. Recorded here so they are not copied into the dataset:

- **`jinyangjo` metre:** popular summaries say 18/8; Korean musicology generally says **24 beats in four groups of six**. Unresolved — assert neither (see §5.2).
- ***pallavi–anupallavi–caraṇam* dates from the 15th c.** (Tallapakam composers), not c. 1800; the Carnatic Trinity perfected the *kṛti*, they did not originate the scheme.
- **jor/jhālā is not instrumental-only** — dhrupad *vocal* ālāp is also ālāp–joḍ–jhālā.
- **In the nūba, *raṣd* is a mode (*ṭabʿ*), not a *mīzān***; the five mīzān are *basīṭ, qāʾim wa-niṣf, bṭāyḥī, darj, quddām*. Morocco preserves **11 complete + 5 partial** nūbāt (24 is the legendary al-Andalus count).
- **In the fasıl the *taksim* comes FIRST**, not last; *şarkı* belongs to the 19th-c. modern fasıl. The peşrev's refrain is the **mülâzime** (*teslim* is the connecting tag).
- **"Standard pattern" is A. M. Jones's term; "time line" is Nketia's** — my brief reversed them. Kubik's term is **"inherent rhythm"**, not "resultant melody". Berliner, *The Soul of Mbira*, is **UC Press 1978**.
- **Do not attribute cycle-not-sectional essentialism to Agawu** — he argues *against* it.
- **Agbekor's sections are *ʋulolo → adzo → ʋutsotsoe***; "banyinyi" is not verifiable for Agbekor (Wikipedia-only, and associated with Agbadza).
- **Uyghur *märghul*** is an interlude *inside* chong näghmä, not its third section (that is **mäshräp**); shashmaqom *talqin* is a piece, not a sub-cycle (those are **Savt** and **Moghulcha**).
- **Irama** is pulse-*halving* with density-doubling and gongan expansion, **the tempo resetting** — not "getting slower".
- **SRDC is Walter Everett's** term, not Björnberg's. **La solita forma** is Basevi's "*solita forma de' duetti*" and includes the *tempo d'attacco*; *stretta* ≠ *cabaletta*.

---

## 6. Overall judgement — can these baselines gate novelty?

### 6.1 Verdict roll-up

| Item | C | I | W | U | F | Missing prior-art families | Trustworthy as a novelty gate? |
|---|---|---|---|---|---|---|---|
| `C5_biology_medicine_24` | 8 | 1 | 2 | 0 | **0** | 12 | **No — conditionally repairable.** One wrong date, one imprecision, but a structural blind spot for physically-mediated modalities plus an inverted Surprise baseline. |
| `C5_arts_humanities_29` | ~27 | 4 | 3 | 0 | **0** | 13 (+6 more) | **Marginal — the best content of the five, but not safe as written.** The failure is that its own `hard_rule[4]` and `expert_baseline` designate occupied territory. |
| `C5_engineering_28` | 2 | 10 | 11 | 0 | **0** | 20 | **No.** Only 2 of 23 claim units survive unamended; 13 mis-dated, all novelty-inflating, by up to 85 years. |
| `C5_materials_chemistry_25` | 26 | 10 | 3 | 0 | **0** | 21 (+2) | **No.** Includes the only reputationally exposed error in the file (MOFs credited without Robson, a 2025 Nobel laureate) and both `expert_baseline` white-space targets are decades-occupied. |
| `C5_arts_humanities_49` | 13 | 7 | **0** | 1 | **0** | ~20 Tier-1, ~16 Tier-2, ~25 Tier-3 | **No — and it is the clearest failure of the five despite being the most factually accurate.** Zero wrong claims, but 17 of 20 entries bare, the catalogue is entirely Western, and it omits its own cited authority's top-level category. |

**Nothing fabricated anywhere in this pass — 0 FABRICATED across all five items and ~130 claim
units.** Every cited paper, patent, book, person and product exists and is correctly named. That is
worth saying plainly: these items were written by someone who knew the literature. The failure is not
invention, it is **dating and coverage**.

**Aggregate: 2 items fail on accuracy (engineering, materials), 1 fails purely on coverage
(musical forms), 2 fail on a designated-white-space contradiction (biology, poetry).** Accuracy and
gate-validity are separate axes, and `C5_arts_humanities_49` is the proof: it is simultaneously the
most factually correct item and the least usable as a gate.

### 6.2 The two 33-entry baselines specifically

The parent question was whether `C5_arts_humanities_29` and `C5_materials_chemistry_25` — the two
largest novelty baselines in the dataset, tied at 33 entries against a file median of 13 — are
trustworthy enough to gate novelty.

For **`C5_arts_humanities_29`**: its *content* is the best of the five. Its 32 forms are genuinely
cross-lingual, the villanelle entry gets right what most references get wrong, and only three entries
are outright WRONG. But size is doing less work than it appears: one entry is a dating note, the nonet
is double-counted, and — decisively — the item's own `hard_rule[4]` and `expert_baseline` tell the
grader that semantic, reader-path, cross-modal and dialogic constraints are unoccupied types, when
each is the defining principle of a documented form, mostly non-Western, and one of them
(*katauta*/*mondōka*) is sitting inside the item's own entry `[12]`. A grader following the item as
written will award New 7-10 and high Surprise to a rediscovery of 4th-century Chinese grid poetry or
12th-century Occitan debate form. **Fixable with the nine substring edits in §2.4 plus a rewrite of
`hard_rule[4]`'s examples and the closing sentence of `expert_baseline`. Do not ship as is.**

For **`C5_materials_chemistry_25`**: **no, and it is the more serious of the two.** Its coverage is
broad and genuinely expert-selected and 26 of ~39 dated claims are right down to volume and page — but
13 are defective and **every one of the 13 dates prior art younger than reality** (CNTs −39 yr, halide
perovskites −31 to −116, amorphous metals −26, zeotypes −30, MOPs −14, high-entropy ceramics −11, MOFs
−10). For an item whose entire scoring weight sits on New and whose gate is "must be distinct from the
**dated** list", a one-directional youth bias is the worst possible bias: in the halide-perovskite case
a judge would actively reward an agent for "inventing" a class Weber synthesised in 1978. Two defects
are qualitatively worse than date drift: the MOF entry omits **Richard Robson**, who shared the **2025
Chemistry Nobel** precisely for originating the family (§3.2), and entry `[17]` fuses two different
materials from two different labs and years. On top of that, **both** `expert_baseline` white-space
targets are decades-occupied — one of them by woven COF-505, which the item lists as prior art in its
*own* entry `[6]` — and the baseline's fallback "porous ordered electride framework" has itself been
published for sodalites (2023, 2025). Plus 21 established families are missing, four of them sitting
exactly where the baseline points. **Repairable, not rotten: apply §3.6, add the top ~8 missing
families, and rewrite both white-space exemplars.**

**Bottom line on the parent question:** neither 33-entry baseline is currently trustworthy enough to
gate novelty. Their size is not the problem and is partly illusory (each has a dating note, materials
bundles 5 multi-discovery entries, poetry double-counts the nonet). The problem is that in both items
the *item itself* tells the grader that already-occupied territory is the novel target, and per §0a the
judge is forbidden from noticing. Both are fixable with the substring edits and additions listed here;
neither should ship unfixed.

### 6.3 Priority ordering for the fix

1. **P0 — blocks release, and this is the one an external reviewer will spot first.**
   `C5_materials_chemistry_25` `[5]`: MOFs credited to "Yaghi/Kitagawa, late 1990s", omitting
   **Richard Robson**, whom the 2025 Nobel committee names as the originator (§3.2).
2. **P0 — blocks release.** Rewrite the `expert_baseline` white-space claims in
   `C5_materials_chemistry_25`, `C5_biology_medicine_24` and `C5_arts_humanities_29`, plus
   `hard_rule[4]`'s examples in the last, so they no longer nominate occupied territory (§0c).
   Correct the `C5_engineering_28` baseline's force estimate. These are **scoring bugs, not citation
   slips**: they invert the Surprise axis, and the judge is barred from correcting them.
3. **P0 — blocks release.** Fix `C5_biology_medicine_24` `[18]` (oncolytic dates: 2004/2005, not
   2015) — the specific defect this audit was asked to resolve.
4. **P1.** Apply the verified-unique substring replacements: 22 for `C5_engineering_28` (§4.3),
   13 for `C5_materials_chemistry_25` (§3.6), 9 for `C5_arts_humanities_29` + 2 for
   `C5_biology_medicine_24` (§2.4), 7 for `C5_arts_humanities_49` (§5.5). **53 edits, every `old`
   string verified by me to occur exactly once in the raw file.** Note the file stores literal UTF-8
   em-dashes (573 of them, zero escapes).
5. **P1 — and this matters more than any date fix.** Add the missing families as new `known_answers`
   entries (§1.4, §2.3, §3.5, §4.4, §5.4). Under §0a this is the *only* protection against false
   novelty. **⚠️ First raise `_MAX_KNOWN_ANSWERS` in `judge/score.py`, currently 40**: after
   additions, `C5_engineering_28` → 42, `C5_arts_humanities_29` → 45, `C5_materials_chemistry_25` →
   ~53, `C5_arts_humanities_49` → 40+. All would cross the cap, at which point the judge silently
   receives a *truncated* baseline — and because entry `[0]` is an instruction header in 20 items,
   the cut preserves the instruction and discards real prior art. Growing the lists without raising
   the cap would make the gate worse, not better.
6. **P1.** For `C5_arts_humanities_49` specifically, state the added principles as **organizing
   principles rather than culture-bound names** ("form built by successive pulse-halving with
   multiplied ornamentation" rather than "*fangman jiahua*"), so the gate fires on the mechanism an
   agent actually proposes rather than on a term it will never use.
7. **P2.** Replace every "(established)", "(established automotive prior art)" and "ancient through"
   with an earliest-publication year (§0b).
8. **P2.** `C5_arts_humanities_49` `hard_rule[3]` requires an absence-proof against **Grove Music
   Online**, which is paywalled (HTTP 403 to automated fetch). The agent under test cannot comply.
   Either drop Grove from the required sources or accept an open substitute.
9. **P2 — outside this audit's scope.** Re-test the four bold items in §0c for the
   occupied-white-space defect. Base rate so far: 5 of 5 items tested carry it.
