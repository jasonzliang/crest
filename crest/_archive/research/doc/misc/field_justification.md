# The Minimal Reviewer-Defensible Field Set for CREST

**Deep research report — 2026-07-30**
Subject: which of the 12 per-item fields in `crest_challenges.jsonl` survive reviewer scrutiny, which
move to a sidecar, and which are cuttable.

---

## Executive Summary

CREST ships 50 items at ~8.7 KB each, of which the agent-visible `query` is 9.7%. The remaining 90%
is per-item scoring machinery. The instinct that this is bloat is half right: one field is misfiled
and one is buying less than it costs, but the two largest fields are the strongest part of the design
and cutting them would be a serious mistake.

The decisive external finding is that **unanchored LLM novelty judgment is not merely noisy, it is
directionally wrong.** RQ-Bench reports that "LLM judges consistently rate model-generated RQs as
highly novel, producing a novelty mirage," while "domain experts... reach the opposite conclusion and
prefer the author-anchored reference questions" [1]. A creativity benchmark that scores New without a
per-item reference set is therefore measuring judge optimism, not novelty. `known_answers` is the
field that buys immunity to the single most damaging objection available to a reviewer, and it should
be defended, not trimmed.

`hard_rules` is on even firmer ground, both externally and in CREST's own data. IFEval's founding
argument is that "LLM-based auto-evaluation is potentially biased or limited by the ability of the
evaluator LLM," which is why it uses constraints "checked with a deterministic program" [2]. CREST's
hard rules are the same move in semantic form, and they demonstrably bind: across 144 verdicts, mean
Useful is **2.84** when a judge cites a rule violation versus **8.27** when it does not.

The genuinely weak field is `expert_baseline`. CREST's own judges score New and Surprising at
r = 0.77–0.94, with 28% of verdicts assigning identical values. This is not a CREST artifact — it
replicates a documented psychometric result. Confirmatory factor analysis finds that **two-factor
(novelty + usefulness) models fit creativity assessments better than three-factor models** [5], an
independent study reports surprise–novelty r = .71 with surprise contributing no additional
predictive variance beyond value and novelty [6], and value/novelty metrics outperform surprise in
predicting creative outcomes [16]. The recommendation is nonetheless **not to cut the field**: keep
it to operationalise the axis at all, but demote Surprising to a secondary/exploratory measure and
disclose the collapse before a reviewer finds it.

`rationale` (20.3% of bytes) reaches no model at runtime — verified: `ch['rationale']` is never read
by `_judge_prompt`. It is not worthless; benchmark documentation norms actively require curation
rationale (BIG-bench required each task to "describe the data source and curation methods" [8]; KDD
and NeurIPS D&B tracks require datasheet-style documentation [9]). It is simply in the wrong file.
Move it to a sidecar and the runtime dataset shrinks 20% with zero behavioural change.

**Recommendation: keep 11 of 12 fields, move `rationale` to a sidecar, retain `expert_baseline` with
demoted status and a disclosed correlation. Cut nothing.** The bytes are not the liability; the
undisclosed axis collapse and the unverified provenance of the novelty baseline are.

---

## Introduction

### Scope

In scope: the justification status of each field in `crest_challenges.jsonl`, judged against
(a) published benchmark-documentation norms, (b) evidence on LLM-judge reliability with and without
per-item anchors, (c) the construct-validity literature on novelty/usefulness/surprise, and
(d) CREST's own 144 judge verdicts.

Out of scope: whether the 50 items are individually well-designed (covered by
`doc/item_vetting.md`), factual accuracy of item content (covered by `doc/hallucination_audit.md`
and a pending live-web pass), and the LOFO-versus-full-panel judging question (separate analysis).

### Assumptions surfaced

"Justified" is operationalised as: **the field answers a specific, foreseeable reviewer objection
that no cheaper field answers.** A field that is merely *used* by the judge is not thereby justified —
usage and necessity are different tests, and the `expert_baseline` finding below is exactly the case
where they diverge. Empirical inputs come from a partial run (112 of 250 records at time of analysis),
so all per-axis statistics are provisional and directional rather than final.

---

## Finding 1 — `known_answers` (30.2%): the field that defeats the most dangerous objection

The reviewer objection this field answers is: *"Your New scores reflect the judge's ignorance of the
literature, not the agent's originality."* Without a per-item reference set there is no answer to it.

The external evidence is unusually direct. RQ-Bench constructs "author-anchored RQs from
[each paper's] cited background, gaps, and contributions" specifically to test novelty judgment, and
finds a systematic failure: "LLM judges consistently rate model-generated RQs as highly novel,
producing a novelty mirage; in comparative evaluations, this preference becomes even stronger" [1].
Critically, the error is not random — experts "reach the opposite conclusion." An unanchored judge
does not merely add variance to New; it shifts New upward in a way that would flatter every entrant
and destroy the benchmark's ability to discriminate.

Corroborating evidence on the reliability side: LLM judges achieve high agreement *with each other*
(ICC .86–.94) while agreeing poorly with humans (ICC .43) [12]. High inter-LLM agreement is therefore
not evidence of validity, and CREST cannot lean on panel consensus as a substitute for an anchor.
Conversely, creativity studies that establish shared anchors through calibration report solid
reliability (Novelty ICC 0.83, Usefulness 0.75) [11] — anchoring is the mechanism that produces
trustworthy novelty scoring, and per-item `known_answers` is a stronger form of it than a calibration
session because it is item-specific and auditable.

CREST's own data is consistent with the field working. New spans the full 1–10 range (mean 5.92,
sd 2.18) and 15% of verdicts land in the 1–3 "restates known content" band. A saturated distribution
would have suggested the list was decorative; a discriminating one with a populated bottom band
suggests judges are actually checking against it. Additionally, 53% of judge rationales invoke
prior-art framing.

**Verdict: keep, and treat as a headline methodological contribution rather than overhead.** The
dated novelty baseline is also the only reason CREST's pre/post-cutoff labelling means anything — a
baseline without a date cannot support a contamination claim.

**Residual risk, and it is real.** The reviewer's counter-move is provenance: *who wrote the list?*
Self-bias research shows it "arises from two additive sources: LLM-as-a-testset and
LLM-as-an-evaluator, and their combination amplifies the effect" [3], and that LLM-generated
benchmarks "systematically favor the model that created them" [3]. CREST's prior-art lists were
assembled with agent assistance, which places them on the LLM-as-a-testset arm of exactly this
failure mode. Published mitigations are ensemble judging [4], calibration, diversity enhancement, and
human involvement [3]. CREST already has the multi-vendor ensemble; what it lacks is **independent
verification of the lists themselves.** `doc/hallucination_audit.md` was explicit that live web
search was unavailable and that "a full per-citation web verification remains a pre-release step,"
leaving 8 items flagged. Closing that gap is the highest-value remaining action on this field —
an unverified novelty yardstick is a load-bearing component resting on unchecked content.

---

## Finding 2 — `hard_rules` (20.8%): the strongest field, and the one closest to objective

The objection answered: *"Your Useful axis rewards fluent prose, and LLM judges are known to do
exactly that."*

IFEval's design rationale is the cleanest statement of why checkable constraints matter: human
evaluation is "expensive, slow, and not objectively reproducible, while LLM-based auto-evaluation is
potentially biased or limited by the ability of the evaluator LLM," which motivates constraints
"checked with a deterministic program, circumventing the need of an LLM or human as judge" [2]. CREST's
hard rules are the semantic analogue — a rule like "the target must not be the target of any
antibacterial that has reached human clinical trials as of the dated known-answers" gives a judge a
factual ground to fail an answer on, rather than an aesthetic one.

CREST's own evidence is the strongest quantitative result in this report:

| condition | mean Useful | n |
|---|---|---|
| verdict cites ≥1 rule violation | **2.84** | 107 |
| no violation cited | **8.27** | 37 |

74% of verdicts cite a specific rule, and the rubric's "violation ⇒ Useful ≤ 3" mandate holds in 83%
of those. Independently, `corr(New, Useful)` is only 0.12–0.38 — Useful is the *one axis that is
cleanly separable* from the others, and the rules are what make it so. Compare this to the
`expert_baseline` result below: same design philosophy, opposite outcome.

**Verdict: keep, unambiguously.** Two upgrades worth noting for the paper's own defence:

1. **The 17% leak.** Roughly one in six verdicts cites a violation yet scores Useful above 3, in
   violation of the rubric's own cap. A reviewer who audits the verdict-level data will find this. It
   is a prompt-adherence problem, fixable by post-hoc enforcement (clamp Useful when
   `hard_rules_violated` is non-empty) rather than by trusting the judge.
2. **Partial programmatic verification.** A subset of CREST's rules are genuinely deterministic —
   cent-error arithmetic, pitch counts, mobility floors, radiative-balance inequalities. Verifying
   those in code and reserving the judge for the semantic remainder would move CREST measurably toward
   IFEval-grade objectivity and pre-empt "why is an LLM checking arithmetic?"

---

## Finding 3 — `expert_baseline` (17.8%): buying an axis that will not stay separate

The objection answered in principle: *"Surprising relative to whose expectation?"* Without a written
baseline the axis is undefined, so the field is not gratuitous. The problem is that supplying the
baseline does not, in practice, produce a distinct axis.

CREST's judges, per-judge:

| judge | corr(New, Surprising) |
|---|---|
| judge_google | 0.94 |
| judge_openai | 0.90 |
| judge_anthropic | 0.77 |

28% of verdicts give New and Surprising identical scores; 70% are within one point.

The important interpretive point is that **this is not a CREST bug.** It reproduces an established
result. Confirmatory factor analysis across entrepreneurship, advertising and art finds that
"composite latent construct models with two factors (novelty and usefulness) represent creativity
assessments... better than one- and three-factor models" [5]. A design-research study reports
surprise–novelty r = .71, describes it as suggesting redundancy, and finds surprise "does not
contribute additional predictive variance beyond value and novelty" [6] — and further that
"creativity, novelty and surprise are perceived as the same dimension" [6]. Reviews of Boden-derived
operationalisations note that "value and novelty metrics often outperform surprise in predicting
creative outcomes" [16]. Surprise has a serious theoretical pedigree in computational creativity
[7] but a poor record as a *separately measurable* rating dimension.

CREST's observed 0.77–0.94 is therefore at or above the literature's r ≈ .71 — the collapse is
expected, not anomalous.

**Verdict: keep the field, demote the axis, disclose the correlation.** Three reasons not to cut:

- Deleting `expert_baseline` deletes the *ability to measure* Surprising, converting an
  informative negative result into an unexamined omission. The measurement is what lets CREST report
  the collapse as a finding.
- Boden-grounded surprise is a stated contribution of the paper; silently dropping it invites
  "why does your NUS triad have two letters?"
- The spread across judges (0.77 vs 0.94) suggests the collapse is *partly* rubric-induced rather
  than inherent. Anthropic separated the axes materially better, so sharper prompt wording may
  recover discriminant validity. That is testable cheaply.

**The consequence that must reach the paper:** `creative_all_three` is presented as three independent
hurdles. At r ≈ 0.9 between two of them it is effectively **two**, which overstates the gate's
stringency. Report the inter-axis correlation matrix, and consider a two-factor composite as the
primary endpoint with Surprising as secondary. A reviewer who computes this correlation from the
released per-judge data — which CREST does release — will otherwise find it first.

---

## Finding 4 — `rationale` (20.3%): right content, wrong file

Verified locally: `_judge_prompt` reads `known_answers`, `hard_rules`, `expert_baseline`, `query`,
`category`, `axis_isolated` — and **not** `rationale`. (An earlier automated check produced a false
positive here by matching the `"rationale"` key in the judge's *output* schema; the corrected test
confirms the challenge field is never read.) `analysis/stats.py` contains no reference to it either.
86 KB reaches no model and no analysis.

That does not make it deletable. Benchmark documentation norms require exactly this content:
BIG-bench required every task to "describe the data source and curation methods on the task README
page" [8]; the KDD 2026 Datasets & Benchmarks CFP requires "dataset documentation and intended uses,"
recommending datasheets for datasets, nutrition labels, and data statements [9]; and work on
benchmark repositories argues datasets are more usable when accompanied by metadata describing
composition and intended tasks [10]. Design rationale is a reviewer *asset* — it is the evidence that
axis-isolation claims were reasoned rather than asserted.

**Verdict: move to a sidecar (`question/item_design.jsonl`, keyed by `id`), do not cut.** This cuts
the runtime dataset by 20% with zero behavioural change, keeps the provenance reviewers want, and has
the incidental benefit of shrinking what must be loaded per judge call. CREST already has
`doc/datasheet.md` as the natural host for the aggregate narrative.

---

## Finding 5 — the label fields (1.2%): cheap and load-bearing

`id`, `category`, `category_name`, `domain`, `axis_isolated`, `time_sensitivity`,
`predicted_direction` together cost ~97 bytes per item. Each maps to a specific analysis or claim:
`category` and `domain` are the fixed effects; `axis_isolated` supports the "the aggregate cannot hide
a weak axis" claim; `predicted_direction` is the pre-registration record that converts C1/C5 losses
from a weakness into mechanism confirmation; `time_sensitivity` supports the contamination split.

**Verdict: keep all.** One caveat with teeth: `time_sensitivity` currently has **n=1** in the
`post_cutoff` stratum, so the pre/post split it exists to enable is not computable. The field is
justified; the *data behind it* is not yet. Either author more post-cutoff items or drop the
contamination claim — and note that the p3 abstract already advertises a "frozen retrieval snapshot"
that `FrozenIndex` raises `NotImplementedError` on. LiveBench's contamination-limited design [14] is
the reference point a reviewer will have in mind.

`category_name` is strictly derivable from `category` and is the one true redundancy in the schema —
1,204 bytes, harmless, keep for human readability.

---

## Synthesis & Insights

Three patterns cut across the findings.

**1. Usage is not justification.** All three large judge-facing fields are *used* by judges. Only two
are *necessary*. `hard_rules` and `known_answers` each produce a measurable, separable effect;
`expert_baseline` produces an axis that will not stay distinct from one it already has. The right test
for a benchmark field is not "does the judge read it" but "does the score change in a way nothing
cheaper achieves."

**2. The anchoring literature and the construct-validity literature point in opposite directions, and
both are right.** Anchoring evidence [1][11] says: give judges per-item reference material or novelty
scoring fails. Construct-validity evidence [5][6] says: surprise will not separate from novelty no
matter what you give judges. These are compatible — anchoring fixes *accuracy* on the axes that exist;
it cannot manufacture *discriminant validity* between two axes that human raters also conflate. CREST
should therefore anchor hard (keep both reference fields) while claiming fewer independent axes.

**3. CREST's largest exposure is provenance, not size.** The self-bias literature's finding that bias
"arises from two additive sources: LLM-as-a-testset and LLM-as-an-evaluator" [3] is the sharpest
available attack on a benchmark whose author also fields an entrant. CREST has mitigated the evaluator
arm (multi-vendor ensemble [4]) and left the testset arm largely unmitigated: the novelty baselines are
agent-assisted and, by the audit's own admission, not web-verified. **Every byte of `known_answers` is
load-bearing and unverified at the same time.** That combination, not the 426 KB, is what would sink a
review.

---

## Limitations & Caveats

- Empirical inputs are a **partial run** (112/250 records, 144 verdicts) from a single day. All
  correlations and means are directional; the New–Surprising correlation should be recomputed on the
  complete run before it enters the paper.
- The judge-level correlations are computed on pooled items across categories. Some of the New–Surprising
  association may be item-driven (a genuinely novel cross-domain mapping *is* genuinely surprising)
  rather than rater-driven. A per-category decomposition would sharpen the diagnosis and is not yet run.
- Several supporting figures (surprise–novelty r = .71; ICC values) were obtained via search-result
  summaries rather than full-text extraction, and carry correspondingly lower confidence than the
  RQ-Bench quotes, which were verified against the source abstract.
- No source directly studies *deep-research-agent* creativity benchmarks with per-item novelty
  baselines; the anchoring evidence is transferred from research-ideation novelty judgment [1][13],
  which is close but not identical.
- Cost-benefit is assessed on reviewer defensibility, not annotation economics. At 500+ items the
  hand-authored fields become infeasible and this analysis would need redoing.

---

## Recommendations

**Keep in the runtime dataset (10 fields):** `id`, `query`, `category`, `category_name`, `domain`,
`axis_isolated`, `time_sensitivity`, `predicted_direction`, `known_answers`, `hard_rules`.

**Keep, with changed status (1 field):** `expert_baseline` — retain, but demote Surprising to a
secondary endpoint, publish the inter-axis correlation matrix, and consider a two-factor primary
composite.

**Move to sidecar (1 field):** `rationale` → `question/item_design.jsonl`. −20% runtime bytes, zero
behavioural change, provenance preserved for reviewers.

**Cut: nothing.**

Ranked actions, highest reviewer-risk-reduction first:

1. **Run the live per-citation verification of `known_answers`.** It is the novelty yardstick, it is
   unverified, and it sits on the exact arm of self-bias reviewers attack [3]. The audit's own 8
   flagged items are the starting list.
2. **Disclose the New–Surprising collapse** and restate `creative_all_three` as a two-hurdle gate.
   Recompute on the full run first.
3. **Enforce the hard-rule cap post-hoc** (clamp Useful ≤ 3 when `hard_rules_violated` is non-empty)
   to close the 17% adherence leak.
4. **Move `rationale` to a sidecar** and point `doc/datasheet.md` at it.
5. **Fix the `time_sensitivity` stratum or drop the contamination claim** — n=1 cannot support a split,
   and the "frozen snapshot" already claimed in the abstract does not exist in code.
6. **Programmatically verify the deterministic subset of `hard_rules`**, moving toward IFEval-grade
   objectivity [2] where the rules permit it.

---

## Bibliography

[1] *On the Limits of LLM-as-Judge for Scientific Novelty Assessment* (RQ-Bench), arXiv:2606.12071, 2026-06-10. https://arxiv.org/abs/2606.12071
[2] Zhou et al., *Instruction-Following Evaluation for Large Language Models* (IFEval), arXiv:2311.07911. https://arxiv.org/abs/2311.07911
[3] *When LLMs Benchmark Themselves: Deconstructing Self-Bias in Automated Evaluation*, arXiv:2509.26600. https://arxiv.org/abs/2509.26600
[4] *Quantifying and Mitigating Self-Preference Bias of LLM Judges*, arXiv:2604.22891. https://arxiv.org/html/2604.22891
[5] *The Alignment of Measures and Constructs in Organizational Research: The Case of Testing Measurement Models of Creativity*, Journal of Business and Psychology. https://link.springer.com/article/10.1007/s10869-009-9147-8
[6] *Creativity, Surprise & Design: An Introduction and Investigation*, Design Society. https://www.designsociety.org/download-publication/32464/creativity_surprise_design_an_introduction_and_investigation
[7] Yannakakis & Liapis, *Searching for Surprise*, ICCC 2016. https://www.computationalcreativity.net/iccc2016/wp-content/uploads/2016/01/Searching-for-Surprise.pdf
[8] *BIG-bench task submission documentation*. https://github.com/google/BIG-bench/blob/main/docs/doc.md
[9] *KDD 2026 Datasets & Benchmarks Track — Call for Papers*. https://kdd2026.kdd.org/datasets-and-benchmarks-track-call-for-papers/
[10] *Benchmark Data Repositories for Better Benchmarking*, arXiv:2410.24100. https://arxiv.org/pdf/2410.24100
[11] *How Do Hackathons Foster Creativity? Towards AI Collaborative Evaluation of Creativity at Scale*, arXiv:2503.04290. https://arxiv.org/pdf/2503.04290
[12] *Creativity Benchmark: A benchmark for marketing creativity for large language models*, arXiv:2509.09702. https://arxiv.org/html/2509.09702v2
[13] *NovBench: Evaluating Large Language Models on Academic Paper Novelty Assessment*, arXiv:2604.11543. https://arxiv.org/html/2604.11543v1
[14] *LiveBench: A Challenging, Contamination-Limited LLM Benchmark*, arXiv:2406.19314. https://arxiv.org/pdf/2406.19314
[15] *Play Favorites: A Statistical Method to Measure Self-Bias in LLM-as-a-Judge*, arXiv:2508.06709. https://arxiv.org/pdf/2508.06709
[16] *Operational Validity of Boden's Creativity Framework*. https://www.emergentmind.com/topics/operational-validity-of-boden-s-creativity-framework

---

## Methodology Appendix

**Mode:** deep (8 phases), with main-analysis section lengths deliberately compressed below the
600–2,000-word-per-finding guideline. The deliverable is an engineering decision, and padding the
findings would have reduced their utility. All other contract elements (evidence persistence,
claim-level sourcing, complete bibliography) are met.

**Retrieval:** `search-cli` was attempted first per methodology but all providers failed
(`status: all_providers_failed`, brave); the documented WebSearch fallback was used for all queries,
with WebFetch for direct verification of source [1]. Six search angles were run: LLM-judge creativity
anchoring; the novelty-mirage result; novelty/surprise construct separability; self-serving benchmark
bias and mitigations; benchmark per-item documentation norms; verifiable-constraint benchmarks.

**Evidence handling:** 16 sources registered in `sources.jsonl` with credibility scores; 16 evidence
spans in `evidence.jsonl` with source IDs, quote text, evidence type (direct quote vs
paraphrase-supported), and locators. Quotes from source [1] were verified verbatim against the
abstract; figures from [5][6][11][12][16] derive from search-result summaries and are labelled
`paraphrase_supported`, a distinction carried into the Limitations section.

**Local empirical inputs:** `records.jsonl` from run
`2026-07-30T081356Z__crest__full50__git84f7a96__51ea6b` (112 records / 144 judge verdicts at analysis
time); field byte-shares computed directly over `crest_challenges.jsonl`; the `rationale`-unused claim
verified by regex against `_judge_prompt` for `ch['rationale']` access, after an initial automated
check returned a false positive.

**Deviation from contract:** HTML/PDF rendering not generated; the markdown is the source of truth and
the actionable output is the ranked recommendation list.

---

## Post-remediation measurements (2026-07-30, after the judge-prompt fixes)

Everything below was measured on the full-panel run `2026-07-30T111856Z` (250 records, 3 judges each,
untruncated answers, anti-web clause present), i.e. on the corrected instrument rather than the one
the reviewers analysed.

> **SUPERSEDED RUN.** `111856Z` is not the canonical run and is **not on disk** (`result/` is
> gitignored), so nothing in this section is reproducible as written. The canonical run is
> `2026-07-31T040653Z`; its recomputed figures live in `doc/design.md` §0, and where the two
> disagree, §0 wins. The *directions* below all survive re-measurement; three magnitudes do not
> (flagged inline). The ablation deltas (+0.98 / −0.02) have no persisted output in either run and
> can only be re-derived by re-running `analysis/ablate_fields.py`.

### `known_answers` — KEEP. Now proven load-bearing by ablation.
Withholding the prior-art list from the judge **inflates New by +0.98** (7.28 -> 8.26 over 50 records).
That is the novelty mirage reproduced in-house, in the correct direction. It also disposes of the
"wrong-signed dose-response" objection: the positive correlation between list length and New was a
category confound, not evidence the field fails. The reviewers' "no ablation, so no evidence it moves
a score" objection is answered.

Consequence worth stating: the S1 fix (adding the rubric's missing "judge ONLY against that list, NOT
against the web or your own background knowledge" clause to the deployed prompt) makes list
CORRECTNESS the only remaining safeguard against a wrong novelty baseline. Before, a judge's own
knowledge was a second, unreliable line of defence. This raises the priority of DOI-per-entry (S13).

### `expert_baseline` — DEMOTE the axis, keep the field. **CONCLUSION REVERSED.**
Withholding it moves Surprising by **-0.02**. It does not anchor the axis it exists for — that part
stands. The recommendation that followed does not: on the argument that r(New, Surprising) ~ 0.93 and
that Surprising was the sole binding axis in ~1 record of 147, this section proposed reporting **two
primary axes** with Surprising exploratory. Both premises were wrong. On the canonical run Surprising
is the sole binding axis in a fifth of all records, and the New/Surprising correlation is
**CONTAMINATED** — the v1 judge prompt stated that correlation *to the judge* — so it cannot evidence
inseparability at all (`design.md` §0). The primary endpoint is `min(New, Useful, Surprising)`, all
three axes. The field is kept because deleting it removes the ability to measure the collapse, and
Boden-grounded surprise is a stated contribution.

Separately, 7 items had answer keys embedded in this field and are now split into judge-hidden
`author_expected_surprises`. For three of them the key was the MAJORITY of the field
(C2_biology_medicine_34 64%, C2_law_policy_37 59%, C2_economics_business_36 58%), so for those items
Surprising was graded recall against an author-written list, not expectation-violation.

### `axis_isolated` — VALID FOR C1 ONLY. Narrow the claim.
Measured after the truncation fix on run `111856Z` (n=196, excluding `balanced`):

| label | binding-axis hit rate | chance | delta (labelled axis - others) |
|---|---|---|---|
| usefulness (C1) | **56%** | 33% | **-1.56** (correct sign) |
| novelty (C3, C5) | 21% | 33% | **+1.51** (wrong sign) |
| surprise (C2) | 15% | 33% | +0.18 |
| overall | 28% | 33% | — |

> **STALE MAGNITUDES.** Recomputed on the canonical run these rates are materially different
> (usefulness 68% sole-binding / 80% including ties; surprise 14% / 40%; novelty 0% / 11%) — see
> `design.md` §0, which is authoritative. The *verdict* is unchanged and in fact strengthened: valid
> for C1/usefulness, wrong-signed for novelty. Cite §0, not this table; the 56 / 21 / 15 triple has
> already leaked into three other docs from here.

C1 is genuinely usefulness-limited. The novelty label is wrong-signed: items built to isolate novelty
are where agents score HIGHEST on New, i.e. they are novelty-EASY rather than novelty-isolating,
which corroborates the earlier finding that C5 is saturable. **Both abstracts must stop describing
the set as axis-isolating in general**; the defensible claim is usefulness-isolation on C1.

### `rationale`, `category_name`, `predicted_direction`
`rationale` reaches no model (verified) -> sidecar. `category_name` and `predicted_direction` removed:
both were deterministic functions of `category`, and the latter could not evidence ordering while it
lived in editable data. Predictions now in `analysis/preregistration.yaml`, which `stats.py` reads and
which self-reports `externally_timestamped: false`.
