# Do we need more categories? — coverage analysis

**Short answer: No. The 5 categories are theory-complete for creative *process*, and on a hard
double-check (below) even the strongest candidate — Scientific Hypothesis Generation — does not
clearly earn a 6th *category*. Stay at 5 and scale to 50.**

## Double-check (revised): is C6 Scientific Hypothesis Generation really a distinct category?
Verdict: **defensible as a task, weak as a distinct category for THIS taxonomy — do not add it.**
1. **Process redundancy.** CREST's categories are creative *processes*; abductive hypothesis
   generation overlaps C3 (recombine distant evidence), C1 (constrained invention), and C4
   (product-type "invent an X"). It introduces no new *mechanism*, and the finding is about
   mechanism dissociation.
2. **Likely non-dissociation from C3.** Its predicted mechanism and direction pattern with C3
   (favored), so it adds breadth but little discriminating power — and risks failing CREST's own
   discriminant-validity bar (the thing that makes the taxonomy credible).
3. **Harder to score validly.** "Useful hypothesis" = testable + plausible + explanatory (contested,
   expert-dependent), and bounding "novel hypothesis" against a dated known-answers list is very
   hard (huge hypothesis space).
Steelman for adding it: C4 ("invent a method") is already a product-type category, so C6 ("invent a
hypothesis") is structurally parallel, and it is the single most on-mission task for a *research*
agent. But that is a *use-case* argument, not a *process* argument — and mixing a use-case axis
into a process taxonomy is exactly the inconsistency to avoid. **Represent hypothesis-generation as
domain instances inside C1/C5 instead.**

## What the 5 categories are, and why they are principled
CREST's categories are not arbitrary; each instantiates a distinct creative *process* from the
literature, and together they were chosen so an agent's creativity can *dissociate* across them
(the dissociation is the paper's finding).

| CREST | Creative process | Theory anchor | Isolated axis |
|---|---|---|---|
| C1 Constrained | exploratory (search a fixed space) | Boden 2004; Simonton 2003 | Useful |
| C2 Counterfactual | reasoning over a causal model | Byrne 2005 (rational imagination) | Surprising |
| C3 Cross-Domain | combinational (structure-mapping) | Gentner 1983; Falkenhainer 1989 | New |
| C4 Meta-Creativity | reflective / space-altering | Boden (transformational, meta) | all three |
| C5 Open-Ended | transformational / blind variation | Boden 2004; Campbell 1960 | New |

## Coverage check against the major creativity taxonomies
- **Boden's trichotomy** (combinational / exploratory / transformational): fully covered
  (C3 / C1 / C5). ✓
- **Rhodes' 4 P's** (Person, Process, Product, Press): CREST is a *Process×Product* benchmark;
  Person and Press don't apply to an agent. ✓ (correctly out of scope)
- **Guilford / Torrance divergent thinking** (fluency, flexibility, originality, elaboration):
  CREST measures **originality** (New) well, but does **not** measure **fluency/flexibility** —
  the ability to generate *many, diverse* valid ideas. This is a genuine gap, but filling it
  needs a *set-level* scoring protocol (score a set of ideas on quantity × diversity × quality,
  à la NoveltyBench/Torrance), not the single-best per-item scoring CREST uses. → **v2 extension,
  not a drop-in category.**
- **Getzels & Csikszentmihalyi problem-finding**: CREST tests creative problem-*solving*, not
  problem-*finding* (posing novel questions). Distinct and research-relevant. → candidate.
- **Scientific creativity / hypothesis generation** (Klahr & Dunbar; Simonton): generating a
  novel, *testable*, non-obvious hypothesis from evidence. C4 is method-invention and C2 is
  counterfactual reasoning — neither is hypothesis generation. → **strongest candidate**, because
  it is precisely what a *research* agent is for.

## Recommendation
1. **Keep the 5 as the core that carries the finding.** They are complete over creative *process*
   and each is theory-grounded; adding categories dilutes per-cell power (already thin at ~6/cell)
   and invites scope creep. For the task-dependence claim, 5 is right.
2. **Do not add C6 as a category** (see the double-check above): it is redundant in *process*,
   likely non-dissociating from C3, and hard to score validly. If hypothesis-generation coverage is
   wanted, add it as *domain instances* within C1 (constrained) and C5 (open-ended), not a 6th category.
3. **Defer C7 Divergent Fluency/Flexibility to v2.** Valuable, but it requires a different
   (set-level) scoring model; bolting it onto the single-best rubric would weaken construct validity.
4. **Do not confuse domains with categories.** CREST already spans 6 *domains* (bio/med, materials,
   econ, law, engineering, arts) — that is breadth. Categories are *process types*. Adding domains
   ≠ adding categories.

## Interaction with the count question — SETTLED
The scale-up recommended below happened: the shipped set is 5 categories × 10 items = **50**, and
C6 was not added. This section is retained as the rationale for the current taxonomy, not as an
open decision. (The count audit it originally cross-referenced, `question_audit.md`, was a review
of the earlier 30-item set and has been deleted as spent; `docs/item_vetting.md` and
`docs/notes/audit_live_*.md` are the per-item record for the shipped 50.)

## One-line verdict
Five categories are sufficient and defensible; the taxonomy stayed at 5 and the budget went to
**10 items/category (50 total)** rather than a 6th category.

*Refs: Boden 2004; Gentner 1983; Falkenhainer 1989; Byrne 2005; Simonton 2003; Campbell 1960;
Guilford 1967 / Torrance 1974 (divergent thinking); Rhodes 1961 (4 P's); Getzels & Csikszentmihalyi
1976 (problem-finding); Klahr & Dunbar 1988 (scientific discovery). Benchmark comparanda:
NoveltyBench (set diversity), LiveIdeaBench (divergent), CreativityPrism (cross-domain), Si et al.
2024 (research ideation).*
