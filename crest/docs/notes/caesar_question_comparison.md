# CREST's 50 vs the Caesar paper's 5 — question-set comparison + run-readiness

Pre-run vetting pass, 2026-07-30. Compares the shipped `questions/crest_challenges.jsonl` against
(a) the five original challenges in the Caesar paper (arXiv:2604.20855, App. pp.19–20) and (b) the
design contract in `science_moonshot/documentation/caesar/caesar_creativity_eval_spec.md` (v1,
2026-07-24). Complements `docs/item_vetting.md` (per-item gates); this note is about the *set*.

## The five original Caesar questions (verbatim)

| Cat | Original query |
|---|---|
| C1 Constrained | "Invent a new emotion that humans don't experience." |
| C2 Counterfactual | "If humans evolved with echolocation instead of color vision, how would that change painting, architecture, and mathematics? Walk through each consequence." |
| C3 Cross-Domain | "Apply the mathematical structure of calculus (not the concepts, but the formal relationships) to cooking." |
| C4 Meta-Creativity | "Create a creativity metric for AI systems that doesn't rely on human judgment, novelty, usefulness, or surprise." |
| C5 Open-Ended | "Invent a completely original business idea that doesn't exist yet." |

Theory anchors are per-category and carried over unchanged: Ward 1994 (C1), Byrne 2005 (C2),
Gentner 1983 (C3), Amabile 1982 inverted (C4), Boden 2004 historical creativity (C5).

## What changed, and why it matters

| Dimension | Caesar paper (5) | CREST (50) | Verdict |
|---|---|---|---|
| n / cell | 5 total, 1 per category | 50, **10 per category** | spec asked ~30 (20 min) — **exceeded**; retires n=5 Cliff's-Delta |
| Domains | none (generic/domain-free) | **6 labeled** (8–9 items each) | meets spec |
| **Research necessity** | **none** — answerable with zero web search | every item demands multi-source literature synthesis | **the biggest fix** (below) |
| Novelty baseline | none | dated `known_answers` per item (8–33 entries) | New is now scored against something |
| Usefulness gate | none | 3–12 checkable `hard_rules` | Useful is now falsifiable |
| Surprise baseline | none | `expert_baseline` per item | Surprise is now anchored |
| Axis isolation | not labeled | `axis_isolated` per item | meets spec |
| Length control | **3 output settings** (full / ELI5 / ELI5-450w) | **1 setting** | **regression** (below) |
| Item overlap | — | zero reuse of the original 5 | supports the paper's "fresh, held-out questions" claim |

### The decisive improvement: the original 5 didn't require research
"Invent a new emotion that humans don't experience" is armchair ideation — an untooled chat model
answers it as well as a deep-research agent. For a *deep-research* creativity claim that is a fatal
confound: search quality cannot influence the score, so the benchmark cannot attribute creativity to
research behaviour. CREST's items instead force literature fusion (e.g. C1_biology_medicine_00 asks
for a novel CRAB antibacterial mechanism grounded across "essentiality data, the CRAB resistome and
clinical pipeline, target druggability, and human off-target risk"). This is what makes the grounding
gate meaningful rather than decorative.

### The one regression: length control was dropped
The Caesar paper ran every query under three output constraints *specifically because* it found a
verbosity confound (r=0.47), and the spec requires ">= 3 length bins; report length-matched
comparisons for EVERY category". CREST runs a single unconstrained setting. `analysis/stats.py`
names length as an intended covariate ("O8 length: output length as a covariate (not just bins)")
but **no length term is implemented** in any model. `records.jsonl` does store
`output_len_tokens`, so a covariate is recoverable post-hoc — length-*matched* bins are not.

## Run-readiness status

### Fixed in this pass (was a hard blocker)
**12 items pointed the agent at content it never receives.** Items 34–45 (the new C2/C3/C4 batch)
contained instructions like "Do not merely restate the obvious first-order effects already listed in
known_answers", "Every correspondence in known_answers is KNOWN", "(see novelty gate)", and — worst
— C4_42–45's hard requirement "Ground it in >=3 traditions from known_answers". The harness passes
only `ch.query`; `known_answers` is judge-side. So these were unfollowable instructions, and because
judges *do* see the rules, an agent could be penalized for failing an instruction it could not read.
Rewrote all 16 occurrences self-contained ("...a domain expert would name immediately", "...already
established in the published literature", "...and earn no novelty credit"), preserving the bar
exactly. No other item touched. `docs/item_vetting.md` missed this because it graded items in
isolation rather than against what the harness actually shows the agent.

Also confirmed already-fixed since that audit: C2_law_policy_09's `expert_baseline` is now real
(1087 chars, was a stub) and `category_name` is backfilled across all 50.

### Clean
All 50 queries well-formed (no truncation, brace/encoding issues), every item has a non-empty dated
`known_answers` (8-33 entries; 729 across the set), >=3 checkable `hard_rules`, an `expert_baseline`, and full labels.
Balanced 10/category; domains 8–9 each.

### Gaps that bound the claims (NOT run blockers)

Recoverable from this run's `records.jsonl` afterwards:
* **No inter-judge reliability.** `judge/judge_config.yaml` mandates `[krippendorff_alpha, icc]`;
  `analysis/stats.py` contains zero references to either. Per-judge scores *are* persisted as a
  list-of-objects, so IRR is computable post-hoc — but it is currently unwritten code.
* **Length covariate** — see above; `output_len_tokens` is recorded.

**Now-or-never** (cannot be fixed after the run):
* **post-cutoff subset is n=1.** Only `C4_arts_humanities_23` is `post_cutoff` (35 `timeless`,
  14 `pre_cutoff`). The spec requires a post-cutoff subset and "report results split
  pre/post-cutoff" — impossible at n=1. Combined with `FrozenIndex` still raising
  `NotImplementedError` and the manifest recording `contamination_controlled: false`, **the
  contamination-control leg of the design is unsupported by this run.** Note the p3 abstract already
  advertises a "frozen retrieval snapshot" — that claim outruns the code.
* **No open-weight judge.** The protocol file requires >=1 ("fewer shared blind spots than the
  frontier trio"); `judge_config.live.yaml` has only anthropic/openai/google. Checked the live keys:
  no open-weight model on the OpenAI key; the Google key exposes `gemma-4-31b-it` /
  `gemma-4-26b-a4b-it`, but Gemma shares Google's lineage, so labeling it `open_weight` would
  partially defeat leave-one-family-out when judging `gemini_shallow`. Satisfying this honestly
  needs a third-party host (Together/Fireworks/Groq) — no key available. Left unsatisfied rather
  than faked.

### Weak tier, unchanged
`C5_economics_business_46`, `C5_law_policy_47`, `C5_engineering_48`, `C5_arts_humanities_49` were
marked REVISE by the earlier audit for thin synthesis / low headroom. Queries have since roughly
doubled (~350 → ~780 chars), but they still carry 5 `hard_rules` vs 7–8 and 21 `known_answers` vs
24–33 for the C5 originals. Partly addressed, not fully. Since C5 is a *predicted-null* category,
a saturable tier inflates C5 scores and weakens the "predicted null" evidence rather than the
headline wins — a bias against the paper's own thesis, so not disqualifying for this run.
