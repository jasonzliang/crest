# Datasheet for CREST

Follows *Datasheets for Datasets* (Gebru et al., 2021). This datasheet describes the artifact **as
shipped**, with anything unbuilt marked `[NOT IMPLEMENTED]` rather than described in the present
tense. It is also a release gate — NeurIPS/ICLR Datasets & Benchmarks desk-reject checks (licensing,
contamination, author-COI, human-subjects) are answered here.

**This file is the SINGLE SOURCE OF TRUTH for dataset composition** — field lists, schema version,
per-category/domain/axis counts, the `time_sensitivity` split, prior-art dating rates and quarantine
status. Other docs cross-reference §2 instead of restating those numbers. Conversely, every figure
measured *from a scored run* (endpoint means, correlations, ICC, judge severity) lives in
`design.md` §0 and is not restated here.

> **Release status: NOT RELEASE-READY**, but no longer for the reason this note used to give. The
> mechanical pre-release gate (`analysis/ci_check.sh`) now **PASSES** all 25 checks: the
> `C1_materials_chemistry_01` self-contradiction it used to fail on has been fixed. Run the gate for
> the live list rather than trusting any transcript, including this one.
> What still blocks release: Croissant/Croissant-RAI metadata is **not written** — there is no
> `croissant.json` in the repo — so the Croissant desk-reject gate is not cleared; **no human study
> has been run**, so the judge panel is unvalidated against human raters; the 250-record run
> directory is gitignored and therefore **not distributed**, so the reported results cannot be
> recomputed from a fresh clone; and both field-ablation deltas quoted in the papers (+0.98 on *New*,
> −0.02 on *Surprising*) were measured on a superseded run and **cannot be re-derived** against the
> released records, which all carry `judge_prompt_version: null`.

## 1. Motivation
- **Purpose.** Measure the *creativity* (novelty / Useful / Surprising) of deep-research web
  agents, organized by task type, to fill the gap left by correctness-only benchmarks
  (GAIA, BrowseComp, DeepResearch Bench, LiveResearchBench). CREST is the evaluation artifact;
  it is not a training set.
- **Who built it / funding.** [Anonymized for double-blind review.] Funding and institutional
  affiliation disclosed in the camera-ready.
- **Conflict of interest (COI).** **Corrected.** This entry previously stated that one entrant (an
  exploration-based agent, cited as prior work) was built by parties overlapping with the benchmark
  authors, and listed four mitigations for it. That was false, and both papers cited this file as
  their COI record while it said so. **No author-built agent was entered.** The released registry
  contains five off-the-shelf commercial systems — `openai_deepresearch`, `openai_shallow`,
  `claude_shallow`, `gemini_deepresearch_max`, `gemini_shallow` — and all 250 scored records belong
  to them, so three of the four mitigations were vacuous ("reported with it removed" removes
  nothing; "does not top every category" and "gated on that entrant not being rank-1" are undefined
  for a non-entrant). The optional mechanism case study those triggers gated has been deleted from
  the paper. The COI that *does* exist is narrower: a prior workshop preprint by the same authors
  piloted an earlier version of this taxonomy on an exploration agent, so the **taxonomy** has
  author provenance even though no **entrant** does.
  **Leave-one-family-out judging is not a mitigation either** — it is off by
  default (`judge/judge_config.live.yaml: leave_one_family_out: false`) because with three vendors
  it confounded judge identity with entrant family and moved the leaderboard more than the
  self-preference it removed. Self-preference is instead *measured*: every judge row is stamped
  `same_family` and enters the model as a covariate, and the LOFO subset is recoverable post-hoc.
  No ranking claim is made at all (`analysis/preregistration.yaml: ranking_claims: none`).

## 2. Composition
- **Instances.** 50 research challenges (10 per category, C1–C5). Each is a natural-language
  research query plus metadata. The shipped schema (`questions/schema.json`, version
  `crest-challenge/3.2.0`, `additionalProperties: false`) defines **nine required fields** —
  `id`, `category` (C1–C5), `domain`, `query`, `axis_isolated`, `time_sensitivity`,
  `known_answers[]`, `hard_rules[]`, `expert_baseline` — plus **one optional field**,
  `author_expected_surprises` (present in 7 of 50 items). Ten fields total.
  - **Judge-hidden fields.** `expert_baseline` and `author_expected_surprises` are retained in the
    dataset for provenance but are **not sent to the judge** (see §"Labels" and `judge/rubric.md`).
  - **Removed fields.** `predicted_direction` and `category_name` (schema v2.0.0) and `rationale`
    (v3.0.0). Predictions now live in `analysis/preregistration.yaml`; per-item design rationale in
    `questions/item_design.jsonl`, whose id-bijection with the challenge file is enforced by
    `analysis/ci_check.sh`. v3.2.0 widened the `domain` enum to twelve values so a second,
    unrelated 50-item AI/ML set (`questions/crest_aiml_challenges.jsonl`) validates against the
    same schema. **That set is not part of this datasheet**: it is not listed in
    `config/eval_config.yaml`, has no `item_design.jsonl` rows, is not covered by the item-vetting
    or live-web audits, and has never been run or scored. A union enum also means nothing now stops
    an arts/humanities item being tagged `systems_efficiency`.
  - **Enforcement.** The schema is validated on load (`harness/run_crest.py::load_challenges`), and
    `Challenge.from_json` **raises** on a missing `id`, `query`, `known_answers` or
    `expert_baseline`. Previously the schema was never applied and a missing `known_answers`
    silently became "(none provided)" in the judge prompt.
- **Balance.** 10 per category × 5 categories; per domain: biology/medicine 9, materials/chemistry 9,
  economics/business 8, engineering 8, law/policy 8, arts/humanities 8. `axis_isolated`: novelty 20,
  usefulness 10, surprise 10, balanced 10. Per-category predicted directions (20 predicted-null,
  20 favored, 10 parity) live in `analysis/preregistration.yaml`, which states in its own header
  that it is **not externally timestamped** and must not be described as pre-registration.
- **Labels/ground truth.** There is no single correct answer (by design). Each item ships three
  authored anchors, but only two of them are used at scoring time: the judge sees `known_answers`
  and `hard_rules`; `expert_baseline` is withheld (ablating it barely moved Surprising — see
  `design.md` §0 — and in 7 items it carried the author's own list of the intended surprises).
  Scores are produced at evaluation time by the LLM judge panel. **`[NOT IMPLEMENTED]` Human
  validation:** no human panel has been run, no human scores exist, and no code reads
  `human_validation_required_categories` — a key that no longer exists in any config, only in
  `docs/judge_protocol_intent.md`, the documentation-only record of the deleted `judge_config.yaml`.
- **Splits.** Items carry a `time_sensitivity` label, but the distribution makes a pre/post-cutoff
  split unusable as shipped: **35 `timeless`, 14 `pre_cutoff`, 1 `post_cutoff`**. Reporting scores
  split by cutoff class — a control this project's own design spec calls for — is therefore not
  currently possible. `[NOT IMPLEMENTED]` There is **no** rolling held-out set and nothing is
  withheld from publication: all 50 items, their prior-art lists and their baselines are in the
  public repo.
- **Prior-art dating.** `known_answers` is documented as a *dated* set, and the judge prompt calls it
  the "DATED PRIOR-ART SET", but most entries are not dated. Measured 2026-07-31 over the shipped
  file, counting an entry as dated if it contains a 4-digit year (`(?<!\d)(19|20)\d\d(?!\d)`) and
  excluding each item's leading `Dated as of …` preamble entry, which is a header rather than prior
  art (21 such entries; 708 substantive entries remain):

  | id block | dated | rate |
  |---|---|---|
  | file-wide | 363 / 708 | **51%** |
  | `_0x` | 64 / 140 | 46% |
  | `_1x` | 101 / 112 | **90%** |
  | `_2x` | 152 / 211 | 72% |
  | `_3x` | 22 / 99 | **22%** |
  | `_4x` | 24 / 146 | **16%** |
  | `_42`–`_45` only | 2 / 48 | **4.2%** (46 of 48 carry no year) |

  Earlier drafts quoted 52% / 91% / 22% / 18%; the first, second and fourth were off by 1–2 pp
  against this definition. Include the preamble entries and the file-wide rate is 53%, so the
  convention matters — hence stating it. An undated bare entry cannot function as a dated novelty
  baseline, and the audit found the dating error direction is one-sided: prior art is consistently
  made to look *younger* than it is, which inflates novelty
  (`docs/notes/audit_live_C4_remainder.md` §2).
- **External data.** `[NOT IMPLEMENTED]` Retrieval is **live provider web search**; `FrozenIndex`
  raises `NotImplementedError`, so no snapshot exists and no run is contamination-controlled — each
  run manifest records `contamination_controlled: false` and states the caveat. Intended design: a
  frozen, dated corpus snapshot (see §4).

## 3. Collection process
- Challenges were authored/adapted by domain-aware authors, seeded from the five reference
  categories, then expanded to 50 with per-item metadata. Each item is *intended* to require
  multi-source synthesis (never a single lookup). **This was verified by reading, not by test:** no
  tool-ablation check (score a no-web model; cut anything it answers) has been run.
- **Provenance caveat on "expert".** There is no documented expert-elicitation protocol, no
  annotator credentials, no annotations-per-item, and no inter-expert agreement — the Croissant-RAI
  `dataAnnotationProtocol` fields are unfilled. One `expert_baseline`
  (`C2_biology_medicine_34`) is explicitly **model-drafted, not expert-written**, and is flagged
  in-field as needing physiologist review.
- **Adversarial item-vetting log** (`docs/item_vetting.md`, appended in summary below). Every item
  was red-teamed for: (i) contamination risk, (ii) synthesis-required, (iii) axis-isolation,
  (iv) headroom, (v) metadata completeness. **That pass is now partly superseded**: a subsequent
  live-web audit of all 50 items (~610 claims, `docs/notes/audit_live_*.md`) contradicted several of
  its PASS grades, and its header records what no longer holds. Both documents should be read
  together; neither alone is current.
- **Quarantine.** `questions/quarantine.yaml` is the mechanism for excluding an item whose defect
  makes its scores uninterpretable; quarantined items are dropped at load with a loud notice, counted
  in the run manifest, and block release. **Currently zero items are quarantined.**
  `C2_biology_medicine_34` was quarantined 2026-07-30 (its `expert_baseline` was 156 chars and failed
  `minLength(200)`; 64% of the field turned out to be an answer key) and **restored 2026-07-31** with
  a 1,620-char model-drafted baseline (measured on the shipped file; `item_vetting.md` said 1,478 and
  was wrong) — so the shipped set is 50/50, with that item's provenance
  weaker than the rest. Three further items are on a documented watch-list, one of them
  (`C4_engineering_45`) with an auditor verdict of "do not release" because its novelty gate is
  inverted: it offers as its example of a new mechanism something its own `known_answers` already
  contains.

## 4. Preprocessing / frozen index
- **Frozen shared index.** `[NOT IMPLEMENTED]` The intended design is that all agents retrieve from
  one dated snapshot through a common search API with matched tool/compute budget, so
  "novelty/Surprising" reflect synthesis rather than fresher retrieval, and runs reproduce; it
  would be released as a manifest (URL + timestamp + SHA-256 per document). **None of this exists.**
  `harness/agents.py::FrozenIndex` raises on construction specifically to stop a live run being
  mislabeled as contamination-controlled. No `--index` CLI flag exists -- the plumbing was removed
  rather than left as a stub implying a mode the harness cannot enter.
  Search budgets are also **not** matched across entrants: the shallow arm is capped where the
  provider exposes a cap and the deep arm's budget is provider-managed and uncappable, which each
  run manifest discloses as a live confound.
- **Canaries.** `[NOT IMPLEMENTED]` **Zero of the 50 items embed a canary string**
  (`grep -ci canary` over the item file returns 0). Planned, not shipped; the release/licensing
  argument in §5–§6 must not rely on it, and `analysis/ci_check.sh` has a check that fails the build
  if any doc makes an unqualified canary claim.
- **Trajectory logging.** Partial. Each run writes immutable `records.jsonl` (per-record status,
  grounding result, per-judge scores, `n_searches`, `output_len_tokens`) and `transcripts.jsonl`
  (full answer text + citations). `[NOT IMPLEMENTED]` Per-query search logs and automated
  search-time-contamination scanning (benchmark-metadata / question-context / explicit-answer
  leakage) do not exist.

## 5. Uses
- **Intended.** Benchmarking and diagnosing the creativity of deep-research agents; studying the
  task-dependence of creativity; judge-validity research.
- **Out of scope / cautions.** Not a leaderboard of overall agent quality (no ranking claim is made:
  measured judge severity exceeds the entire between-entrant spread — `design.md` §0); not a correctness or safety
  benchmark; not a training set. **The no-training request rests on the license and on this
  document only — there are no canaries to detect ingestion and no gated split to withhold.**
  Creativity scores are LLM-panel scores throughout: no category is human-anchored, so the automated
  judge should not be treated as authoritative anywhere, and least of all on C1/C5, where this
  project's own prior human data reversed the LLM judge.

## 6. Distribution & licensing
- Questions, schema, judge config + rubric, harness and analysis code are in one public repo under
  **Apache-2.0** (single `LICENSE` at the repo root). `[NOT IMPLEMENTED]` The per-layer licensing the
  design calls for — code Apache-2.0/MIT, authored questions and answer keys CC-BY-4.0 — is **not**
  in place: there is no separate data license and no data-use agreement.
- `[NOT IMPLEMENTED]` No frozen-index manifest exists to distribute (see §4), so the "hash/URL
  manifest, not redistributed content" argument currently describes an artifact that has not been
  built. No copyrighted source content is redistributed either way: the repo ships authored prose
  and citations only.
- `[NOT IMPLEMENTED]` Croissant and Croissant-RAI records. No `croissant.json` is produced.
- Versioning today is the git history plus the challenge-schema version string
  (`crest-challenge/3.2.0`); each run directory pins the git commit, the config snapshot, and the
  judge model IDs actually used. A semver dataset release that pins model snapshots is not yet cut.

## 7. Maintenance
- Maintained by the (anonymized) authors; issues/PRs via the public repo. Defective items are
  handled through `questions/quarantine.yaml`, which records the defect, why scores would be
  uninterpretable, what resolves it, and — for released items — the resolution, so the record
  survives the fix. `[NOT IMPLEMENTED]` A rolling fresh-question set, per-cycle refresh, and item
  tombstones do not exist yet. `[NOT IMPLEMENTED]` There is also **no open-weight entrant and no
  frozen index**, so the "permanently reproducible anchor" the design asks for does not exist: the
  five current entrants are all closed, provider-hosted models (three shallow: Anthropic/OpenAI/
  Google; two deep: OpenAI/Google — the deep arm has no Anthropic entrant, an asymmetry to
  disclose). The judge panel has the same gap: three vendors, no genuinely open-weight judge.

## Human subjects (judge-validation study)
- `[NOT IMPLEMENTED] — planned, not run.` The intended human validation and pairwise-expert study
  would use paid domain experts scoring model outputs (not personal data). No study has been
  conducted, no raters recruited, and no human labels exist in this repo. IRB/ethics status and
  consent language: [to be finalized before any such study]; if run, no PII would be collected and
  raters would be compensated at/above local standard rates.

---

## Appendix: adversarial item-vetting log
Per-item dispositions (contamination / synthesis-required / axis-isolation / headroom / metadata):
see **`docs/item_vetting.md`** for the full per-item table and rationale, and read its
"superseded" header first — the later live-web audit (`docs/notes/audit_live_*.md`) overturned
several of its grades, most importantly on `known_answers` dating and on `C4_engineering_45`.
