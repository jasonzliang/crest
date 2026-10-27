# CREST — Reviewer Objections Register (governing checklist)

Consolidated from a 4-lens ICLR-2027 red-team: **Novelty & Positioning**, **Methodology & Soundness**, **Benchmark Integrity / COI**, and **Significance / Area-Chair**. Ranked by likelihood × severity.

**How to use this file:** every LaTeX section and code component drafted for CREST must *visibly close* the objections assigned to it (see the Section-Ownership Map at the bottom). Objections that cannot be fully closed are listed honestly under "Irreducible residual risks" — the paper must *acknowledge* those in Limitations, not hide them.

**One confirmed load-bearing fact (verified against arXiv:2604.20855 §5.1):** the Caesar preprint *already publishes, verbatim,* the five categories (Constrained Synthesis, Counterfactual Reasoning, Cross-Domain Synthesis, Meta-Creativity, Open-Ended Synthesis), the New/Useful/Surprising 1–10 rubric, a cross-agent table (Caesar vs Gemini 3 / Sonnet 4.5 / GPT-5.2), the 3-judge panel + self-preference analysis, and two ablations. This is the root of objections #1, #2, #6 below.

---

## TIER 1 — CRITICAL / potentially decisive (fix these or don't submit to ICLR)

### O1. Self-overlap with the authors' own preprint → "no novel contribution" (EXISTENTIAL)
- **L×S:** High × Critical (desk-level for a skeptic who opens the cited preprint).
- **Defense:** Front-load an explicit **delta-vs-prior-work paragraph in §1**. The genuinely new objects — and the *only* ones — are: (a) **scale** (5 single queries → ~30 challenges × ≥6 domains; per-cell n≥5 vs n=1); (b) a **released, versioned public artifact** (rubric + judge harness + frozen snapshots; the preprint released none); (c) a **multi-agent field** where Caesar is one de-emphasized entrant; (d) the **axis-dependence finding as a pre-registered hypothesis test** (never claimed in the preprint). Position CREST as *measurement + finding*, not the agent.
- **Residual:** the taxonomy + rubric are **not** novel to CREST. Whether "scale + release + reframe" clears ICLR-main novelty is a genuine coin-flip. **This is the paper's existential risk.** Do not hope the reviewer won't open the preprint — it is cited by number.

### O2. Construct validity — is N/U/S actually *creativity*, and is "Surprising" discriminant from "New"?
- **L×S:** High × High. In the preprint's own Table 1, New ≈ Surprising are near-collinear (Caesar 8.64 / 8.27).
- **Defense:** Ground the construct in **independent theory** — Runco & Jaeger (novelty + usefulness = the standard definition), Boden (+ surprise), Amabile's Consensual Assessment Technique for scoring — and cite the **cog-sci sources, not the Caesar preprint,** as the rubric's provenance. Add a **discriminant-validity study**: inter-axis correlation matrix + factor analysis proving Surprising carries variance beyond New; **convergent validity** vs a human-expert CAT panel *across all agents*; and **discriminant from accuracy and verbosity**.
- **Residual:** may empirically collapse to a 2-factor (novelty + value) construct; factor structure is under-identified at N≈30. If the correlation stays high, "creativity ≠ novelty" fails. Data-determined; cannot be pre-argued.

### O3. The flagship finding is confounded with judge-invalidity (near-fatal)
- **L×S:** Very High × Very High. The C1/C5 **nulls coincide exactly** with the two categories where the LLM judge fails human agreement — so "axis-dependent creativity" is indistinguishable from "axis-dependent judge failure."
- **Defense:** Report **α/ICC per category** (never pooled); **validity-stratified results** separating judge-valid cells (C2/C3/C4) from judge-invalid cells (C1/C5); make the **human panel the primary scorer for C1/C5** and re-run the null test on human scores; label sub-threshold cells **"measurement inconclusive," not "null."** Do not present C1/C5 nulls as confirmed predictions.
- **Residual:** even human-scored, C1/C5 stay underpowered (O5); cannot prove a true null vs Type II error. Dampen, don't dissolve.

### O4. Construct validity + a *reproducible* judge is THE accept gate (AC meta-verdict)
- **L×S:** High × Critical (the necessary condition for everything else).
- **Defense:** Make **§4 (judge validation) the load-bearing section**: released runnable judge; agreement with human-expert creativity ratings; reported reliability; discriminant from accuracy/verbosity. If the measure isn't credibly creativity *and* reproducible, the finding and the significance story mean nothing.
- **Residual:** creativity has no ground truth; CAT + reliability bounds subjectivity but never removes the judge-defines-construct circularity.

---

## TIER 2 — HIGH (score-depressing; several are partial-fix-only)

### O5. Statistical power — ~5–6 items/cell cannot support null/parity claims
- **Defense:** mixed-effects (items + domains crossed random effects); **MDE / power curves for every null**; **TOST equivalence tests** so nulls read as evidence-for-null; **positive controls** (strong C2/C3 signal proves the instrument is sensitive); effect sizes + CIs everywhere; replace "null/parity" with "not detectable at N; CI includes zero." **Highest-leverage single change: expand N.**
- **Residual:** power vs multiplicity is **unwinnable at N=30** (correction annihilates power; crossed random effects go singular). Honest posture: nulls/parity are *hypothesis-generating*, only the largest wins are confirmatory.

### O6. COI / self-serving benchmark — builder also competes (post-"Leaderboard Illusion")
- **Defense:** a **prominent COI statement** (anonymized), not a citation; **pre-register outcome-independence** (the contribution is the benchmark+method regardless of where Caesar lands); engineer for **Caesar-not-first + full removability** (all headline findings hold with Caesar excluded); LOFO judging; **budget parity**; if Caesar wins, an extraordinary-evidence bar (replicate under LOFO + human CAT + alt-rubrics + hidden split; no screenshots).
- **Residual:** builder-run results are down-weighted regardless of controls; the only clean outcome is *a frontier agent first, Caesar strong-but-second.* You don't control where it lands.

### O7. LLM-judge bias — documented ±2.5-pt self-preference in the preprint (Table 2)
- **Defense:** LOFO + multi-vendor + ≥1 open-weight + majority vote; **blind judging** (no agent identity/family); **human-IRR** (κ/ICC ≥ ~0.75 target); show the axis-dependence pattern is **invariant across judge backbones**.
- **Residual:** frontier judges share RLHF-induced biases (verbosity, sycophancy) → panel diversity does *not* cancel them; the open-weight judge is weaker, so the panel is dominated by correlated frontier judges.

### O8. Length/verbosity confound (r = 0.47 in the preprint)
- **Defense:** length as a **covariate in the mixed model** (bins fail at N=30 — ~2 items/bin); report within-covariate effects; frame **confound vs mediator** explicitly.
- **Residual:** length may be a *mediator* of creativity (elaboration is part of the act) — "controlling" it risks over-correction; shared judge length-bias persists.

### O9. Contamination — "novelty = fetched fresher pages," not synthesis
- **Defense:** post-cutoff subset + **frozen dated snapshot + one shared search index** (neutralizes recency); define "New" relative to a **fixed reference corpus**, not the judge's cutoff; FACT gate blocks hallucinated novelty; report pre/post-cutoff split.
- **Residual:** freezing the index removes the live-retrieval skill deep-research agents exist for (realism tradeoff); must report live **and** frozen; they may disagree.

### O10. "So what?" — is agent creativity important now, or niche? (AC significance)
- **Defense:** frame the measurement gap precisely — every existing agent eval scores accuracy/coverage/faithfulness/completion; creativity is the axis separating a **research collaborator from a search summarizer**, and it's the unmeasured one; tie to the AI-co-scientist moment.
- **Residual:** an AC may deem it premature (reliability/accuracy is the binding constraint; creativity a "luxury metric"), or "interesting but boutique."

### O11. Axis-dependence looks obvious / post-hoc
- **Defense:** harden from "scores vary by task" to a **theory-predicted crossover / rank-reversal interaction** (the agent most creative on New is *not* the one most creative on Surprising; Gentner-analogy creativity dissociates from Byrne-counterfactual); pre-register the predictions; report the agent×axis interaction test with CIs.
- **Residual:** "obvious in hindsight" is irreducibly subjective; the interaction may not reach robustness at N≈6/cell.

---

## TIER 3 — MEDIUM (checklist-satisfiable; mostly desk-reject-preventable)

- **O12. Releasability** (licensing, snapshots, IRB, dual-use): release **URLs + timestamps + content hashes** (not scraped content) with per-source license; artifact license (Apache-2.0 / CC-BY); **IRB approval or documented exemption + consent + fair pay + de-identification** for the (external) rater study; dual-use harm statement with the FACT gate as guard + content screening. *Residual:* web-corpus licensing is never fully clean; IRB-exemption boundaries vary.
- **O13. Gaming + reproducibility of a released judge benchmark:** hidden held-out split; a **creativity-hack red-team** (show verbosity/keyword-stuffing does NOT inflate CREST); pinned judge snapshots + prompts + seeds; Docker + lockfile + verify.py + SHA-256 at a tagged anonymized commit + Zenodo DOI; report a **reliability/drift envelope + rank-stability** (bit-reproduction is impossible with drifting judges); living-benchmark governance (no builder-privileged post-release access). *Residual:* no public judge benchmark is gaming-proof; held-out splits leak over time.
- **O14. Double-blind de-anonymization:** strict **third-person** Caesar citation ("prior/concurrent work by a group we do not identify"); git filter-repo history rewrite + PDF/EXIF scrub + fingerprint scrub (e.g., status lines, "fourth pillar" phrasing); anonymized repo; **route the COI to the AC**. *Residual:* a publicly-named agent is guessable by an expert — document to the AC as accepted risk.
- **O15. Cross-agent fairness:** normalize tool/compute budgets (equal search-call cap, token/wall-clock); report a **cost-vs-creativity Pareto frontier** rather than a single rank. *Residual:* heterogeneous agent architectures make perfect parity ill-defined.
- **O16. FACT hard-zero gate:** validate the gate (precision/recall vs human faithfulness labels); sensitivity with/without + graded vs binary; report per-agent firing rate; use a **hurdle/two-part model** for the resulting zero-inflation. *Residual:* the gate itself is an LLM-judge with error and can fire differentially by agent.
- **O17. Venue fit (ICLR main has no D&B track):** lead with the *finding + theory-grounded framework*, not the artifact; cite ICLR precedent for accepted analysis/benchmark papers. *Residual:* structural ~0.5–1-point tax some reviewers won't drop.

---

## Irreducible residual risks (state plainly in Limitations)
1. **Power vs multiplicity is unwinnable at N≈30** — nulls/parity are hypothesis-generating, not confirmatory.
2. **Closed-agent results are not reproducible** — only time-indexed snapshots; the reproducible core is (open-weight agent + frozen index).
3. **Freezing the index changes the task** — removes the defining live-retrieval capability; report both regimes.
4. **Multi-vendor judges do not give independent errors** — shared RLHF biases; panel diversity ≠ bias cancellation.
5. **Length may be a mediator, not a confound** — no purely statistical adjustment resolves it.
6. **N/U/S dimensionality is theory-supported but data-under-identified** at N≈30.
7. **Creativity has no ground truth** — the judge-defines-construct circularity is bounded, not eliminated.
8. **COI vs double-blind vs construct-capture-assessment is an irreducible three-way tension** — surface it to the AC explicitly.

## Required artifacts (pre-empt desk-level concerns)
- **Datasheet (Gebru et al.):** motivation incl. COI; composition (instances, splits incl. hidden, copyright/PII/dual-use flags); collection (authoring + scraping/freezing dates + robots.txt/ToS); labeling (rubric + **cog-sci provenance, not Caesar** + judge versions + rater protocol); uses (out-of-scope, gaming vectors); distribution (artifact license + per-source corpus license + URL/hash mechanism + DOI + versioning); maintenance (refresh/contamination policy, judge-snapshot retention); human-subjects (IRB/exemption, consent, pay).
- **Ethics statement:** COI + enumerated controls (LOFO, pre-registration, Caesar excluded from rubric design, human validation, outcome-independence, budget parity); IRB/consent/pay; copyright/robots/PII; dual-use analysis.
- **Reproducibility statement:** OSF pre-registration (frozen rubric/weights/decision rules, timestamp predating scoring); pinned judge snapshots + prompts + seeds + retention; frozen corpus + hashes + live/frozen modes; full harness (Docker + lockfile + verify.py + SHA at tag, anon repo, DOI); reliability reporting (ICC/κ, human-LLM concordance, drift envelope, calibration set); statistical protocol.

## Prioritized fix order (highest leverage first)
1. **Sever the rubric's provenance from Caesar** and prove **construct validity** against human consensus on non-Caesar agents (O2, O4, O1).
2. **Pre-register** taxonomy, items, and the "predicted nulls"; **independent/blind item authoring** with held-out replication (O1, O6, O11).
3. **Validity-stratified reporting** + human scoring on C1/C5; **per-category α/ICC** (O3).
4. **MDE/power + effect-size/CI + TOST**, replacing all "null/parity" language; **expand N** if at all possible (O5).
5. **Prominent COI statement** + engineer **Caesar-not-first + removability** (O6).
6. Length-as-covariate + confound/mediator framing; cross-backbone judge invariance (O7, O8).
7. Datasheet / ethics / repro / anonymization / anti-gaming (O12–O16) — checklist-satisfiable.

## Venue implication (from the AC lens)
As designed (~30 items, subjective judge, finding not yet a crossover) → **NeurIPS Datasets & Benchmarks maximizes both the fair significance read and acceptance odds** (its reviewers weigh construct validity / datasheets / reproducibility as native strengths, not reject triggers). **ICLR main wins only if the axis-dependence result is hardened into a statistically robust, theory-predicted rank-reversal** — then it is a *findings* paper and ICLR's audience amplifies it. Provisional AC read on the current draft: **borderline-reject at ICLR main, borderline-accept at NeurIPS D&B.**

---

## Section-Ownership Map (what closes what in the paper/code)
| Objection | Owner (paper section / artifact / experiment) |
|---|---|
| O1 self-overlap | §1 delta paragraph; §2 related-work table; pre-registration |
| O2 construct/discriminant validity | §3 construct grounding; §4 validity study (inter-axis corr + factor analysis + human CAT) |
| O3 nulls⟂judge-invalidity | §4 per-category α/ICC; §5 validity-stratified results (human scoring on C1/C5) |
| O4 reproducible judge | §4 (load-bearing); released judge harness |
| O5 power | §5 stats (mixed-effects, MDE, TOST, CIs); dataset size |
| O6 COI | COI statement; §5 removability + Caesar-not-first; ethics |
| O7 judge bias | §4 LOFO + blind + backbone-invariance |
| O8 length | §5 length-covariate + confound/mediator |
| O9 contamination | §3 frozen snapshot/shared index; §5 pre/post split |
| O10 significance | §1 motivation |
| O11 obvious/post-hoc | §5 crossover-interaction test; pre-registration |
| O12 releasability | datasheet + ethics + repro |
| O13 gaming/repro | repro statement; harness; hidden split; creativity-hack red-team |
| O14 anonymity | submission hygiene; third-person citation |
| O15 fairness | §5 budget parity + Pareto |
| O16 FACT gate | §6 grounding (gate validation + hurdle model) |
| O17 venue | framing / venue decision |
