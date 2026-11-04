# CREST: Creativity of Research Agents

CREST benchmarks the creativity of deep research agents and AI scientist papers using **pairwise LLM judging**. Judges choose one overall winner, guided by **New, Useful, and Surprising**. Saved answers, judgments, configurations, API costs, and timing make each comparison inspectable.

The research benchmark compares [Caesar](https://github.com/jasonzliang/caesar-agent), OpenAI Responses with hosted web search, Google Deep Research, and Anthropic (Sonnet + web search) on **50 questions across five categories**. A complete run contains **200 answers and 1,800 judgments**.

| Pipeline | What it compares | Documentation |
| --- | --- | --- |
| `crest` | Answers generated for the same research questions | [Research guide](docs/crest-guide.html) · [Completed comparison](docs/deep-research-creativity.html) |
| `crest_ais` | Released papers from AI scientist systems | [Paper comparison method](docs/ai-scientist-method.html) · [Completed comparison](docs/ai-scientist-creativity.html) |

## Quick start

Use Python 3.11–3.13. Clone Caesar alongside CREST as `rome`, matching the default configuration:

```bash
git clone https://github.com/jasonzliang/caesar-agent.git rome
git clone https://github.com/jasonzliang/crest.git
cd crest
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ../rome -e '.[test]'

export OPENAI_API_KEY=your_key
export GOOGLE_API_KEY=your_key
export ANTHROPIC_API_KEY=your_key
```

`GEMINI_API_KEY` also works. Credentials come from the environment; CREST does not automatically load dotenv files. Review the single master [configuration](crest/configs/crest.yaml) for models, budgets, and provider concurrency before running; it holds every model, prompt, budget, depth and concurrency setting.

Start with one question:

```bash
python -m crest plan --limit 1
python -m crest generate --limit 1

# Replace this path with the run_dir printed by generation.
CREST_RUN=crest/results/YYYY-MM-DD/HH-MM-SS-TZ-ID
python -m crest judge --run "$CREST_RUN"
python -m crest analyze --run "$CREST_RUN"
```

Planning and analysis are local. Generation and judging make paid API calls. Every research system has a **$4 per-answer warning threshold** (`budget_usd: 4.0`) under its current soft budget. Research settings aim at about **$3** inside a **$2–4** range (Caesar keeps a fixed depth of 300 iterations and 3 × 20 Q&A rounds; OpenAI and Anthropic use research rounds that aim at a $3 floor; Google has no depth control and its 600-word pilot fell below the range). Each agent's `budget_cap` says how the budget binds: `soft` (every agent now) flags and warns about an overrun in the answer and the report but stops nothing; `hard` enforces it (Caesar's SDK audit refuses further calls, OpenAI cancels the hosted job, Anthropic starts no further server turn); `auto` enforces it and overrides the depth settings with values derived from it (`python -m crest.budget 4.0` shows them; every override is printed when the config loads and listed by `crest plan`). Google can only be `soft`. OpenAI and Anthropic also have a `budget_floor_usd` of 3.0: when a finished answer cost less, the adapter sends `research_continuation_prompt` as the next turn and the agent researches further and rewrites the answer, up to `max_research_rounds` rounds, aiming at about $3 inside the $2–4 range; a round starts only if it would not overshoot that aim by more than the current shortfall, and under a hard or auto cap only if it also fits under `budget_usd`. Judging costs extra. The published 2026-10-26 run measured $1.60 (Caesar), $0.10 (OpenAI), and $3.71 (Google) per answer; the settings have since been raised, so a one-question pilot is the way to measure spending under the current configuration.

| System | `budget_cap` | Depth | When an answer passes `budget_usd` |
|---|---|---|---|
| Caesar | soft | 300 iterations, 3 drafts × 20 Q&A rounds | Flagged. `hard`: the SDK audit refuses further calls. `auto`: depth overridden from the budget. |
| OpenAI (Sol + web search) | soft | Research rounds toward the $3 floor, at most 6 | Flagged. `hard`/`auto`: the hosted job is cancelled. |
| Google Deep Research | soft (only option) | None; the managed agent decides | Flagged. |
| Anthropic (Sonnet + web search) | soft | Research rounds toward the $3 floor, at most 14 | Flagged. `hard`/`auto`: no further server turn starts. |

Every system except Caesar receives a shared creativity prompt (`research_prompt` in the configuration, switched per agent by `use_research_prompt`). It asks for a novel, thought-provoking answer focused on emergent patterns, novel connections, surprising directions, and tensions. Caesar receives the bare question because Rome does its own prompting. All systems share a 600-word limit (`answer_word_limit`): hosted systems get it through `{max_words}` in the prompt, and Caesar gets it as Rome's `synthesis_max_length` word target for each draft and the merge. The pipeline records each answer's word count and flags answers over the limit as a warning, not a failure.

Omit `--limit 1` for all 50 questions. `python -m crest run` runs all three stages. Use `--config PATH` to select another configuration file, `--agents` (new generation runs only) or `--judges` to run any subset of the configured names, or `--run PATH` to resume a run and rerun judging or analysis.

## Pipeline and saved results

| Stage | Command | Output |
| --- | --- | --- |
| Generate | `python -m crest generate` | Answers, source records, configurations, cost, and elapsed time |
| Judge | `python -m crest judge --run PATH` | Overall A/B verdicts with comparative explanations |
| Analyze | `python -m crest analyze --run PATH` | Rankings, head-to-head results, uncertainty, and judge diagnostics |

Runs live in `crest/results/YYYY-MM-DD/HH-MM-SS-TZ-ID/`, with dated folders for each stage. Generation caches are shared across runs; judgment and analysis caches live inside each run. Changing the rubric or judges reuses the saved answers. Configuration identities distinguish answers generated with different settings.

Provider concurrency adapts to successful requests and rate limits, within configured bounds. Failed attempts have bounded retries. Cost and timing records retain the original measurements when cached work is reused.

## How the ranking works

For each question, three judges see every system pair in both answer orders: **6 pairs × 3 judges × 2 orders = 36 judgments**. Across 50 questions, that is 1,800 judgments and 900 comparisons involving each system.

Systems rank by their share of overall wins on common complete questions. New, Useful, and Surprising guide a single decision; they are not separate rankings. Question-level bootstrap intervals describe sensitivity to the question mix with saved answers and judges held fixed. These results measure judge preferences, not verified factual accuracy or absolute creativity.

See the [judging method](docs/judging-method.html), [current NUS v2 rubric](crest/prompts/nus_pairwise_v2.txt), and [50-question dataset](crest/data/queries_n50_v2.jsonl). The [original NUS v1 rubric](crest/prompts/archive/nus_pairwise_v1.txt) is archived unchanged for reproducibility; its old path remains a compatibility link. V2 credits substantive combinations, distinguishes unfamiliarity from demonstrated novelty, and evaluates usefulness within the task's premises. These are design improvements, not measured gains in agreement with human judges. The current set was generated by the three judge models in the five categories of Caesar's original [50 questions](crest/data/queries_n50.jsonl), which the published comparison used.

## Browse the reports

The reports are self-contained HTML files. To read them locally:

```bash
python -m http.server 8000
```

Open [the documentation index](http://localhost:8000/docs/index.html) for the research comparison, AI scientist comparison, guides, and historical project material.

## Development

```bash
python -m pytest
```

The master test command runs both packages' tests in parallel across all logical CPU cores. Use `-n 4` to limit workers or `-n 0` for serial debugging.

Licensed under [Apache 2.0](LICENSE).

## Citation

```bibtex
@misc{liang2026crest,
  author       = {Liang, Jason},
  title        = {{CREST}: Creativity of Research Agents},
  year         = {2026},
  howpublished = {GitHub repository},
  url          = {https://github.com/jasonzliang/crest}
}
```
