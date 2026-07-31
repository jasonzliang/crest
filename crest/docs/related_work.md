# CREST vs. Related Work (differentiation)

Standalone differentiation doc backing the paper's §Related Work. The one-line thesis:
**every deep-research benchmark measures correctness; every creativity metric targets short-form
LLM text — CREST is the first to measure the Non-redundancy/Useful/Surprising creativity of
browsing-and-citing research agents, organized by task type, against a dated per-item prior-art
set.**

> Two claims that appeared in earlier drafts of this doc are **not true of the released system** and
> must not be made: retrieval is **live provider-native web search, not a frozen shared index**
> (`harness/agents.FrozenIndex` raises; runs are not contamination-controlled), and the judge panel
> is **not human-validated** (no human study has been run). `analysis/ci_check.sh` fails the build if
> either is asserted un-negated in the paper body.

## 1. Deep-research / agent benchmarks — measure correctness, not creativity
| Benchmark | Measures | Not measured |
|---|---|---|
| GAIA (Mialon 2023) | tool-use correctness on assistant tasks | creativity |
| BrowseComp (Wei 2025) | hard-to-find fact retrieval | creativity |
| DeepResearch Bench (2025) | report quality + FACT citation faithfulness | creativity |
| LiveResearchBench (2025) | live, user-centric citation support | creativity |
| DeepScholar-Bench (2025) | generative research synthesis quality | creativity |
| ResearcherBench (2025) | frontier-question research quality | creativity |
| MLR-Bench (2025) | open-ended ML research task success | creativity (N/U/S) |

**CREST relation:** complementary. CREST adds the missing *creativity* axis and borrows these
benchmarks' citation-faithfulness framing for a **separate grounding check** (never folded into the
creativity score), so "creative AND well-sourced" is shown on the same reports. Honest scope: the
shipped gate (`judge/score.py::grounding_gate`) is a **regex cue-counter pilot proxy, not FACT**, and
on the current entrant field — all using provider-native search — it measurably contributes nothing
beyond an empty-answer check. A per-claim FACT verifier is the production version.

## 2. Creativity / novelty metrics & ideation benchmarks — not for research agents
| Work | Target | Gap vs CREST |
|---|---|---|
| Si et al. 2024 (novel research ideas) | LLM idea generation, human study | not browsing agents; ideas not full cited reports |
| LiveIdeaBench (2024) | divergent thinking, minimal context | novelty-leaning; no retrieval; no N/U/S triad |
| CreativityPrism (2025) | cross-domain LLM creativity | short-form; not deep-research agents |
| NoveltyBench (2025) | output diversity/humanlike variety | diversity ≠ New/Useful/Surprising |
| Creativity Index (Lu 2024) | linguistic novelty vs web n-grams | rewards text unlike the web → rewards fabrication |
| Death of the Novel(ty) (Saakyan 2026) | critique of n-gram novelty | motivates *why* CREST avoids n-gram novelty |

**CREST relation:** we do **not** claim "no creativity test exists." Our precise deltas:
(i) target deep-research agents that *browse and cite*; (ii) score **non-redundancy AND usefulness
jointly** — primary endpoint `min(non-redundancy, Useful)`, with Surprising reported as an
exploratory third axis — not novelty alone; (iii) organize by **task type** to expose
task-dependence; (iv) anchor the first axis to a **dated, published, per-item prior-art set** so it
means not-reducible-to-known-work rather than unlike-the-web (a *frozen shared retrieval index* is
the intended contamination control and is **future work**, not a released property); (v) **avoid**
embedding/n-gram novelty metrics that reward fabrication.

## 3. LLM-as-judge methodology — the validity backbone
| Work | Contribution | How CREST uses it |
|---|---|---|
| MT-Bench / Chatbot Arena (Zheng 2023) | LLM-as-judge feasibility + protocol | baseline judging protocol |
| Panickssery 2024 | judges favor their own generations | motivates the `same_family` covariate; **leave-one-family-out** kept as a robustness check (see below) |
| Ye 2024 (Justice or Prejudice) | catalog of judge biases | blind judging (the prompt carries no agent name). *Not* order randomization: scoring is single-answer, not pairwise, so there is no order to randomize |
| The Leaderboard Illusion (2025) | leaderboard/style confounds | length covariate, budget parity |
| "novelty mirage" (2026) | LLM judges over-rate novelty | reproduced in our own ablation (+0.98 when the prior-art set is withheld) ⇒ the axis is anchored and renamed non-redundancy; human validation is future work |
| Krippendorff α (Hayes 2007); ICC (Koo 2016) | reliability estimators | reported (`analysis/stats.py::reliability_report`), alongside **per-judge severity** — severity spread exceeded the between-agent spread here, so agreement alone would have hidden the effect that decided the leaderboard |

**On leave-one-family-out.** CREST ran LOFO as the default protocol until 2026-07-30 and then
reversed it: with three vendors it makes judge identity perfectly confounded with entrant family
(one judge was +2.0 to +3.2 points more lenient than the others and was dropped for exactly the
entrants of its own family), which makes the leaderboard unidentifiable. The full panel now scores
every entrant, `same_family` is stamped per judge row and modelled as a covariate, and LOFO is
recoverable post-hoc as a robustness filter. That reversal is itself one of the paper's findings.

## 4. Construct grounding (creativity theory)
Runco & Jaeger 2012 (standard definition) + Boden 2004 (surprise, exploratory/transformational);
Gentner 1983 / Falkenhainer 1989 (structure-mapping → C3); Byrne 2005 (rational imagination → C2);
Simonton 2003 / Campbell 1960 (constrained/blind variation → C1/C5); Amabile 1982/1996 (Consensual
Assessment Technique → scoring protocol). This is what lets CREST define creativity **independently
of any evaluated agent** — the property reviewers most need to see.

## 5. Dataset documentation & release
Gebru 2021 (Datasheets), Pushkarna 2022 (Data Cards), Mitchell 2019 (Model Cards),
Croissant 2024 (+ Croissant-RAI). CREST ships the datasheet today (`docs/datasheet.md`) and targets
the rest at release — the Croissant / Croissant-RAI records (`croissant.json`) are **not generated
yet**, so do not cite them as shipped.

## The one-sentence gap
CREST is the first benchmark to score the **non-redundancy and usefulness** (plus exploratory
surprise) of **deep-research agents**, **by task type**, against a **dated per-item prior-art set**,
with a **multi-vendor full panel** whose self-preference is measured rather than assumed, and a
**separate** citation-grounding check — turning "is this report creative?" from an unmeasured
question into a released, reproducible instrument. A frozen shared index and human validation of the
judge are the two named gaps, both future work; the released instrument is honest about that rather
than claiming either.
