# CREST vs. Related Work (differentiation)

Standalone differentiation doc backing the paper's §Related Work. The one-line thesis:
**every deep-research benchmark measures correctness; every creativity metric targets short-form
LLM text — CREST is the first to measure the full New/Useful/Surprising creativity of
browsing-and-citing research agents, organized by task type, on a frozen shared index.**

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

**CREST relation:** complementary. CREST adds the missing *creativity* axis and reuses these
benchmarks' citation-faithfulness metrics as a **separate grounding check** (never folded into the
creativity score), so "creative AND well-sourced" is shown on the same reports.

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
(i) target deep-research agents that *browse and cite*; (ii) score the **full N/U/S triad**
(all three required), not novelty alone; (iii) organize by **task type** to expose
task-dependence; (iv) use a **frozen shared retrieval index** so "New" means new-vs-known, not
unlike-the-web; (v) **avoid** embedding/n-gram novelty metrics that reward fabrication.

## 3. LLM-as-judge methodology — the validity backbone
| Work | Contribution | How CREST uses it |
|---|---|---|
| MT-Bench / Chatbot Arena (Zheng 2023) | LLM-as-judge feasibility + protocol | baseline judging protocol |
| Panickssery 2024 | judges favor their own generations | motivates **leave-one-family-out** |
| Ye 2024 (Justice or Prejudice) | catalog of judge biases | blind + order-randomization |
| The Leaderboard Illusion (2025) | leaderboard/style confounds | length covariate, budget parity |
| "novelty mirage" (2026) | LLM judges over-rate novelty | human-validation + validity-stratified reporting |
| Krippendorff α (Hayes 2007); ICC (Koo 2016) | reliability estimators | required reporting |

## 4. Construct grounding (creativity theory)
Runco & Jaeger 2012 (standard definition) + Boden 2004 (surprise, exploratory/transformational);
Gentner 1983 / Falkenhainer 1989 (structure-mapping → C3); Byrne 2005 (rational imagination → C2);
Simonton 2003 / Campbell 1960 (constrained/blind variation → C1/C5); Amabile 1982/1996 (Consensual
Assessment Technique → scoring protocol). This is what lets CREST define creativity **independently
of any evaluated agent** — the property reviewers most need to see.

## 5. Dataset documentation & release
Gebru 2021 (Datasheets), Pushkarna 2022 (Data Cards), Mitchell 2019 (Model Cards),
Croissant 2024 (+ Croissant-RAI). CREST ships all of these (see `datasheet.md`), matching the
release rigor of accepted D&B-track benchmark papers.

## The one-sentence gap
CREST is the first benchmark to score the **full New/Useful/Surprising creativity** of
**deep-research agents**, **by task type**, on a **frozen shared index**, with a **human-validated
leave-one-family-out judge** and a **separate** citation-grounding check — turning "is this report
creative?" from an unmeasured question into a released, reproducible instrument.
