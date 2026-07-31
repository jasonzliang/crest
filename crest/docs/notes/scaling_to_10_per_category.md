> **SPENT — RECOMMENDED FOR DELETION.** This is a *plan* that was fully executed: the set is
> 50 items, 10 per category, and the 20 new items have since been vetted (`docs/item_vetting.md`)
> and live-web audited (`docs/notes/audit_live_*.md`). Nothing here describes the shipped artifact;
> it also refers to entrant keys (`*_dr`) and item fields (`predicted_direction`, `category_name`)
> that no longer exist, and its §6 acceptance checklist asserts a contamination scan and an embedded
> no-train marker, neither of which exists for any of the 50 items.
>
> It is retained ONLY because two of its lines (in §3 and §6) are under the approval-list gate in
> `analysis/ci_check.sh`, and one of them is a deliberate, currently-red failure: the approval file
> lists it under "Deliberately ABSENT (known false claims, so the gate stays red until they are
> fixed)". Deleting this file *resolves* that failure by removing the false claim — which changes
> the gate's failure set, so it must be done together with retiring the corresponding entry in the
> approval file. Whoever owns that file should do both in one commit.

# How to scale CREST from 6 → 10 items per category (EXECUTED — see header)

Goal: grow the scored set from **30 (6/category)** to **50 (10/category)** — i.e. author
**20 new challenges** — without lowering the quality bar or breaking the pre-registered structure.
This is a method + an allocation plan + a generation pipeline, grounded in `benchmark_best_practices.md`.

## 1. Why 10 (the statistical rationale)
- A grouping factor needs **≥8 (ideally ≥10) levels** to estimate its variance component reliably;
  below ~5 the item-variance is biased toward zero (Harrison; Oberpriller 2022; McNeish). At
  **6/cell CREST can rank agents but cannot credibly claim generalization** to the category's
  question universe — the exact gap the reviewer panel flagged.
- The headline endpoint is *conjunctive* ("creative only if New ∧ Useful ∧ Surprising"), whose
  power is far below any single axis; the crossover-interaction and TOST-equivalence tests are
  power-hungry. **10/cell is the smallest count that makes the confirmatory claim defensible.**
- Rule from the stats research: **prefer more items over more judges** when the claim is
  generalization. So spend the budget on items, not a bigger panel.

## 2. Target structure — where the 20 new items go
The predicted direction and isolated axis are **fixed by category**, so scaling is clean:

| Category | Isolated axis | Predicted dir | now | add | → |
|---|---|---|---|---|---|
| C1 Constrained | Useful | null | 6 | +4 | 10 |
| C2 Counterfactual | Surprising | favored | 6 | +4 | 10 |
| C3 Cross-Domain | New | favored | 6 | +4 | 10 |
| C4 Meta-Creativity | all three | parity | 6 | +4 | 10 |
| C5 Open-Ended | New | null | 6 | +4 | 10 |

That keeps the pre-registered split intact (**20 null, 20 favored, 10 parity**).

**Domain balance** (6 domains, currently 5 each → 30). 50 doesn't divide evenly by 6; target
**4 domains × 8 + 2 domains × 9 = 50** (so +3 to four domains, +4 to two). Assign each new item a
(category, domain) so no category repeats a domain more than twice.

**Reserve some of the 20 as deliberate control/dissociation items** (best-practices §construct):
- ≥1 *novel-but-unsurprising* (far from known list, yet exactly what experts predicted),
- ≥1 *surprising-but-not-novel* (a known-but-forgotten answer that violates expert expectation),
- ≥1 *novel+surprising-but-useless* (violates the category hard rules).
These aren't filler — they are the **discriminant-validity evidence** that New/Useful/Surprising
actually dissociate, which is a top reviewer ask.

**Split for contamination resistance** (best-practices §contamination):
- Make **≥8 of the 20 post-training-cutoff** (fresh) items so the confirmatory run tests
  knowledge the models could not have memorized.
- Route a subset into a **private held-out tier** (answer keys + expert baselines never published);
  headline scores are reported on the private tier, a public sample stays for calibration.

## 3. The per-item quality bar (what "as good as the existing 30" means)
Every new item must ship, at the level of the current items:
1. `query` — a self-contained, multi-hop **synthesis** task (answer on **no single page**),
   with the isolated axis genuinely pinned.
2. `known_answers[]` — a **dated** list (as-of the knowledge cutoff) of what is already known,
   each with a source, so *New* is judged against knowledge, not the open web.
3. `hard_rules[]` — **machine-checkable** constraints that gate *Useful* and block trivial/known
   answers (for C3, the Gentner structure-mapping checklist; for C2, Byrne's fault-line taxonomy).
4. `expert_baseline` — the **convergent expected expert answer** (ideally elicited as a small
   *distribution* of expert predictions), so *Surprising* = divergence from what was predicted.
5. Metadata: `category`, `domain`, `axis_isolated`, `time_sensitivity` (pre/post-cutoff),
   `predicted_direction`, `rationale`, a **canary**, and a Croissant RecordSet entry.

## 4. Authoring workflow (per item)
1. **Blueprint** — fix (category, domain, isolated axis, pre/post-cutoff, control-type if any).
2. **Draft the query** from the category's mechanism (exploratory / counterfactual / structure-
   mapping / meta / transformational) — reuse an existing same-category exemplar as the template.
3. **Build the dated known-answers list** — the web-research-heavy step: sweep the literature for
   what is already known, date it to the cutoff, cite each entry. *(This is what makes "New" fair.)*
4. **Write hard rules + expert baseline** — checkable constraints; elicit the expected answer.
5. **Adversarial vet** (the committed red-team) — score the item on: contamination risk,
   synthesis-required (no single-source answer), axis-isolation, headroom (not saturable), single
   unintended "intended answer", metadata completeness. Log the disposition in `datasheet.md`.
6. **Pilot for headroom** — run 2–3 agents (the harness already does this); **cut any item a
   no-web / weak baseline solves** (tool-ablation check) and any item that saturates. Confirm
   inter-judge reliability (Krippendorff α / ICC) on the new items.

## 5. Semi-automated generation pipeline (reuse what built the first 30)
The original 30 came from a multi-agent generation workflow; scale the same shape for the +20:
- **Author agents** (1 per (category, domain) slot): given the category mechanism + an exemplar,
  draft `query` + `hard_rules` + a candidate `expert_baseline`.
- **Known-answers agents** — here is the key unlock: **use the deep-research agents themselves**
  (`claude_dr` / `openai_dr`, which have live web access via the API) to compile and date the
  known-answers list per item. This sidesteps the exhausted top-level web-search budget.
- **Red-team/verifier agents** — run the §4.5 vetting gates; reject or return-for-revision.
- **Human-in-the-loop expert pass** — verify known-answers dating and expert baselines (the two
  artifacts that most determine validity); this is the irreducible manual step.
Only items passing all gates are appended to `crest_challenges.jsonl` (schema-validated).

## 6. Acceptance criteria (gate before the item is added)
- Passes schema validation and all metadata present.
- Tool-ablation: a no-web baseline does **not** score well (else memorizable → cut).
- Axis-isolation confirmed by the post-hoc inter-axis correlation check (the item's non-isolated
  axes don't drive its score).
- Length-vs-score correlation near zero (apply the K-candidate + length-budget controls).
- Contamination scan clean (canary embedded; not derivable from a single indexed page).

## 7. Outcome (recorded 2026-07-31)
The 20 items were authored (ids `_3x`/`_4x`) and appended; C6 was not added (`category_coverage.md`).
What the plan asked for and did **not** get: the tool-ablation check (§6) was never run; the
post-cutoff target was missed badly (`datasheet.md` §2, "Splits"); no private tier and no embedded
no-train marker exist; and the dating acceptance gate was not enforced — the `_3x`/`_4x` blocks are the
worst-dated in the file (`datasheet.md` §2, "Prior-art dating"). The §3 quality bar was met on
structure and missed on provenance.
