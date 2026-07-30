# Area Chair Meta-Review — CREST (ICLR Datasets & Benchmarks)

**Reviewers:** 4 independent red-teams of the per-item field schema, all 3/10.
**AC action:** spot-check the decision-relevant claims, deduplicate, triage, and produce one plan.

**Evidence base.** All run-data numbers below are computed on a frozen snapshot of
`result/runs/2026-07-30T081356Z__crest__full50__git84f7a96__51ea6b/records.jsonl`
taken at **154 records / 147 scored / 32 of 50 items / 5 agents / 2 judges per record**.
The live run is still appending, so reviewer numbers computed at n=138 and mine at n=147 differ
by small amounts. Where a reviewer's number and mine disagree I report both and say which
direction the discrepancy runs. **No Caesar/author-system records exist in either run
directory** — this matters for p3 and is stated again in §5.

**AC decision (stated up front, then justified):**

- **p3_caesar_hybrid — reject this cycle.** Its headline claim has zero supporting records, its
  ablation claim has zero supporting records, and its central rhetorical defense
  ("winning only where the mechanism predicts") rests on a pre-registration that
  `git log -S caesar_win` falsifies in one command.
- **p2_benchmark_only — major revision, not reject.** The artifact is real and one nearly-free
  re-judge plus honest text can support a genuine, publishable methodological contribution.
  But it cannot go out with its current abstract.

---

## 1. Spot-checks

I checked eight claims, chosen because each would flip my decision if false. Two reviewer
claims are overturned in detail while their substance survives; three reviewer numbers are
worse than the reviewer stated; one reviewer argument I discard as a weak instrument.

### SC-1 — Canary strings asserted but absent. **HOLDS.**
`grep -ci canary questions/crest_challenges.jsonl` → **0**. `docs/datasheet.md:50-52` states
"Each item embeds a canary string enabling post-hoc detection in future model training corpora"
and `datasheet.md` §5 further leans on it ("not a training set (canaries + license restrict
training use)"). `paper/p2_benchmark_only/sections/03_benchmark_design.tex` and
`paper/p3_caesar_hybrid/sections/03_crest_benchmark.tex` both repeat the claim. The only
`canary` hits in the repo are these prose assertions plus incidental occurrences in agent
transcripts. One command, contradicts a datasheet claim. This is the archetype of a D&B
integrity failure.

### SC-2 — Frozen retrieval snapshot released. **HOLDS (worse than stated).**
`harness/agents.py:62-66` — `class FrozenIndex` whose constructor raises `NotImplementedError`;
`harness/run_crest.py:236` calls it with the comment `# raises (future work)`. The p2 abstract
nonetheless asserts "a frozen, shared retrieval index gives a fair, reproducible,
contamination-controlled run mode" and "We release the challenges, judge harness, **frozen
snapshots**, and datasheet." The p3 abstract lists "frozen retrieval snapshot" among released
artifacts. `datasheet.md` goes further than the reviewers noted: it claims the manifest is
"Released as a manifest (URL + timestamp + SHA-256 per document)." Three documents describe a
released artifact that is a stub that deliberately raises.

### SC-3 — rubric.md is loaded by no code; the deployed prompt drops its key clause. **HOLDS.**
`grep -rn rubric --include=*.py .` returns two occurrences, both inside comments
(`harness/run_crest.py:82`, `harness/cache.py:6`). `judge/rubric.md` is documentation only.
`rubric.md:17` — "*Judge against the dated known-answers list, NOT against the web at large
(avoids penalizing grounding).*" — is **absent** from `_judge_prompt` (`judge/score.py:96-123`).

Partial credit to the authors that R1 did not give: the deployed prompt does say
"New: novelty vs the DATED KNOWN ANSWERS below." So the list is named. But the scoring anchor
immediately after is "**Restating anything already known** => 1-3", which is unanchored and
re-delegates to judge world-knowledge, and the anti-web-at-large instruction that would
resolve the ambiguity is gone. Substantive claim upheld.

**Two further findings in this family that no reviewer flagged**, and they are sharper:
`judge/judge_config.yaml` sets `randomize_answer_order: true` and
`grounding_gate: {metric: fact_precision, threshold: 0.8}`. `judge_config.live.yaml`'s own
header states that "Only `judges` and `threshold_all_three` are read by
`JudgePanel.from_config`." So the shipped config file **declares two experimental controls
that no code reads** — and one of them (`fact_precision`) is a materially different grounding
gate from the cue-counting heuristic actually implemented in `grounding_gate()`.
`analysis/stats.py:414` completes the pattern: `--prereg` defaults to
`crest/analysis/preregistration.yaml`, which does not exist, and `prereg` appears at exactly
one line in the file — the argparse definition. It is never consumed.

### SC-4 — `predicted_direction` is not a pre-registration. **HOLDS, verbatim.**
`git show eadce0c:crest/questions/schema.json` — the original enum was
`["caesar_win", "parity", "predicted_null"]`. The original data:
`{('C2','caesar_win'): 10, ('C3','caesar_win'): 10, ('C1','predicted_null'): 10,
('C5','predicted_null'): 10, ('C4','parity'): 10}`. The value was renamed to `favored` in
`b89761e` (2026-07-29 23:34), **14h13m** after `eadce0c` (2026-07-29 09:21), in a commit
titled "reorganize + config-driven eval entry point + model adapters + **honesty fixes**".
No commit in the history contains predictions without results.
`paper/p2_benchmark_only/sections/05_experiments.tex:4` claims
"We pre-register the per-category predictions and the analysis plan before scoring
**(OSF, timestamped)**" — there is no OSF identifier anywhere in the repo.

A field whose enum was named after the intended winner is not a pre-registration; it is a
statement of hope. This is the most damaging single finding in the whole set, because p3's
defense against "you found this post hoc" is *entirely* this field.

### SC-5 — `hard_rules` self-contradiction in C1_materials_chemistry_01. **HOLDS (all four sub-claims).**
Read verbatim from the item:
- **Se permit/ban.** R6: "X may be a halide (Cl, Br, I), a **chalcogenide (S, Se)**, a nitride,
  or an oxide". R9: "(This deliberately bans Ag, Au, Pd, Pt, Rh, Ir, Re, In, Te, **Se**, Bi,
  and Sb…)". Direct contradiction.
- **R4 excludes the item's own reference answer.** R4 requires mu = rB/rX in **[0.40, 0.90]**
  and explains it was "deliberately widened below the classic 0.414 radius-ratio cutoff **to
  admit sulfide perovskites**." The item's own `expert_baseline` reports "octahedral
  mu~**0.39**-0.42 (Shannon radii)" for BaZrS3/BaHfS3 (Zr4+ 0.72 / S2- 1.84 = 0.391). The rule
  written to admit sulfide perovskites excludes the sulfide perovskite the item nominates.
- **R2 permits a motif and bans its definition.** R2 permits "a vacancy-ordered A2BX6" and in
  the same sentence requires "Corner-sharing BX6 octahedral connectivity in at least 2
  dimensions … this bans 0-D/1-D **isolated**-octahedra motifs." Vacancy-ordered A2BX6
  (Cs2SnI6-type) *is* the isolated-octahedra motif.
- **R11 ∧ R12 unsatisfiable for a retrieval-only agent.** R11 demands "predicted energy above
  the convex hull … <= 50 meV/atom, with the competing decomposition products explicitly
  named"; R12 voids the answer if the composition "appear[s] in … ICSD/**Materials
  Project**/OQMD/AFLOW". A composition with a citable hull energy is in the database; one
  absent from the database has no citable hull energy. A web-research agent cannot run its own
  DFT.

**Reviewer overturned on a citation, upheld on the finding:** R2 asserts the R11/R12 catch-22
"also in C1_materials_chemistry_31." That item has **7** hard rules, no R11 or R12 — the
citation **FAILS**. The defect *is* present in that item under different numbering: R1
requires checking "ICSD, Materials Project" for non-existence while R3 requires "the
DFT/**Materials Project** band gap" and R4 the "**Materials Project** grand-potential/reaction
phase diagram." Same catch-22, wrong rule labels.

I also confirm **C3_arts_humanities_17 R5** misstates a theorem it forbids misstating: it
requires correct use of "'holonomy around a contractible loop is trivial iff the connection is
flat'." As written for a single loop the forward direction is false — a non-flat connection can
have trivial holonomy around a particular contractible loop. The correct statement quantifies
over *all* contractible loops.

### SC-6 — The three-axis structure collapses. **HOLDS; two reviewer numbers overturned.**
On my n=147 snapshot:

| Quantity | R3 claim | AC measurement |
|---|---|---|
| r(New, Surprising), aggregated | — | **0.938** |
| r(New, Surprising), per-judge verdicts | — | **0.929** |
| ICC(1,1) New / Useful / Surprising | 0.420 / 0.181 / 0.226 | **0.395 / 0.184 / 0.226** |
| Disattenuated r(New, Surprising) | ">1.0" | **3.11** |
| kappa on `creative_all_three` between judges | 0.149 | **0.135** |
| `all_three` rate at threshold 6.0 | — | **27.2%** |
| rate across +/-1 point (t=5 / t=7) | 6.3% – 37.0% | **5.4% – 36.1%** |
| records with an axis exactly 6.00 | 25% | **25.9%** |
| Adding S>=6 to an N&U>=6 gate | removes 1 of 41 | **removes 2 of 42** |
| Leaderboard tau(New, Surprising) | 1.00 | **0.80** (r = 0.977) |
| Surprising is *sole* binding axis | 1 of 138 | **22 of 147** |

**Overturned:** tau is 0.80, not 1.00 — `claude_shallow` and `gemini_shallow` swap (they are
0.37 apart on New). And "Surprising is the sole binding axis in 1 of 138 records" is wrong as
written: by argmin it is the sole minimum in **22 of 147**. R3 appears to have computed the
*threshold*-relative version, which does replicate (S is the sole sub-threshold axis in 2 of
147; it removes 2 of 42 from an N&U gate). R3 should state the defensible version.

**Worse than stated:** a disattenuated correlation of **3.11** is not "high" — it is a model
violation. It says the two axes are one latent variable and the reliability estimate is
mis-specified. That is stronger evidence for R3's conclusion than R3's own framing.

**R3's bar citation is apples-to-oranges, and the corrected comparison still fails.**
`benchmark_best_practices.md:125` sets the 0.80 bar on **ICC(k)** — panel reliability — not on
ICC(1,1). Applying the doc's own Spearman-Brown formula to my ICC(1) estimates for the
deployed **k=2** panel: ICC(2) = **0.566 New / 0.311 Useful / 0.369 Surprising**. Judges
needed to reach ICC(k)>=0.80: **6.1 / 17.7 / 13.7**. Comparison repaired; conclusion
unchanged and quantified. Useful — the axis that binds 96 of 147 records — would need an
18-judge panel at the current instrument's reliability.

**Score leakage HOLDS and is 2 items, not 1.** `expert_baseline` is injected verbatim at
`score.py:118`. `C1_materials_chemistry_01` ends: "Predicted expert scores on the isolated
axis: Useful ~7-8 …, New ~3-4, Surprising ~2-3." `C3_arts_humanities_17` leaks the same way.

**Surprise pre-specification HOLDS, and this is the mechanism, not a side-effect.** R3 says 9
of 10 surprise-isolated items pre-specify the surprising content. My read of the C2
`expert_baseline` fields confirms the substance. `C2_biology_medicine_34`, in full:
"The baseline would not anticipate that erythrocyte apoptosis machinery could reshape
*Plasmodium* virulence evolution, that stiffer cells force a different splenic filtration
architecture, or that fetal nucleated red cells crossing the placenta would rewrite prenatal
diagnostics." That is an answer key with three enumerated answers, handed to the judge.
`C2_materials_chemistry_07` is explicit: "coherent consequences beyond this list are the
surprising ones."

### SC-7 — `hard_rules` bind (R2's concession). **HOLDS, and it is the artifact's best asset.**
Useful when a judge cites a rule violation: **2.69** (n=221 verdicts). Without: **8.37**
(n=73). Gap **5.68**. R2's 2.84/8.27 replicates at the earlier n.
I add a dose-response check the reviewers did not run:
`corr(n_hard_rules, mean Useful) = **-0.495**` across 32 items — **correctly signed**. This is
the only correctly-signed dose-response in the artifact and it is the one thing p2 can
defensibly claim today (§5).

But the same data shows the judge cannot agree on *which* rule was broken: mean Jaccard on the
violated-rule sets between the two judges is **0.127**, with exact-set agreement **11.6%**,
and both judges report no violation in only **11 of 147** records. So the *presence* of a
violation is a strong signal and its *identity* is noise. Both facts must be reported.

### SC-8 — 12000-character truncation. **HOLDS; substantially worse than R2 stated.**
`judge/score.py:121` — `{report_text[:12000]}`. Measured against the transcripts:
- mean answer length **21,451** chars, median 17,972, max 57,282;
- **66.0%** of scored answers (97 of 147) exceed 12,000 chars;
- for those, the judge sees a mean of **49%** of the answer;
- **56.8%** of all violation citations come from records whose answer was cut.

R2 quoted ~38%; the true exposure is that two-thirds of answers are judged at roughly half
length. Hard rules of the form "the answer must state every ion's oxidation state," "the
specific radii used must be reported," "report the DFT band gap" are satisfied in exactly the
methods/table sections that get cut. Truncation therefore *manufactures* violations, and a
violation caps Useful at <=3, and Useful is the sole binding axis for **96 of 147** records.

---

## 1b. The objection all four reviewers missed — and it is the one that kills the leaderboard

Leave-one-family-out, with a 3-vendor panel and one severity-outlier judge, assigns a
**different panel to each entrant family by construction**:

| entrant | family | panel actually used |
|---|---|---|
| `openai_shallow`, `openai_deepresearch` | openai | {anthropic, **google**} |
| `claude_shallow` | anthropic | {**google**, openai} |
| `gemini_shallow`, `gemini_deepresearch_max` | google | {anthropic, openai} — **no google** |

And `judge_google` is a severity outlier, measured **within the same records** (paired, so this
is pure severity and not content):

| judge | n verdicts | New | Useful | Surprising | flags `creative` | mean #violations |
|---|---|---|---|---|---|---|
| `judge_anthropic` | 122 | 5.24 | 3.42 | 4.04 | **6.6%** | 2.48 |
| `judge_openai` | 85 | 5.46 | 2.64 | 4.48 | **7.1%** | 3.61 |
| `judge_google` | 87 | 7.89 | 6.49 | 8.08 | **55.2%** | 1.16 |

Paired within-record differences on min(N,U,S):
`google - openai = **+2.04**`, `google - anthropic = **+3.24**`,
`anthropic - openai = **-0.02**`.

So two judges are calibrated to each other and the third is ~2-3 points more lenient, and LOFO
deterministically removes the lenient one **exactly for the Google entrants**. Consequence:

```
observed min-axis leaderboard        google on panel?
  openai_shallow          5.20            yes
  openai_deepresearch     5.10            yes
  claude_shallow          3.14            yes
  gemini_shallow          3.08            NO
  gemini_deepresearch_max 2.34            NO
observed spread                       = 2.86
mean(with lenient judge) - mean(without) = 1.77
```

**About 60% of the entire observed leaderboard spread is attributable to which judge families
LOFO happened to leave in.** The two bottom-ranked entrants are precisely the two never scored
by the lenient judge, and the design provides **no common-judge comparison** for them at all —
`judge_google` never scores a Google entrant, so there is no judge shared by all five entrants.
The leaderboard is not identifiable from this data.

This also explains R3's finding more economically than R3 does: if one severity dimension
dominates every axis for every entrant, of course New and Surprising produce the same ranking.

The anti-self-preference control (O7) has, at k=2, introduced a larger bias than the one it
removes. The fix is cheap (§4, item 1) — but nothing in either paper survives without it.

---

## 2. Double-counting, contradictions, and root causes

Four reviewers found four field defects. There are **four root causes**, and they do not map
one-to-one onto the four fields.

### RC-A — One 12-character instrument bug drives most of the "field" objections
`report_text[:12000]` truncates 66% of answers to ~49%. Truncation manufactures hard-rule
violations. A violation caps Useful at <=3. Useful is the sole binding axis in 96 of 147
records. Therefore:

- R2's "the rules are unverifiable by construction" is **partly** a truncation artifact, not a
  rule-authoring artifact;
- R3's "Useful ICC(1,1) = 0.184, the worst axis" is downstream of judges disagreeing about
  content half of them cannot see;
- R4's "`axis_isolated` has negative discriminative validity" is **entirely** downstream. My
  measurement of the labeled-axis hit rate is not the flat 28% R4 reports — it is violently
  heterogeneous: **C1 (labeled `usefulness`) 82%, C2 (`surprise`) 41%, C3 (`novelty`) 4%, C5
  (`novelty`) 3%**, overall 35% vs 33% chance. `axis_isolated` is not an invalid label. It is a
  *valid* label for C1 and a label that Useful-domination overwrites for C3/C5. Fix RC-A and
  this objection has to be re-measured from scratch.

**Direct contradiction between R2 and R4.** R2's positive finding (hard_rules demonstrably
bind, 5.68-point gap) *is the mechanism of* R4's negative finding (the labeled axis is not the
binding axis). They cannot both be reported as independent defects. R4's `axis_isolated`
objection should be withdrawn as an independent charge and folded into RC-A.

### RC-B — New and Surprising are two names for one measurement against one author-written key
`known_answers` is a **negative** key ("do not credit this"). `expert_baseline` is a
**positive** key that in C2 literally enumerates the intended surprises. Both are pasted into
the same prompt. So both axes ask the judge one question: *is this content on the author's
list?* Hence r=0.93, disattenuated 3.11, identical rankings, kappa 0.135.

R1's "the novelty yardstick is uncitable" and R3's "Surprising is redundant" and R3's "graded
recall against an author key" are **one defect with two field names**. Any remediation that
touches only `known_answers` or only `expert_baseline` will not move the correlation.

The authors already know this. `docs/notes/field_justification.md` reports "CREST's own judges
score New and Surprising at r = 0.77-0.94, with 28% of verdicts assigning identical values,"
cites the CFA literature showing two-factor beats three-factor, and recommends demoting
Surprising to secondary. The finding is in the repo and not in the papers.

### RC-C — Documentation-as-claim: the papers describe an instrument that was never built
One defect, eight instances, spread across all four reviews: canaries (SC-1), frozen index
(SC-2), `rubric.md` not loaded and its key clause dropped (SC-3),
`randomize_answer_order: true` read by nothing (SC-3), `grounding_gate.metric:
fact_precision` read by nothing (SC-3), `--prereg` pointing at a nonexistent file that is never
consumed (SC-3), OSF timestamp (SC-4), human validation (13 assertion sites, zero data).
`schema.json` belongs here too: it is a well-formed JSON Schema that **no code validates** —
`grep -rn "jsonschema" --include=*.py .` returns nothing — so its `required` list, including
`known_answers`, is decorative, and `Challenge.from_json` (`run_crest.py:35-38`) uses
`d.get()`, so a missing `known_answers` becomes `None` and the judge silently reads
"(none provided)".

This is not four field problems. It is one process problem: **specification documents are
being shipped as evidence.** For a D&B submission that is the single most reputationally
expensive category of error, because every instance is falsifiable in one command.

### RC-D — Under-powered by construction, and the project's own doc says so
R3's rater-level unreliability and R4's item-level power complaint are the same complaint at
two levels of the design.

- **Rater level:** ICC(1) = 0.395/0.184/0.226; deployed panel k=2 gives ICC(2) =
  0.566/0.311/0.369; the project's own `benchmark_best_practices.md:125` bar of ICC(k)>=0.80
  needs 6/18/14 judges.
- **Item level:** MDE for a paired agent contrast at n=10 items/cell is **2.47** points
  (R4: 2.26); the observed C2 spread — p2's declared positive control — is **1.75** (R4: 1.83).
  Below MDE. `category x domain` cells are n=1 (10 cells) or n=2 (20 cells), so the
  `(1|challenge)+(1|judge)` model *with a domain term* promised in
  `p2/05_experiments.tex:8` is not identifiable.
- ICC(item) is far lower than R4 reported: **0.171 New / 0.041 Useful / 0.006 min3** (R4 said
  0.359). Items explain essentially no variance in the compound endpoint. R4 understated this.

`benchmark_best_practices.md` prescribes the remedies — size the panel by Spearman-Brown, use
`min(New, Useful, Surprising)` on the 1-10 scale instead of a "fragile threshold crossing",
report ICC(k) as headline, encode checkable constraints as a "deterministic pre-filter before
human rating." **None of the four was done.** The most efficient rebuttal the authors can
write is one that follows their own document.

### Reviewer arguments I discard

**R1's dose-response argument (corr(n known_answers, mean New) = +0.51).** I measure
**+0.341** on 32 items, so the sign replicates and the magnitude does not. But the argument is
a weak instrument regardless: list length is not a dose of novelty difficulty. Authors wrote
longer lists for well-trodden areas, which are also the areas where a judge with no anchor
rates generously. The positive correlation is as consistent with "authors calibrated list
length to field maturity" as with "the field does not work." R1 should drop this and lead with
the zero-citation finding, which is unarguable.

**R1's "22 items in 11 wordings" / "7 items with obviousness-tags."** Both undercount the
heterogeneity. With a combined pattern I find **20 of 50 items** carry judge-directive prose
inside `known_answers`, **38 entries**, and **27 distinct normalized wordings** — not 11. And
**11 items** (not 7) contain obviousness-tags rather than prior art. Crucially the split is
*systematic by category*, which R1 missed: for C1/C3/C5 `known_answers` holds published prior
art; for C2 it holds the author's list of "obvious" counterfactual consequences — e.g.
`C2_law_policy_37`: "Dockets overwhelmed and huge backlogs form without negotiated pleas
(obvious)." There is no publication asserting that. So `known_answers` is not one field
measuring one construct noisily; it is **two constructs sharing a key**, and the C2 half cannot
carry a citation even in principle. That reframing matters for remediation: adding DOIs fixes
C1/C3/C5 and is *impossible* for C2, which needs a separate field.

**R1's zero-URL/zero-DOI count and missing prior art.** Confirmed: **729** entries,
**0** containing `http`, **0** containing a DOI, **50.6%** with no 4-digit year (R1: 52.6%).
And `C5_law_policy_47` has 21 entries covering FPTP through liquid democracy while omitting
Phragmén (1894), Nanson (1882), and random ballot / random dictatorship (Gibbard 1977) — three
methods whose defining principles are absent from all 21 listed entries. An agent that proposes
sortition-over-ballots earns New credit for a 1977 result. Upheld.

---

## 3. Triage: BLOCKING / MAJOR / MINOR

**The line I draw.** For a D&B submission the reviewer's decision turns on two things:
(i) does the released artifact match its description, and (ii) is the headline claim
identifiable from the released data. So:

- **BLOCKING** = the *submitted claim* cannot be made true within a rebuttal cycle, either
  because it needs new data collection or because making it true requires withdrawing the
  paper's contribution. Note that "the fix is cheap" does not make an objection non-blocking if
  the fix changes every number in the paper — a rebuttal cannot introduce an entirely new
  results section.
- **MAJOR** = repairable before camera-ready with existing data plus engineering, or removable
  by an honest text edit that leaves a contribution standing.
- **MINOR** = hygiene. A reviewer will note it and it will not move a score.

### BLOCKING

**B1. The leaderboard is confounded with panel composition (§1b).** 1.77 of the 2.86-point
observed spread tracks whether the lenient judge was on the panel; no judge is shared by all
five entrants. Every ranking, dissociation, and crossover claim in both papers is
unidentifiable. The re-judge that fixes it is nearly free, but it replaces the entire results
section — that is a revision, not a rebuttal.

**B2. "Human-validated judge panel" with zero human data.** Asserted in **13 places**
including *both abstracts*, p2 §01's contribution list, all of p2 §04, both conclusions, and
`datasheet.md`. `find . -iname "*human*" -o -iname "*annot*" -o -iname "*rater*"` returns
**nothing**. p2 §04 goes furthest: it reports a "bounded scope (honest)" result that the panel
"is reliable on C2/C3/C4 but *not* on C1/C5" and builds a validity-stratification protocol on
it. That stratification is derived from a study that does not exist. Credible expert
annotation cannot be collected in a rebuttal window, and for a benchmark whose entire
instrument is a subjective LLM judge with ICC(k=2)=0.31 on the binding axis, an unvalidated
judge is a fundamental artifact deficiency, not a missing appendix.

**B3. The three-axis construct is not identified (RC-B).** "The first benchmark to score
deep-research outputs on the full New/Useful/Surprising triad" is p3's stated contribution.
A disattenuated New-Surprising correlation of 3.11, Surprising removing 2 of 42 records from
an N&U gate, and 9 of 10 C2 items handing the judge the answer key together mean the triad is
a dyad plus a leak. Repairing it means rewriting `expert_baseline` for 50 items *and*
re-measuring. The paper can retreat to a two-axis claim — which
`docs/notes/field_justification.md` already recommends — but the triad claim as submitted
cannot be rescued.

**B4. Pre-registration misrepresentation (SC-4).** `git log -S caesar_win` plus two `git show`
commands. Enum named after the intended winner; renamed 14 hours pre-submission in a commit
titled "honesty fixes"; no commit with predictions and no results; "(OSF, timestamped)" with no
OSF record; `--prereg` pointing at a file that does not exist and is never read. The only
repair is to delete every pre-registration claim — which removes p3's sole defense against
"this is post hoc," i.e. removes the argument the paper is built on. Unrecoverable this cycle.

### MAJOR

**M1. 12000-char truncation (SC-8, RC-A).** Judge-only re-run. Must be first; every other
number depends on it.

**M2. Self-contradictory and unsatisfiable hard rules (SC-5).** At least 1 item verified in
full detail with four independent defects; R2 reports >=6 of 50. Needs a rule audit plus
re-judge. Bounded work.

**M3. `expert_baseline` leaks target scores (2 items) and answer keys (all C2).** Data edit
plus re-judge. Cheap and high-value.

**M4. Asserted-absent artifacts other than human data:** canaries, order randomization,
`fact_precision` gate, dead config keys, unvalidated `schema.json`. Canaries and order
randomization are each <20 lines — *implement them*. The frozen index is not; *delete the
claim*.

**M5. `threshold_all_three = 6.0` is unpre-registered and fragile** (27.2% at 6.0; 5.4%-36.1%
across +/-1; 25.9% of records sit exactly at 6.00). Switch the primary endpoint to
`min(N,U,S)` on the 1-10 scale, per the project's own `benchmark_best_practices.md`.
Analysis-only.

**M6. Schema and loader hygiene:** `schema.json` never validated, `additionalProperties`
unset, no `enum` on `domain`, no `minItems` on `known_answers`, `category_name` absent from the
schema and silently dropped by `from_json` and present in **6** distinct values (one item
carries a long-form description as its value), `hard_rules` not in `required`,
`time_sensitivity` not written to `records.jsonl`, `d.get()` turning a missing
`known_answers` into "(none provided)". Half a day, no re-run, plus a CI test.

**M7. Statistical over-reach:** drop `domain` from the mixed model (cells n=1-2, not
identifiable); report the MDE; state that C2 fails as a positive control at 1.75 < 2.47.
Text plus re-analysis.

### MINOR

- `time_sensitivity` has `post_cutoff` n=1 and is never written to records — drop the field or
  populate it. It currently supports no contamination analysis at all.
- 50.6% of `known_answers` entries lack a year despite the field's own "dated" framing.
- `rationale` is 20.3% of item bytes and is never read at runtime (the authors already
  document this).
- With k=2 after LOFO, "median-aggregated" is a mean of two. Reword.

---

## 4. Prioritized remediation plan

Ordered by (value / effort), and by dependency — item 1 must precede all analysis because every
number changes.

| # | Change | Kills | Effort | Needs |
|---|---|---|---|---|
| 1 | **Re-judge everything with a common panel and no truncation.** Delete `[:12000]` (chunk-and-aggregate, or a long-context judge). Score every record with **all three** judges — LOFO becomes a robustness check with a judge random effect, not the primary. Report per-judge severity openly. | B1, M1, and forces a re-measure of the folded-in `axis_isolated` charge | hours | **re-judge only** (cache exists) |
| 2 | **Delete every claim the repo cannot instantiate.** "human-validated" (13 sites), "(OSF, timestamped)", "frozen retrieval snapshot"/"frozen snapshots", "canary", "order-randomized", "pre-register(ed)" wherever no artifact exists. Delete the dead `--prereg` arg and the two unread `judge_config.yaml` keys, or implement them. **Make p3's abstract placeholder disclaimer visible text — it is currently a LaTeX comment and invisible in the PDF.** | B4, most of M4, all of RC-C | ~1 day | **text only** |
| 3 | **Demote Surprising to secondary; make `min(N,U,S)` the primary endpoint.** Report ICC(k) as headline with ICC(1)+kappa alongside. Disclose the New-Surprising collapse in the paper, with the disattenuated-r>1 result stated as a model violation. | B3 as fatal, M5, R3 in full | 1-2 days | **text + re-analysis** |
| 4 | **Strip the answer keys out of the judge prompt.** Remove the 2 predicted-score leaks. Split the field: `expert_baseline` (the *expected* answer, judge-visible) vs `author_expected_surprises` (sidecar, never shown). | M3, half of RC-B | 2-3 days | data edit + **re-judge** |
| 5 | **Audit and repair `hard_rules`; make the checkable subset deterministic.** (a) machine-check every rule pair for permit/ban collisions over element and structure vocabularies; (b) **assert that every item's own `expert_baseline` satisfies that item's own rules** — C1_materials_chemistry_01 fails this today; (c) implement `benchmark_best_practices.md`'s prescription: a deterministic pre-filter for the arithmetic rules (charge balance, t, mu, tau, abundance, toxicity) so the LLM judge only scores in-constraint outputs. Report violation-set Jaccard (0.127) as a known limit. | M2, R2 in full | ~1 week | data + code + **re-judge** |
| 6 | **Cite the novelty yardstick and split its two constructs.** Add a URL or DOI to every prior-art entry (729 entries, 0 citations today). Add a `kind` tag: `prior_art` vs `obvious_consequence` — 11 items currently mix them and all 10 C2 items are the latter, which cannot be cited even in principle and needs its own field. Add the missing prior art (Phragmén 1894, Nanson 1882, Gibbard 1977 for C5_law_policy_47). Move all judge-directive prose (20 items, 38 entries, 27 wordings) out of the data and into **one** template rendered by `score.py`. | R1 in full, half of RC-B | 1-2 weeks | data edit + **re-judge** |
| 7 | **Schema and loader hygiene + CI.** `additionalProperties: false`, `minItems` on `known_answers`, `enum` on `domain`, add `category_name` and `hard_rules`; validate on load; make `from_json` **raise** on missing `known_answers` instead of emitting "(none provided)"; fix the 6th `category_name` value; write or delete `time_sensitivity`. One CI test that validates all 50 items. | M6, R4's schema bullets | half a day | **code only** |
| 8 | **Re-scope the statistics to what n supports.** Drop `domain` from the model. Publish the MDE and state C2 is underpowered as a positive control (1.75 < 2.47). Either scope claims to categories at n=50 (MDE 1.11) or add items. Ship the "statistics card" the project's own doc asks for. | M7, RC-D at item level | 2-3 days | **text + re-analysis** |
| 9 | **Human validation.** >=3 experts, all five categories, a stratified subset; Krippendorff alpha (ordinal) plus judge-human agreement against the human-human ceiling. Panel sizing from the measured ICC(1), which today implies 6/18/14 judges — so this study is also what tells you whether to fix the instrument instead of buying judges. | B2 — the only real fix | weeks, real budget | **new human data** |

**Do 1-3 before anything else.** Items 1 and 2 together cost about a day and a half and remove
every objection that a reviewer can verify in one command. Item 3 converts the strongest
surviving objection into a disclosed limitation using the authors' own internal analysis. That
is the whole rebuttal.

---

## 5. Honest minimum viable claim, today, with no new data

### What this artifact can support

1. **A released benchmark artifact.** 50 expert-authored deep-research creativity challenges
   with per-item scoring machinery and an open judge harness, agent-facing prompts held short
   and open (median ~110 words) with the scoring machinery judge-side. That design choice is
   real, defensible, and novel. This is a genuine D&B contribution and it is not what the
   reviewers attacked.

2. **One positive empirical finding: `hard_rules` bind.** Useful is **2.69** when a judge cites
   a rule violation vs **8.37** when it does not (n=294 verdicts), and
   `corr(n_hard_rules, mean Useful) = -0.50` across 32 items. This is the artifact's only
   correctly-signed dose-response, and — importantly — it is a **within-verdict** contrast, so
   it survives the panel-composition confound that destroys the leaderboard. Report it with its
   limit: judges agree a rule was broken but not which one (Jaccard 0.127).

3. **A publishable negative/methodological finding.** On 147 verdicts: New and Surprising are
   not separable (per-judge r=0.93; disattenuated correlation 3.11, a model violation);
   single-rater ICC(1) is 0.40/0.18/0.23 so the deployed 2-judge panel reaches ICC(2) of
   0.57/0.31/0.37; the binding axis is Useful in 96 of 147 records; and — the sharpest result —
   **leave-one-family-out with a 3-vendor panel makes the leaderboard unidentifiable**, because
   judge severity varies by 2-3 points on the 1-10 scale and LOFO assigns panels by entrant
   family. That last result is a real, generalizable warning to everyone building LLM-judge
   leaderboards with self-preference controls, and CREST is in a strong position to be the paper
   that reports it.

A paper making claims 1-3 is honest, is supported by data in this repo today, and is
interesting. It is a different paper from either submission.

### What it currently claims and must stop claiming

**p2, `sections/00_abstract.tex:2`:**
- *"Entrants run under their provider-native web search, and a frozen, shared retrieval index
  gives a fair, reproducible, contamination-controlled run mode."* — **delete the second
  clause.** `FrozenIndex.__init__` raises.
- *"Scoring uses a **human-validated**, leave-one-family-out, **median-aggregated**
  multi-vendor judge panel"* — delete "human-validated" (no human data); "median-aggregated" is
  a mean of two after LOFO.
- *"Evaluating a field of frontier deep-research agents, we find that agent creativity is
  axis- and task-dependent and dissociates across systems: the pattern is theory-predicted"* —
  **withdraw.** Replace with something like: "In a pilot on five frontier agents we find that
  judge-severity variance under leave-one-family-out exceeds the between-agent spread, and we
  therefore make no ranking claim."
- *"We release the challenges, judge harness, **frozen snapshots**, and datasheet."* — delete
  "frozen snapshots".

**p2 elsewhere:**
- `01_introduction.tex:11` *"A validated judge. A **human-validated**, leave-one-family-out
  judge panel … reported with per-category reliability and honest bounds on where it fails."* —
  delete "human-validated"; the per-category reliability numbers must be the measured ones.
- `04_judge_validation.tex:8` and `:10` — the entire "Human validation" paragraph and the
  "reliable on C2/C3/C4 but *not* on C1/C5" validity-stratification describe a study that does
  not exist. Cut, or relabel as planned work in future tense.
- `05_experiments.tex:4` *"(OSF, timestamped)"* — delete.
- `05_experiments.tex:10` *"All headline numbers therefore come from the pre-registered
  frozen-index run and remain **[PLACEHOLDER]**."* — a D&B submission cannot ship with
  placeholder headline numbers while the abstract asserts a finding. Fill from the re-judged run
  (plan item 1) or remove the finding from the abstract. As submitted the abstract and §5
  contradict each other.
- `09_conclusion.tex:2` — "contamination-controlled", "human-validated", "frozen snapshots",
  and *"Our cross-agent finding is that creativity does not order current agents on a single
  scale---it dissociates by task in a theory-predicted way"* all go.

**p3, `sections/00_abstract.tex`:**
- *"**human-validated**, multi-vendor leave-one-family-out judge panel"* — delete
  "human-validated".
- *"Using CREST we report a task-dependent effect: an exploration-based research agent … is
  more creative on tasks that require connecting distant fields or counterfactual ('what-if')
  reasoning, but not on single-answer or open-ended tasks."* — **withdraw.** There are **no
  Caesar records in either run directory.** The five agents present are
  `claude_shallow`, `gemini_shallow`, `openai_shallow`, `openai_deepresearch`,
  `gemini_deepresearch_max`.
- *"Ablations indicate the effect is mechanism-driven---disabling one component of the agent
  degrades one task type but not others"* — **withdraw.** No ablation data exists.
- *"whereas winning only where the mechanism predicts, on a benchmark whose own author's system
  does not top every category, argues the effect is real"* — **delete.** This argument is
  entirely load-bearing on the pre-registration, and `git log -S caesar_win` shows the
  prediction field was named after the intended winner and renamed 14 hours before submission.
- *"We release CREST---questions, **frozen retrieval snapshot**, judge, and analysis"* — delete
  "frozen retrieval snapshot".
- The `% [NUMBERS ARE PLACEHOLDERS: …]` disclaimer is a **LaTeX comment** and does not render.
  Either make it visible text or do not submit p3 this cycle. Shipping an abstract that asserts
  findings while the disclaimer is invisible is the version of this problem that a reviewer will
  describe as deliberate.

**p3 elsewhere:** `03_crest_benchmark.tex:30` *"We **pre-register** the per-task-type
prediction"* and `:35` *"the pre-registered predicted direction"* → "the authors' stated prior
expectation, recorded in the item file; not externally timestamped."

**`docs/datasheet.md:47-52`** — the frozen-index manifest ("Released as a manifest (URL +
timestamp + SHA-256 per document)") and the canary claim. Delete or implement. Note the canary
claim is also load-bearing for the datasheet's licensing argument in §5, which must change too.

---

## 6. AC summary

The four reviewers are substantially right and somewhat over-counted. Of eight decision-relevant
claims I checked, **six HOLD**, **two are PARTIAL** (R3's tau=1.00 and sole-binding-axis
framing; R2's C1_31 citation), and in **four cases the true state is worse than the reviewer
reported** (truncation 66% not 38%; disattenuated r 3.11 not ">1"; ICC(item) 0.006-0.18 not
0.359; two score-leaking items not one). One reviewer argument — R1's dose-response — I discard
as a weak instrument. One reviewer charge — R4's `axis_isolated` invalidity — I fold into
another root cause and it must be re-measured after the truncation fix.

More importantly: **all four reviewers missed the objection that actually decides the paper.**
Leave-one-family-out with a 3-vendor panel and a 2-3 point judge-severity spread makes the
leaderboard non-identifiable, and accounts for roughly 60% of the observed agent spread. The
four field-schema critiques are about *whether the axes mean anything*; this one is about
*whether the headline number means anything*. It does not.

The good news, and the authors should hear it: **the single highest-value fix costs hours, not
weeks.** A judge-only re-run with a common panel and no truncation (a generation cache exists)
plus a day of deleting unsupported claims removes every objection a reviewer can verify in one
command. What remains after that is a real artifact and an honest, genuinely interesting
methodological result about the limits of LLM-judged creativity. That paper is publishable.
Neither of the papers currently in front of me is.
