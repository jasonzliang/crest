# CREST Paper Comparison — P2 (`paper_p2_benchmark_only/`) vs P3 (`paper_p3_caesar_hybrid/`)

**Question:** which framing is the stronger ICLR 2027 submission?
- **Paper A = P2 (`paper_p2_benchmark_only/`)** — benchmark-only. CREST is the sole hero; the authors' agent (Caesar) is one cited entrant among many; mechanism/ablation analysis is an optional, IP-gated §7.
- **Paper B = P3 (`paper_p3_caesar_hybrid/`)** — CREST + Caesar hybrid. CREST + a "creativity is task-dependent" finding + Caesar as co-hero, with component ablations and a citation-grounding sanity check.

Method: four independent ICLR-reviewer agents (benchmark-track rigor; construct validity; adversarial Area Chair on novelty/positioning; statistics & experimental design), each read **both** full drafts + `DESIGN.md`, judged the *design/framing* (experiment numbers are intentional placeholders), and declared the stronger paper with no ties allowed.

## Verdict: 4–0 for Paper A (P2, benchmark-only)

| Reviewer (lens) | Paper A (P2) | Paper B (P3) | Stronger |
|---|---|---|---|
| R1 — Datasets & Benchmarks | **7** / Accept (borderline) | 6 / Borderline | **A** |
| R2 — Construct validity | **7** / Accept | 6 / Borderline | **A** |
| AC — Adversarial novelty/positioning | **5** / Borderline | 4 / Reject | **A** |
| R4 — Statistics & experimental design | **7** / Accept (leaning) | 6 / Borderline | **A** |
| **Mean** | **6.5** | **5.5** | **A (unanimous)** |

This corroborates the earlier independent P2-vs-P3 decision (P2) — now via four fresh, blinded reviewer lenses rather than the decision-analysis ensemble.

## The core trade-off the reviewers converged on

- **Higher ceiling: B (P3).** If every placeholder lands — clean single-dissociation ablations, the pattern generalizes across agents, the human study confirms C2/C3, Caesar is top-2 on grounding — B is the richer, more mechanistic, more citable paper. It answers *why*, not just *what*, and its draft carries better contamination hygiene and a larger item set (50 vs 30).
- **Higher floor / lower rejection risk: A (P2).** Removable agent, quarantined optional mechanism, cleanest novelty story, construct defined independently of any evaluated agent. Its worst case is "borderline/incremental," not "desk-reject."
- **All four picked the higher floor.** B buys its extra contributions precisely by leaning into the material that creates the shared *existential* risk (self-overlap with the authors' own Caesar preprint), and stakes a *general* title on one builder-owned system. "A wins in expectation; B wins only in the world where all placeholders land **and** self-overlap/COI/de-anonymization are all forgiven." (AC)

## Why A wins on each lens

- **Benchmarks (R1):** A reads as a *neutral community standard* (agent de-emphasized, not top-1, all findings hold with it excluded); B's co-hero framing + "our agent ranks top-2 on grounding" invites the self-serving-benchmark critique that most damages a benchmark submission. A also has the deeper, first-class judge validation.
- **Construct validity (R2):** A is the only draft that *empirically tests* discriminant validity (does *Surprising* carry variance beyond *New*?) via a pre-committed inter-axis correlation matrix + factor analysis, and it defuses the "predicted-null categories are exactly the judge-unreliable ones" confound with validity-stratified, human-primary scoring on C1/C5. B never checks N-vs-S dissociation and has a validation-format mismatch (1–10 CAT judge vs pairwise human study).
- **Adversarial AC:** B's single most likely rejection reason is *existential self-overlap* — agent, architecture, ablations, and cross-agent table all already in the cited preprint, plus a builder-owned co-hero. A's most likely rejection reason is thinner novelty over the same preprint, but A *minimizes* that shared risk instead of amplifying it.
- **Statistics (R4):** Both share the same machinery (crossed random effects, multiplicity, TOST, LOFO, length/budget controls). A's plan is scoped slightly *above* its claims (instrument + descriptive crossover, with honest power caveats). B takes on a *causal, mechanism-level* burden but backs it with n=1-agent ablations and load-bearing off-target equivalence tests it never concedes are underpowered, plus taxonomy-agent circularity A avoids by making no mechanism claim. "B's headline outruns its design."

## Consensus weaknesses to fix

**In A (the chosen paper) — all fixable, port from B:**
1. **Contamination/release machinery is under-specified in the paper text** (R1, decisive caveat): B's draft §3 explicitly states SHA-256-hashed snapshot, canary strings, rolling brand-new-question set, Croissant metadata; A's §3 names only frozen snapshot + pre/post-cutoff split + datasheet. **Port B's contamination hygiene language into A's §3 and ship the datasheet.** (Structural in B; a one-paragraph omission in A.)
2. **Small item set** (R1, R4): 30 items, ~6/cell — the crossover interaction and TOST equivalence A leans on hardest are the most power-hungry tests. **Scale toward ~50 items (~10/cell)**, as B already specifies.
3. **Soft taxonomy cell** (R2): C4 "meta-creativity" lacks a mechanism of Gentner/Byrne-level rigor. Tighten its theoretical grounding.
4. **§7 dilemma** (R2): if the optional IP-gated mechanism case study is *kept*, it re-imports the single-entrant COI it was designed to avoid; if *dropped*, the finding stays abstract. Keep it removable and gated on Caesar not being top-1 (as designed).

**In B (not pursued) — mostly structural, not cheaply fixable:**
- Self-serving co-hero framing + existential self-overlap with the preprint; single-agent generality on a general title; §6 "Caesar top-2" showcase; COI/double-blind/IP exposure from describing the authors' own agent; no discriminant-validity test; pairwise-vs-1–10 validation mismatch.

## Decision

**Ship Paper A (P2, `paper_p2_benchmark_only/`).** Absorb B's two cheap wins — contamination/release hygiene in §3 + the datasheet, and a larger item set — without absorbing B's framing risk. Keep the P3 hybrid (`paper_p3_caesar_hybrid/`) on the shelf as the **IP-gated upgrade path**: it becomes viable only if the five pre-registered triggers go green (Caesar clearly not top-1, cross-agent generality confirmed, judge↔human agreement secured on C1/C5, IP clearance to describe the agent, and the ablation single-dissociation holds).

---

## Round 2 re-review (post-revision: 50 items, upgraded judge, short prompts)

After the fix sweep — scaled to **50 challenges (10/category)**, agent-facing prompts made **short and open** with all rigor held judge-side, a **multi-vendor LOFO + open-weight, human-validated** judge, the renamed **factual-grounding check**, implemented statistics, and an honest live-web pilot — the same four reviewers re-reviewed both papers. **Verdict unchanged: unanimous 4–0 for P2.**

| Reviewer (lens) | P2 | P3 | Stronger |
|---|---|---|---|
| Datasets & Benchmarks | **7** Accept(borderline) | 5 Borderline | **P2** |
| Construct validity | **6** Borderline(lean accept) | 4 Reject | **P2** |
| Adversarial Area Chair | **6** Borderline | 4 Reject | **P2** |
| Statistics & design | **6** Borderline(accept-leaning) | 4 Reject | **P2** |
| **Mean** | **6.25** | **4.25** | **P2 (unanimous)** |

**What the revision changed:** the shared upgrades **lifted P2's floor from ~borderline-reject toward borderline-accept** — the scale-up + implemented stats + the discriminant-validity (New-vs-Surprising factor) test directly answered round 1's power and construct-validity critiques. They did **not** move P3's binding constraint: self-overlap with the authors' own preprint + COI (agent as co-hero, the "our agent ranks top-2" grounding showcase) + a **causal, mechanism-level claim whose limiting unit is a single agent (n=1)** — which the stats reviewer notes *item-scaling structurally cannot fix* (you need more agents, not more items). P3 retains the higher ceiling if every placeholder lands; P2 retains the decisively higher floor. **Decision stands: ship P2; keep P3 as the IP-gated upgrade path.**

*Reviewer transcripts synthesized from two rounds of four parallel `general-purpose` agent reviews; scores on the ICLR 1–10 scale.*
