# CREST — Creativity of deep-Research agenTs

CREST generates research answers, compares them with binary pairwise judges, and
produces a descriptive creativity ranking. Each stage runs separately and caches
its work, so changing the judging rubric does not regenerate paid answers.

The default experiment uses the **exact 50 questions** bundled in
[crest/data/queries_n50.jsonl](crest/data/queries_n50.jsonl). This is a byte-for-byte
copy of `../rome/caesar/config/llm_as_judge/queries/queries_n50.jsonl`.
Question loading uses the bundled copy; Caesar still requires the Rome installation.

| Stage | Work |
|---|---|
| 1. Generate | Caesar, OpenAI research, and Gemini Deep Research answer every question independently. |
| 2. Judge | OpenAI and Gemini compare every pair in both answer orders, choosing A or B separately for New, Useful, and Surprising. |
| 3. Analyze | Rank agents on complete question blocks; report coverage, uncertainty, judge differences, and costs. |

A full experiment contains **150 generations, 600 judge calls, and 1,800 binary
choices**. There are no numerical creativity ratings or per-comparison tie options.

## Install

Use Python 3.11 or newer from the repository root:

```bash
python -m pip install -e '.[test]'
python -m pip install -e ../rome
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
```

`GEMINI_API_KEY` also works for Google. Credentials come from the environment;
CREST does not automatically load `.env` files. Caesar needs Rome's dependencies.
Alternatively, set `research.caesar.python_executable` in `crest.yaml` to the
absolute Python path in an existing Rome environment. CREST also installs `psutil`
for safe identification and cleanup of Caesar worker processes.

## Plan, then run a small pilot

`crest.yaml` contains paths, model settings, budgets, and provider concurrency.
Paths resolve relative to that file. Planning makes no API calls or run folders:

```bash
python -m crest plan
python -m crest plan --limit 1
python stage1_generate.py --limit 1
```

The one-question pilot generates three answers. Set `RUN` to the `run_dir` printed
by stage 1, then run the next two scripts independently:

```bash
RUN=results/YYYY-MM-DD/UTC-TIMESTAMP-UNIQUE-ID
python stage2_judge.py "$RUN"
python stage3_analyze.py "$RUN"
```

The **$5 per answer budget is a target**, not a guaranteed server-side spending
cap. A full uncached generation targets about $750; judging costs extra. Hosted
research can exceed its target. Usage, cost estimates, and overruns are recorded;
cost reports include failed paid attempts, and missing cost data stays unknown.
Caesar reserves $1.50 for synthesis within its $4 handler guard and $5 overall target.

## Run all 50 questions

```bash
python -m crest plan
python stage1_generate.py
# Set RUN to this generation's printed run_dir.
python stage2_judge.py "$RUN"
python stage3_analyze.py "$RUN"
```

The CLI also supports the full sequence with `python -m crest run`. Its individual
commands are `plan`, `generate`, `judge`, and `analyze`; installed environments can
use `crest` in place of `python -m crest`. Add `--config PATH` for another config.

To inspect or rerun an existing experiment:

```bash
python -m crest plan --run "$RUN"
python stage1_generate.py --run "$RUN"
python stage2_judge.py "$RUN"
python stage3_analyze.py "$RUN"
```

Later stages use the latest generation run when no result directory is supplied.
Pass `RUN` explicitly when working with several experiments. `--limit` applies to
new generation runs; an existing run keeps its question and generation snapshots.

## Parallelism and retries

Provider jobs run independently with adaptive concurrency. `initial_concurrency`
sets the starting capacity; `concurrency` sets its ceiling:

| Stage | Provider | Start | Maximum |
|---|---|---:|---:|
| Generate | Caesar | 1 | 4 |
| Generate | OpenAI | 3 | 12 |
| Generate | Gemini | 2 | 8 |
| Generate | **Total** | **6** | **24** |
| Judge | OpenAI | 4 | 16 |
| Judge | Gemini | 4 | 16 |
| Judge | **Total** | **8** | **32** |

Each provider gains one slot after two successful uncached jobs and halves its
capacity on HTTP 429. A shared cooldown honors `Retry-After` and available rate
reset headers. Limits apply per pipeline process. Hosted agents' internal usage
and other account traffic vary, so these controls cannot guarantee zero 429s.

The default is four total attempts with backoff: creation is retried only after
an explicit 429 rejection; idempotent polling and cancellation also retry transient
server or transport errors. An ambiguous creation POST is never blindly resubmitted.
Concurrency and retry setting changes reuse completed paid cache entries.

Stage 3 makes no API calls. `analysis.workers: 0` automatically uses up to six
independent bootstrap views for large analyses; the default 50 questions and
1,000 draws stay serial to avoid process startup overhead and usually take under a second.

For a laptop, `--config crest.mbp.yaml` starts with four research jobs and permits
at most two Caesar workers, six hosted OpenAI jobs, and four hosted Gemini jobs.
Judging starts at two jobs per provider and permits eight each; analysis stays
serial. Use the same configuration argument on each stage or run
`python -m crest run --config crest.mbp.yaml` for the full sequence.

## Results and cache

Each stage invocation creates a new UTC-timestamped directory inside the same run:

```text
results/
  .cache/generation/                  # generation cache shared across runs
  YYYY-MM-DD/UTC-TIMESTAMP-UNIQUE-ID/
    run.json                         # questions, generation jobs, stage registry
    01-generate-UTC-TIMESTAMP/        # answers.jsonl, readable answers/, manifest
    02-judge-UTC-TIMESTAMP/           # judgments and frozen answers/rubric/settings
    03-analysis-UTC-TIMESTAMP/        # ranking.json, ranking.csv, report.md
    .cache/judgments/                # paid judgments reused within this run
    .cache/analysis/                 # local analysis reused within this run
```

Rerunning stages 2 or 3 creates a new stage folder while reusing matching cache
entries. Analysis identifies the stage-2 snapshot it used. Historical stage
folders remain available for inspection. Stage 1's `answers.jsonl` is canonical;
the Markdown files in `answers/` are copies for reading.

Cache identities include the question/prompt, relevant provider settings and
adapter version; judgments also include ordered answers and rubric contents.
Changing one entrant affects its answers and their comparisons. Changing a judge
or rubric affects judging; changing bootstrap settings affects analysis. Generation
settings are frozen for an existing run: start a new stage-1 run to apply changed
generation settings, reusing unaffected answers from the shared cache.

For an intentional fresh call, increment `revision` under the relevant entrant or
judge in `crest.yaml`. Generation revisions take effect in a new generation run.
Completed work is saved atomically, and remote job IDs are checkpointed for
retrieval after interruption. An ambiguous submission requires manual reconciliation
with the provider before retrying; a revision change is not a recovery procedure.

## Models and interpretation

Caesar's primary, exploration, and knowledge-base models and OpenAI's native
research workflow use `gpt-6.1-sol`. Gemini uses the standard
`deep-research-preview-04-2026` agent, which Google [introduced with Gemini 3.1 Pro](https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/)
on April 21, 2026. Google controls its backbone and exposes no underlying-model override. Judges
use `gpt-6.1-sol` and `gemini-3.1-pro-preview`, without web tools.

For dated repository comparisons, verified pricing, and the selected Caesar preset,
see [the research comparison](docs/research-comparison.md).

The adapted [NUS rubric](crest/prompts/nus_pairwise.txt) preserves New, Useful, and
Surprising as separate criteria. All three agent pairs receive both judges and
both answer orders. Identical answers are flagged rather than given arbitrary wins.

Ranking uses equal-weight binary win rates across criteria, opponents, judges,
and answer orders, retaining only questions with every required answer and valid
judgment. Reports include per-axis/per-judge results, opponent matrices, disagreement,
order inconsistency, exclusions, and question-level bootstrap confidence intervals.
Aggregate ties and preference cycles are retained. These are comparative preferences,
not absolute creativity measurements; small samples give limited uncertainty estimates.

## Development and history

```bash
python -m pytest
```

The active runtime is the small set of flat modules under `crest/`. Historical
material lives under [crest/_archive/](crest/_archive/README.md): the previous
runtime in `runtime/`, and question sets, documents, papers, and results in
`research/`. Old run caches are not automatically imported into the new protocol.

Apache License 2.0 — see [LICENSE](LICENSE).
