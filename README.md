# CREST: Creativity of Research Agents

CREST benchmarks the creativity of deep research agents and AI scientist papers using **pairwise LLM judging**. Judges choose one overall winner, guided by **New, Useful, and Surprising**. Saved answers, judgments, configurations, API costs, and timing make each comparison inspectable.

The research benchmark compares [Caesar](https://github.com/jasonzliang/caesar-agent), OpenAI Responses with hosted web search, and Google Deep Research on **50 questions across five categories**. A complete run contains **150 answers and 600 judgments**.

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
```

`GEMINI_API_KEY` also works. Credentials come from the environment; CREST does not automatically load dotenv files. Review the [configuration](crest/configs/crest.yaml) for models, budgets, and provider concurrency before running.

Start with one question:

```bash
python -m crest plan --limit 1
python -m crest generate --limit 1

# Replace this path with the run_dir printed by generation.
CREST_RUN=crest/results/YYYY-MM-DD/HH-MM-SS-TZ-ID
python -m crest judge --run "$CREST_RUN"
python -m crest analyze --run "$CREST_RUN"
```

Planning and analysis are local. Generation and judging make paid API calls. The default research budget is a **$5 target per answer**, not a guaranteed spending cap; judging costs extra.

Omit `--limit 1` for all 50 questions. `python -m crest run` runs all three stages. Use `--config PATH` to select another profile, or `--run PATH` to resume a run and rerun judging or analysis.

## Pipeline and saved results

| Stage | Command | Output |
| --- | --- | --- |
| Generate | `python -m crest generate` | Answers, source records, configurations, cost, and elapsed time |
| Judge | `python -m crest judge --run PATH` | Overall A/B verdicts with comparative explanations |
| Analyze | `python -m crest analyze --run PATH` | Rankings, head-to-head results, uncertainty, and judge diagnostics |

Runs live in `crest/results/YYYY-MM-DD/HH-MM-SS-TZ-ID/`, with dated folders for each stage. Generation caches are shared across runs; judgment and analysis caches live inside each run. Changing the rubric or judges reuses the saved answers. Configuration identities distinguish answers generated with different settings.

Provider concurrency adapts to successful requests and rate limits, within configured bounds. Failed attempts have bounded retries. Cost and timing records retain the original measurements when cached work is reused.

## How the ranking works

For each question, two judges see every system pair in both answer orders: **3 pairs × 2 judges × 2 orders = 12 judgments**. Across 50 questions, that is 600 judgments and 400 comparisons involving each system.

Systems rank by their share of overall wins on common complete questions. New, Useful, and Surprising guide a single decision; they are not separate rankings. Question-level bootstrap intervals describe sensitivity to the question mix with saved answers and judges held fixed. These results measure judge preferences, not verified factual accuracy or absolute creativity.

See the [judging method](docs/judging-method.html), [rubric](crest/prompts/nus_pairwise_v2.txt), and [50-question dataset](crest/data/queries_n50.jsonl).

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
