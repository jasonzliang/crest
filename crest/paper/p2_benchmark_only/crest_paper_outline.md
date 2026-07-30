# CREST — ICLR 2027 Paper Outline (P2, benchmark-hero)

**Title (working):** *When Does Web Search Make a Research Agent Creative? The CREST Benchmark.*
**Thesis:** creativity of deep-research web agents is measurable, axis/task-dependent, and holds across the frontier — and it is the value-bearing axis no existing benchmark scores.
**Framing:** P2 — the released benchmark + the cross-agent finding are the contribution; Caesar is one *cited* entrant (arXiv:2604.20855). The Caesar mechanism ablation is an OPTIONAL, IP-gated §7 (P3 upgrade), included only if all five decision triggers are green.

Each section lists the reviewer objections it must close (see `reviewer_objections.md`).

- **00 Abstract** — gap, CREST, the cross-agent axis-dependence finding, the grounding gate, release. *(closes O10 framing)*
- **01 Introduction** — everyone scores accuracy/coverage/faithfulness; nobody scores creativity of a *web-grounded* agent. Preview the finding. **Explicit delta-vs-prior-work paragraph.** *(O1, O10, O17)*
- **02 Related Work** — differentiation table vs deep-research eval (accuracy/coverage/faithfulness) and vs creativity/ideation eval (ungrounded); the empty intersection. *(O1, O2 positioning, O17)*
- **03 Benchmark Design** — construct grounding (Runco&Jaeger + Boden + Amabile CAT); 5 categories × ≥6 domains; per-item dated known-answers + hard rules + expert baseline; frozen snapshot + shared index; pre/post-cutoff. *(O2 construct, O9 contamination)*
- **04 The Judge and Its Validation (LOAD-BEARING)** — LOFO multi-vendor + open-weight panel; blind + order-randomized; human-expert CAT validation; per-category α/ICC; discriminant vs accuracy/verbosity; "novelty mirage" as the threat model. *(O2, O3, O4, O7)*
- **05 Experiments — the cross-agent finding** — pre-registered per-category predictions; validity-stratified results (human scoring on C1/C5); **crossover/rank-reversal interaction test**; per-item mixed-effects + TOST + CIs; length as covariate; budget parity; diversity signal. *(O3, O5, O6, O8, O11, O15)*
- **06 Grounding side-check (cross-agent)** — FACT citation-faithfulness gate (fail ⇒ creativity 0) on all agents' outputs; hurdle model for zero-inflation; "creative AND grounded." *(O16, O2-usefulness-gate)*
- **07 [OPTIONAL/IP-gated] Mechanism case study** — compact, caveated Caesar ablation (cite preprint); Caesar not top-1; excisable. *(P3 upgrade only)*
- **08 Limitations** — the irreducible residual risks (power-vs-multiplicity at N≈30; closed-agent non-reproducibility; frozen-index realism tradeoff; correlated judge errors; length-as-mediator; N/U/S under-identification; COI). *(honesty; O5,O6,O7,O8)*
- **09 Conclusion** — creativity is the next axis; CREST + finding + release.
- **Ethics / Reproducibility / Datasheet** appendices — COI statement; IRB/consent/pay; Croissant+RAI; pinned judge snapshots; anonymized harness + DOI. *(O6, O12, O13, O14)*

**Venue rule:** ICLR main only if §5 delivers a robust theory-predicted crossover; else NeurIPS Datasets & Benchmarks. (See `reviewer_objections.md` venue implication.)
