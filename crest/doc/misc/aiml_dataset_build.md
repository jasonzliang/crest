# AI/ML CREST dataset — build report

> ## ⚠ THIS REPORT DESCRIBES A SUPERSEDED BUILD (annotated 2026-07-31)
>
> It documents the **41-item** intermediate state. The shipped file
> `questions/crest_aiml_challenges.jsonl` now has **50 items, 10 per category**: ids `00`–`40` are
> unchanged and every per-item finding below still points at a real item, but ids **`41`–`49` are
> new (C4 ×3, C5 ×6) and are covered by NOTHING in this report** — no audit record, no
> discrimination review, no dedupe check.
>
> Three items this report marks BLOCKING are **CLOSED**:
> - §8.1 the 9 missing items — authored and appended as `_41`–`_49`.
> - §7 schema incompatibility — `questions/schema.json` is now `crest-challenge/3.2.0` with the
>   twelve-value `domain` enum, and all 50 items load and validate.
> - §8.2's provenance loss — the C5 source is tracked at
>   `questions/aiml_build/c5_source_verbatim.json`. The *unaudited* half of §8.2 still stands.
>
> §5's distributions are re-measured in place below. §0, §4 and §7 are superseded and cut to their
> surviving conclusions. **This dataset is not wired into `config/eval_config.yaml`, has no
> `item_design.jsonl` rows (so `ci_check.sh`'s bijection check does not cover it), and has never
> been run or scored.** It is not the dataset any published CREST number refers to.

Built 2026-07-31. Output: `questions/crest_aiml_challenges.jsonl`
(one JSON object per line, UTF-8, LF-terminated).

---

## 0. HEADLINE — the build shipped 41 of 50; the remaining 9 were authored later. **CLOSED.**

At build time the five category batches were not all available: C1/C2/C3 had 10 each on disk, C4
had **7** (`questions/c4_ml_new10.audited.json`, committed mid-audit), and C5 had **no source file
at all** — 5 items were transcribed verbatim from the task prompt, and the prompt itself cut off
inside item 6. Minus one cross-category duplicate (§3) ⇒ **41 shipped**. Nothing was invented to
reach 50 at the time, which was the right call: the alternative was authoring 8 items with
fabricated prior-art catalogues.

**The 9 were authored separately and appended as ids `_41`–`_49`, so the file is 50/50 and squared
at 10 per category.** They were NOT produced by this build and carry none of its audit apparatus —
see the header. The C5 transcription is now tracked at
`questions/aiml_build/c5_source_verbatim.json`; it remains **unverified against any original**
(§8.2).

---

## 1. Per-category verdict counts

### 1a. Audit activity (pre-audit vs post-audit artifact diff)

C1, C2 and C3 each have both a pre-audit and a post-audit artifact on disk, so the auditor's
verdicts are recoverable exactly by diffing them.

| Batch | Items touched | `known_answers` added | amended in place | deleted | `hard_rules` added | amended | `expert_baseline` rewritten |
|---|---|---|---|---|---|---|---|
| C1 | 10 / 10 | +41 | 7 | −6 | +7 | 4 | 6 |
| C2 | 10 / 10 | +35 | 9 | −5 | +10 | 4 | 10 |
| C3 | 10 / 10 | +17 | 11 | −1 | +1 | 1 | 1 |
| C4 | 7 / 7 (no pre-audit copy retained) | n/a | n/a | n/a | n/a | n/a | n/a |
| C5 | **0 / 4 — NEVER AUDITED** | — | — | — | — | — | — |

**Every C1/C2/C3 item was modified by its auditor. None passed clean.** 100% touch rate across
30 items is the headline verdict number.

C4's audited file has no retained pre-audit sibling, so its verdict counts cannot be
reconstructed; its corrections are visible only as in-artifact prose (its `known_answers`
preambles all carry the "dated by FIRST publication (arXiv v1 or first venue), not by a later
version, rebranding or product name" rubric, which is the C4 auditor's signature).

**C5 was never audited at all.** It is the only batch in the file with no audit provenance.

### 1b. Audit apparatus surviving in the shipped file

| Batch | n | `known_answers` (mean) | `hard_rules` (mean) | `NEGATIVE RESULT` | `KNOWN AND BINDING` | `CONCEPT DATE NOTE` |
|---|---|---|---|---|---|---|
| C1 | 10 | 244 (24.4) | 73 (7.3) | 0 | 0 | 0 |
| C2 | 10 | 173 (17.3) | 65 (6.5) | 0 | 66 | 0 |
| C3 | 10 | 126 (12.6) | 71 (7.1) | **10 (one per item)** | 0 | 0 |
| C4 | 7 | 179 (25.6) | 57 (8.1) | 0 | 0 | 0 |
| C5 | 4 | 89 (22.2) | 20 (5.0) | 0 | 0 | 7 |

Each batch's auditor used a different marker convention. C3's ten `NEGATIVE RESULT` blocks each
record the exact searches run and state "absence of evidence only; a contesting citation
overrides this entry" — the most honest of the four conventions. C2's 66 `KNOWN AND BINDING`
tags mark facts an answer may not contradict. C5's 7 `CONCEPT DATE NOTE` tags are the only
audit-shaped content in that batch, and they were authored with the items, not by an auditor.

C5's rule count (mean 5.0) is visibly thinner than every other category (6.5–8.1). See §8.4.

---

## 2. Fabrication and date errors caught, and how each was resolved

**Zero outright fabrications were found in any batch.** Every named paper, DOI, arXiv id,
statute and system in the shipped file resolves to a real artifact. The defect class that
actually dominated is **concept-date inflation**: prior art dated to a later paper, product
launch, rebranding or venue rather than to first publication. In every case found, the error
ran in the direction that makes the prior art look *younger* — i.e. that makes a submission
look *more novel* than it is, which directly inflates the New score. Not one error ran the
other way.

### 2a. C1 — architecture / alignment / systems

| Item (final id) | Defect | Resolution in shipped file |
|---|---|---|
| `C1_architectures_training_00` | Constant-size recurrent state credited to Mamba (2023) | Rewritten to credit **S4 (2021, arXiv:2111.00396)** as establishing the constant-size recurrent state; Mamba demoted to "added input-dependent selection", Mamba-2/SSD to the scan. Now reads "KNOWN from 2021, **not 2023**". |
| `C1_architectures_training_00` | Delta-rule / gated linear attention dated 2023+ | Prepended **fast-weight programmers / delta-rule linear attention (2021, arXiv:2102.11174)**, with the note that the delta rule traces to Schmidhuber's 1992 fast weights. |
| `C1_architectures_training_00` | Compressive memory credited to Infini-attention (2024) / Titans | Rewritten as "Segment recurrence and learned compressive memory", now anchored at **Transformer-XL (2019, arXiv:1901.02860)** and **Compressive Transformer (2019, arXiv:1911.05507)**; reads "KNOWN from 2019, **not 2022-2024**". Titans redated to its true v1, **2024-12-31**, not 2025. |
| `C1_architectures_training_00` | Constant-time addressable memory missing | Added **Large Memory Layers with Product Keys (2019, arXiv:1907.05242)** — this closes a live novelty hole: the item's own R2 invites an O(1) lookup structure, and product-key addressing already is one. Also added AutoCompressors (2305.14788) and In-context Autoencoder (2307.06945). |
| `C1_architectures_training_01` | Router z-loss attributed to Switch Transformer | Corrected: Switch contributes "selective precision for router stability"; **the router z-loss itself is ST-MoE (2022), not Switch (2021)**. |
| `C1_architectures_training_01` | Node-limited routing credited to DeepSeek-V3 (2024-12) | New entry: **DeepSeek-V2 (2024-05, arXiv:2405.04434)** already has device-limited routing plus device-level and communication balance losses. "the node-limited constraint predates DeepSeek-V3". |
| `C1_architectures_training_01` | Expert Race (2503.16057) listed as a plain LM router | Qualified: "introduced for **diffusion transformers rather than decoder-only LMs**, and therefore batch-coupled in the sense R1 forbids". |
| `C1_alignment_safety_03` | AI-control baseline numbers quoted at the wrong audit budget | The published protocol menu (15%/100%, 62%/97%, 92%/94%) is from a **5,000-problem stream at a 2% budget**; this item specifies 10,000 tasks at **1%**. Rule text now says the numbers are known "**AT A 2% BUDGET** — an answer must rescale them to this item's 1% budget rather than quote them directly." This closes a scoring hole where a copied number would have read as a derived one. |
| `C1_systems_efficiency_06` | KV-quantisation citation list mis-grouped and one entry misdated | PolarQuant (2502.00527) and TurboQuant (2504.19874) moved into the rotation/transform group with correct descriptions; a duplicated TurboQuant/PolarQuant tail and a 2026 SAW-INT4 entry removed from the sub-2-bit group. |
| `C1_theory_learning_08` | Synthetic-textbook pretraining credited to Phi-4 (2024) | Corrected to **Textbooks Are All You Need / phi-1 (2023, arXiv:2306.11644)** first, with Phi-4 retained as the production follow-on. |

Plus 6 of 10 C1 `expert_baseline` fields rewritten, and 7 new / 4 amended hard rules — chiefly
the addition of the `R-CLOSEST PRIOR ART` numeric-delta disclosure rule, which is now present
in **all 10** C1 items.

### 2b. C2 — counterfactual worlds

| Item (final id) | Defect | Resolution |
|---|---|---|
| `C2_architectures_training_10` | Attention-sink mechanism stated wrongly ("sinks exist because softmax must allocate a full unit of mass") | Rewritten to the published account: sinks are **tied to** softmax's mass constraint, **function as key biases / an over-mixing brake**, and are attenuated when the normalisation is replaced. Added **Gu et al. 2024 (arXiv:2410.10781)** as the empirical study. |
| `C2_architectures_training_10` | Associative-recall gap credited to Zoology (2023) | Backdated by adding **H3 / Hungry Hungry Hippos (2022-12-28, arXiv:2212.14052)**. |
| `C2_architectures_training_10` | Low-bit-serving claim unqualified | Added the counter-evidence **Quamba (2024, arXiv:2410.13229)** documenting massive activation outliers in softmax-free recurrent models, plus a new hard rule forbidding "no softmax ⇒ low-bit is easy" without reconciling it. This inverts a claim the item would previously have rewarded. |
| `C2_architectures_training_11` | LLaDA described vaguely as "roughly comparable to a same-size autoregressive model" | Replaced with the paper's actual claims: 8B trained from scratch, competitive with LLaMA3 8B on ICL and (after SFT) instruction following, **beats GPT-4o on reversal poem completion**. |
| `C2_architectures_training_11` | The "16×" masked-diffusion figure used loosely | Pinned precisely: the **scaling rate** is comparable with a "relatively small compute gap"; the **16×** figure is specific to matching a KV-cached ARM's *text-generation* quality (while sampling ~1.4× faster). A hard rule now states that conflating the two is an error. |
| `C2_systems_efficiency_16` | "AI and Memory Wall" dated 2024 (arXiv) | Redated to first publication: **RISELab blog post, 2021-03-29**, then arXiv:2403.14123 (2024) and IEEE Micro. Entry now reads "2021/2024". |
| `C2_systems_efficiency_17` | **Materially stale law.** US Executive Order 14110's 10²⁶-op reporting threshold cited as operative | Corrected: EO 14110 was **revoked 2025-01-20 by EO 14179**. The operative operation-count thresholds as of this dating are **California SB 53** (Transparency in Frontier AI Act, signed 2025-09-29, in force 2026-01-01, >10²⁶ integer or FP operations) and **New York's RAISE Act**. |
| `C2_evaluation_benchmarking_15` | METR time-horizon result cited without its actual metric | Corrected to the **50%-task-completion time horizon**, with full author list and title. |
| `C2_alignment_safety_12`, `C2_alignment_safety_13` | Truncated "et al." author lists on load-bearing citations | Expanded (Wen/Zhong/Khan/Perez/Steinhardt/Huang/Bowman/He; Cunningham/Ewart/Riggs/Huben/Sharkey). |

**All 10** C2 `expert_baseline` fields were rewritten, and 10 new / 4 amended hard rules added.

### 2c. C3 — cross-domain imports

| Item (final id) | Defect | Resolution |
|---|---|---|
| `C3_architectures_training_20` | Price Equilibrium Routing dated 2025, incomplete citation | Corrected to **2026**, with authors (Zhao, Zheng & Zhang), Springer LNCS pp. 3–16, doi:10.1007/978-981-95-4972-6_1. This matters: it is flagged as the **CLOSEST market framing**, so its date sets the novelty bar. |
| `C3_architectures_training_20` | DA-MoE / ExpertFlow cited by title only, ExpertFlow mischaracterised | Authors added; ExpertFlow re-described as "an offloading/caching and token-scheduling system **rather than a budget rule**". |
| `C3_architectures_training_21` | Goyal et al. data-filtering scaling law presented as a text-pretraining result | Qualified: "**experiments are on vision-language web data rather than text-only pretraining**". |
| `C3_architectures_training_21` | Villalobos et al. cited under its 2024 title | Corrected: posted **2022-10-26** as "Will we run out of data? An analysis of the limits of scaling datasets in Machine Learning"; the commonly quoted title is the **2024 revision**. |
| `C3_alignment_safety_22` | Holmström career-concerns model dated 1999 (the reprint) | Corrected: **first circulated 1982** in *Essays in Economics and Management in Honor of Lars Wahlbeck*; RES 66(1):169–182 (1999) is the reprint. A 17-year error on the item's central imported result. |
| `C3_alignment_safety_22` | arXiv:2602.21556 described as contract design | Re-described as "a principal-agent **elicitation** framework for multi-model aggregation **rather than contract design proper**". |
| `C3_architectures_training_21` | Nonrivalry premise unchecked | The **DECISIVE DISANALOGY** entry (Jones & Tonetti 2020, AER, doi:10.1257/aer.20191330) plus a matching hard rule now force the answer to name the rival quantity, because Hotelling's rule is a theorem about a *rival* stock and text is nonrival. Without this the item rewarded "tokens are like oil". |
| all 10 C3 items | Novelty gates unbacked by a search | Each item now carries a **`NEGATIVE RESULT`** block naming the exact queries run on 2026-07-31 and stating "absence of evidence only; a contesting citation overrides this entry". |

### 2d. C4 — no pre-audit copy retained

C4's corrections are not reconstructible as a diff. What is verifiable in the shipped file:
each `known_answers` list opens with the first-publication rubric, and specific entries carry
corrective detail (e.g. `C4_architectures_training_30` dates the Needle-In-A-Haystack repo to
its **creation date, 11 November 2023**, and notes the URL now redirects;
`C4_architectures_training_31` marks LV-Eval's keyword-replacement design as "the closest
published control for the leakage problem this item names", i.e. an explicitly located
novelty bar rather than a bare citation).

### 2e. C5 — no audit

The 7 `CONCEPT DATE NOTE` entries in C5 were written with the items. They are correct as far
as they go and they are the right shape (Hopfield 1982 vs the 2020 attention-equivalence;
Schmidhuber 1992 fast weights vs the 2021 equivalence paper; Anil et al. 2021 prover-verifier
vs the 2024 legibility application; Cotra 2021 sandwiching vs the 2022 empirical study; Lord
1980 IRT vs the 1982 review; Curse of Recursion 2023 vs the 2024 *Nature* version, plus the
2022 Data Feedback Loops / corrupt-datasets precedents). But **no independent auditor has
checked C5's remaining ~82 catalogue entries**, and given that C1/C2/C3 each showed a 100%
item-level defect rate, the prior that C5 is clean is low. §8.2.

---

## 3. Items dropped

**One item dropped, for cross-category duplication.**

### `C5_alignment_safety_03` — DROPPED (dedupe against `C4_alignment_safety_32`)

Both items pose the same open problem: *detect reward hacking while an RL run is still going,
without a trustworthy gold signal, and report the overhead, the trigger threshold, the
false-alarm handling and the blind spots.* A single well-constructed answer satisfies both
asks. Lexical Jaccard on the two queries is only 0.103 — the collision is semantic, and was
caught by reading, not by the overlap scan.

`C4_alignment_safety_32` was kept and `C5_alignment_safety_03` dropped, for three reasons:

1. **Stronger discrimination.** C4 requires three distinct outputs (R1 genuine improvement;
   R2 proxy rising via a stylistic correlate; R3 *true quality rising while the proxy stays
   flat because the reward model underrates it*). R3 in particular is a discriminator that
   almost no naive answer produces. C5's only discrimination requirement is "name a class of
   hack it cannot catch."
2. **Validation protocol.** C4 rule (b) demands a positive control with reward hacking
   deliberately induced, plus a reported detection rate *and* false-positive rate. C5 has no
   validation requirement.
3. **C5's exclusion list leaks.** C5 bans reward-model ensembles, adversarial verifiers,
   CoT-reading monitors, KL/entropy penalties and post-hoc transcript review — but its own
   `expert_baseline` names the convergent answer as "a trusted held-out probe set scored
   periodically during the run", which **none of its own hard rules exclude**. The item
   therefore fails to box the expert baseline out, which is the entire point of a C5 item.
   That is an independent defect, not just a tie-breaker.

Cost: C5 falls from 5 items to 4.

### Not dropped, but adjacent — flagged for human adjudication

Five further pairs sit close enough that a reviewer should confirm the call. In each case the
*deliverable* differs even though the topic overlaps, which is the test applied here (would one
answer substantially answer the other?).

| Pair | Shared topic | Why kept |
|---|---|---|
| `C1_evaluation_benchmarking_04` / `C4_evaluation_benchmarking_34` | black-box contamination | C1 wants a **hypothesis test** (statistic, null distribution, provable FPR ≤ 5%, power); C4 wants an **effect-size estimate** (how many score points of inflation, with uncertainty). Different outputs, different access models. |
| `C1_evaluation_benchmarking_05` / `C4_evaluation_benchmarking_35` | emergence vs metric artifact | C1 is a **two-way** test on rich private data (12 checkpoints × 3 seeds, per-item scores, loss) with a rescoring-invariance requirement. C4 is a **three-way attribution** (measurement / models / mid-family pipeline change) from public reported scores, plus a forward prediction. |
| `C1_alignment_safety_03` / `C3_alignment_safety_23` | audit-budgeted oversight | C1 wants a **control protocol** with a safety probability against an adversary that picks its attack rate; C3 wants a **risk-limiting certification** (manifest, assorter, margin, escalation, conditional error bound α). |
| `C1_theory_learning_08` / `C3_architectures_training_21` / `C5_architectures_training_38` | the data wall | C1 wants a **non-divergence theorem** for self-training; C3 wants an **intertemporal depletion policy** (Euler/Hotelling condition); C5 explicitly **excludes** synthetic data and verifier RL, so C1's answer is inadmissible there. |
| `C2_evaluation_benchmarking_14` / `C5_evaluation_benchmarking_40` | contamination-free evaluation | C2 is counterfactual **consequence reasoning** about a world where the artifact exists; C5 is the **design** of the artifact. |

Cross-category lexical Jaccard was computed for all 695 cross-category query pairs. Maximum
was 0.129 (`C1_theory_learning_08` / `C5_architectures_training_38`); the whole distribution
is low, so no pair is a textual near-duplicate.

**No items were dropped for schema failure.** All 42 candidates passed every content check.

---

## 4. Schema enforcement

The build-time checker (`.tmp_build/assemble.py`) passed 0 errors on the 41 items it wrote. **This
section is superseded by the live gate**: all 50 items now validate against
`questions/schema.json` (`crest-challenge/3.2.0`) via `harness/run_crest.load_challenges`, which is
the check that matters. The one build-time convention worth keeping on the record:

- Every item's `known_answers` carries ≥ 8 *substantive* entries with both a resolvable identifier
  (arXiv id / DOI / stable URL) **and** a 4-digit year, on top of a leading `Dated as of …`
  preamble entry that carries neither by design and is excluded from that count. (This is a
  markedly stricter dating bar than the shipped CREST set achieved — `datasheet.md` §2.)

Two `known_answers` entries do not match the identifier/year regex and were manually cleared
as false positives, not defects:

- `C2_systems_efficiency_17` — the BIS advanced-computing control entry. Its identifier is the
  **ECCN (3A090)** and the Total Processing Performance metric, not an arXiv id or DOI. Valid.
- `C3_systems_efficiency_27` — the MQA/GQA/MLA cache-reduction entry. Carries three arXiv ids
  (1911.02150, 2305.13245, 2405.04434) but no spelled-out year; the years are encoded in the
  arXiv ids. Valid, though spelling out "2019 / 2023 / 2024" would be more consistent with the
  rest of the file.

---

## 5. Distributions

**Re-measured 2026-07-31 on the shipped 50-item file** (the 41-item tables this section originally
carried are gone; they described the intermediate build).

**Category:** 10 / 10 / 10 / 10 / 10 — squared.

**Domain × category** (all six AI/ML domains used; still not square):

| domain | C1 | C2 | C3 | C4 | C5 | total |
|---|---|---|---|---|---|---|
| `architectures_training` | 2 | 2 | 2 | 2 | 2 | **10** |
| `alignment_safety` | 2 | 2 | 2 | 2 | 1 | **9** |
| `evaluation_benchmarking` | 2 | 2 | 2 | 2 | 1 | **9** |
| `systems_efficiency` | 2 | 2 | 2 | 2 | 0 | **8** |
| `theory_learning` | 1 | 1 | 1 | 1 | 3 | **7** |
| `multimodal_agents` | 1 | 1 | 1 | 1 | 3 | **7** |

C1–C4 are now identically shaped (2/2/2/2/1/1); the 6 late C5 items went to `theory_learning` ×3
and `multimodal_agents` ×3, so C5 is the odd row and `systems_efficiency` has **no** C5 item.

**Time sensitivity × category** — total 37 `pre_cutoff` / 8 `post_cutoff` / 5 `timeless`:

| | pre_cutoff | post_cutoff | timeless |
|---|---|---|---|
| C1 | 5 | 5 | 0 |
| C2 | **10** | 0 | 0 |
| C3 | 4 | 1 | 5 |
| C4 | **10** | 0 | 0 |
| C5 | 8 | 2 | 0 |

C1 is the only balanced category. **C2 and C4 are 100% `pre_cutoff`** — defensible on design
grounds (a counterfactual world and a measurement-invention task do not need a post-cutoff hook),
but the pre/post-cutoff contrast stays confounded with category: every `post_cutoff` item is C1,
C3 or C5. Any analysis crossing category with time sensitivity will not identify. §8.5.
NB this is the one place the AI/ML set is materially *better* than the shipped CREST set, which has
a single post-cutoff item (`datasheet.md` §2, "Splits").

**Axis isolated** — novelty 18, usefulness 11, balanced 11, surprise 10. Near-confounded with
category rather than perfectly confounded as at 41 items: C1 = `usefulness` ×10, C2 = `surprise`
×10, C3 = `novelty` ×10, C4 = `balanced` ×9 + `usefulness` ×1, C5 = `novelty` ×8 + `balanced` ×2.
C3 and C5 share the `novelty` label, so no axis label identifies a single category.

**Rule counts:** mean `hard_rules` per category 7.3 / 6.5 / 7.1 / 8.1 / 5.6 — C5 is still the
thinnest tier (§8.4). `known_answers` 10–30 per item; `expert_baseline` 517–2,408 chars.

---

## 6. Discrimination evidence, per item

"Discrimination" = the machinery in each item that separates a strong answer from the
convergent expert baseline. Each category uses a different device, and the strength is uneven.

### C1 (n=10) — program-checkable arithmetic + numeric prior-art delta

Every C1 item carries **`R-CLOSEST PRIOR ART`**: name exactly ONE published method and give a
**numeric** delta on the item's binding metric; "ours differs" with no number FAILS; a zero
delta honestly reported is allowed. That last clause is the real discriminator — it removes
the incentive to bluff. Plus item-specific arithmetic gates:

| item | binding numeric gate |
|---|---|
| `C1_architectures_training_00` | per-layer byte table summing to ≤ 2.56e8 bytes at L=1e6; R5 forces a bits-required-vs-bits-budgeted accounting, and the design **FAILS on its own arithmetic** if R5 > R1 |
| `C1_architectures_training_01` | R3 forces computing the random-routing reference (2048 ± Poisson, r≈1.07) rather than asserting balance; **R6** forces converting expert-level ratio r to device-level r_dev over 32 devices and using r_dev for any throughput claim |
| `C1_alignment_safety_02` | FLOP breakdown ≤ 1.3× vanilla PPO; R5 forces an eval-set size computation with clustered SEs such that the CI half-width is < 2% |
| `C1_alignment_safety_03` | expected audits ≤ 100 over 10,000 tasks, arithmetic shown, including audits triggered by resampling/escalation |
| `C1_evaluation_benchmarking_04` | R6 separates permutation replicates (free) from fresh model generations (costly) inside a 20,000-generation budget |
| `C1_evaluation_benchmarking_05` | R4 requires using the 1,000 per-item scores and per-checkpoint loss — a criterion from the 12 aggregate accuracies alone FAILS; R5 forces seed variance into the noise model |
| `C1_systems_efficiency_06` | R6 requires 128k degradation reported separately from short-context, because cache-quantisation error accumulates with sequence length and weight-quantisation error does not |
| `C1_systems_efficiency_07` | R3 requires a parametric verifier-score family jointly consistent with AUC 0.78 **and** FPR 12% |
| `C1_theory_learning_08` | effective-data multiplier over 400B real tokens, with the assumption that breaks first named |
| `C1_multimodal_agents_09` | R1 forces stating where the check runs and enumerating what an attacker who controls the context can see at that placement |

### C2 (n=10) — scope locks + explicit no-credit list

C2's device is negative: **66 `KNOWN AND BINDING` tags** naming facts the answer may not
contradict, plus 2 `KNOWN AND EXPLICITLY EXCLUDED FROM CREDIT` tags naming the obvious answer
so it earns nothing. Examples that bite hard:

- `C2_architectures_training_10`: prefill/decode accounting rule — "long inputs become free" is
  invalid; and the low-bit-serving rule that must be reconciled with Quamba's outlier evidence.
- `C2_architectures_training_11`: "this world has no reversal curse" is **explicitly excluded
  from credit** (it is arXiv:2406.05183), and so is "they would invent a block-wise cache"
  (arXiv:2503.09573, arXiv:2505.22618).
- `C2_alignment_safety_12`: must name a respect in which the world is **less safe**, and must
  distinguish exploiting reward-model error from tampering with the reward channel.
- `C2_evaluation_benchmarking_15`: must separate predictability of **capability** from
  predictability of **propensity**.
- `C2_multimodal_agents_19`: must not conflate semantic transfer with transfer of computational
  structure (arXiv:2103.05247).

**Weakness:** 4 of 10 C2 items (`_11`, `_13`, `_14`, `_17`) have **no explicit discrimination
clause** in `hard_rules` — they rely entirely on the `known_answers` no-credit list. That is
weaker than an in-rule gate, because a judge reading only the rules will not see it.

### C3 (n=10) — novelty gate + negative-result search

**Every C3 item carries a `NOVELTY GATE` rule naming the specific convergent answer that earns
zero**, which is the sharpest discrimination device in the file. Each gate is backed by a
`NEGATIVE RESULT` block recording the exact searches run.

| item | the answer that scores zero |
|---|---|
| `_20` MoE apportionment | any correspondence in the prior-art set; must exceed all of them |
| `_21` Hotelling data | ditto, plus the rivalry rule forces naming what is actually depleted |
| `_22` contract theory | "optimization distorts effort toward measured dimensions" (arXiv:2603.28063) |
| `_23` election audits | "sample outputs for human review, prioritised by a monitor score, under a fixed budget" (arXiv:2312.06942) |
| `_24` capture-recapture | running or combining existing contamination detectors, or moving to a fresh benchmark |
| `_25` Signor-Lipps | "emergence is a metric artifact" / "continuous metrics smooth the curve" |
| `_26` von Neumann multiplexing | stochastic rounding, loss scaling, higher-precision outliers, block scaling, smooth precision scaling laws |
| `_27` reservoir design | evicting low-attention tokens, sinks + recent window, paging, learned eviction, architectural cache shrinkage |
| `_28` island biogeography | replay buffers, weight regularisation, "larger models forget less" |
| `_29` immunology | trained injection classifier, instruction hierarchy, provenance capability restriction, sandboxing, dual-LLM quarantine |

### C4 (n=7 of the shipped 10 — `_41`/`_42`/`_43` not reviewed) — named discrimination cases with labelled arms

C4 is the only category with an explicit, uniformly-applied `DISCRIMINATION CASE` rule, and it
names the arms:

| item | arms | must produce |
|---|---|---|
| `_30` routing quality | M1 token-identity-deterministic router vs M2 context-dependent router | different scores, direction justified, plus where M1 falls relative to the permutation null. Rule (c) additionally pins the **permutation null to the floor**, so perfect load balance alone cannot raise the score |
| `_31` effective context | L1 lexical-match-only vs L2 k dispersed facts | distinct outputs; a single scalar that ties them FAILS |
| `_32` reward hacking | R1 real improvement / R2 stylistic correlate / R3 real improvement the proxy misses | three distinct outputs; collapsing R2 with R3, or R3 with "no progress", FAILS |
| `_33` explanation believability | E1 large explanation, high in-sample fit, no transfer vs E2 smaller explanation that transfers | distinct scores |
| `_34` contamination inflation | C1 verbatim memoriser vs C2 genuinely strong model | distinct outputs, plus rule (d) requires the difficulty-matching control between seen and unseen items be **established and verified** |
| `_35` emergence attribution | J1 vanishes under graded rescoring / J2 survives rescoring / J3 pipeline change | three distinct verdicts |
| `_36` reasoning-budget fairness | S1 high peak at large budget, flat low-budget vs S2 lower peak, strong low-budget | distinct rankings |

### C5 (n=4 of the shipped 10 — `_44`–`_49` not reviewed) — exclusion lists only

C5's device is the query-level exclusion list plus, in two items, an `expert_baseline` that
explicitly says the convergent answer is itself excluded:

- `C5_architectures_training_37`: "the specific fix most experts reach for first, a
  constant-size recurrent state plus a local exact-attention window, **is itself prior art here
  and is excluded by this item's own constraints**." Strong.
- `C5_evaluation_benchmarking_40`: "the reflexes of dating items or refreshing them after the
  model's cutoff **are excluded by this item's own constraints**, so they do not count as a
  response." Strong. Also the only C5 item with an in-rule discrimination clause (the property
  making leakage irrelevant "must not be item secrecy, a private held-out split, or items being
  newer than the model").
- `C5_architectures_training_38` and `C5_alignment_safety_39`: **no in-rule discrimination
  clause, and their `expert_baseline` does not claim the convergent answer is excluded.** These
  two are the weakest-discriminating items *of those reviewed here*. §8.4.

---

## 7. COMPATIBILITY — **CLOSED 2026-07-31**

At build time `questions/schema.json` pinned `domain` to the six ORIGINAL domains, so all 41 items
failed validation on `domain` and nothing else — every other constraint (`id` pattern, `required`,
`additionalProperties: false`, the two other enums, `minLength`, `minItems`) already passed. The
schema has since been bumped to **`crest-challenge/3.2.0`** with a twelve-value `domain` enum, and
all 50 items load and validate through `harness/run_crest.load_challenges`.

The trade-off that decision made, and which is now live: a **union** enum permits an
arts/humanities item to be tagged `systems_efficiency`. The alternative considered was a second
schema file selected per dataset, which would need a change to `load_challenges`' `_SCHEMA`
constant. That was not done.

Two compatibility notes that are **still open**:

- `ci_check.sh` enforces an id bijection between `questions/crest_challenges.jsonl` and
  `questions/item_design.jsonl`. `item_design.jsonl` has **no rows for these 50 ids**, so this
  dataset has no design-rationale sidecar and the bijection gate does not cover it.
- `expert_baseline` is judge-hidden as of 2026-07-30 and is **not** read by
  `judge/score.py::_judge_prompt`. It is carried here for provenance only. Nothing in §6's
  discrimination analysis reaches the judge unless it is also in `hard_rules` or `known_answers` —
  which is precisely why the four C2 items and two C5 items with no in-rule discrimination clause
  are flagged (§8.4).

---

## 8. What still needs human review

Ordered by how much damage it does if left alone.

### 8.1 The 9 missing items — **CLOSED.** Authored and appended as `_41`–`_49`
C4 gained `multimodal_agents`, `theory_learning`, `systems_efficiency`; C5 gained
`multimodal_agents` ×3 and `theory_learning` ×3. The file is 50 rows, 10 per category. Note what
that means for everything else in this report: those 9 items came from a different pass and carry
**no audit record, no discrimination review (§6 stops at `_40`) and no dedupe check** here. If any
of them duplicates `C4_alignment_safety_32` — the dedupe that cost the original 41st slot — this
report would not know.

### 8.2 C5 has never been audited — **STILL OPEN** (provenance half closed)
Zero independent citation checking on the C5 items, ~89 catalogue entries. C1, C2 and C3 each had a
**100% item-level defect rate** under audit; assuming C5 is clean contradicts the observed base
rate. The C5 items were also **transcribed from the task prompt, not read from a source artifact**,
so the transcription needs diffing against whatever the original was; if no original exists, C5 must
be treated as unsourced. **Closed:** the transcription is no longer gitignored — it is tracked at
`questions/aiml_build/c5_source_verbatim.json`, so the chain survives a clean clone. `assemble.py`
and `renumber_map.json` remain untracked under `crest/.tmp_build/` and will not.

### 8.3 C4 has no retained pre-audit artifact
Its corrections cannot be reconstructed or spot-checked, so §2d is thinner than §2a–2c by
necessity. If the C4 auditor's working copy still exists anywhere, retain it.

### 8.4 Weak-discriminating items
Six of the items reviewed here have no in-rule discrimination clause and therefore rely wholly on the
`known_answers` no-credit list, which a judge reading `hard_rules` will not see:
`C2_architectures_training_11`, `C2_alignment_safety_13`, `C2_evaluation_benchmarking_14`,
`C2_systems_efficiency_17`, `C5_architectures_training_38`, `C5_alignment_safety_39`. The last
two are worst, and C5 is still the thinnest tier at 50 items (mean 5.6 rules vs 6.5–8.1 elsewhere,
§5). Neither item's `expert_baseline` claims the convergent answer is excluded. Consider adding an
explicit gate. `_44`–`_49` have not been checked for this at all.

### 8.5 Confounded design axes
`axis_isolated` is near-1:1 with `category` (C3/C5 share `novelty`; C4 and C5 each carry one
off-label item — §5). `time_sensitivity` is near-confounded: C2 and C4 are 100% `pre_cutoff`, so
every `post_cutoff` item is C1, C3 or C5. Any model comparison crossing category with time
sensitivity will not identify. Decide whether that is intended before running.

### 8.6 Post-cutoff citations to future-dated arXiv ids
The catalogues cite ids in the 2602–2606 range (e.g. arXiv:2603.28063, 2604.16242, 2606.04923,
2605.26047, 2604.09780, 2606.09711). These are load-bearing — several are named as the
**closest prior art** and therefore set the novelty bar. They should be re-resolved
immediately before release; if any fails to resolve, the novelty gate on that item is void.
`C3_alignment_safety_22`'s gate rests entirely on arXiv:2603.28063 resolving.

### 8.7 Two style inconsistencies in `known_answers`
`C3_systems_efficiency_27`'s MQA/GQA/MLA entry carries arXiv ids but no spelled-out year, and
`C2_systems_efficiency_17`'s BIS entry uses an ECCN rather than a DOI. Both are valid; both
differ from the file's convention. Normalise or leave.

### 8.8 Dedupe calls to confirm
The five adjacent pairs in §3. `C1_evaluation_benchmarking_04` / `C4_evaluation_benchmarking_34`
is the closest of them and the most likely to be overturned by a second reader.

### 8.9 Legal and regulatory currency
`C2_systems_efficiency_17` now turns on California SB 53 (in force 2026-01-01) and New York's
RAISE Act after EO 14110's revocation. Regulatory facts decay fastest of anything in this file
and should be re-checked at release.

---

## Appendix — id renumbering

`NN` runs 00–40, globally unique, assigned by one counter walking C1→C5 in batch order. Ids
`41`–`49` were appended later by a different pass and have no row here.

| new id | old id | source |
|---|---|---|
| `C1_architectures_training_00` | `C1_architectures_training_01` | `.tmp_axv/items.audited.json` |
| `C1_architectures_training_01` | `C1_architectures_training_02` | `.tmp_axv/items.audited.json` |
| `C1_alignment_safety_02` | `C1_alignment_safety_03` | `.tmp_axv/items.audited.json` |
| `C1_alignment_safety_03` | `C1_alignment_safety_04` | `.tmp_axv/items.audited.json` |
| `C1_evaluation_benchmarking_04` | `C1_evaluation_benchmarking_05` | `.tmp_axv/items.audited.json` |
| `C1_evaluation_benchmarking_05` | `C1_evaluation_benchmarking_06` | `.tmp_axv/items.audited.json` |
| `C1_systems_efficiency_06` | `C1_systems_efficiency_07` | `.tmp_axv/items.audited.json` |
| `C1_systems_efficiency_07` | `C1_systems_efficiency_08` | `.tmp_axv/items.audited.json` |
| `C1_theory_learning_08` | `C1_theory_learning_09` | `.tmp_axv/items.audited.json` |
| `C1_multimodal_agents_09` | `C1_multimodal_agents_10` | `.tmp_axv/items.audited.json` |
| `C2_architectures_training_10` | `C2_architectures_training_00` | `.tmpaudit/c2_items_fixed.json` |
| `C2_architectures_training_11` | `C2_architectures_training_01` | `.tmpaudit/c2_items_fixed.json` |
| `C2_alignment_safety_12` | `C2_alignment_safety_02` | `.tmpaudit/c2_items_fixed.json` |
| `C2_alignment_safety_13` | `C2_alignment_safety_03` | `.tmpaudit/c2_items_fixed.json` |
| `C2_evaluation_benchmarking_14` | `C2_evaluation_benchmarking_04` | `.tmpaudit/c2_items_fixed.json` |
| `C2_evaluation_benchmarking_15` | `C2_evaluation_benchmarking_05` | `.tmpaudit/c2_items_fixed.json` |
| `C2_systems_efficiency_16` | `C2_systems_efficiency_06` | `.tmpaudit/c2_items_fixed.json` |
| `C2_systems_efficiency_17` | `C2_systems_efficiency_07` | `.tmpaudit/c2_items_fixed.json` |
| `C2_theory_learning_18` | `C2_theory_learning_08` | `.tmpaudit/c2_items_fixed.json` |
| `C2_multimodal_agents_19` | `C2_multimodal_agents_09` | `.tmpaudit/c2_items_fixed.json` |
| `C3_architectures_training_20` | `C3_architectures_training_01` | `questions/c3_ml_new10.corrected.json` |
| `C3_architectures_training_21` | `C3_architectures_training_02` | `questions/c3_ml_new10.corrected.json` |
| `C3_alignment_safety_22` | `C3_alignment_safety_03` | `questions/c3_ml_new10.corrected.json` |
| `C3_alignment_safety_23` | `C3_alignment_safety_04` | `questions/c3_ml_new10.corrected.json` |
| `C3_evaluation_benchmarking_24` | `C3_evaluation_benchmarking_05` | `questions/c3_ml_new10.corrected.json` |
| `C3_evaluation_benchmarking_25` | `C3_evaluation_benchmarking_06` | `questions/c3_ml_new10.corrected.json` |
| `C3_systems_efficiency_26` | `C3_systems_efficiency_07` | `questions/c3_ml_new10.corrected.json` |
| `C3_systems_efficiency_27` | `C3_systems_efficiency_08` | `questions/c3_ml_new10.corrected.json` |
| `C3_theory_learning_28` | `C3_theory_learning_09` | `questions/c3_ml_new10.corrected.json` |
| `C3_multimodal_agents_29` | `C3_multimodal_agents_10` | `questions/c3_ml_new10.corrected.json` |
| `C4_architectures_training_30` | `C4_architectures_training_01` | `questions/c4_ml_new10.audited.json` |
| `C4_architectures_training_31` | `C4_architectures_training_02` | `questions/c4_ml_new10.audited.json` |
| `C4_alignment_safety_32` | `C4_alignment_safety_03` | `questions/c4_ml_new10.audited.json` |
| `C4_alignment_safety_33` | `C4_alignment_safety_04` | `questions/c4_ml_new10.audited.json` |
| `C4_evaluation_benchmarking_34` | `C4_evaluation_benchmarking_05` | `questions/c4_ml_new10.audited.json` |
| `C4_evaluation_benchmarking_35` | `C4_evaluation_benchmarking_06` | `questions/c4_ml_new10.audited.json` |
| `C4_systems_efficiency_36` | `C4_systems_efficiency_07` | `questions/c4_ml_new10.audited.json` |
| `C5_architectures_training_37` | `C5_architectures_training_00` | `.tmp_build/c5_from_prompt.json` (transcribed) |
| `C5_architectures_training_38` | `C5_architectures_training_01` | `.tmp_build/c5_from_prompt.json` (transcribed) |
| `C5_alignment_safety_39` | `C5_alignment_safety_02` | `.tmp_build/c5_from_prompt.json` (transcribed) |
| `C5_evaluation_benchmarking_40` | `C5_evaluation_benchmarking_04` | `.tmp_build/c5_from_prompt.json` (transcribed) |

Dropped: `C5_alignment_safety_03` (dedupe, §3). Authored later, outside this build: `_41`–`_49` (§8.1).
