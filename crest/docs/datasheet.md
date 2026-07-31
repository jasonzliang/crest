# Datasheet for CREST

Follows *Datasheets for Datasets* (Gebru et al., 2021) and ships with Croissant + Croissant-RAI
metadata (`croissant.json`, produced at release). This datasheet is a release gate: NeurIPS/ICLR
Datasets & Benchmarks desk-reject checks (licensing, contamination, author-COI, human-subjects)
are answered here.

## 1. Motivation
- **Purpose.** Measure the *creativity* (New / Useful / Surprising) of deep-research web agents,
  organized by task type, to fill the gap left by correctness-only benchmarks
  (GAIA, BrowseComp, DeepResearch Bench, LiveResearchBench). CREST is the evaluation artifact;
  it is not a training set.
- **Who built it / funding.** [Anonymized for double-blind review.] Funding and institutional
  affiliation disclosed in the camera-ready.
- **Conflict of interest (COI).** One entrant (an exploration-based agent, cited as prior work) was
  built by parties overlapping with the benchmark authors. Mitigations: leave-one-family-out
  judging; the entrant is one of many; **all headline findings are reported with it removed**; the
  benchmark is designed so that entrant does not top every category; and the optional mechanism
  case study is gated on that entrant *not* being rank-1.

## 2. Composition
- **Instances.** 50 expert-authored research challenges (10 per category). Each is a natural-language
  research query plus metadata (see `questions/schema.json`): `id`, `category` (C1–C5), `domain`,
  `axis_isolated`, `time_sensitivity`, `known_answers[]` (dated), `hard_rules[]`, `expert_baseline`,
  `predicted_direction`, `rationale`.  [REMOVED 2026-07-30 -> analysis/preregistration.yaml]
- **Balance.** 10 per category × 5 categories; 8–9 per domain × 6 domains (biology/medicine,
  materials/chemistry, economics/business, law/policy, engineering, arts/humanities). Predicted
  directions: 20 predicted-null, 20 favored, 10 parity (used only for pre-registration).
- **Labels/ground truth.** There is no single correct answer (by design). Each item ships the three
  scoring anchors (known-answers list, hard rules, expert baseline). Scores are produced at
  evaluation time by the judge panel + human validation, not stored as fixed labels.
- **Splits.** Items are tagged pre/post training-cutoff; a rolling held-out set is added each cycle
  and is not published until after its evaluation window.
- **External data.** [NOT IMPLEMENTED] Retrieval is **live provider web search**; `FrozenIndex`
  raises `NotImplementedError`, so no snapshot exists and no run is contamination-controlled.
  Intended design: a frozen, dated corpus snapshot (see §4); that snapshot
  manifest ships as URLs + timestamps + SHA-256 hashes, not raw content.

## 3. Collection process
- Challenges were authored/adapted by domain-aware authors, seeded from the five reference
  categories, then expanded to 50 with per-item metadata. Each item requires multi-source synthesis
  (never a single lookup), verified during vetting.
- **Adversarial item-vetting log (§ appended below).** Every item passed an ICLR-reviewer-style
  red-team for: (i) contamination risk, (ii) synthesis-required (no single-source answer),
  (iii) axis-isolation (item exercises its labeled category, not a confound), (iv) headroom (not
  saturable by a strong baseline), (v) metadata completeness. Failures were revised or replaced;
  the log records disposition per item.

## 4. Preprocessing / frozen index
- **Frozen shared index.** All agents retrieve from one dated snapshot through a common search API
  with matched tool/compute budget, so "New/Surprising" reflect synthesis rather than fresher
  retrieval, and runs reproduce. Released as a manifest (URL + timestamp + SHA-256 per document).
- **Canaries.** [NOT IMPLEMENTED] **Zero of the 50 items currently embed a canary string**
  (`grep -ci canary` over the item file returns 0). Planned, not shipped; the release/licensing
  argument in §5 must not rely on it. Would enable post-hoc detection in future model
  training corpora.

## 5. Uses
- **Intended.** Benchmarking and diagnosing the creativity of deep-research agents; studying the
  task-dependence of creativity; judge-validity research.
- **Out of scope / cautions.** Not a leaderboard of overall agent quality; not a correctness or
  safety benchmark; not a training set (canaries + license restrict training use). Creativity scores
  on C1/C5 are human-anchored — do not treat the automated judge as authoritative there
  (see the paper's judge-validation section).

## 6. Distribution & licensing
- Questions, schema, frozen-index manifest, judge config + rubric, and analysis code are released
  under a documented open license. The corpus is distributed as a hash/URL manifest (not
  redistributed content) to respect source licensing. Croissant + Croissant-RAI records accompany
  the release. Versioned (semver); each version pins model-snapshot IDs used in reported runs.

## 7. Maintenance
- Maintained by the (anonymized) authors; issues/PRs via the public repo. Rolling fresh-question
  set refreshed each cycle; deprecated items retained with tombstones for reproducibility. Model
  snapshots for closed agents are time-indexed; the open-weight entrant on the frozen index is the
  permanently reproducible anchor.

## Human subjects (judge-validation study)
- The human validation and pairwise-expert study use paid domain experts scoring model outputs
  (not personal data). IRB/ethics status and consent language: [to be finalized before camera-ready];
  no PII is collected; raters are compensated at/above local standard rates.

---

## Appendix: adversarial item-vetting log
Per-item dispositions (contamination / synthesis-required / axis-isolation / headroom / metadata).
[TABLE GENERATED BY THE COMMITTED VETTING PASS — one row per challenge id; see
`analysis/item_vetting.md` for the full rationale per item.]
