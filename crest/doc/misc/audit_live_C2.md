# CREST live-web citation audit — C2 (counterfactual reasoning), 10 items

**Scope:** the 10 items whose `id` starts with `C2_` in `question/crest_challenges.audit.jsonl`
(working copy; **no `.jsonl` file was edited by this audit**).
**Method:** live WebSearch + WebFetch against primary sources (arXiv, Crossref, PubMed/PMC,
legislation.gov.uk statute PDFs, CourtListener/Justia, publisher pages, MacTutor, Wikipedia
as secondary corroboration only). Only real-world factual claims were graded; the
counterfactual reasoning itself is not fact-checkable and was left alone.
**Date:** 2026-07-30.

Items audited: `C2_arts_humanities_11`, `C2_biology_medicine_06`, `C2_biology_medicine_34`,
`C2_economics_business_08`, `C2_economics_business_36`, `C2_engineering_10`,
`C2_law_policy_09`, `C2_law_policy_37`, `C2_materials_chemistry_07`, `C2_materials_chemistry_35`.

---

## 0. Headline findings

1. **`C2_engineering_10` — WRONG figure, in `known_answers`.** The Hippke citation itself is
   clean (venue, year, arXiv id, submission month all correct), but the paper's `~400,000 t`
   fuel figure is for a **45 t Apollo-class** mission, not a "Hubble-class payload". Hippke
   never mentions Hubble; his telescope example is **JWST at 6.2 t → 55,000 t**. This is a
   `known_answers` error and must be fixed before release.
2. **`C2_biology_medicine_06` — two hard author-list errors, both in `known_answers`.**
   Rudensky is not an author of Aluvihare et al., *Nat Immunol* 2004 (third author is
   Kallikourdis); Dunn is not an author of the 2011 *Science* immunoediting paper
   (Schreiber, Old & Smyth). Nothing fabricated — both papers exist — but the attributions
   are wrong.
3. **`C2_arts_humanities_11` — one substantively wrong example.** Melozzo da Forlì
   (c. 1438–1494) is offered as foreshortening that *predates* the vanishing-point
   construction; he postdates Brunelleschi and Alberti by two generations and works inside
   the perspective tradition.
4. **`C2_economics_business_08` — the prior pass's removals held.** A byte-level scan of the
   item found **no** `%`, no `GDP`, no `billion/trillion`, no `Cox`, no `Edward` anywhere in
   `query`/`known_answers`/`expert_baseline`/`hard_rules`. The suspected-fabricated
   "5-20% of U.S. GDP" statistic and the "Edward Cox 1855" reference are gone and nothing
   comparable replaced them. Its ~19 legal-history and finance-theory claims verify
   remarkably well, including against the **primary statute text** of the Companies Act 1879.
   Two residual soft spots: the `1863-1933` double-liability date range, and an unsourced
   characterisation of Murray Rothbard.
5. **`C2_engineering_10` also carries an unsourced number and a wrong hard rule.** The
   "sustained ~16 g for a minute may be lethal" figure traces to a single uncited Wikipedia
   sentence that carries a live *citation-needed* tag; the standard primary reference
   (Eiband, NASA Memo 5-19-59E, 1959) explicitly says no lethal boundary has been
   established. Separately, `hard_rules[1]`'s "LOX/LH2 vacuum Isp <= ~450 s" is beaten by
   flown hardware (RL10B-2 = 465.5 s) — a rule that could penalise a *correct* agent answer.
6. **Nothing fabricated anywhere in C2.** Every cited paper, book, statute and case exists
   with the stated author/title. The failure mode in this category is *misattribution,
   date/figure drift, and absolutes that the comparative literature contradicts* — not
   invention. C2 is markedly cleaner than a category with invented citations would be, but
   four items need edits before release.

---

## 1. Priority claim 1 — `C2_engineering_10` / Michael Hippke

`known_answers[2]` states:

> Michael Hippke, 'Spaceflight from Super-Earths is difficult,' Int. J. Astrobiology 18 (2019),
> arXiv:1804.04727 (submitted Apr 2018) … chemical rockets remain (barely) viable only up to
> ~10 Earth masses (a few g) … (e.g., a Hubble-class payload from a 10-Earth-mass world would
> need on the order of ~400,000 t of fuel).

| Sub-claim | Verdict | Evidence |
|---|---|---|
| Author "Michael Hippke" | CONFIRMED | https://arxiv.org/abs/1804.04727 |
| Title "Spaceflight from Super-Earths is difficult" | CONFIRMED | same |
| Venue *Int. J. Astrobiology* vol. **18**, year **2019** | CONFIRMED | journal ref on arXiv: *Int. J. Astrobiology* **18** (2019) 393–395; DOI 10.1017/S1473550418000198 |
| arXiv id **1804.04727** | CONFIRMED | same |
| "submitted Apr 2018" | CONFIRMED | v1 **12 April 2018**; v2 18 May 2018 |
| "required propellant mass is an EXPONENTIAL function of surface gravity" | CONFIRMED | abstract: "the required fuel mass for a given payload is an exponential function of planetary surface gravity" |
| "chemical rockets … viable only up to ~10 Earth masses" | CONFIRMED | abstract: "chemical rockets still allow for escape velocities on Super-Earths up to 10x Earth mass" |
| "(a few g)" | CONFIRMED | Hippke's worked case is a 10 M⊕ / 1.7 R⊕ world ⇒ g ≈ 3.5 g₀; real Kepler-20 b is 9.7 M⊕ / 1.868 R⊕ ⇒ g ≈ 2.8 g₀ — https://en.wikipedia.org/wiki/Kepler-20b |
| **"a Hubble-class payload … ~400,000 t of fuel"** | **WRONG** | The paper attributes ~400,000 t to a **45 t Apollo-class** mission, and never mentions Hubble at all. Its telescope example is **JWST (6.2 t) → 55,000 t**. https://ar5iv.labs.arxiv.org/html/1804.04727 |

**Verbatim from the paper** (via ar5iv full text):

> "For a mass ratio of 83, the minimum rocket (1 t to v_esc) would carry 9,000 t of fuel on
> Kepler-20 b … To lift a more useful payload of 6.2 t as required for the James Webb Space
> Telescope on Kepler-20 b, the fuel mass would increase to 55,000 t … For a classical Apollo
> moon mission (45 t), the rocket would need to be considerably larger, ~400,000 t."

(For comparison the paper gives Saturn V a total mass of ~3,050 t for the same 45 t lunar
payload. Hubble's actual launch mass is ~11 t — i.e. between Hippke's two bracketing cases,
so the substituted label is wrong in *both* directions: wrong payload class *and* a figure
that belongs to a payload 4× heavier.)

**Exact replacement (old → new)** — in `C2_engineering_10.known_answers[2]`:

- OLD: `(e.g., a Hubble-class payload from a 10-Earth-mass world would need on the order of ~400,000 t of fuel)`
- NEW: `(e.g., from a 10-Earth-mass world like Kepler-20 b, a 6.2 t James-Webb-class payload would need ~55,000 t of fuel and a 45 t Apollo-class mission ~400,000 t, against the Saturn V's ~3,050 t for the same 45 t)`

This matters: the item's whole design is to *cap cheap surprise* by pre-listing Hippke's
headline result as KNOWN. A judge holding a wrong quantitative anchor could mark a correct
agent answer (55,000 t for a telescope-class payload) as a factual error.

---

## 2. Priority claim 2 — `C2_economics_business_08` residual-statistic check

**Question asked:** did any unsupported statistic or dubious attribution survive the prior
pass that removed a suspected-fabricated "5-20% of U.S. GDP" figure and an unconfirmed
"Edward Cox 1855" reference?

**Answer: essentially no.** A programmatic scan of the item's `query`, `known_answers`,
`expert_baseline` and `hard_rules` returns **zero** matches for `%`, `percent`, `GDP`,
`billion`, `trillion`, `Cox`, or `Edward`. A file-wide scan for `5-20` returns only
false positives elsewhere (`~15-20` mass ratios in `C2_engineering_10`; `2025-2026` date
ranges in C4/C5 items). The item is now unusually statistic-free for an economics
counterfactual — every quantitative-sounding claim has been replaced by dated legal/
institutional facts, which is the right trade.

`known_answers[9]` even carries an explicit epistemic hedge that reads like the scar tissue
of the removal:

> "…the aggregate magnitude of these externalities is contested and not precisely quantified
> in the literature."

**Two residual soft spots remain** (details in §4): the `1863-1933` double-liability range
(IMPRECISE) and the Rothbard attribution in the same sentence as the hedge above
(UNVERIFIABLE / mischaracterisation risk).

---

## 3. `C2_engineering_10` — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| Galileo, *Two New Sciences* (1638), square-cube law | CONFIRMED | *Discorsi e dimostrazioni matematiche intorno a due nuove scienze*, Leiden (Elzevir) 1638; the square-cube law and the disproportionate thickening of large animals' bones are in **Day Two** | https://en.wikipedia.org/wiki/Two_New_Sciences |
| Max self-supporting height ∝ 1/g | CONFIRMED (analytic) | h_max = σ/(ρg) for a uniform column ⇒ exactly ∝ 1/g | derivation |
| **Tsiolkovsky rocket equation (1903)** | **IMPRECISE** | 1903 is right for Tsiolkovsky's publication (*Nauchnoe Obozrenie*, 1903; his own manuscript dated 1897), but the equation was **first derived by William Moore** — outlined 1810, elaborated in *A Treatise on the Motion of Rockets* (1813) — and independently by Goddard (1912) and Oberth (1920) | https://en.wikipedia.org/wiki/Tsiolkovsky_rocket_equation |
| LEO Δv ~9.4–9.7 km/s incl. gravity and drag losses | CONFIRMED | Standard budget: 7.8 km/s orbital + 1.5–2 km/s losses = 9.3–9.8 km/s; ISS-altitude launch quoted at ~9.4 km/s | https://en.wikipedia.org/wiki/Delta-v_budget |
| Hippke citation (venue/year/arXiv/date) | CONFIRMED | *IJA* 18 (2019) 393–395; arXiv:1804.04727 v1 12 Apr 2018 | https://arxiv.org/abs/1804.04727 |
| **Hippke "~400,000 t / Hubble-class"** | **WRONG** | 400,000 t = 45 t Apollo-class; JWST 6.2 t → 55,000 t; Hubble not mentioned | https://ar5iv.labs.arxiv.org/html/1804.04727 |
| Munroe *What If?* + worldbuilding essays ~2012–2023 | CONFIRMED | *What If?* Houghton Mifflin Harcourt, 2014 (inside the stated window) | https://openlibrary.org/search.json?q=What+If+Munroe |
| "acute human tolerance is ~5 g before loss of consciousness (unpressurised, vertical)" | CONFIRMED | Untrained, sudden-onset +Gz blackout occurs between **4 and 6 g**; trained pilots in g-suits using anti-g straining reach 12–14 g. Burton RR, "G-induced loss of consciousness: definition, history, current status," *Aviat Space Environ Med* 59(1):2–5, 1988 | https://pubmed.ncbi.nlm.nih.gov/3281645/ |
| **"a sustained ~16 g for a minute may be lethal"** | **UNVERIFIABLE — recommend cutting** | Traces to a **single uncited sentence in the Wikipedia g-force article** ("a constant 16 g for a minute, however, may be deadly") whose wikitext carries a live `Citation needed (August 2021, reason: Where does 16g come from?)` tag. The standard primary reference — Eiband, "Human Tolerance to Rapidly Applied Accelerations: A Summary of the Literature," NASA Memo 5-19-59E (1959) — covers only rapidly applied accelerations (plateau ≲1 s) and states outright: "Sufficient experimental data have not been obtained to indicate the magnitude of the lethal boundary of severe injury." Burton 1988 and the G-LOC literature were also checked. **This is an unsourced internet number, not an aerospace-medicine result.** | https://en.wikipedia.org/wiki/Special:Export/G-force ; https://ntrs.nasa.gov/api/citations/19980228043/downloads/19980228043.pdf |
| **"McMahon elastic similarity, 1973; R. McN. Alexander"** | CONFIRMED (paper) / **IMPRECISE (bundling)** | Thomas McMahon, "Size and shape in biology," *Science* **179**(4079):1201–1204, 23 Mar 1973 — the elastic-similarity paper ✓. But R. McNeill Alexander is a **separate** researcher who did not co-author it; the bundled citation string reads as joint authorship | https://pubmed.ncbi.nlm.nih.gov/4689015/ |
| Lift/drag independent of g; 1.5× weight ⇒ 1.5× lift | CONFIRMED (textbook) | L = ½ρv²SC_L contains no g | derivation |
| Aerostatic float condition is gravity-INVARIANT | CONFIRMED (analytic) | (ρ_air−ρ_gas)Vg = mg ⇒ g cancels identically | derivation |
| Staging/reuse penalties are Δv-driven (2010s) | CONFIRMED (textbook) | | |
| Space elevator: Pearson 1975, Edwards 2000s; taper ∝ exp(ρgR/σ) | CONFIRMED | Jerome Pearson, "The orbital tower: a spacecraft launcher using the Earth's rotational energy," *Acta Astronautica* **2**(9–10):785–799 (1975) ✓. Edwards: NIAC Phase I "The Space Elevator" (2000), Phase II report + book with Westling (2002–03) ✓. Taper: A(R_g)/A_s = exp[(ρ/T)·4.85×10⁷ m²/s²], the constant being the Earth gravitational-plus-centrifugal potential integral — exactly the ρgR/σ form claimed (steel ⇒ ~10³³ taper; CNT ⇒ ~1.6) | https://en.wikipedia.org/wiki/Space_elevator |
| Orbital velocity ∝ √g at fixed R (7.8 → 9.5 km/s) | CONFIRMED (analytic) | v = √(gR); √1.5 = 1.2247; 7.8 × 1.2247 = 9.55 | derivation |
| Mass ratio 8–9 (Earth) → 15–20 (1.5 g) for hydrolox | CONFIRMED (analytic) | e^(9.5/4.4)=8.7; e^(12.5/4.4)=17.0; still holds at v_e=4.565 (8.0 → 15.5) | derivation |
| Grashof/Rayleigh driving force scales with g | CONFIRMED | Gr = gβΔT·L³/ν², Ra = Gr·Pr — g appears to the first power in both, so buoyancy-driven passive cooling does get **stronger** at 1.5 g | https://en.wikipedia.org/wiki/Grashof_number ; https://en.wikipedia.org/wiki/Rayleigh_number |
| structural steel yield ~250–550 MPa | CONFIRMED for common grades (incomplete as a class ceiling) | EN 10025 common grades 195/235/275/355/420/460 MPa; ASTM A36 = 250, A992 = 345. Quenched-and-tempered structural grades (A514, S690–S960) reach **690–960 MPa**, so the range describes *ordinary* structural steel. Harmless here — the item uses it as a realism floor, not a cap | https://en.wikipedia.org/wiki/Structural_steel |
| **`hard_rules[1]`: "LOX/LH2 vacuum Isp <= ~450 s, i.e. v_e <= ~4.4 km/s"** | **WRONG** | 450 s is not an upper bound — several flown LOX/LH2 engines beat it. Highest flown: **RL10B-2 = 465.5 s (4.565 km/s)**, Delta III / Delta IV DCSS, in service since 1998. Also above 450 s: RL10E-1 460.9, Vinci ~457, RS-25/SSME 452.3, RL10C-1-1 453.8. Correct bound ≈ **465 s / 4.56 km/s** | https://en.wikipedia.org/wiki/RL10 |

**Exact replacement (old → new)** — in `C2_engineering_10.hard_rules[1]`:

- OLD: `chemical-propellant specific impulse (LOX/LH2 vacuum Isp <= ~450 s, i.e. exhaust velocity v_e <= ~4.4 km/s)`
- NEW: `chemical-propellant specific impulse (LOX/LH2 vacuum Isp <= ~465 s, i.e. exhaust velocity v_e <= ~4.6 km/s; the RL10B-2 upper-stage engine is the flown ceiling at 465.5 s)`

Note this fix is *safe for the item's own arithmetic*: re-running the baseline at
v_e = 4.565 km/s gives mass ratios 8.0 → 15.5, still inside the item's stated "~8-9 to ~15-20"
band, and chemical SSTO at 1.5 g remains impossible. Leaving the low ceiling in place would
let a correct agent answer (citing 465 s) be scored as a rule violation.

**Two further replacements for `C2_engineering_10`:**

`known_answers[4]` — cut the unsourced lethality figure:

- OLD: `acute human tolerance is ~5 g before loss of consciousness (unpressurised, vertical), and a sustained ~16 g for a minute may be lethal; sustained MODERATE hypergravity (2-5 g) is poorly characterised`
- NEW: `acute human tolerance to sudden-onset +Gz is ~4-6 g before loss of consciousness (unpressurised, untrained), rising to 12-14 g for trained pilots in g-suits performing anti-g straining (Burton 1988); sustained MODERATE hypergravity (2-5 g) is poorly characterised, and no lethal-boundary magnitude for sustained acceleration is established in the literature (Eiband, NASA Memo 5-19-59E, 1959)`

`known_answers[1]` and `known_answers[5]` — priority/authorship precision (optional, low stakes):

- OLD: `Tsiolkovsky rocket equation (1903)`
- NEW: `Tsiolkovsky rocket equation (published 1903; first derived by W. Moore, 1810-13)`
- OLD: `Biomechanical scaling (McMahon elastic similarity, 1973; R. McN. Alexander)`
- NEW: `Biomechanical scaling (McMahon's elastic-similarity paper, Science 1973; and separately R. McN. Alexander's work on locomotor scaling)`

---

## 4. `C2_economics_business_08` — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| Butler 1911 (Columbia) "greatest single discovery of modern times"; steam & electricity "reduced to comparative impotence without it" | CONFIRMED | Speech "Politics and Economics", 143rd Annual Banquet, Chamber of Commerce of the State of New York, 1911, pp. 43–55. Quote verbatim: "I weigh my words, when I say that in my judgment the limited liability corporation is the greatest single discovery of modern times…" | https://conversableeconomist.com/2017/07/27/the-limited-liability-corporation-is-the-greatest-single-discovery-of-modern-times/ |
| Easterbrook & Fischel, "Limited Liability and the Corporation," *U. Chi. L. Rev.* 1985 | CONFIRMED | **52 U. Chi. L. Rev. 89 (1985)** | https://chicagounbound.uchicago.edu/uclrev/vol52/iss1/3/ |
| Easterbrook & Fischel, *The Economic Structure of Corporate Law*, 1991 | CONFIRMED | Harvard University Press, 1991 | https://openlibrary.org/search.json?q=The+Economic+Structure+of+Corporate+Law+Easterbrook+Fischel |
| Hansmann & Kraakman, "The Essential Role of Organizational Law," *Yale L.J.* 2000 | CONFIRMED | **110 Yale L.J. 387 (2000)** | https://api.crossref.org/works?query.bibliographic=Essential+Role+of+Organizational+Law+Hansmann+Kraakman |
| Hansmann & Kraakman, "Toward Unlimited Shareholder Liability for Corporate Torts," *Yale L.J.* 1991 | CONFIRMED | **100 Yale L.J. 1879 (1991)** | https://api.crossref.org/works?query.bibliographic=Toward+Unlimited+Shareholder+Liability+for+Corporate+Torts+Hansmann+Kraakman |
| Micklethwait & Wooldridge, *The Company: A Short History of a Revolutionary Idea*, 2003 | CONFIRMED | Modern Library, 2003 (paperback 2005) | https://openlibrary.org/search.json?q=The+Company+Micklethwait+Wooldridge |
| UK Bubble Act 1720, repealed 1825 | CONFIRMED | Bubble Act 1720 (6 Geo. 1. c. 18), passed 11 June 1720; main repeal by the Bubble Companies etc. Act 1825; residue not repealed until 1901 (Royal Exchange Assurance Act 1901) — the standard "repealed 1825" is fine, the 1901 residue is a footnote | https://en.wikipedia.org/wiki/Bubble_Act |
| New York 1811 general limited-liability manufacturing statute, "called 'the world's first modern limited liability law'" | CONFIRMED (as an attributed description) | "The world's first modern limited liability law was enacted by the state of New York in 1811." The item's hedge ("called") is doing correct work — primacy claims of this kind are contested in the business-history literature (cf. Ron Harris), so keep the hedge | https://en.wikipedia.org/wiki/Limited_liability |
| UK Limited Liability Act 1855 | CONFIRMED | 18 & 19 Vict. c. 133, Royal Assent **14 August 1855** | https://en.wikipedia.org/wiki/Limited_Liability_Act_1855 |
| Joint Stock Companies Act 1856 | CONFIRMED | UK-wide; settled separate personality + limited liability for Scottish companies | same |
| Companies Act 1862 **extended to insurers** | CONFIRMED | Insurers were excluded from the 1855 Act; "Limited liability for insurance companies was allowed by the Companies Act 1862 (25 & 26 Vict. c. 89)" | same |
| *Salomon v A Salomon & Co Ltd* (1897), separate legal personality | CONFIRMED | [1896] UKHL 1, **[1897] AC 22**, House of Lords | https://en.wikipedia.org/wiki/Salomon_v_A_Salomon_%26_Co_Ltd |
| German GmbH statute 1892 | CONFIRMED | "The laws governing the GmbH were introduced in the German Empire in **1892**" | https://en.wikipedia.org/wiki/Gesellschaft_mit_beschr%C3%A4nkter_Haftung |
| UK Limited Liability Partnerships Act 2000 | CONFIRMED | c. 12; Royal Assent **20 July 2000**; main provisions in force **6 April 2001** | https://en.wikipedia.org/wiki/Limited_Liability_Partnerships_Act_2000 |
| City of Glasgow Bank failure **1878** ruined unlimited-liability shareholders | CONFIRMED | Closed **2 October 1878**; "The 1,200 shareholders and their families suffered greatly. Their liability was unlimited, and the failure ruined most of them." | https://en.wikipedia.org/wiki/City_of_Glasgow_Bank |
| …and "prompted the **Companies Act 1879** permitting banks to adopt limited/reserve liability" | CONFIRMED **from primary statute text** | Companies Act 1879 (42 & 43 Vict. c. 76), Royal Assent **15 August 1879**, long title: *"An Act to amend the Law with respect to the Liability of Members of Banking and other Joint Stock Companies; and for other purposes."* s.4 lets "any company registered … as an unlimited company … register … as a limited company"; s.5 is headed "Reserve capital of company, how provided" and provides that increased/uncalled capital "shall not be capable of being called up, except in the event of and for the purposes of the company being wound up." s.2 excepts the Bank of England. | https://www.legislation.gov.uk/ukpga/Vict/42-43/76/pdfs/ukpga_18790076_en.pdf |
| **U.S. national banks carried "double liability" 1863-1933 (abolished in the 1930s reforms)** | **IMPRECISE** | Imposed by the National Banking Act 1863 §12 ✓. Abolition was staged, not a 1933 event: Banking Act of 1933 §22 eliminated it **only for shares issued after 16 June 1933**; from **1935** national banks could terminate it on existing shares on six months' notice; full statutory abolition came **1953**. "1863-1933" overstates the 1933 Act. | https://en.wikipedia.org/wiki/Double_liability ; https://en.wikipedia.org/wiki/Banking_Act_of_1933 |
| **California's constitution imposed proportionate unlimited shareholder liability "from 1849 until 1931"** | **IMPRECISE (end date)** | Substance correct — 1849 Const. §36: "Each stockholder of a corporation, or joint-stock association, shall be individually and personally liable for his proportion of all its debts and liabilities"; carried into Art. XII §3 of the 1879 Constitution. But the constitutional provision was **repealed by amendment on 4 November 1930**; only the implementing Civil Code §322 repeal took effect 14 August 1931. | https://www.bainbridgeoncorporations.com/p/a-brief-history-of-limited-liability ; https://en.wikisource.org/wiki/The_Federal_and_State_Constitutions/Constitution_of_California%E2%80%941849 |
| **Lloyd's "Names" unlimited until the 1990s reconstruction (triggered by 1988-1992 asbestos/pollution losses) admitted limited-liability corporate capital** | **IMPRECISE (ordering)** | Substance correct: "The liability of the individual Names was unlimited, and thus all their personal wealth and assets were at risk." But limited-liability **corporate members were admitted in 1994**, which *preceded* the Reconstruction & Renewal plan (1995) and the transfer of pre-1993 liabilities to Equitas (September 1996). R&R did not itself admit corporate capital. | https://en.wikipedia.org/wiki/Lloyd%27s_of_London |
| American Express operated as an unlimited-liability joint-stock association until 1965 | CONFIRMED (existence of the phenomenon and the literature); 1965 date SUPPORTED but not independently pinned | The claim is the subject of two dedicated law-and-economics papers: Peter Z. Grossman, "The Market for Shares of Companies with Unlimited Liability: The Case of American Express," **24 J. Legal Stud. 63 (1995)**, and Mark I. Weinstein, "Don't Buy Shares without It: Limited Liability Comes to American Express," **37 J. Legal Stud. 189 (2008)**, DOI 10.1086/588261. The U. Chicago Press article page blocks automated fetch, so the specific year 1965 rests on the secondary literature rather than a page I could read. | https://api.crossref.org/works?query.bibliographic=Market+for+Shares+of+Companies+with+Unlimited+Liability+American+Express+Grossman |
| Naomi Lamoreaux + business-history scholarship (1990s-2000s) on persistence of partnership forms | CONFIRMED (attribution accurate) | e.g. Lamoreaux & Rosenthal, "Legal Regime and Business's Organizational Choice: A Comparison of France and the United States" (Feb 2004); Lamoreaux, "Business Organization," *Historical Statistics of the United States, Millennial Edition* | https://api.crossref.org/works?query.bibliographic=Lamoreaux+partnership+corporation+organizational+forms+nineteenth+century |
| Modigliani-Miller (1958) capital-structure irrelevance under frictionless markets | CONFIRMED | Modigliani, F. & Miller, M., "The Cost of Capital, Corporation Finance and the Theory of Investment," *American Economic Review* **48(3): 261–297 (1958)**; irrelevance holds only absent taxes, bankruptcy costs, agency costs, asymmetric information | https://en.wikipedia.org/wiki/Modigliani%E2%80%93Miller_theorem |
| Markowitz portfolio selection (1952) | CONFIRMED | Markowitz, H., "Portfolio Selection," *Journal of Finance* **7(1): 77–91 (1952)**, DOI 10.1111/j.1540-6261.1952.tb01525.x | https://api.crossref.org/works?query.bibliographic=Portfolio+Selection+Markowitz+Journal+of+Finance+1952 |
| **"Murray Rothbard's position that liability for torts should be full/unlimited"** | **UNVERIFIABLE** (and probably mischaracterised) | Tried: mises.org book landing pages for *Power and Market* and *Man, Economy, and State* (no substantive text served); the *Power and Market* CDN PDF (HTTP 403); the *Journal of Libertarian Studies* 19(3) article on the corporation (extracted full text — contains **no mention of Rothbard**); two search-proxy attempts (CAPTCHA / 403); WebSearch budget exhausted. Substantive caution: Rothbard is conventionally read as a *defender* of limited liability to voluntary creditors as a purely contractual arrangement, while holding that tort liability cannot be contracted away. Filing him under "critical literature [that] argues limited liability enables negative corporate externalities" inverts his overall stance even if the tort half is right. | https://cdn.mises.org/19_3_3.pdf (checked, no Rothbard) |
| `hard_rules[1]`: "early UK railways and canals were built under charter with unlimited or ambiguous liability" | UNVERIFIABLE in detail | Tried: Companies Clauses Consolidation Act 1845 page (no liability detail served); WebSearch exhausted. Directional caution: pre-1845 UK canal/railway companies were incorporated by individual private Act, each setting its own liability terms, so "unlimited **or ambiguous**" is defensible as a hedge but would be wrong as a blanket "unlimited". The hedge should stay. | https://en.wikipedia.org/wiki/Companies_Clauses_Consolidation_Act_1845 |

### Exact replacements for `C2_economics_business_08`

`known_answers[6]`, three separate edits:

1. **Double liability**
   - OLD: `U.S. national banks carried 'double liability' 1863-1933 (abolished in the 1930s reforms)`
   - NEW: `U.S. national banks carried 'double liability' from the National Banking Act 1863 until the New Deal banking reforms wound it down in stages (Banking Act of 1933 s.22 ended it for shares issued after 16 June 1933; national banks could terminate it on existing shares from 1935; full statutory abolition 1953)`

2. **California**
   - OLD: `California's constitution imposed proportionate unlimited shareholder liability from 1849 until 1931`
   - NEW: `California's constitution imposed proportionate unlimited shareholder liability from 1849 (Const. 1849 s.36, carried into Art. XII s.3 of the 1879 Constitution) until the amendment repealing it was adopted 4 November 1930, with the implementing Civil Code s.322 repeal effective 14 August 1931`

3. **Lloyd's**
   - OLD: `Lloyd's of London 'Names' bore unlimited personal liability until the 1990s reconstruction (triggered by 1988-1992 asbestos/pollution losses) admitted limited-liability corporate capital`
   - NEW: `Lloyd's of London 'Names' bore unlimited personal liability until the asbestos/pollution (APH) losses of the 1988-1992 years of account forced limited-liability corporate members to be admitted in 1994, followed by the Reconstruction & Renewal plan (1995) and the transfer of all pre-1993 liabilities to Equitas in September 1996`

`known_answers[9]` — Rothbard:

- OLD: `Critical literature argues limited liability enables negative corporate externalities through risk-shifting (e.g., Murray Rothbard's position that liability for torts should be full/unlimited); the aggregate magnitude of these externalities is contested and not precisely quantified in the literature.`
- NEW: `Critical literature argues limited liability enables negative corporate externalities through risk-shifting; a distinct libertarian strand (e.g. Rothbard) instead accepts owner-shielding as a contractual matter between the firm and its VOLUNTARY creditors while denying that tort liability to third parties can be contracted away. Either way, the aggregate magnitude of these externalities is contested and not precisely quantified in the literature.`

(Or simply drop the Rothbard parenthetical. It is the only remaining attribution in the item
that I could not source to a document, and it sits in the same sentence as the hedge left
behind by the prior removal — the same failure signature as the "Edward Cox 1855" reference.)

---

## 5. `C2_arts_humanities_11` — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| Panofsky 1927, *Perspective as Symbolic Form* | CONFIRMED | "Die Perspektive als 'symbolische Form'," lecture 31 Jan 1925, printed in *Vorträge der Bibliothek Warburg 1924–1925* (1927), pp. 258–330; Eng. Zone Books 1991. Argument verified in the translation: perspective as "one of those 'symbolic forms'"; perspectival space "infinite, unchanging and homogeneous"; vanishing point as "the concrete symbol for the discovery of the infinite itself". Minor: delivered 1925, printed 1927 — both dates circulate. | https://archive.org/details/ErwinPanofskyPerspectiveAsSymbolicForm |
| Andersen, *The Geometry of an Art* | CONFIRMED | Kirsti Andersen, *The Geometry of an Art: The History of the Mathematical Theory of Perspective from Alberti to Monge*, Springer 2007 | https://link.springer.com/book/10.1007/978-0-387-48946-9 |
| Field, *The Invention of Infinity* | CONFIRMED | J. V. Field, *The Invention of Infinity: Mathematics and Art in the Renaissance*, OUP 1997 | https://doi.org/10.1093/oso/9780198523949.001.0001 |
| **"Kepler (1604) and Desargues (c.1639) introduced the point at infinity"** | **IMPRECISE** | Kepler's *Ad Vitellionem paralipomena* (1604) posits the parabola's second focus as a *caecus focus* at infinity — the earliest known use of a point at infinity, but as a limiting-case device for **one conic**, plus an early principle of continuity. The **general** projective point at infinity is Desargues (1639). | https://en.wikisource.org/wiki/1911_Encyclop%C3%A6dia_Britannica/Geometrical_Continuity ; https://mathshistory.st-andrews.ac.uk/Biographies/Kepler/ |
| Desargues c. 1639 | CONFIRMED | *Brouillon project d'une atteinte aux evenemens des rencontres du Cone avec un Plan*, Paris 1639 | https://mathshistory.st-andrews.ac.uk/Biographies/Desargues/ |
| Monge, descriptive geometry, late 18th c. | CONFIRMED | Method devised c. 1765–66 at Mézières; taught at École Polytechnique from 9 Nov 1794; *Géométrie descriptive* 1799 | https://mathshistory.st-andrews.ac.uk/Biographies/Monge/ |
| Poncelet's 1822 treatise founded modern projective geometry | CONFIRMED | *Traité des propriétés projectives des figures*, 1822 | https://mathshistory.st-andrews.ac.uk/Biographies/Poncelet/ |
| **Camera obscura "known since antiquity (Mozi, Aristotle, Alhazen)"** | **IMPRECISE** | Mozi ✓ (4th c. BC); Ibn al-Haytham ✓ (*On the Shape of the Eclipse*, first experimental analysis; *Book of Optics* c. 1027). The pinhole/crescent observation attributed to Aristotle is in the **pseudo-Aristotelian *Problemata* Book XV**, a Peripatetic compilation of doubted authenticity, final form anywhere from the 3rd c. BC to the 6th c. AD. | https://en.wikipedia.org/wiki/Camera_obscura ; https://en.wikipedia.org/wiki/Problems_(Aristotle) |
| Hockney-Falco thesis; Hockney *Secret Knowledge* 2001; contested | CONFIRMED | *Secret Knowledge: Rediscovering the Lost Techniques of the Old Masters*, 2001 (2nd ed. 2006); co-proponent Charles M. Falco from March 2000; contested by art historians and by David G. Stork on optical-distortion grounds | https://en.wikipedia.org/wiki/Hockney%E2%80%93Falco_thesis |
| Byzantine "reverse/inverse perspective" | CONFIRMED | Established term (also inverse/inverted/divergent perspective); canonical treatment Pavel Florensky, "Reverse Perspective" (1919) | https://en.wikipedia.org/wiki/Reverse_perspective |
| **"(Alberti, Leonardo's paragone)"** | **IMPRECISE** | Alberti solid: *De pictura* (1435), first written description of the linear-perspective construction. But *paragone* is the art-historical **label** for the Renaissance painting-vs-sculpture debate, crystallising with Varchi's 1546 solicitation of artists' views — not Leonardo's own coinage. Leonardo's arguments survive in the posthumously compiled *Trattato della pittura* / Codex Urbinas. | https://en.wikipedia.org/wiki/Paragone ; https://en.wikipedia.org/wiki/De_pictura |
| **"Foreshortening … predate and are independent of the vanishing-point construction (e.g. Melozzo da Forli, Roman fresco)"** | **WRONG (the Melozzo half)** | Melozzo da Forlì is c. 1438–1494; his *di sotto in sù* works (Santi Apostoli vault c. 1472–74; *Sixtus IV Appointing Platina* 1477; Loreto cupola after 1484) postdate Brunelleschi's panels (c. 1415–20) and Alberti's *De pictura* (1435) by **two generations** and sit **inside** the perspective tradition. He cannot evidence "predates and is independent of". The Roman-fresco half is fine: Villa of P. Fannius Synistor (1st c. BC) uses "multiple vanishing points … in a systematic but not fully consistent manner". | https://en.wikipedia.org/wiki/Melozzo_da_Forl%C3%AC ; https://en.wikipedia.org/wiki/Perspective_(graphical) |
| Skenographia (5th c. BC) and Euclid's *Optics* (c. 300 BC) treated apparent size without a general vanishing point | CONFIRMED (hedge the inventor) | Vitruvius credits **Agatharchus of Samos** with inventing scene painting for an Aeschylus tragedy, with Democritus and Anaxagoras building on his treatise; but Aristotle's *Poetics* instead credits Sophocles — so "attributed inventor" should stay hedged. Euclid's *Optics* c. 300 BC: visual-cone propositions on apparent size, and prop. 8 explicitly **denies** simple proportionality of perceived size to distance; no general vanishing-point construction. | https://en.wikipedia.org/wiki/Agatharchus ; https://en.wikipedia.org/wiki/Euclid%27s_Optics |
| Le Nôtre at Versailles; Baroque quadratura; illusionistic proscenium | CONFIRMED | André Le Nôtre (1613–1700), Versailles gardens from 1661, documented forced perspective. *Quadratura* correct for illusionistic feigned-architecture ceilings: Lanfranco (Sant'Andrea della Valle 1625–27), Pietro da Cortona (Palazzo Barberini 1633–39), Pozzo (Sant'Ignazio 1691–94) | https://en.wikipedia.org/wiki/Andr%C3%A9_Le_N%C3%B4tre ; https://en.wikipedia.org/wiki/Quadratura |
| Brunelleschi peephole demonstration; Alberti; Piero | CONFIRMED | Two lost panels c. 1415–1420 (Florence Baptistery; Palazzo Vecchio), viewed through a bored hole against a mirror; known via Antonio Manetti's *Vita di Filippo Brunelleschi*. Piero della Francesca, *De prospectiva pingendi*, mid-1470s–1480s. Note the item's `query` says "no Brunelleschi peephole demonstration", consistent. | https://en.wikipedia.org/wiki/Filippo_Brunelleschi ; https://en.wikipedia.org/wiki/De_prospectiva_pingendi |
| Camera obscura independent of pictorial perspective ⇒ photography still possible | CONFIRMED | | https://en.wikipedia.org/wiki/Camera_obscura |
| Chinese oblique/parallel projection, ukiyo-e, Persian miniature as counter-examples | CONFIRMED (standard) | | https://en.wikipedia.org/wiki/Perspective_(graphical) |
| 20th-c. modernism (Cézanne, Cubism, abstraction) abandoned single-point perspective | CONFIRMED | "Linear perspective developed during the Renaissance was vacated"; Cubist "simultaneity"; Cézanne's plural viewpoint as precursor | https://en.wikipedia.org/wiki/Cubism |
| `expert_baseline`: "~400-year painterly rehearsal" | CONFIRMED | Alberti 1435 → Daguerre 1839 = 404 yr; full plausible range 391–426 (Brunelleschi c. 1415–20 / Alberti 1435 → Niépce 1826 / Daguerre 1839) | https://en.wikipedia.org/wiki/History_of_photography |
| `expert_baseline`: stereotomy, fortification, gnomonics could regenerate descriptive geometry | CONFIRMED | Stereotomy: "Descriptive geometry can be considered as an evolution of stereotomy"; its canonical text (Frézier 1737–39) was written by a career **fortification** engineer. Gnomonics = sundial design, i.e. projection of the celestial sphere onto inclined planes. Monge's first discoveries (1765) came from a **fortification defilement** problem at Mézières. | https://en.wikipedia.org/wiki/Stereotomy_(descriptive_geometry) ; https://en.wikipedia.org/wiki/Gnomonics ; https://en.wikipedia.org/wiki/Descriptive_geometry |

### Exact replacements for `C2_arts_humanities_11`

1. `known_answers[8]` — the substantive fix:
   - OLD: `(e.g. Melozzo da Forli, Roman fresco)`
   - NEW: `(e.g. Roman fresco such as the Villa of P. Fannius Synistor, 1st c. BC, which uses multiple inconsistent vanishing points; Ambrogio Lorenzetti's convergent-line floor in the Presentation at the Temple, 1342)`

2. `known_answers[2]` — Kepler precision:
   - OLD: `Kepler (1604) and Desargues (c.1639) introduced the point at infinity`
   - NEW: `Kepler (1604) introduced a point at infinity as a limiting-case device for the parabola and Desargues (c.1639) the general projective point at infinity`

3. `known_answers[3]` — Aristotle precision:
   - OLD: `known since antiquity (Mozi, Aristotle, Alhazen)`
   - NEW: `known since antiquity (Mozi, 4th c. BC; the pseudo-Aristotelian Problemata; Ibn al-Haytham/Alhazen, early 11th c.)`

4. `known_answers[6]` — paragone precision:
   - OLD: `(Alberti, Leonardo's paragone)`
   - NEW: `(Alberti's De pictura, 1435; Leonardo's arguments in the posthumous Trattato della pittura, conventionally grouped under the paragone debate)`

---

## 6. `C2_biology_medicine_06` — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| SCID / David Vetter (1971-1984) | CONFIRMED | b. 21 Sep 1971, d. 22 Feb 1984 | https://en.wikipedia.org/wiki/David_Vetter |
| 2011 Nobel to Beutler, Hoffmann, Steinman | CONFIRMED | Half jointly Beutler & Hoffmann "for their discoveries concerning the activation of innate immunity"; half Steinman for the dendritic cell. Hoffmann's *Drosophila* Toll work correctly attributed. | https://www.nobelprize.org/prizes/medicine/2011/press-release/ |
| "roughly 97% of animal species (all invertebrates)" | CONFIRMED (defensible, don't harden) | 97% is citable (May RM, *Science* 1988;241:1441-9) but ~95% is at least as common in textbooks; the value is an artifact of the total-species estimate chosen. | https://en.wikipedia.org/wiki/Invertebrate |
| Trained immunity, Netea et al. 2011 onward; BCG heterologous protection | CONFIRMED | Netea MG, Quintin J, van der Meer JWM, "Trained immunity: a memory for innate host defense," *Cell Host Microbe* 2011;9(5):355-61 (PMID 21575907). BCG: Kleinnijenhuis et al., *PNAS* 2012;109(43):17537-42 — NOD2-dependent, epigenetic monocyte reprogramming, protective **in lymphocyte-deficient mice** | https://pubmed.ncbi.nlm.nih.gov/21575907/ ; https://pubmed.ncbi.nlm.nih.gov/22988082/ |
| **VLRs in "lamprey/hagfish" — Pancer & Cooper et al., *Nature* 2004** | **IMPRECISE** | The 2004 paper is **sea lamprey only**: Pancer Z, Amemiya CT, Ehrhardt GRA, Ceitlin J, Gartland GL, Cooper MD, "Somatic diversification of variable lymphocyte receptors in the agnathan sea lamprey," *Nature* 2004 Jul 8;430(6996):174-80. LRR-based / non-immunoglobulin ✓. **Hagfish VLRs are a separate paper**: Pancer et al., *PNAS* 2005;102(26):9224-9. | https://pubmed.ncbi.nlm.nih.gov/15241406/ ; https://pubmed.ncbi.nlm.nih.gov/15964979/ |
| **"Burnet-Thomas hypothesis (1957)"** | **IMPRECISE** | 1957 is Burnet only: Burnet M, "Cancer; a biological approach. I," *Br Med J* 1957;1(5022):779-86. Lewis Thomas's contribution is standardly dated **1959** (discussion in Lawrence HS ed., *Cellular and Humoral Aspects of the Hypersensitive States*, pp. 529-32). | https://pubmed.ncbi.nlm.nih.gov/13404306/ |
| 2002 Nature Immunology immunoediting paper | CONFIRMED | Dunn GP, Bruce AT, Ikeda H, Old LJ, Schreiber RD, *Nat Immunol* 2002;3(11):991-8 | https://pubmed.ncbi.nlm.nih.gov/12407406/ |
| **"Dunn, Old & Schreiber formalization (… Science 2011)"** | **WRONG** | The 2011 *Science* paper has **no Dunn**: Schreiber RD, Old LJ, Smyth MJ, "Cancer immunoediting: integrating immunity's roles in cancer suppression and promotion," *Science* 2011;331(6024):1565-70 | https://pubmed.ncbi.nlm.nih.gov/21436444/ |
| Allison & Honjo, 2018 Nobel | CONFIRMED | "for the discovery of cancer therapy by inhibition of negative immune regulation" | https://en.wikipedia.org/wiki/James_P._Allison |
| Selective (not uniform) cancer excess in adaptive-immunodeficient hosts | CONFIRMED (standard) | | https://pubmed.ncbi.nlm.nih.gov/21436444/ |
| **"regulatory T-cell expansion (Aluvihare/Betz/Rudensky, Nature Immunology 2004)"** | **WRONG** | **Rudensky is not an author.** Actual: Aluvihare VR, **Kallikourdis M**, Betz AG, "Regulatory T cells mediate maternal tolerance to the fetus," *Nat Immunol* 2004;5(3):266-71 (PMID 14758358, doi 10.1038/ni1037). Rudensky's maternal-fetal work is later and mechanistically different: Samstein RM et al., "Extrathymic generation of regulatory T cells in placental mammals mitigates maternal-fetal conflict," *Cell* 2012;150(1):29-38 (CNS1 enhancer). | https://pubmed.ncbi.nlm.nih.gov/14758358/ ; https://pubmed.ncbi.nlm.nih.gov/22770213/ |
| IDO-mediated tryptophan catabolism (Munn & Mellor, *Science* 1998) | CONFIRMED | Munn DH, Zhou M, Attwood JT, Bondarev I, Conway SJ, Marshall B, Brown C, Mellor AL, "Prevention of allogeneic fetal rejection by tryptophan catabolism," *Science* 1998;281(5380):1191-3. First author Munn, senior author Mellor — exactly as claimed. | https://pubmed.ncbi.nlm.nih.gov/9712583/ |
| trophoblast HLA-G | CONFIRMED (standard) | | https://pubmed.ncbi.nlm.nih.gov/9712583/ |
| **"IgE-mediated type-I hypersensitivity (Ishizaka, 1966)"** | **IMPRECISE** | 1966 is right for the Ishizakas' identification of the reagin-carrying immunoglobulin (Ishizaka K, Ishizaka T, Hornbrook MM, *J Immunol* 1966;97(1):75-85), but IgE was **co-discovered independently** by Johansson & Bennich (Uppsala, 1967) and the name "IgE" was fixed by a joint 1968 paper. "Ishizaka, 1966" alone drops the Swedish group. | https://pubmed.ncbi.nlm.nih.gov/4162440/ ; https://en.wikipedia.org/wiki/Immunoglobulin_E |
| Medawar acquired tolerance (1940s-50s; 1960 Nobel) | CONFIRMED | 1960 Nobel shared with Frank Macfarlane Burnet "for discovery of acquired immunological tolerance"; primary work Billingham, Brent & Medawar, *Nature* 1953 | https://en.wikipedia.org/wiki/Peter_Medawar |
| Herd immunity concept, 1920s-30s | CONFIRMED (dating nuance) | Concept traces to Topley & Wilson (1923, experimental mouse epidemics) and Hedrich's 1930s Baltimore measles data. Nuance: the *phrase* first appears in 1894 veterinary usage. Canonical history: Fine PEM, *Epidemiol Rev* 1993;15(2):265-302. | https://pubmed.ncbi.nlm.nih.gov/8174658/ |
| Influenza antigenic drift/shift, original antigenic sin presuppose antibody | CONFIRMED (standard) | | https://en.wikipedia.org/wiki/Herd_immunity |
| Peto's paradox (Peto, 1975) | CONFIRMED | Peto R, Roe FJC, Lee PN, Levy L, Clack J, "Cancer and ageing in mice and men," *Br J Cancer* 1975;32(4):411-26. Caulin & Maley themselves cite this 1975 paper as the paradox's origin, so **1975 is not an error**. | https://pubmed.ncbi.nlm.nih.gov/1212409/ |
| Caulin & Maley, *TREE* 2011 | CONFIRMED | "Peto's Paradox: evolution's prescription for cancer prevention," *Trends Ecol Evol* 2011;26(4):175-82 | https://pmc.ncbi.nlm.nih.gov/articles/PMC3060950/ |
| Latent herpesvirus (EBV/CMV) control is strongly CD8-dependent | CONFIRMED | Riddell et al., *Science* 1992;257:238-41; Walter et al., *NEJM* 1995;333:1038-44; Rooney et al., *Lancet* 1995;345:9-13 | https://pubmed.ncbi.nlm.nih.gov/1352912/ |

### Exact replacements for `C2_biology_medicine_06`

1. `known_answers[5]` — **hard citation error, highest priority**:
   - OLD: `regulatory T-cell expansion (Aluvihare/Betz/Rudensky, Nature Immunology 2004)`
   - NEW: `regulatory T-cell expansion (Aluvihare, Kallikourdis & Betz, Nature Immunology 2004; and Samstein et al., Cell 2012, for the placental-mammal-specific CNS1 enhancer)`

2. `known_answers[4]` — **hard citation error**:
   - OLD: `Burnet-Thomas hypothesis (1957); Dunn, Old & Schreiber formalization (Nature Immunology 2002; Science 2011)`
   - NEW: `Burnet-Thomas immunosurveillance hypothesis (Burnet 1957; Thomas 1959); formalization by Dunn, Bruce, Ikeda, Old & Schreiber (Nature Immunology 2002) and Schreiber, Old & Smyth (Science 2011)`

3. `known_answers[3]`:
   - OLD: `jawless vertebrates (lamprey/hagfish) - Pancer & Cooper et al., Nature 2004`
   - NEW: `jawless vertebrates - Pancer & Cooper et al., Nature 2004 (sea lamprey) and PNAS 2005 (hagfish)`

4. `known_answers[1]` — soften the statistic:
   - OLD: `roughly 97% of animal species (all invertebrates) persist on innate immunity only`
   - NEW: `roughly 95-97% of animal species (all invertebrates) persist on innate immunity only`

5. Optional, `known_answers[6]`:
   - OLD: `IgE-mediated type-I hypersensitivity (Ishizaka, 1966)`
   - NEW: `IgE-mediated type-I hypersensitivity (Ishizaka & Ishizaka 1966; independently Johansson & Bennich 1967; class named IgE 1968)`

---

## 7. `C2_materials_chemistry_07` (no-crystallinity world) — full claim table

Seventeen `known_answers` entries, almost all textbook condensed-matter facts. This is the
best-sourced item in C2: **no wrong facts**, one attribution slip, two range quibbles.

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| Crystals have long-range periodic order; glasses only short-range | CONFIRMED (definitional) | | https://en.wikipedia.org/wiki/Amorphous_solid |
| X-ray crystallography needs a periodic lattice; DNA helix from fibre diffraction; non-crystalline methods are cryo-EM, NMR, PDF/EXAFS | CONFIRMED (textbook) | | https://en.wikipedia.org/wiki/X-ray_crystallography |
| "a-Si:H has low electron mobility (~1 cm2/V.s)" | CONFIRMED (needs a one-word qualifier) | ~1 cm²/V·s is correct for the **drift / field-effect** mobility, which is the device-relevant number (TOF drift mobility at 320 K ≈ 1). The *extended-state (band)* mobility is much higher — 10–20 cm²/V·s classically, ~46 in a 2024 reanalysis. Add "field-effect" or "drift" and it is airtight | https://pubs.aip.org/aip/apl/article/50/15/983/52295 ; https://arxiv.org/abs/2408.03678 |
| **"a-IGZO … (Hosono et al. 2004), reach mobility ~10 cm2/V.s (roughly 10x a-Si:H)"** | CONFIRMED (figure) / **IMPRECISE (attribution)** | Figure verified **verbatim** in the paper: "Hall effect mobilities exceeding 10 cm² V⁻¹ s⁻¹, which is an order of magnitude larger than for hydrogenated amorphous silicon." But the paper is conventionally cited **Nomura et al. 2004** — Nomura K, Ohta H, Takagi A, Kamiya T, Hirano M, **Hosono H**, "Room-temperature fabrication of transparent flexible thin-film transistors using amorphous oxide semiconductors," *Nature* **432**(7016):488–492 (2004). Hosono is last/corresponding author. (TFT *saturation* mobility in that paper was 6–9 cm²/V·s) | https://www.nature.com/articles/nature03090 ; https://pubmed.ncbi.nlm.nih.gov/15565150/ |
| LEDs/laser diodes need crystalline direct-gap semiconductors; amorphous shows Urbach tails, localized states below a mobility edge | CONFIRMED (textbook) | | https://en.wikipedia.org/wiki/Urbach_energy |
| Zeolites/MOFs shape-selective; FCC and xylene isomerization use zeolites | CONFIRMED (textbook) | | https://doi.org/10.1039/C5CS00376H |
| "Amorphous silica-alumina was the pre-zeolite cracking catalyst and is far less shape-selective" | CONFIRMED | "The original FCC catalyst contained clay, and later amorphous silica-alumina and silica-magnesia were used, before zeolite-based catalytic cracking was adopted in the early 1960s." ASA has broad pore-size distribution, no molecular-sieve selectivity; it survives in modern FCC as the *active matrix* pre-cracking molecules too large for zeolite pores | https://link.springer.com/article/10.1007/s11814-016-0327-8 |
| "Bulk metallic glasses (e.g. Zr-based Vitreloy) … high yield strength, large elastic limit, poor tensile ductility, localized shear banding, negligible work hardening" | CONFIRMED | ~2 GPa strength, ~2% elastic limit, essentially zero tensile ductility ("fracture instantly upon yielding"), deformation localized into shear bands, strain-**softening** rather than work hardening. Vitreloy 1 = Zr₄₁.₂Ti₁₃.₈Cu₁₂.₅Ni₁₀Be₂₂.₅ (Caltech 1992) — Zr-based as stated | https://pmc.ncbi.nlm.nih.gov/articles/PMC3996486/ ; https://en.wikipedia.org/wiki/Amorphous_metal |
| "Nd2Fe14B and SmCo derive coercivity from high magnetocrystalline anisotropy; Fe-based metglas is magnetically SOFT, used in low-loss transformer cores" | CONFIRMED including the formula | Hard phase is the tetragonal **Nd₂Fe₁₄B** intermetallic; coercivity in SmCo₅ and Nd₂Fe₁₄B from high magnetocrystalline anisotropy (4f crystal-field + spin-orbit). Fe-based amorphous Metglas (2605SA1, 2605HB1M) is soft and cuts distribution-transformer no-load loss to ~⅓ of grain-oriented silicon steel | https://www3.aps.anl.gov/haskel/PS/ndfeb.pdf ; https://metglas.com/distribution-transformer-electrical-steel/ |
| Piezo/pyro/ferroelectricity require non-centrosymmetric crystals; quartz oscillators; poled PVDF/glass as substitutes | CONFIRMED (textbook) | | https://en.wikipedia.org/wiki/Piezoelectricity |
| "layered LiCoO2, spinel LiMn2O4, olivine LiFePO4" | CONFIRMED (all three) | LiCoO₂ layered (2-D Li diffusion), LiMn₂O₄ spinel (3-D), LiFePO₄ olivine (1-D channels). Minor: Wikipedia files LiFePO₄ under the broader "polyanion" label, but "olivine" is the standard structure-type name in the battery literature | https://en.wikipedia.org/wiki/Lithium-ion_battery |
| Single-crystal Ni-base superalloy turbine blades eliminate grain boundaries to resist creep | CONFIRMED (textbook) | | https://en.wikipedia.org/wiki/Superalloy |
| "Crystalline ice Ih (~0.917 g/cm3) … LDA ~0.94 … HDA ~1.17" | CONFIRMED (HDA is the top of its range) | Ice Ih 0.917 g/cm³ at 0 °C vs liquid water 0.9998 ✓. LDA ≈ 0.94 ✓. **HDA is standardly quoted as 1.15–1.17 g/cm³**, so "~1.17" is the range top rather than the central value. Also: medium-density amorphous ice (MDA, ~1.06 g/cm³) was reported in 2023, so the binary LDA/HDA framing is now slightly dated | https://pmc.ncbi.nlm.nih.gov/articles/PMC10879119/ |
| "Conventional BCS superconductivity occurs in some amorphous/disordered metals" | CONFIRMED | Amorphous MoGe — "a typical type-II superconductor and follows the conventional Bardeen-Cooper-Schrieffer (BCS) equation"; amorphous ReZr — "conventional strong coupling Type II"; quench-condensed amorphous Bi superconducts at Tc = 6.1 K vs **0.53 mK** for crystalline Bi (disorder *helps*) | https://arxiv.org/abs/2402.00387 ; https://link.aps.org/doi/10.1103/PhysRev.147.384 |
| NLO/EO crystals (KDP, LiNbO3, BBO, KTP); silica fibre is a glass carrying the internet via χ(3), χ(2) only by poling | CONFIRMED (textbook) | | https://en.wikipedia.org/wiki/Nonlinear_optics |
| "some amorphous nanostructures (e.g. certain bird feathers) produce non-iridescent structural color" | CONFIRMED, researchers named | Noh H, Liew SF, Saranathan V, **Prum RO**, Mochrie SGJ, **Dufresne ER**, Cao H, "How noniridescent colors are generated by quasi-ordered structures of bird feathers," *Advanced Materials* 22 (2010) / arXiv:0912.4487. Mechanism: isotropic short-range-ordered β-keratin/air nanostructure ⇒ "colors … invariant with the viewing angle" | https://arxiv.org/abs/0912.4487 |
| Bloch's theorem / band structure / Brillouin zones presuppose periodicity; disorder described by Anderson localization, mobility edges, Mott | CONFIRMED (textbook) | | https://en.wikipedia.org/wiki/Bloch%27s_theorem |

### Exact replacements for `C2_materials_chemistry_07`

1. `known_answers[4]` — attribution:
   - OLD: `a-IGZO (indium-gallium-zinc-oxide, Hosono et al. 2004)`
   - NEW: `a-IGZO (indium-gallium-zinc-oxide, Nomura et al., Nature 432, 488 (2004), from Hosono's group)`

2. `known_answers[3]` — mobility type (optional but recommended, since `hard_rules[3]` makes retained-fact accuracy invalidating):
   - OLD: `hydrogenated amorphous silicon (a-Si:H) has low electron mobility (~1 cm2/V.s)`
   - NEW: `hydrogenated amorphous silicon (a-Si:H) has low electron field-effect/drift mobility (~1 cm2/V.s)`

3. `known_answers[12]` — HDA range (optional):
   - OLD: `high-density (HDA, ~1.17 g/cm3) forms`
   - NEW: `high-density (HDA, ~1.15-1.17 g/cm3) forms (with medium-density MDA, ~1.06 g/cm3, reported 2023)`

---

## 8. `C2_materials_chemistry_35` (non-protective Al oxide) — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| "aluminum's … Pilling-Bedworth ratio ~1.3" | CONFIRMED | Al/Al₂O₃ PBR = **1.28**, inside the 1 < R_PB < 2 passivating window | https://en.wikipedia.org/wiki/Pilling%E2%80%93Bedworth_ratio |
| "The real Al2O3 film is ~4 nm, dense, adherent, self-healing" | CONFIRMED (upper end of the range) | Literature: **~2–4 nm** for air-formed native oxide, growing to ~5 nm after years of exposure; some sources give 2–10 nm for aged/humid surfaces. Growth is self-limiting (inverse-logarithmic kinetics); the film is amorphous, dense and adherent | https://www.sciencedirect.com/science/article/abs/pii/S0169433215011617 ; https://en.wikipedia.org/wiki/Passivation_(chemistry) |
| "Iron's oxide is flaky and non-protective, so iron rusts progressively" | CONFIRMED (with a mechanism caveat) | Fe₂O₃ PBR = **2.14** (Fe₃O₄ = 1.90, FeO = 1.7); R_PB > 2 means the oxide "chips off and provides no protective effect." Caveat worth knowing: PBR is a crude criterion — iron scale is really non-protective because it grows fast via high cation diffusivity in porous FeO and spalls under compressive growth stress in a multilayer FeO/Fe₃O₄/Fe₂O₃ stack; two of the three oxides have PBR < 2 yet still aren't protective | https://en.wikipedia.org/wiki/Pilling%E2%80%93Bedworth_ratio |
| "Anodizing works by deliberately thickening aluminum's protective oxide" | CONFIRMED | | https://en.wikipedia.org/wiki/Anodizing |
| "Sapphire and ruby are stable crystalline bulk Al2O3; divergence is the surface film only" | CONFIRMED | | https://en.wikipedia.org/wiki/Corundum |
| **`query` + `expert_baseline`: "the 1960s beverage-can revolution"** | **IMPRECISE** | Invention precedes the 1960s: the first all-aluminum beverage can was **1958** (Hawaii Brewing, Primo beer — a commercial flop); **Coors, 22 January 1959** brought the 7-oz all-aluminum can mainstream. The genuine 1960s inflection is the *adoption ramp*: Reynolds' drawn-and-ironed two-piece can (**1963**) became the industry standard, Schlitz aluminum pull-tab (1963), 40% of US beer cans had aluminum tops by end-1963 and 80% by 1968, Coca-Cola and PepsiCo adopted 1967. Steel was not actually displaced until the 1980s–90s (shipments 0.5 B in 1965 → 8.5 B in 1972; today ~95%+ aluminum) | https://www.lightmetalage.com/news/industry-news/applications-design/60-years-of-the-aluminum-can/ |
| Overhead transmission conductors are predominantly aluminum (ACSR etc.); aluminum displaced copper | CONFIRMED (the "when" is weakly sourced) | ACSR is "the most common conductor in use for transmission today," with AAAC also common; aluminum wins on ~half the weight of equal-resistance copper plus lower cost; copper "was more popular in the past and is still in use, especially at lower voltages and for grounding." Trade sources put ACSR development in the **early 1900s**, spurred by wartime copper demand (ACSS 1970s; composite-core ACCC/ACCR early 2000s). No scholarly source pins a crossover year — treat "early 20th century" as approximate | https://en.wikipedia.org/wiki/Overhead_power_line |
| Sacrificial anodes, aluminized coatings, aluminum fuel powders exist and behave as described | CONFIRMED (real technologies) | Aluminum-alloy sacrificial anodes, hot-dip/spray aluminizing, and aluminum powder as a solid-rocket/thermite fuel are all standard | https://en.wikipedia.org/wiki/Galvanic_anode |
| Direct substitution to steel/titanium/composites; higher lifecycle cost | CONFIRMED (trivially, and correctly labelled "obvious") | | — |

### Exact replacement for `C2_materials_chemistry_35`

`expert_baseline`:

- OLD: `aborts the 1960s beverage-can revolution`
- NEW: `aborts the aluminum beverage can (first all-aluminum can 1958-59; the 1963 drawn-and-ironed two-piece can drove 1960s adoption, with steel fully displaced only by the 1980s-90s)`

(The `query` also says "the beverage-can and packaging industry" without a date, which is fine.
Only the `expert_baseline` carries the "1960s" dating.)

---

## 9. `C2_biology_medicine_34` (non-enucleated red cells) — full claim table

Only nine `known_answers` entries, all short and undated — no papers cited, so no fabrication
risk. But three of them are stated as absolutes that the comparative literature contradicts,
and one of those (`known_answers[9]`) is load-bearing for the item's malaria/apoptosis thread.

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| `query`: mammalian RBCs evolved enucleation; mature mammalian erythrocytes lose nucleus **and mitochondria** | CONFIRMED for the adult definitive lineage; IMPRECISE as an absolute | Enucleation of definitive erythrocytes is universal in mammals, and mammals are the only vertebrate class with anucleate mature RBCs; mitochondria, Golgi and ER are also lost ✓. **But nucleated erythrocytes circulate normally in mammalian embryos/fetuses** (large "primitive" erythroblasts), and appear in neonates and in pathological states — so the claim holds only of the adult definitive lineage | https://en.wikipedia.org/wiki/Red_blood_cell ; Newton et al., *J Cell Sci* 2024;137(19):jcs261673 |
| "Nucleated cells hold less hemoglobin per cell volume, lowering per-cell oxygen capacity" | CONFIRMED with numbers | Human MCHC 32–36 g/dL vs broiler chicken (Ross 308) **MCHC 22.9–27.2 g/dL** — avian RBCs are ~25–30% *lower* in hemoglobin concentration | https://pmc.ncbi.nlm.nih.gov/articles/PMC12289124/ ; https://en.wikipedia.org/wiki/Mean_corpuscular_hemoglobin_concentration |
| "A rigid nucleus makes erythrocytes larger and stiffer" | "larger" CONFIRMED; **"stiffer" UNVERIFIABLE** | Larger ✓: human MCV 80–100 fL vs chicken **MCV 123.6–151.6 fL** (~1.5×). Stiffer: no measured comparative deformability data found; the closest support is Keerthivasan et al. 2011 stating enucleation "**likely**" imparts flexibility for traversing capillaries half the cell's diameter — an inference, not a measurement. Treat as plausible-but-unsourced | https://pmc.ncbi.nlm.nih.gov/articles/PMC12289124/ ; https://en.wikipedia.org/wiki/Mean_corpuscular_volume |
| "Retained mitochondria consume some transported oxygen, raising cell metabolic cost" | CONFIRMED (mechanistically standard) | | https://en.wikipedia.org/wiki/Red_blood_cell |
| **"Nucleated erythrocytes are the documented norm in birds, reptiles, amphibians, fish"** | **IMPRECISE** | The norm is right (Glomski et al., "The phylogenetic odyssey of the erythrocyte" III & IV; reptiles, birds confirmed). But there are documented exceptions that undercut a strict "norm" claim: **five clades of plethodontid salamanders have evolved enucleate RBCs** (up to ~99% enucleate in *Batrachoseps attenuatus*); fish of genus *Maurolicus* have enucleate RBCs; channichthyid icefish lack erythrocytes and hemoglobin entirely | https://pubmed.ncbi.nlm.nih.gov/18328681/ ; https://en.wikipedia.org/wiki/Red_blood_cell |
| "Mammalian enucleation is standardly explained as aiding capillary deformability and hemoglobin packing (textbook thesis)" | CONFIRMED (correctly labelled a thesis, not a fact) | | https://pmc.ncbi.nlm.nih.gov/articles/PMC3159172/ |
| "Reticulocytes transiently retain organelles in reality" | CONFIRMED | Mitochondria persist into the reticulocyte and are cleared by NIX/BNIP3L-dependent mitophagy, independent of BAX/BAK — Schweers RL et al., *PNAS* 2007;104(49):19500–5 | https://pubmed.ncbi.nlm.nih.gov/18048346/ |
| "Cell-free fetal DNA in maternal plasma underlies real noninvasive prenatal testing" | CONFIRMED | Lo YMD, Corbetta N, Chamberlain PF, Rai V, Sargent IL, Redman CWG, Wainscoat JS, "Presence of fetal DNA in maternal plasma and serum," *Lancet* 1997;350(9076):485–7 | https://pubmed.ncbi.nlm.nih.gov/9274585/ |
| "Smears and automated counts must separate nucleated red cells from leukocytes" | CONFIRMED | Avian nucleated RBCs are documented to interfere with automated counters, forcing manual methods | https://pmc.ncbi.nlm.nih.gov/articles/PMC12289124/ |
| **"Anucleate red cells cannot become cancerous; nucleated ones could in principle mutate"** + `query`'s "nucleated cells possess apoptosis machinery" | **IMPRECISE — both halves** | (a) Mature **anucleate** human RBCs *do* undergo a regulated suicidal death, **eryptosis** — Ca²⁺ entry, cell shrinkage, phosphatidylserine scrambling (Lang KS et al., *Cell Physiol Biochem* 2005;15(5):195–202; Lang & Lang, *Biomed Res Int* 2015:513518). So the implicit "nucleus ⇒ death machinery, no nucleus ⇒ no programmed death" premise is wrong, and the item's Plasmodium/apoptosis thread rests on it. (b) Red-lineage cancers exist but arise **upstream in nucleated precursors**: pure erythroid leukemia arises from erythroblasts (Wang W et al., *Am J Hematol* 2017;92(3):292–6), polycythemia vera is a clonal HSC disorder (James C et al., *Nature* 2005;434:1144–8). Correct framing: "the mature anucleate erythrocyte is not itself a transformable target" | https://pubmed.ncbi.nlm.nih.gov/15956782/ ; https://pubmed.ncbi.nlm.nih.gov/28006859/ |

### Exact replacements for `C2_biology_medicine_34`

1. `known_answers[9]` — the load-bearing one:
   - OLD: `Anucleate red cells cannot become cancerous; nucleated ones could in principle mutate (obvious).`
   - NEW: `The mature anucleate red cell is not itself a transformable target, though red-lineage cancers already arise in nucleated precursors (erythroblasts in pure erythroid leukemia; HSCs in polycythemia vera); note also that anucleate mammalian RBCs are NOT death-machinery-free, since they undergo regulated eryptosis (obvious).`

2. `known_answers[4]`:
   - OLD: `Nucleated erythrocytes are the documented norm in birds, reptiles, amphibians, fish (factual baseline).`
   - NEW: `Nucleated erythrocytes are the documented norm in birds, reptiles, amphibians, fish, with rare convergent exceptions (enucleate RBCs in several plethodontid salamander clades and in the fish genus Maurolicus) (factual baseline).`

3. `query` — the apoptosis premise (this is the one that changes what the item is asking):
   - OLD: `(especially Plasmodium/malaria, given that nucleated cells possess apoptosis machinery)`
   - NEW: `(especially Plasmodium/malaria, given that nucleated cells possess full transcription-dependent apoptosis machinery, whereas real anucleate mammalian RBCs are limited to eryptosis)`

---

## 10. `C2_law_policy_09` (no statute of limitations) — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| Roman law: usucapio in the Twelve Tables (c. 450 BCE); longi temporis praescriptio (3rd c. CE) | CONFIRMED | Roman usucaption required "one year for chattels, two years for land" — the Twelve Tables periods. *Longi temporis praescriptio* is conventionally traced to a rescript of Septimius Severus and Caracalla c. 199–200 CE, i.e. the turn of the 3rd century — the item's "3rd c. CE" is defensible | https://en.wikipedia.org/wiki/Usucaption |
| maxim *vigilantibus non dormientibus jura subveniunt* | CONFIRMED (standard maxim) | "the law assists the vigilant, not the sleeping" | https://www.law.cornell.edu/wex/statute_of_limitations |
| *Wood v. Carpenter*, 101 U.S. 135 (1879) | CONFIRMED | Decided **22 December 1879**, opinion by **Justice Swayne**; concerns fraudulent concealment and statute-of-limitations policy. Its famous passage covers all three rationales the item lists: "They promote repose… They stimulate to activity and punish negligence. While time is constantly destroying the evidence of rights, they supply its place by a presumption…" | https://www.courtlistener.com/opinion/90102/wood-v-carpenter/ |
| Justice Jackson in *Order of Railroad Telegraphers v. Ry. Express Agency*, 321 U.S. 342 (1944) | CONFIRMED **from the official U.S. Reports scan** | **321 U.S. 342**, argued 10 Nov 1943, decided **28 February 1944**: "MR. JUSTICE JACKSON delivered the opinion of the Court." The passage supporting all three rationales, at **321 U.S. 348–349**: "Statutes of limitation… are designed to promote justice by preventing surprises through the revival of claims that have been allowed to slumber until evidence has been lost, memories have faded, and witnesses have disappeared… the right to be free of stale claims in time comes to prevail over the right to prosecute them." ⚠️ Do **not** confuse with Jackson's other well-known formulation ("Statutes of limitation find their justification in necessity and convenience rather than in logic… by definition arbitrary") — that is *Chase Securities Corp. v. Donaldson*, 325 U.S. 304, 314 (1945) | https://tile.loc.gov/storage-services/service/ll/usrep/usrep321/usrep321342/usrep321342.pdf |
| 1968 UN Convention on Non-Applicability of Statutory Limitations to War Crimes and Crimes Against Humanity (in force 1970) | CONFIRMED **exactly** | Title verified; **adopted 26 November 1968**; **entered into force 11 November 1970** per art. VIII; open for signature 16 Dec 1968 – 31 Dec 1969; 56 states parties | https://treaties.un.org/pages/ViewDetails.aspx?src=TREATY&mtdsg_no=IV-6&chapter=4&clang=_en |
| **"murder has no statute of limitations in most U.S. states"** | **IMPRECISE — understated in the item's own favour** | **No U.S. state imposes a limitations period on murder**, so "most" is weaker than the truth. Federally, 18 U.S.C. § 3281: "An indictment for any offense punishable by death may be found at any time without limitation." Cal. Penal Code § 799(a); N.Y. CPL § 30.10(2)(a) ("may be commenced at any time"). Residual caveats: *lesser* homicides (manslaughter) can be time-barred, and extreme delay can still trigger speedy-trial/due-process dismissal — so "murder" specifically, not "homicide" | https://www.law.cornell.edu/uscode/text/18/3281 ; https://www.nysenate.gov/legislation/laws/CPL/30.10 |
| California AB 218 (2019) look-back window | CONFIRMED | **Approved by the Governor 13 October 2019.** Extended the limitations period to 22 years past majority (or 5 years from discovery, whichever is later) AND created a **three-year revival window**: claims "otherwise be barred as of January 1, 2020… [are] revived, and these claims may be commenced within three years of January 1, 2020" (i.e. to 1 Jan 2023) | https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=201920200AB218 |
| New York Child Victims Act (2019) look-back window | CONFIRMED, with precision | S2440, ch. 11 of 2019, **signed 14 February 2019**: civil claims to age 55, criminal clock from age 23, plus a revival window opening 6 months after the effective date — originally **1 year (14 Aug 2019 – 13 Aug 2020)**, extended to **14 Aug 2021** by S7082 (signed 3 Aug 2020) | https://www.nysenate.gov/legislation/bills/2019/S2440 ; https://www.nysenate.gov/legislation/bills/2019/S7082 |
| Catholic dioceses and Boy Scouts of America (Ch. 11, 2020) bankruptcies | CONFIRMED, with a **primary-source causal link** | Third Circuit, 137 F.4th 126 (3d Cir. 13 May 2025): "**Meanwhile, many states enacted revival statutes enabling survivors to assert claims that were previously barred by statutes of limitation, and by 2019, it became apparent that BSA could not continue to defend individual abuse claims on a case-by-case basis and would need to declare bankruptcy. On February 18, 2020, BSA filed for bankruptcy protection in the District of Delaware.**" Bar date 16 Nov 2020; **over 100,000 proofs of claim** (~82,000–92,700 abuse claims in various tallies). This is the strongest single piece of evidence in the item — a federal appellate court expressly attributing the bankruptcy to SOL revival | https://storage.courtlistener.com/pdf/2025/05/13/boy_scouts_of_america_and_delaware_bsa_llc_v..pdf |
| CERCLA/Superfund 1980 | CONFIRMED (standard) | Comprehensive Environmental Response, Compensation, and Liability Act, enacted 1980 | https://www.epa.gov/superfund/superfund-cercla-overview |
| T. Merrill, "Property Rules, Liability Rules, and Adverse Possession," 1985 | **CONFIRMED — and 1985 is the correct year** | **Thomas W. Merrill, "Property Rules, Liability Rules, and Adverse Possession," 79 Nw. U. L. Rev. 1122 (1985)** — recommended citation taken verbatim from the author's own institutional repository, corroborated by OpenAlex (`publication_year` 1985). A minority of citations render it "(1984)" because vol. 79 spans the 1984–85 academic year, but the publisher/repository year is 1985. Only nit: "T. Merrill" should be "Thomas W. Merrill". | https://scholarship.law.columbia.edu/faculty_scholarship/373/ |
| Posner, *Economic Analysis of Law* | CONFIRMED as to the work; **pin-cite unverified** | Richard A. Posner, *Economic Analysis of Law*, 1st ed. **1973** (Little, Brown), 9 editions through 2014. The efficiency treatment of adverse possession is standard in the property chapter and is what Merrill's 1985 article engages, but the book text could not be opened (Internet Archive item lending-restricted, 403; Google Books API rate-limited), so no specific passage was confirmed | https://en.wikipedia.org/wiki/Richard_Posner |
| Torrens system, South Australia, 1858 | CONFIRMED | **Real Property Act 1858**; first sale under the system **25 August 1858** | https://en.wikipedia.org/wiki/Torrens_title |
| Torrens curtain/mirror/indemnity principles | CONFIRMED **verbatim** | "The Torrens system works on three principles: Mirror principle… Curtain principle… Indemnity principle" | https://en.wikipedia.org/wiki/Torrens_title |
| *In re African-American Slave Descendants Litigation*, 471 F.3d 754 (7th Cir. 2006) | CONFIRMED | **471 F.3d 754**, Seventh Circuit, decided **13 December 2006**, panel Easterbrook / **Posner** / Manion (Posner wrote); the district-court proceedings below are 272 F. Supp. 2d 755 (N.D. Ill. 2003) etc. | https://www.courtlistener.com/opinion/796269/in-re-african-american-slave-descendants-litigation-appeals-of-deadria/ |
| Mau Mau claims against the UK settled June 2013 | CONFIRMED **exactly** | Foreign Secretary **William Hague**'s statement to Parliament, **6 June 2013**: **£19.9 million** for **5,228 claimants**; the Government expressly did not concede liability and noted the difficulty of claims "relating to events that occurred overseas… more than fifty years ago" | https://www.gov.uk/government/news/statement-to-parliament-on-settlement-of-mau-mau-claims |
| Herero/Nama claims against Germany | CONFIRMED; dismissal ground worth noting | ***Rukoro v. Federal Republic of Germany*, 363 F. Supp. 3d 436 (S.D.N.Y. 2019)** (Swain, J., 11 Mar 2019), **aff'd 976 F.3d 218 (2d Cir. 24 Sept 2020)**: "we affirm the district court's dismissal for lack of subject matter jurisdiction" — the FSIA expropriation exception, § 1605(a)(3), did not apply. The dismissal turned on **sovereign immunity, not limitations**, which actually *strengthens* the item's own `known_answers[9]` point that other gatekeepers survive when SOL is removed. (⚠️ CourtListener's metadata mislabels the district court as "S.D. Illinois"; the opinion says S.D.N.Y.) | https://storage.courtlistener.com/pdf/2020/09/24/rukoro_v._federal_republic_of_germany.pdf |
| **"the U.S. HEAR Act (2016) lifting state SOL for Nazi-looted art"** | **IMPRECISE** | Name and year correct — Holocaust Expropriated Art Recovery Act of 2016, Pub. L. 114-308, **approved 16 December 2016**. But the Act does **not "lift"** state statutes of limitations; it **preempts them and substitutes a uniform federal 6-year period running from actual discovery**. Operative text: a claim may be filed "not later than **6 years** after the **actual discovery** by the claimant or the agent of the claimant" of both identity/location and possessory interest, and this applies "**Notwithstanding any other provision of Federal or State law or any defense at law relating to the passage of time**." This distinction is load-bearing for *this specific item*: HEAR replaces one time-bar with another (and a fairly short one), so it is a poor illustration of a world with no time-bars — it is better cited as evidence that legislatures reach for *discovery-triggered* limitations rather than abolition. | https://www.govinfo.gov/content/pkg/PLAW-114publ308/html/PLAW-114publ308.htm |
| **South Africa TRC, "1995-1998"** | **IMPRECISE** | Founding statute confirmed: **Promotion of National Unity and Reconciliation Act, No. 34 of 1995**. First HRV hearing 15 April 1996; five-volume report handed over late **October 1998**. But the Amnesty Committee continued and the TRC formally **ended its work in March 2003** with the final volumes (Vol. 7 dated 2002). Precise span: **1995–2003, with core hearings 1996–1998** | https://www.justice.gov.za/trc/ ; https://www.justice.gov.za/trc/report/finalreport/victims_main_vol7.pdf |
| Asbestos + "occurrence" vs "claims-made" coverage wars; insurer insolvencies (1970s-2000s) | CONFIRMED (standard insurance history) | | https://www.epa.gov/superfund/superfund-cercla-overview |
| "even where SOL is absent or waived, claims are still gated by sovereign immunity, act-of-state, standing, non-retroactivity, causation, burden of proof" | CONFIRMED (standard doctrine) | | https://www.law.cornell.edu/wex/statute_of_limitations |

### Exact replacement for `C2_law_policy_09`

`known_answers[7]`:

- OLD: `Holocaust-era art, addressed by the U.S. HEAR Act (2016) lifting state SOL for Nazi-looted art`
- NEW: `Holocaust-era art, addressed by the U.S. HEAR Act (Pub. L. 114-308, 16 Dec 2016), which preempts state SOLs and substitutes a uniform federal 6-year period running from ACTUAL DISCOVERY rather than abolishing the time-bar`

---

## 11. `C2_law_policy_37` (no plea bargaining) — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| `query` + `known_answers[3]`: "~95% of US convictions are real-world guilty pleas" | **IMPRECISE (coarse rather than false)** | *Missouri v. Frye*, **566 U.S. 134, 143 (2012)**, verbatim: "**Ninety-seven percent of federal convictions and ninety-four percent of state convictions are the result of guilty pleas**." "~95%" traces to *Padilla v. Kentucky*, 559 U.S. 356, 372 & n.13 (2010) ("nearly 95% of all criminal convictions"), so it is not invented — but it understates federal by 2–3 points and collapses the federal/state split Frye deliberately drew. **Current figures: federal 97.2%** of convictions by plea (USSC 2024 Sourcebook tbl. 11, FY2024, n=61,678) / **97.6%** (BJS *Federal Justice Statistics, 2023* tbl. 6); **state — no national estimate newer than 2006 (94%)**, the BJS series having ended, with BJS *Felony Defendants in Large Urban Counties, 2009* tbl. 21 as the nearest proxy at ~96–97%. Precise version: **~97–98% federal, ~94–97% state** | https://tile.loc.gov/storage-services/service/ll/usrep/usrep566/usrep566134/usrep566134.pdf ; https://www.ussc.gov/sites/default/files/pdf/research-and-publications/annual-reports-and-sourcebooks/2024/Table11.pdf |
| `known_answers[6]`: "The 'trial penalty' (harsher post-trial than post-plea sentences) is documented" | CONFIRMED, but **the magnitude is order-of-magnitude ambiguous** | NACDL, *The Trial Penalty: The Sixth Amendment Right to Trial on the Verge of Extinction and How to Save It*, **2018** (released 10 July 2018). Raw magnitude, Fig. 1 (USSC FY2015): **10.8 yrs post-trial vs 3.3 yrs post-plea ≈ 3.3×** (embezzlement/burglary ~8×; excludes 144 life sentences, so understated). **Regression-adjusted estimates are far smaller: +45% falling to +16% with guideline controls** (Ulmer, Eisenstein & Johnson, *Justice Quarterly* 27(4):560–592 (2010)) and **+64%** (Kim, 84 Miss. L.J. 1195 (2015)), both via Vera Institute, *In the Shadows* (2020) 40–41. Codified discount: USSG § 3E1.1 (2–3 levels). **Flag for scoring:** raw (~3×) and controlled (+16% to +64%) magnitudes differ by an order of magnitude, so any agent claim about trial-penalty size must specify which — and a judge should not mark either as wrong | https://www.nacdl.org/getattachment/95b7f0f5-90df-4f9f-9115-520b3f58036a/the-trial-penalty-the-sixth-amendment-right-to-trial-on-the-verge-of-extinction-and-how-to-save-it.pdf ; https://www.vera.org/downloads/publications/in-the-shadows-plea-bargaining.pdf |
| Premise coherence check: is "plea bargaining constitutionally prohibited" a genuine counterfactual? | CONFIRMED — the real doctrine is the opposite | *Brady v. United States*, **397 U.S. 742, 752 (1970)** (4 May 1970): "guilty pleas are not constitutionally forbidden." *Santobello v. New York*, **404 U.S. 257, 260 (1971)** (20 Dec 1971): plea bargaining "is an essential component of the administration of justice. Properly administered, it is to be encouraged." *Bordenkircher v. Hayes*, **434 U.S. 357, 363 (1978)** (decided 18 Jan 1978; the 6 Mar 1978 date some databases show is the rehearing denial, 435 U.S. 918) immunised hard bargaining. Note the trajectory — the Court *declined to prohibit* → *encouraged* → *immunised*; it never affirmatively created the practice. A "constitutionally prohibited" counterfactual must also unwrite **Fed. R. Crim. P. 11(e)** (1974 amendment recognising "the propriety of plea discussions") | https://tile.loc.gov/storage-services/service/ll/usrep/usrep397/usrep397742/usrep397742.pdf ; https://tile.loc.gov/storage-services/service/ll/usrep/usrep404/usrep404257/usrep404257.pdf |
| "Dockets overwhelmed"; "needs far more judges/prosecutors/defenders/courtrooms/jurors"; "per-case time and cost rise sharply"; "plea bargaining mainly manages caseload volume"; "speedy-trial and pretrial-detention pressures rise" | CONFIRMED as correctly-labelled obvious first-order effects (not independently checkable factual claims) | | — |

### Optional replacement for `C2_law_policy_37`

`known_answers[3]` — restore the split Frye drew:

- OLD: `About 95% of US convictions are real-world guilty pleas (factual baseline).`
- NEW: `Roughly 97% of federal and 94% of state US convictions are guilty pleas (Missouri v. Frye, 566 U.S. 134, 143 (2012)); current federal figures are ~97-98% (USSC FY2024; BJS FJS 2023), and no post-2006 national state estimate exists (factual baseline).`

The `query`'s "~95%" can stay as a round framing figure — it is *Padilla*'s own number.

---

## 12. `C2_economics_business_36` (no shipping container) — full claim table

| Claim | Verdict | Correct value / note | Source |
|---|---|---|---|
| "McLean's Ideal-X (1956) and later ISO standards are the real origin" | CONFIRMED (date/route/count) | From Levinson's own text (publisher-hosted ch. 1): "On April 26, 1956, a crane lifted fifty-eight aluminum truck bodies aboard an aging tanker ship moored in Newark, New Jersey. Five days later, the Ideal-X sailed into Houston…" Converted **T-2 tanker** (ex-*Potrero Hills*), Pan-Atlantic Steamship Company, **Malcom** McLean (his own spelling; born Malcolm). ⚠️ **Two Wikipedia errors to avoid** (and which an earlier draft of this audit repeated): the containers were **33 ft, not 35 ft** (35 ft came in 1957), and the origin was **Port Newark**, not "Port Newark–Elizabeth" (Elizabeth opened 1962) | http://assets.press.princeton.edu/chapters/s10724.pdf |
| "with its ISO dimensions" | CONFIRMED, and datable — but **the widely-circulated timeline is corrupt** | Verified against ISO's own records: **ISO/TC 104 created 1961**; draft (ISO Recommendation 804) circulated May 1965; ISO Council accepted it **February 1968** as **ISO/R 668-1968 "Dimensions and ratings of freight containers"**; 2nd ed. Oct 1970 added the 8 ft 6 in height. Companions: **R 790:1968** (markings), **R 830:1968** (terminology), **R 1161:1970** (corner fittings), **R 1496:1970** (specification/testing), **R 1894:1970** (minimum internal dimensions). ISO 668 became a full International Standard from **1973**. 🚩 The commonly cited timeline's "**R-1897**, October 1970" is a **typo for ISO/R 1894:1970** (ISO/R 1897 is a phenol/cresol test method under TC 47); "ISO 668 defined the terminology" is also wrong (terminology was R 830), and the Council decision was February, not January 1968. The error originates in Rushton et al., *Handbook of Logistics* (2004) and is repeated verbatim by Wikipedia's *Containerization* article — an earlier draft of this audit repeated it too | https://cdn.standards.iteh.ai/samples/3397/c8286982808b49629df3238b3feddcaa/ISO-R-668-1970.pdf ; https://www.iso.org/committee/51156.html |
| "Containerization historically cut loading costs by one-to-two orders of magnitude" | **IMPRECISE (defensible, but narrower than it sounds)** | Correct figures, Levinson *The Box* **p. 52**: "Loading loose cargo on a medium-size cargo ship cost **$5.83 per ton** in 1956. McLean's experts pegged the cost of loading the Ideal-X at **15.8 cents per ton**." That is **36.9× ≈ 1.57 orders of magnitude**, so the stated range holds — **but only for ship-*loading* cost, on a single figure pair that compares an industry average against McLean's own in-house estimate for one voyage.** Levinson himself warns the underlying series does not exist ("Such data do not exist"). (Wikipedia's "$5.86 / 16 cents" is a rounded misquote; an earlier draft of this audit used it.) The legitimate counterweight is Hummels, *JEP* 21(3):131–154 (2007): "the ad-valorem impact of ocean shipping costs is not much lower today than in the 1950s" | https://pmc.ncbi.nlm.nih.gov/articles/PMC8014098/ ; https://www.aeaweb.org/articles?id=10.1257/jep.21.3.131 |
| "Standard thesis (Levinson, 'The Box')" | CONFIRMED | Marc Levinson, *The Box: How the Shipping Container Made the World Smaller and the World Economy Bigger*, Princeton University Press, **2006** (2nd ed. with a new chapter, 5 April 2016) | https://press.princeton.edu/books/paperback/9780691170817/the-box |
| "general cargo continues to move as manually handled break-bulk freight… as it did before the mid-1950s" | CONFIRMED as a premise (historical half solid) | Break-bulk — manually handled, heterogeneous cargo, ships spending as much time in port as at sea — was indeed dominant before the mid-1950s. This is true only as an explicit *counterfactual* premise: in the real world UNCTAD's *Review of Maritime Transport 2024* records that "Containerization has reduced the need for general cargo ships, with breakbulk cargo increasingly transported in containers." The item frames it correctly | https://unctad.org/system/files/official-document/rmt2024ch2_en.pdf ; http://assets.press.princeton.edu/chapters/s10724.pdf |
| "Ocean freight stays labor-intensive"; "trade volume grows slower"; "longshoring stays a large unionized workforce"; "slower, costlier long-distance logistics dampen trade" | CONFIRMED as correctly-labelled obvious first-order effects | | — |

### Optional replacement for `C2_economics_business_36`

`known_answers[5]` — scope the cost claim so an agent cannot over-read it:

- OLD: `Containerization historically cut loading costs by one-to-two orders of magnitude (documented, not new).`
- NEW: `Containerization cut ship-LOADING cost by roughly 37x on the canonical figure pair (loose cargo $5.83/ton in 1956 vs ~15.8 cents/ton for the Ideal-X; Levinson, The Box, p. 52) - note this compares an industry average against an in-house estimate for one voyage, and total ad-valorem ocean freight fell far less (Hummels 2007) (documented, not new).`

Otherwise the item is clean: the Ideal-X details, the Levinson citation, the ISO chronology and
the break-bulk premise all verify.

---

## 13. Summary table — all graded claims

Only claims with a non-CONFIRMED verdict, plus the two priority claims, are itemised here;
the per-item tables above carry the full set.

| Item | Claim | Verdict | Correct value | Source URL |
|---|---|---|---|---|
| `C2_engineering_10` | Hippke: venue *IJA* 18 (2019), arXiv:1804.04727, submitted Apr 2018 | **CONFIRMED** | *Int. J. Astrobiology* 18 (2019) 393–395; v1 12 Apr 2018 | https://arxiv.org/abs/1804.04727 |
| `C2_engineering_10` | Hippke: "~400,000 t" for a "Hubble-class payload" | **WRONG** | 400,000 t is for a **45 t Apollo-class** mission; a **6.2 t JWST-class** payload needs **55,000 t**; Hubble is never mentioned | https://ar5iv.labs.arxiv.org/html/1804.04727 |
| `C2_engineering_10` | `hard_rules[1]` LOX/LH2 Isp ≤ ~450 s / v_e ≤ ~4.4 km/s | **WRONG** | ≤ ~465 s / 4.56 km/s (RL10B-2 = 465.5 s, flown since 1998) | https://en.wikipedia.org/wiki/RL10 |
| `C2_engineering_10` | "sustained ~16 g for a minute may be lethal" | **UNVERIFIABLE** | Unsourced Wikipedia sentence with a live citation-needed tag; Eiband (NASA Memo 5-19-59E, 1959) says no lethal boundary is established | https://ntrs.nasa.gov/api/citations/19980228043/downloads/19980228043.pdf |
| `C2_engineering_10` | Tsiolkovsky rocket equation (1903) | **IMPRECISE** | Published by Tsiolkovsky 1903; **first derived by W. Moore, 1810–13** | https://en.wikipedia.org/wiki/Tsiolkovsky_rocket_equation |
| `C2_engineering_10` | "McMahon elastic similarity, 1973; R. McN. Alexander" | **IMPRECISE** | McMahon, *Science* 179:1201–04 (1973) is sole-authored; Alexander is a separate researcher | https://pubmed.ncbi.nlm.nih.gov/4689015/ |
| `C2_biology_medicine_06` | "Aluvihare/Betz/**Rudensky**, Nature Immunology 2004" | **WRONG** | Aluvihare VR, **Kallikourdis M**, Betz AG, *Nat Immunol* 2004;5(3):266–71. Rudensky's work is Samstein et al., *Cell* 2012 | https://pubmed.ncbi.nlm.nih.gov/14758358/ |
| `C2_biology_medicine_06` | "**Dunn**, Old & Schreiber… Science 2011" | **WRONG** | Schreiber RD, Old LJ, **Smyth MJ**, *Science* 2011;331(6024):1565–70 — no Dunn | https://pubmed.ncbi.nlm.nih.gov/21436444/ |
| `C2_biology_medicine_06` | "Burnet-Thomas hypothesis (1957)" | **IMPRECISE** | Burnet 1957 (*BMJ* 1(5022):779–86); **Thomas 1959** | https://pubmed.ncbi.nlm.nih.gov/13404306/ |
| `C2_biology_medicine_06` | VLRs in "lamprey/hagfish" — Nature 2004 | **IMPRECISE** | *Nature* 2004 is **sea lamprey only**; hagfish is *PNAS* 2005;102(26):9224–9 | https://pubmed.ncbi.nlm.nih.gov/15964979/ |
| `C2_biology_medicine_06` | "IgE… (Ishizaka, 1966)" | **IMPRECISE** | Co-discovered by Johansson & Bennich 1967; class named IgE 1968 | https://en.wikipedia.org/wiki/Immunoglobulin_E |
| `C2_biology_medicine_06` | "roughly 97% of animal species" | **CONFIRMED (don't harden)** | 97% is citable (May 1988) but ~95% is equally common; the figure is an artifact of the total-species estimate | https://en.wikipedia.org/wiki/Invertebrate |
| `C2_arts_humanities_11` | "Foreshortening… predate[s]… (e.g. **Melozzo da Forli**)" | **WRONG** | Melozzo is c. 1438–1494 — two generations *after* Brunelleschi and Alberti, inside the perspective tradition. Use Roman fresco (Villa of P. Fannius Synistor, 1st c. BC) or Lorenzetti 1342 | https://en.wikipedia.org/wiki/Melozzo_da_Forl%C3%AC |
| `C2_arts_humanities_11` | "Kepler (1604)… introduced the point at infinity" | **IMPRECISE** | Kepler gave a *limiting-case* point at infinity for the parabola; the general projective concept is Desargues 1639 | https://mathshistory.st-andrews.ac.uk/Biographies/Kepler/ |
| `C2_arts_humanities_11` | camera obscura "(Mozi, **Aristotle**, Alhazen)" | **IMPRECISE** | The pinhole observation is in the **pseudo-Aristotelian *Problemata*** | https://en.wikipedia.org/wiki/Problems_(Aristotle) |
| `C2_arts_humanities_11` | "**Leonardo's** paragone" | **IMPRECISE** | *Paragone* is an art-historical label for the painting-vs-sculpture debate (Varchi 1546), not Leonardo's coinage | https://en.wikipedia.org/wiki/Paragone |
| `C2_economics_business_08` | "5-20% of U.S. GDP" statistic; "Edward Cox 1855" | **ABSENT — removal held** | Zero occurrences of `%`/`GDP`/`Cox`/`Edward` anywhere in the item | (programmatic scan of the audit `.jsonl`) |
| `C2_economics_business_08` | double liability "1863-1933" | **IMPRECISE** | 1933 Act ended it only for shares issued after 16 Jun 1933; 1935 voluntary termination on existing shares; full abolition **1953** | https://en.wikipedia.org/wiki/Double_liability |
| `C2_economics_business_08` | California "from 1849 until 1931" | **IMPRECISE** | Constitutional provision repealed by amendment **4 Nov 1930**; Civil Code s.322 repeal effective 14 Aug 1931 | https://www.bainbridgeoncorporations.com/p/a-brief-history-of-limited-liability |
| `C2_economics_business_08` | Lloyd's: "the 1990s reconstruction… admitted limited-liability corporate capital" | **IMPRECISE** | Corporate members admitted **1994**, *before* R&R (1995) and Equitas (Sept 1996) | https://en.wikipedia.org/wiki/Lloyd%27s_of_London |
| `C2_economics_business_08` | "Murray Rothbard's position that liability for torts should be full/unlimited" | **UNVERIFIABLE** | 5 retrieval routes failed; and Rothbard is conventionally read as a *defender* of contractual limited liability, so filing him under "critical literature" inverts his stance | https://cdn.mises.org/19_3_3.pdf (checked, no Rothbard) |
| `C2_economics_business_08` | `hard_rules[1]` early UK railways/canals "unlimited or ambiguous liability" | **UNVERIFIABLE in detail** | Pre-1845 statutory companies each set liability terms by private Act; the "or ambiguous" hedge should stay | https://en.wikipedia.org/wiki/Companies_Clauses_Consolidation_Act_1845 |
| `C2_law_policy_09` | "HEAR Act (2016) **lifting** state SOL" | **IMPRECISE** | Pub. L. 114-308 (16 Dec 2016) **preempts** state SOLs and substitutes a uniform federal **6-year period from actual discovery** | https://www.govinfo.gov/content/pkg/PLAW-114publ308/html/PLAW-114publ308.htm |
| `C2_law_policy_09` | Merrill, "Property Rules, Liability Rules, and Adverse Possession," 1985 | **CONFIRMED** | Thomas W. Merrill, **79 Nw. U. L. Rev. 1122 (1985)** — 1985 is correct; only nit is "T. Merrill" → "Thomas W. Merrill" | https://scholarship.law.columbia.edu/faculty_scholarship/373/ |
| `C2_law_policy_09` | South Africa TRC "1995-1998" | **IMPRECISE** | Act No. 34 of 1995; main report Oct 1998; but the Amnesty Committee ran on and the TRC ended work **March 2003** — precise span **1995–2003** | https://www.justice.gov.za/trc/report/finalreport/victims_main_vol7.pdf |
| `C2_law_policy_09` | "murder has no SOL in **most** U.S. states" | **IMPRECISE (understated)** | **No** U.S. state imposes a limitations period on murder; 18 U.S.C. § 3281 for federal capital offences | https://www.law.cornell.edu/uscode/text/18/3281 |
| `C2_law_policy_37` | "About 95% of US convictions are guilty pleas" | **IMPRECISE (coarse)** | *Frye* (2012): **97% federal / 94% state**; current federal 97.2–97.6%; no post-2006 national state estimate. "~95%" is *Padilla*'s round number, so not invented | https://tile.loc.gov/storage-services/service/ll/usrep/usrep566/usrep566134/usrep566134.pdf |
| `C2_economics_business_36` | "cut loading costs by one-to-two orders of magnitude" | **IMPRECISE (defensible but narrow)** | Levinson p. 52: **$5.83/ton → 15.8¢/ton = 36.9× ≈ 1.57 orders of magnitude** ✓, but it is a *loading*-cost pair comparing an industry average to an in-house estimate for one voyage; total ad-valorem ocean freight fell far less (Hummels 2007) | https://pmc.ncbi.nlm.nih.gov/articles/PMC8014098/ |
| `C2_biology_medicine_34` | "Anucleate red cells cannot become cancerous" + `query`'s apoptosis premise | **IMPRECISE (both halves)** | Anucleate RBCs undergo regulated **eryptosis**; red-lineage cancers arise in nucleated precursors (erythroblasts, HSCs) | https://pubmed.ncbi.nlm.nih.gov/15956782/ |
| `C2_biology_medicine_34` | "Nucleated erythrocytes are the… norm in birds, reptiles, amphibians, fish" | **IMPRECISE** | Real convergent exceptions: enucleate RBCs in ≥5 plethodontid salamander clades (~99% in *Batrachoseps attenuatus*) and in fish genus *Maurolicus* | https://pubmed.ncbi.nlm.nih.gov/18328681/ |
| `C2_biology_medicine_34` | "A rigid nucleus makes erythrocytes larger and **stiffer**" | "larger" CONFIRMED; "stiffer" **UNVERIFIABLE** | Larger ✓ (chicken MCV 124–152 fL vs human 80–100). No comparative deformability measurement found; Keerthivasan 2011 says only "likely" | https://pmc.ncbi.nlm.nih.gov/articles/PMC12289124/ |
| `C2_materials_chemistry_07` | a-IGZO "**Hosono et al.** 2004" | **IMPRECISE** | Conventionally **Nomura et al.**, *Nature* 432(7016):488–492 (2004); Hosono is last author | https://www.nature.com/articles/nature03090 |
| `C2_materials_chemistry_07` | a-Si:H mobility "~1 cm2/V.s" | **CONFIRMED (qualify)** | Correct for **drift/field-effect** mobility; extended-state mobility is 10–20+ | https://arxiv.org/abs/2408.03678 |
| `C2_materials_chemistry_07` | HDA ice "~1.17 g/cm3" | **CONFIRMED (range top)** | Standard range **1.15–1.17**; MDA (~1.06) reported 2023 | https://pmc.ncbi.nlm.nih.gov/articles/PMC10879119/ |
| `C2_materials_chemistry_35` | "the **1960s** beverage-can revolution" | **IMPRECISE** | First all-aluminum can **1958** (Primo); Coors **22 Jan 1959**; 1963 drawn-and-ironed can drove the 1960s ramp; steel displaced only by the 1980s–90s | https://www.lightmetalage.com/news/industry-news/applications-design/60-years-of-the-aluminum-can/ |
| `C2_materials_chemistry_35` | Al PBR ~1.3; native oxide ~4 nm | **CONFIRMED** | PBR = 1.28; native oxide **2–4 nm** (to ~5 nm with age) — "~4 nm" is the range top | https://en.wikipedia.org/wiki/Pilling%E2%80%93Bedworth_ratio ; https://www.sciencedirect.com/science/article/abs/pii/S0169433215011617 |
| *(audit self-correction)* | three rows in an earlier draft of this report | **CORRECTED** | Wikipedia was wrong and this audit initially repeated it: Ideal-X containers were **33 ft not 35 ft** and sailed from **Port Newark** not "Port Newark–Elizabeth"; Levinson's figures are **$5.83 / 15.8¢** not "$5.86 / 16¢"; and the ISO timeline's "**R-1897**" is a typo for **ISO/R 1894:1970** (with terminology in R 830, and a February not January 1968 Council decision) | http://assets.press.princeton.edu/chapters/s10724.pdf ; https://cdn.standards.iteh.ai/samples/3397/c8286982808b49629df3238b3feddcaa/ISO-R-668-1970.pdf |

---

## 14. Counts by verdict

Counting distinct graded factual claims across the ten items (compound `known_answers`
entries are counted once per checkable sub-claim; the full per-item tables are the
authoritative list).

| Verdict | Count | Where |
|---|---|---|
| **CONFIRMED** | **110** | spread across all ten items; includes every statute/treaty/case cite in `C2_economics_business_08` and `C2_law_policy_09` (several verified against primary statute text or official U.S. Reports scans), and every condensed-matter fact in `C2_materials_chemistry_07` |
| **WRONG** | **4** | `C2_engineering_10` ×2 (Hippke 400,000 t / Hubble-class; `hard_rules[1]` Isp ceiling), `C2_biology_medicine_06` ×2 (Rudensky; Dunn) — plus 1 substantively wrong *example* in `C2_arts_humanities_11` (Melozzo), giving **5** if that is counted as WRONG rather than a bad illustration |
| **IMPRECISE** | **22** | `C2_arts_humanities_11` ×3, `C2_biology_medicine_06` ×3, `C2_biology_medicine_34` ×3, `C2_economics_business_08` ×3, `C2_engineering_10` ×2, `C2_law_policy_09` ×3 (HEAR Act, TRC span, "most states"), `C2_law_policy_37` ×2 (95% figure, trial-penalty magnitude), `C2_economics_business_36` ×1, `C2_materials_chemistry_07` ×1, `C2_materials_chemistry_35` ×1 |
| **UNVERIFIABLE** | **4** | `C2_engineering_10` (16 g lethality), `C2_economics_business_08` ×2 (Rothbard; early UK railway liability), `C2_biology_medicine_34` ("stiffer"). Plus one partial: the Posner pin-cite in `C2_law_policy_09` (book confirmed, passage not opened) |
| **FABRICATED** | **0** | — |

**Per-item damage report** (edits needed before release):

| Item | WRONG | IMPRECISE | UNVERIFIABLE | Release-blocking? |
|---|---|---|---|---|
| `C2_engineering_10` | 2 | 2 | 1 | **YES** — a wrong figure in `known_answers` and a wrong `hard_rule` |
| `C2_biology_medicine_06` | 2 | 3 | 0 | **YES** — two wrong author lists in `known_answers` |
| `C2_arts_humanities_11` | 1 (example) | 3 | 0 | **YES** — the Melozzo example contradicts the point it is cited for |
| `C2_biology_medicine_34` | 0 | 3 | 1 | Recommended — the eryptosis point is load-bearing for the item's malaria thread |
| `C2_economics_business_08` | 0 | 3 | 2 | Recommended — all date-precision; the Rothbard line is the one worth cutting |
| `C2_law_policy_09` | 0 | 3 | 0 (+1 partial) | Recommended — the HEAR Act mischaracterisation matters *for this item specifically* |
| `C2_law_policy_37` | 0 | 2 | 0 | Optional — the 95% figure is *Padilla*'s own; worth restoring Frye's split |
| `C2_economics_business_36` | 0 | 1 | 0 | Optional — scope the loading-cost claim |
| `C2_materials_chemistry_07` | 0 | 1 | 0 | Optional |
| `C2_materials_chemistry_35` | 0 | 1 | 0 | Optional |

---

## 15. Overall assessment: are C2's baselines trustworthy?

**Broadly yes, with four items needing edits first.** The verdict distribution —
110 CONFIRMED, 4–5 WRONG, 22 IMPRECISE, 4 UNVERIFIABLE, **0 FABRICATED** — is a healthy
profile for a benchmark of this size. Every paper, book, statute, treaty and case cited across
the ten items **exists** with the stated author and title. There is no invented-citation
problem in C2. That is the single most important finding, because a fabricated `known_answers`
entry would silently corrupt the novelty baseline in a way no agent could detect or contest.

**The real failure mode is misattribution and figure drift, and it clusters in `known_answers`
— the worst possible place.** `known_answers` is what every agent answer is scored against for
New/Surprise, so an error there does not merely mislead a reader; it *inverts the grade*. Three
concrete instances:

1. **`C2_engineering_10`'s Hippke figure.** The item's entire design is to pre-declare Hippke's
   result KNOWN so agents cannot earn cheap Surprise. But the pre-declared anchor is wrong: an
   agent that correctly reports 55,000 t for a telescope-class payload now *disagrees with the
   rubric* and can be marked down for a correct fact. The same item's `hard_rules[1]` sets an
   Isp ceiling (450 s) that real flown hardware exceeds (465.5 s), so an agent citing the RL10B-2
   correctly could be scored as violating a hard rule. Both are self-inflicted scoring hazards,
   not merely cosmetic errors.
2. **`C2_biology_medicine_06`'s two author lists.** Rudensky-for-Kallikourdis and Dunn-on-the-
   2011-*Science*-paper are the classic LLM-generated-citation signature: right paper, right
   year, right journal, plausible-but-wrong senior author drawn from the topic's most famous
   name. Worth treating as a systematic risk indicator for the rest of the benchmark.
3. **`C2_arts_humanities_11`'s Melozzo example.** Cited to prove foreshortening *predates* the
   vanishing-point construction, but Melozzo works two generations after Alberti and inside the
   perspective tradition. The claim it is meant to support is true; the evidence offered
   refutes itself.

**A distinct, subtler category: absolutes that the comparative literature contradicts.**
`C2_biology_medicine_34` states that anucleate red cells lack the death machinery that nucleated
ones have — but mammalian RBCs undergo regulated **eryptosis**, and the item's `query` builds its
Plasmodium/apoptosis thread on exactly that premise. Similarly "nucleated erythrocytes are the
norm in birds, reptiles, amphibians, fish" has real convergent exceptions (plethodontid
salamanders, *Maurolicus*). These are not citation errors; they are over-confident biology, and a
well-read agent that *correctly* raises eryptosis would be penalised as off-premise.

**On the flagged economics item, the prior pass's work held cleanly.** A programmatic scan found
no percentage, no GDP reference, and no trace of "Edward Cox" anywhere in
`C2_economics_business_08`. Nothing comparable crept in to replace them. Its remaining ~19 claims
are unusually well-sourced for legal history — I verified the Companies Act 1879's re-registration
and reserve-liability provisions against the **primary statute text**, and the Butler 1911 quote,
the four law-review citations, Modigliani-Miller and Markowitz all check out precisely. The only
residue worth acting on is the Rothbard parenthetical, which sits in the same sentence as the
epistemic hedge the prior removal left behind — the same signature as the excised "Edward Cox"
line, and my recommendation is to cut or rewrite it.

**No item is entirely error-free, but two carry no WRONG verdicts at all:** `C2_law_policy_37`
and `C2_economics_business_36` need only optional precision work (restore *Frye*'s 97%/94% split;
scope the loading-cost claim to *loading* rather than freight generally). The error rate tracks
citation density, which is the expected pattern and suggests retrieval noise rather than
systematic invention.

**A methodological finding worth carrying to the other categories.** Three claims in this audit's
own first draft were wrong because Wikipedia was wrong and I trusted it: the Ideal-X's container
length (33 ft, not 35 ft) and departure port (Port Newark, not Port Newark–Elizabeth); Levinson's
cost pair ($5.83/15.8¢, not $5.86/16¢); and the ISO container timeline, whose widely-copied
"ISO/R 1897" is a typo for **ISO/R 1894:1970** that originates in Rushton et al., *Handbook of
Logistics* (2004) and propagates through Wikipedia. Each was caught only by going to the primary
document (Princeton's hosted chapter of *The Box*, ISO's own deliverables catalogue). Any C2-style
claim currently resting on a Wikipedia corroboration should be treated as provisional; the primary
sources exist and are reachable.

**Recommendation.** Apply the exact replacements in §§1 and 3–10 above — 4 WRONG fixes plus 17
precision fixes plus 2 recommended cuts. Do not publish `C2_engineering_10`,
`C2_biology_medicine_06` or `C2_arts_humanities_11` unedited. After those edits, C2's baselines
are trustworthy enough to score against.

**Two audit caveats.** (a) The session's WebSearch budget (200 calls) was exhausted partway
through; the majority of verdicts were therefore established by direct WebFetch against primary
sources — arguably stronger evidence than search snippets, but it meant some low-value claims
were corroborated via Wikipedia rather than a primary document, and those are labelled as such.
(b) Two claims resisted every retrieval route available — the Rothbard tort-liability attribution
(five routes: two mises.org book pages, the *Power and Market* CDN PDF, the *JLS* 19(3) article
full text, two search proxies) and the Posner adverse-possession pin-cite (Internet Archive
lending-restricted, Google Books rate-limited). Both are flagged rather than guessed. Merrill's
1985 year, initially unverifiable, was resolved from the author's own institutional repository and
is **correct as written**.

---

## 16. Provenance / integrity note for whoever applies these fixes

- **No `.jsonl` file was edited by this audit.** All 26 `OLD` strings above were re-validated
  against `question/crest_challenges.audit.jsonl` at the end of the audit: each matches
  **exactly once**, byte-for-byte, so every replacement can be applied as a literal
  find-and-replace without disambiguation.
- `question/crest_challenges.audit.jsonl` **was** modified during this audit window, but by
  **other auditors working other categories** — `doc/misc/hallucination_audit_live_log.jsonl`
  gained 13 entries for C1, C4 and C5 items while this audit ran. All ten C2 items were
  re-hashed afterwards and are unchanged. If these C2 fixes are applied later, re-confirm the
  `OLD` strings first in case a sibling pass touches C2.
- Suggested log lines for `hallucination_audit_live_log.jsonl`, in priority order:
  1. `C2_engineering_10` — Hippke 400,000 t / "Hubble-class" → Apollo-class 45 t; add JWST 6.2 t → 55,000 t
  2. `C2_engineering_10` — `hard_rules[1]` Isp ceiling 450 s → 465 s
  3. `C2_biology_medicine_06` — Aluvihare/Betz/**Rudensky** → Aluvihare, **Kallikourdis** & Betz
  4. `C2_biology_medicine_06` — **Dunn**, Old & Schreiber (Science 2011) → Schreiber, Old & **Smyth**
  5. `C2_arts_humanities_11` — Melozzo da Forlì → Roman fresco / Lorenzetti 1342
  6. `C2_engineering_10` — cut the unsourced "~16 g for a minute may be lethal"
  7. `C2_biology_medicine_34` — eryptosis correction (anucleate RBCs are not death-machinery-free)
  8. `C2_law_policy_09` — HEAR Act "lifting" → preempts with a 6-year discovery-triggered period
  9. `C2_economics_business_08` — double liability / California / Lloyd's date precision; Rothbard cut
  10. `C2_law_policy_09` — TRC span 1995–1998 → 1995–2003; "most U.S. states" → "no U.S. state"
  11. `C2_law_policy_37` — restore *Frye*'s 97% federal / 94% state split (optional)
  12. `C2_economics_business_36` — scope the loading-cost claim to *loading* (optional)
- **Still open, needs a manual paywalled/primary-text check:** a citable primary source for the
  Rothbard tort-liability attribution, and the Posner adverse-possession pin-cite. Merrill's
  1985 year is **resolved and correct** (79 Nw. U. L. Rev. 1122 (1985)).
