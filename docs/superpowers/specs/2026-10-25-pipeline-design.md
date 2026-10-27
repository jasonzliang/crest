# CREST three-stage pipeline

Implement the user's authorized replacement in the clean `/Users/jason/Desktop/crest` checkout. Preserve historical datasets, reports, papers, and result directories. Archive the old runtime rather than leave two active harnesses. Also replace the explicitly named Rome rubric with the same binary pairwise rubric shipped by Crest. No paid experiment is part of implementation verification.

1. **Generate:** read the exact 50 `query` strings from bundled `crest/data/queries_n50.jsonl`, copied byte-for-byte from `../rome/caesar/config/llm_as_judge/queries/queries_n50.jsonl`; run Caesar, OpenAI research, and Gemini Deep Research independently with bounded provider concurrency. Persist each answer before judging. Use GPT-6.1 Sol for Caesar and OpenAI; Gemini's managed standard research agent exposes no model override and is documented as based on Gemini 3.1 Pro. Use that model for the Gemini judge and Sol for the OpenAI judge. Record all model/helper differences. Budgets target $5 per answer; native hosted workflows cannot guarantee a dollar ceiling. Preserve actual usage, estimated costs, and overruns rather than hiding them.
2. **Judge:** for every question, compare all three agent pairs with both judges in both answer orders. Three independent binary choices: New, Useful, Surprising. Each choice contains a comparative reason and `A` or `B`; no numerical ratings, tie option, or overall verdict. Preserve the Rome rubric's definitions. Answers are untrusted data, anonymized as A/B, never truncated silently. Identical answers are explicitly flagged, not adjudicated arbitrarily.
3. **Analyze:** rank agents by equal-weight mean preference rate over the three criteria on common complete-question coverage. Show per-criterion and per-judge rankings, opponent matrices, disagreement/order inconsistency, coverage/exclusions, costs and question-level bootstrap intervals. Preserve genuine aggregate ties and pairwise cycles. A ranking is a descriptive preference ranking, not an absolute creativity measurement.

## Usability and cache

One configuration (`crest.yaml`), one CLI (`python -m crest`, optionally installed as `crest`), commands `plan`, `generate`, `judge`, `analyze`, `run`. Re-running resumes and reuses completed work; changing the rubric/judge does not regenerate answers. Changing one model affects only that entrant/judge. Default full experiment: 150 generations, 600 judgment calls, 1,800 binary criterion choices.

Use atomic per-job JSON records and OS file locks for process-safe single-flight execution. Cache identities contain full question/prompt content, relevant settings, explicit adapter/protocol versions, ordered answer content, and rubric content. Remote background job IDs are checkpointed immediately and resumed by retrieval, not resubmission. Ambiguous submission failure is persisted and never automatically creates a second paid job. Keep raw responses and errors for diagnosis. Rendering/reporting is local and repeatable.

Caesar runs in an isolated subprocess per question, with unique output and Chroma collection names. Crest owns the compatibility shim and usage audit; Rome application code remains unchanged. The only intentional Rome edit is the requested rubric.

## Timestamped organization (user addition)

Stage 1 creates `results/YYYY-MM-DD/<UTC-timestamp>-<unique-id>/` with `run.json` and `01-generate-<UTC-timestamp>/`. Stage 2 creates `02-judge-<UTC-timestamp>/` inside the same run, snapshotting the rubric, settings and answers with its judgments. Stage 3 creates `03-analysis-<UTC-timestamp>/`, identifying the precise stage-2 directory analyzed. Every stage has a manifest and timestamps. New invocations never overwrite earlier stage directories. `--run PATH` selects an existing run; otherwise later stages use the latest generation run. Generation cache is shared across runs; judgment and analysis caches live within each run. Analysis reads its selected stage-2 snapshot, never mutable global-cache contents.

Latest user refinements: standalone scripts `stage1_generate.py`, `stage2_judge.py RESULT_DIR`, `stage3_analyze.py RESULT_DIR`; stage-1 cache under `results/.cache/generation`, stage-2/3 caches under `RESULT_DIR/.cache/judgments` and `RESULT_DIR/.cache/analysis`. All obsolete runtime and historical research assets live under `crest/_archive`, preserved intact. Adaptive concurrency starts at Caesar 1 + OpenAI research 3 + Gemini research 2 and can grow to 4 + 12 + 8 (24 research jobs). Judges start at 4 + 4 and grow to 16 + 16 (32 jobs). Each provider gains one slot per two successful uncached jobs and halves capacity after 429s. Shared cooldowns honor available retry/reset headers; safe retries allow four total attempts. These are per-process job limits, not provider-internal request-count guarantees.

## Runtime interface (binding)

`crest.cache.Job` exposes `key: str`, `directory: pathlib.Path`, `state: dict`, and synchronous `save(**changes) -> None`, which atomically merges checkpoint fields. Providers may use `remote_id`, `remote_status`, `submitted_at`, `submission_unknown`, `raw`, `worker_pid`, `result_path` in state. The pipeline owns final `status`, `result`, `error`.

Each provider module implements:

```python
async def generate(prompt: str, settings: dict, job: Job, *, client=None) -> dict: ...
# OpenAI and Gemini also implement:
async def judge(prompt: str, settings: dict, job: Job, *, client=None) -> dict: ...
```

The optional client is an `httpx.AsyncClient` for offline transport tests. Providers open/close their own client when absent. Generation result fields: `text` (nonempty full answer), `citations` (list of URL/title dictionaries), `model`, `usage` (normalized dictionary), `cost_usd` (number or null), `cost_estimated` (bool), `warnings` (list), `raw` (full response or worker record). Judge transport result uses the same envelope, with JSON text in `text`. No provider accepts `incomplete`/failed/empty output as a successful answer. Costs must be unknown rather than falsely zero if essential usage is absent.

`crest.judging`: `CRITERIA = ('new','useful','surprising')`, `SCHEMA` JSON schema; `build_prompt(question: str, answer_a: str, answer_b: str, rubric: str) -> str`; `validate_verdict(value: dict) -> dict`; `make_judgment_jobs(questions: list[dict], answers: list[dict], judges: dict, rubric: str) -> list[dict]`. Questions are `{id, text}`. Answers are `{question_id, agent, key, result}` where result follows generation envelope. Jobs are `{key, question_id, pair: [canonical_agent_1,canonical_agent_2], order: [agent_for_A,agent_for_B], judge, settings, prompt, answer_keys, answer_hashes}`. Pair/order comparisons use sorted agent IDs. Completed judgments add `verdict` and optional `cost_usd`/`usage`; each verdict has exactly the three criteria, each `{reason: nonempty str, winner: 'A'|'B'}`.

`crest.analysis`: `analyze(questions: list[dict], answers: list[dict], judgments: list[dict], *, agents: list[str], judges: list[str], bootstrap_samples: int=1000, seed: int=2026, failures: list[dict] | None=None, workers: int=1) -> dict`; `write_report(report: dict, output_dir: Path) -> None` emits `ranking.json`, `ranking.csv`, `report.md`. Analysis is offline, deterministic for its seed, and handles zero complete questions honestly.

## Default settings

- OpenAI research: `model=gpt-6.1-sol`, `reasoning_effort=high`, `max_output_tokens=40000`, `max_tool_calls=25`, `budget_usd=5.0`, `timeout_seconds=1800`, `poll_interval_seconds=5`, provider concurrency 3 initially, ceiling 12. Explicit standard service tier, background/store true, native web search. `$5` is a target, with best-effort cancellation when observable usage exceeds it.
- Gemini research: `agent=deep-research-preview-04-2026`, `billing_model=gemini-3.1-pro-preview`, `budget_usd=5.0`, `timeout_seconds=1800`, `poll_interval_seconds=5`, provider concurrency 2 initially, ceiling 8. Background/store true, visualization off, collaborative planning false. No fabricated server-side budget field.
- Caesar: primary/exploration/KB model `gpt-6.1-sol`, low exploration/KB reasoning, medium synthesis, 30 exploration iterations, depth 6, 3 additional seed queries, 5 extra searches, 2 drafts x 5 Q&A rounds, 8 retrieval chunks, no reranking/images/extra rewrites, DDGS, 5.0 budget target, 4.0 handler guard, 6000 main completion limit, 2000 exploration limit, 64000 input limit. Concurrency 1 initially, ceiling 4. Reserve $1.50 for synthesis within the handler guard. Preserve model configurability and complete provenance. Existing Rome API can call Chat Completions here because it does not pass API tools; web exploration occurs in Python.
- Judges: OpenAI `gpt-6.1-sol` medium, Gemini `gemini-3.1-pro-preview` high; max output 12000, no web tools, concurrency 4 initially and ceiling 16 per provider. Both orders always.

## Verification

Meaningful offline tests cover content invalidation, locking, interruption/resume, remote submit ambiguity, exact completion status, usage/cost fields, strict binary schema, swapped-label remapping, incomplete coverage, ties/cycles, dataset count, and an end-to-end fake-transport pipeline. No live API calls and no secrets-file reads. Model/provider limitations must be visible in plan output and README.

Analysis uses deterministic question bootstrap. Automatic workers choose up to six independent views only for large workloads; the default 50 questions and 1,000 draws are faster serial. Reports keep partial observed failure costs separate from final unknown bills.
