# CREST: Creativity of Research Agents

CREST benchmarks the creativity of deep research agents and AI scientist papers using **pairwise LLM judging**. Judges choose one overall winner, guided by **New, Useful, and Surprising**. Saved answers, judgments, configurations, API costs, and timing make each comparison inspectable.

The current research configuration compares five systems on **50 questions across five categories**: [Caesar](https://github.com/jasonzliang/caesar-agent), OpenAI Responses with hosted web search, Google Deep Research, Anthropic Opus 5.5 with client-side search, and [GPT Researcher](https://github.com/assafelovic/gpt-researcher). The completed study has **250 answers and 3,000 judgments** per rubric. Its main ranking uses the NUS v1 rubric; the same answers judged under NUS v2 and NUS v3 are in collapsed sections at the bottom of the page. Across the three rubrics, Claude Opus 5.5 refused five judgments on question 48, and Claude Sonnet 5.5 made them in its place. See [Deep Research Comparison v3](docs/deep-research/deep-research-comparison-v3.html) for results and costs. All five configured research budgets are soft.

The previous study used three research systems and two judges, with **150 answers and 600 judgments**. Its saved models, settings, scores, and costs are historical and do not measure the current configuration.

| Pipeline | What it compares | Documentation |
| --- | --- | --- |
| `crest` | Answers generated for the same research questions | [Research Pipeline](docs/deep-research/research-pipeline.html) · [Deep Research Comparison v3](docs/deep-research/deep-research-comparison-v3.html) · [Deep Research Comparison v2](docs/deep-research/deep-research-comparison-v2.html) · [Deep Research Comparison v1](docs/deep-research/deep-research-comparison-v1.html) |
| `crest_ais` | Released papers from AI scientist systems | [AI Scientist Comparison Method](docs/ai-scientists/ai-scientist-comparison-method.html) · [AI Scientist Comparison v1](docs/ai-scientists/ai-scientist-comparison-v1.html) |

## Quick start

Use Python 3.11–3.13 for CREST and Caesar. Clone Caesar alongside CREST as `rome`, matching the default configuration:

```bash
git clone https://github.com/jasonzliang/caesar-agent.git rome
git clone https://github.com/jasonzliang/crest.git
cd crest
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ../rome -e '.[test]'
```

### Credentials and gateway

Load credentials into the shell from a private file outside the checkout. Replace the example path below with your own; do not commit the file, print its contents, or enable shell tracing while loading or using keys.

```bash
set +x
set -a
source /absolute/path/to/private/crest-keys.sh
set +a
```

The file should supply `OPENAI_API_KEY` for OpenAI, Caesar, and GPT Researcher; `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) for Google; and `LITELLM_API_KEY` for Anthropic. The active Anthropic research and judge settings use `api_base: https://litellm.evolution.ml` and `api_key_env: LITELLM_API_KEY`, not a direct `ANTHROPIC_API_KEY`. See the public [LiteLLM gateway setup guide](https://llm-keys.evolution.ml/guide#claude-code). CREST reads environment variables and does not automatically load dotenv files.

Review the single master [configuration](crest/configs/crest.yaml) before running. It holds the models, prompts, budgets, depth, concurrency, and transport settings. The active inputs are [`crest/data/queries_n50_v2.jsonl`](crest/data/queries_n50_v2.jsonl) and [`crest/prompts/nus_pairwise_v3.txt`](crest/prompts/nus_pairwise_v3.txt). Do not redirect the OpenAI-backed providers through the Anthropic gateway: their configured route and pricing are direct OpenAI.

### Active models

| Research provider | Model / effort | Research tools |
| --- | --- | --- |
| `caesar` | Sol (`gpt-6.1-sol`), **medium** main research, **high** synthesis; Luna exploration and KB helpers, low | Caesar/Rome exploration and synthesis |
| `openai` | Sol (`gpt-6.1-sol`), **high** | OpenAI hosted web search |
| `gemini` | Standard managed `deep-research-preview-04-2026` | Google-managed research; no exposed effort/depth control |
| `anthropic` | Opus 5.5 (`claude-opus-5-5`), **high**, through LiteLLM | Free source bootstrap, then client-side DDGS public web search and HTTP fetch |
| `gpt_researcher` | Sol (`gpt-6.1-sol`), **high** for every role: fast, smart, and strategic | DDGS public web search and HTTP fetch in an isolated worker |

All three judges use **high** reasoning/thinking/effort: **Opus 5.5** through the gateway, **Sol** through direct OpenAI, and **Gemini 4 Argon**. Judges do not use tools. If Opus refuses a judgment on every one of its `retry_attempts`, `judges.anthropic.refusal_substitute` sends the same prompt to **Sonnet 5.5** (`claude-sonnet-5-5`) at its own rates. The stand-in is a transport setting, so judgment cache keys do not change, and each attempt records its `substitute_model`. See [Judge Models](docs/judging/judge-models.html) for request settings and prices.

The gateway's Bedrock route rejects native Anthropic `web_search`, so the active Anthropic research mode is explicitly `tool_mode: client`, with **no fallback to native hosted tools**. Before the first paid model request, a free DDGS bootstrap search must return usable source text and actual source URLs. The adapter checkpoints that evidence as untrusted context, not a fabricated model tool call; if retrieval supplies no usable evidence, it stops before submitting a paid request. Client searches through DDGS’s free public-engine auto mode and HTTP fetches have **no search/fetch API fee**; the model tokens used to read and reason over those results are still billed. OpenAI's hosted search is a separate, paid tool.

### GPT Researcher setup

GPT Researcher is the fifth provider, named `gpt_researcher`. Keep its dependencies in **`../gpt-researcher/.venv`**, separate from CREST and Caesar. From the CREST checkout, use Python 3.12 or later for this worker (the current GPT Researcher checkout requires it):

```bash
# Skip cloning if the sibling checkout already exists.
git clone https://github.com/assafelovic/gpt-researcher.git ../gpt-researcher
git -C ../gpt-researcher checkout --detach ddd4db36208d9c8e49f3b2436efda97baecb5433
python3.12 -m venv ../gpt-researcher/.venv
../gpt-researcher/.venv/bin/python -m pip install -e ../gpt-researcher 'ddgs>=9.14.4,<10'
../gpt-researcher/.venv/bin/python -m pip freeze > ../gpt-researcher/.venv/requirements.lock
```

The canonical CREST worker, [crest/providers/gpt_researcher_worker.py](crest/providers/gpt_researcher_worker.py), uses that checkout and isolated interpreter; no GPT Researcher web server is needed. Fast, smart, and strategic roles are configured for Sol/high, with **no final-answer word cap** or hidden `TOTAL_WORDS` target. Keep CREST’s model, tool, and accounting settings rather than upstream defaults. The corrected input-fit profile passed full offline and independent review.

**GPT Researcher:** Sol/high for all roles; 32,000 research and writer completion tokens; $3.40 planning target, $0.50 synthesis allowance and soft $4 warning. Answer concurrency starts at **4** and can grow to **8** (Caesar: **25** growing to **50**); inner research concurrency stays **2** (breadth 4, depth 3). Call/total timeouts are 600/5,400 seconds. The 64,000 conservative input bound counts UTF-8 JSON bytes plus framing, not tokenizer usage; fitting applies only to branch learning evidence. No answer word cap or guaranteed spend.

### All five providers in parallel

From the repository root, the master configuration uses exactly [`crest/data/queries_n50_v2.jsonl`](crest/data/queries_n50_v2.jsonl) and [`crest/prompts/nus_pairwise_v3.txt`](crest/prompts/nus_pairwise_v3.txt). Preview all 50 questions, five research providers and three judges first:

```bash
# Preview the full plan locally; no paid calls.
python -m crest plan --dry-run --config crest/configs/crest.yaml \
  --agents caesar openai gemini anthropic gpt_researcher \
  --judges anthropic openai gemini

# Paid generation, judging and analysis; run only with authorization.
python -m crest run --config crest/configs/crest.yaml \
  --agents caesar openai gemini anthropic gpt_researcher \
  --judges anthropic openai gemini
```

`run` schedules the research providers concurrently within configured limits, then judges with Opus/high, Sol/high and Argon/high and analyzes the results. Planning is local, not live credential clearance. Generation and judging are paid; repeated work may reuse cache. Do not clear active caches or relaunch an existing pilot.

### One-provider pilots

Start with one provider and one question. Planning is local; generation makes paid model calls and live web requests. These are example commands; recorded pilot outcomes are listed below:

```bash
# Opus/high gateway/client-tool pilot.
python -m crest plan --agents anthropic --limit 1
python -m crest generate --agents anthropic --limit 1

# Separate GPT Researcher pilot, after its isolated setup.
python -m crest plan --agents gpt_researcher --limit 1
python -m crest generate --agents gpt_researcher --limit 1
```

Inspect each run’s saved answer, sources, word count, usage, request ledger where available, unresolved charges, and elapsed time before scaling up. Repeated generation can reuse cached work and is not automatically a fresh paid calibration.

### Current pilot outcomes

| Provider / attempt | Outcome and recorded cost | Important distinction |
| --- | --- | --- |
| Anthropic Sonnet/xhigh v4 | Complete; $3.04599548 | Soft $4.50 profile; 2,074 words, 38 turns / 13 rounds, 106 citation records. Complete final answer; cost accounting settled. |
| Caesar synthesis-only recovery | Complete; $3.837518580 cumulative known + $0.001510625 historically unresolved | Reused exploration; all 3 drafts and merge completed. New known charges: $2.541199485. Cumulative total remains unknown; not a fresh soft-300-iteration average. |
| OpenAI Sol/xhigh q1 | Complete; $3.1459949 | Existing hard-policy pilot with a nonbinding ceiling; 2,184 words. Usable single-question evidence, not a new all-soft run. |
| Google standard q1 | Complete; actual cost unverified | 4,525 words. Historical v2 conditional mean: **$2.9209 per answer across 50**, under the older 600-word profile, not today’s actual cost. |
| GPT Researcher input-fit v4 | Stopped at user request before final writing; no completed-answer cost calibration. | No final answer from this attempt. |

GPT v3 returned an answer at $0.377987 and used 16,848 writer output tokens, demonstrating the larger output allowance. Its first research round stopped at the input-size request_bound guard, not the dollar threshold; it was not full-depth or near-$3 calibration.

These are single-question usage-priced observations, not invoices or current-profile averages. The historical xhigh pilot costs do not calibrate current high-effort research. Citation records are collected URLs, not independently fact-checked support. Soft thresholds do not prevent overruns or guarantee spending near $3; judging costs extra. Caesar’s recovery used a separate soft $2.70 advisory for new synthesis work and retained the original unresolved exposure.

Earlier failures and hard-policy pilots are covered in [historical context](docs/deep-research/research-pipeline.html#pilot-history).

**Mac runs:** Keep the Mac awake with its lid open. Optional `caffeinate -i -w PID` suppresses idle sleep, not lid-closure sleep. Inspect receipts and unresolved exposure before any separately authorized retry; never reset unknown charges.

A one-provider pilot cannot produce pairwise rankings. For an actual comparison, select at least two providers and use the run directory printed by that generation:

```bash
python -m crest plan --agents openai anthropic --limit 1
python -m crest generate --agents openai anthropic --limit 1
# Replace this illustrative path with the printed run_dir.
CREST_RUN=crest/results/YYYY-MM-DD/HH-MM-SS-TZ-anthropic-openai-q1-ID
python -m crest judge --run "$CREST_RUN"
python -m crest analyze --run "$CREST_RUN"
```

Judging makes additional paid calls; analysis is local. Omit `--limit 1` for all 50 questions. `python -m crest run` runs all three stages; without `--agents`, it selects all configured providers. Use `--config PATH` for another configuration, `--agents` for new generation runs only, `--judges` for a judge subset, or `--run PATH` to resume an existing run with its saved agent settings. A judge call whose submission outcome is unknown stops judging for review; `judge --resend-unknown` resends each such call once, and the first try keeps its unknown cost.

### Budgets and recorded prices

**Configured policy for new runs: all five research providers use `budget_cap: soft`.** Warning thresholds are **$4 for every research provider**. Crossing a USD threshold alone does not refuse requests, cancel jobs or shrink output allowances to fit a dollar ceiling. Offline validation passed; these remain warning thresholds, not spending caps.

| System | Configured soft policy | Work limits / planning |
| --- | --- | --- |
| Caesar | Soft $4 warning; $2.60 reserve inactive in soft | Up to 300 iterations, 3 drafts × 20 Q&A rounds; no reserve-driven handoff or USD-ceiling admission stop |
| OpenAI | Soft $4 warning; fixed 5 rounds (initial + 4 follow-ups) | A follow-up is skipped only if one as costly as the last would pass $4; no hosted-job cancellation solely for exceeding the USD threshold |
| Google Deep Research | Soft $4 warning, unchanged | Managed standard agent decides; overruns are flagged, not prevented |
| Anthropic Opus 5.5 | Soft $4 warning; fixed 7 rounds (initial + 6 follow-ups) | A follow-up is skipped only if one as costly as the last would pass $4; 50 client-tool continuations; configured 64,000-token request limit remains independent of the USD threshold |
| GPT Researcher | Soft $4 warning; $3.40 planning target, $0.50 synthesis planning allowance | Target-driven research/writer handoff; ledger tracks charges and unresolved exposure, not a hard USD admission ceiling |

**Caesar limits:** Sol/medium research, Sol/high synthesis and Luna/low exploration/KB. Up to 300 exploration iterations; synthesis allows 32,768 tokens, with 1,200-second calls and 21,600 seconds overall. Answer concurrency starts at **25** and can grow to **50**; 50 concurrent answers ran on 2026-11-23 without rate limits, using about 32 GB including Chroma. The $2.60 reserve is inactive in soft mode; hard-only pricing/admission checks do not apply. Unknown exposure is still recorded.

Soft budgets warn rather than stop spending. Provider-specific validation, finite work/token/time limits and accounting still apply. OpenAI/Anthropic run a fixed number of follow-up rounds, sized from pilot costs to land near $3 within $2–4 (OpenAI 5 rounds: mean $3.12 over 51 replayed pilot answers, 46 inside $2–4; Anthropic 7 rounds: half the 14 that put two Sonnet pilots at $3.18–3.25, since Opus tokens cost 2× Sonnet's and client search is free for both). Those pilots used xhigh effort; the configured high effort may land lower, so confirm with a pilot. GPT uses its planning target and allowance. None forces minimum spending or guarantees a final cost.

**Cost limits:** Estimates are not invoices. Unknown usage is not zero; preserve outstanding exposure and receipts before any authorized retry. Saved runs retain their original policies; judging costs are separate. For the report only, [cost_imputation.py](crest/cost_imputation.py) imputes a cost for each call that never reported one (failed Caesar calls, a lost Anthropic turn, judge first tries that were resent) from comparable known calls, and keeps it apart from the known total; saved records are not changed. Google's assumed-price estimate stays marked incomplete.

The verified active-route assumptions are USD per million tokens:

| Route / model | Input | Cached input | Cache write | Output |
| --- | ---: | ---: | ---: | ---: |
| LiteLLM gateway / Opus 5.5 research and judge | $4.40 | $0.22 | $5.50 (5-minute) | $22 |
| Direct OpenAI / Sol | $2 | $0.10 | $2.50 (default 30-minute) | $10 |

These are route-specific estimates, not account invoices; use the gateway tariff rather than Anthropic's direct tariff for gateway requests. Cached reads and writes replace ordinary input tokens, and reasoning/thinking is billed once. Long-context pricing and hosted-tool charges may change a request's total; [Judge Models](docs/judging/judge-models.html#cost) records the estimator assumptions. Client DDGS/HTTP tools add no API fee, but their content consumes billed model tokens.

For historical context, the published **2026-10-26** run measured **$1.60 (Caesar), $0.10 (OpenAI), and $3.71 (Google)** per answer. The older **2026-11-02** standard Google pilot at 600 words was below the $2–4 range. Neither those measurements nor earlier pilots establish spending for the current Opus/high or GPT Researcher/high profiles.

**Google pricing assumptions / sensitivity:** Both Google figures use the same conditional estimator: high-context rates, tool-use tokens counted as extra input, and full-price searches. The historical 600-word v2 profile totals $146.0447 across 50 answers, or $2.9209 per answer. Applied to the new uncapped q1, that pricing scenario gives $6.9990348. Neither is a verified bill; the q1 figure is not a confirmed overrun or current mean. See the [historical v2 comparison](docs/deep-research/deep-research-comparison-v2.html#resources).

Every system except Caesar receives the shared creativity prompt (`research_prompt`, selected by `use_research_prompt`). It asks for novel, thought-provoking answers focused on emergent patterns, connections, surprising directions, and tensions. Caesar receives the bare question because Rome owns its prompting. **There is no final-answer word cap for any research provider** (`answer_word_limit: null`). Shared research and continuation prompts impose no word target, and Caesar and GPT Researcher do not restore a hidden draft or final-answer word cap. Word counts remain descriptive, not a truncation or rejection threshold. Removing the word cap does **not** remove provider output/completion-token limits (`max_output_tokens`, `max_completion_tokens`) or budget controls; these remain request-safety safeguards, not word-count requirements or invoice guarantees. Historical 600-word pilots retain their original limits and measurements and do not calibrate this uncapped-word configuration.

## Pipeline and saved results

| Stage | Command | Output |
| --- | --- | --- |
| Generate | `python -m crest generate` | Answers, source records, configurations, cost, and elapsed time |
| Judge | `python -m crest judge --run PATH` | Overall A/B verdicts with comparative explanations |
| Analyze | `python -m crest analyze --run PATH` | Rankings, head-to-head results, uncertainty, and judge diagnostics |

New runs live in `crest/results/YYYY-MM-DD/HH-MM-SS-TZ-<agents>-q<count>-<id>/`, with dated folders for each stage. The provider slug uses the selected research provider IDs in sorted order, with underscores changed to hyphens; `q<count>` records the actual number of selected questions, not an unchecked `--limit` value. The final run ID is eight lowercase hexadecimal characters. If the provider slug exceeds 40 characters, it becomes `<N>-research-agents`; all five current providers therefore use names such as `HH-MM-SS-TZ-5-research-agents-q50-ID`. A one-question OpenAI/Anthropic comparison uses `HH-MM-SS-TZ-anthropic-openai-q1-ID`, while a GPT Researcher-only pilot uses `HH-MM-SS-TZ-gpt-researcher-q1-ID`. These are naming examples, not recorded runs.

Existing run directories keep their original names, including older `HH-MM-SS-TZ-ID` paths. Resume or analyze them using their exact saved `--run` path; do not rename historical runs to match the new format. Same-name collisions receive a numeric suffix such as `-2` without overwriting existing work. These readable names do not change paid-work cache identities. Generation caches remain shared across runs; judgment and analysis caches live inside each run. Changing the rubric or judges reuses the saved answers. Configuration identities distinguish answers generated with different settings.

Cited URLs that an answer's text never links are appended as a `Sources:` list. URLs are compared by a normalized key (case, fragment, trailing slash, tracking parameters), so a variant of a link already present is not added again.

Provider concurrency adapts to successful requests and rate limits, within configured bounds. Failed attempts have bounded retries. Cost and timing records retain the original measurements when cached work is reused.

## How the ranking works

With all five current providers, each question has **10 pairs × 3 judges × 2 orders = 60 judgments**: 3,000 across 50 questions, with 1,200 judgments involving each system. These are design counts before missing answers, invalid judgments, or retries. The earlier four-system design had **6 pairs × 3 judges × 2 orders = 36 judgments** per question, or 1,800 across 50 questions and 900 involving each system; the published three-system/two-judge study retains its own 600-judgment count.

Systems rank by their share of overall wins on common complete questions. New, Useful, and Surprising guide a single decision; they are not separate rankings. Question-level bootstrap intervals describe sensitivity to the question mix with saved answers and judges held fixed. These results measure judge preferences, not verified factual accuracy or absolute creativity.

See the [NUS Rubric](docs/judging/nus-rubric.html), [default NUS v3 rubric](crest/prompts/nus_pairwise_v3.txt), and [50-question dataset](crest/data/queries_n50_v2.jsonl). [NUS v2](crest/prompts/nus_pairwise_v2.txt) and [NUS v1](crest/prompts/nus_pairwise_v1.txt) are also available; select their prompt path explicitly for comparisons. Saved runs keep the exact prompt text they used. V3 has the judge state the expected approach from the task before reading either answer, credits what an answer adds to a cited idea rather than the idea itself, and judges payoff against the task's need rather than the answer's framing. It neither credits nor penalizes wording about an answer's own research, such as "the supplied material". These are design improvements, not measured gains in agreement with human judges.

Rubric file versions (NUS v1, v2, v3) are separate from the judging protocol version, which sets the response instructions added after every NUS rubric. NUS jobs use protocol `nus-overall-pairwise-v4` by default (`CURRENT_NUS_PROTOCOL` in [rubrics.py](crest/rubrics.py)): it asks for the stronger creative contribution, has the judge consider the guidance as a whole rather than as separate scales, and asks for about 150–300 words, a target rather than a limit. Protocol `nus-overall-pairwise-v3`, which the 50-question study used under all three rubrics, is frozen so saved stages and their cache keys can be rebuilt exactly; the protocol is part of the judgment key, so a `nus-overall-pairwise-v4` pass does not reuse v3-protocol judgments. Judge stage manifests and protocol-v4 jobs record `rubric_id` (the rubric file name and the SHA-256 of its text). It is not part of the job key, and `rubrics.resolve_rubric_version` names the packaged rubric by content, so a renamed file still resolves. The AI scientist pipeline follows the same split: `crest_ais` plans use `crest-ais-overall-v4` by default, and `crest-ais-overall-v3` plans stay frozen.

The current question set was generated by the three judge models configured at the time, in the five categories of Caesar's original [50 questions](crest/data/queries_n50_v1.jsonl), which the published comparison used.

## Browse the reports

The reports are self-contained HTML files. To read them locally:

```bash
python -m http.server 8000
```

Open [the documentation index](http://localhost:8000/docs/index.html) for the research comparison, AI scientist comparison, guides, and historical project material.

Page names use title case, with matching lowercase kebab-case HTML filenames. `docs/index.html` is the only page at the top of `docs/`; the rest sit in one folder per index section: `judging/`, `deep-research/` and `ai-scientists/`. Directory landing pages use `index.html`. The canonical names and compatibility aliases live in `crest_ais/site.py`. Old archive URLs redirect to their canonical page, keeping query strings and section fragments when JavaScript is enabled, and give a readable link without it.

To render a comparison page from a complete 50-question run, without API calls:

```bash
python -m crest.report RUN --output docs/deep-research/deep-research-comparison-v3.html \
  --rubric-run OTHER_RUBRIC_RUN --rubric-run ANOTHER_RUBRIC_RUN
```

Pass `--rubric-run` once for each extra run that judged the same answers under another packaged NUS rubric; those results appear in collapsed sections at the bottom of the page. The published v3 page renders the NUS v1 run `crest/results/2026-11-24/04-13-43-CST-5-research-agents-q50-6324120b` with the NUS v3 run `2026-11-23/22-38-07-CST-5-research-agents-q50-1eaaa56c` and the NUS v2 run `2026-11-24/04-14-01-CST-5-research-agents-q50-d1ec03a9`. Run outputs are local and ignored by Git.

`Updated YYYY-MM-DD` is the **page-update date**, not the study date or run date. Saved answers, judgments, scores, tables, figures, and original study metadata are not changed when publication wrappers are updated. Report writers accept `updated="YYYY-MM-DD"`; `python -m crest.report` also accepts `--updated`. Date precedence is the explicit argument, `CREST_PAGE_UPDATED`, `SOURCE_DATE_EPOCH` (UTC), then the current UTC build date. Set `CREST_PAGE_UPDATED` to a page's shown date to reproduce that publication. Canonical report filenames determine the versioned page title; custom filenames retain the generic comparison title. Regenerating a canonical report in this site automatically updates its index entry date and the index page date. Legacy output filenames are rejected so they cannot overwrite compatibility redirects. For manually edited pages, update the page header and its matching index date together. The catalog’s `updated` fields are recorded dates, not a build-time clock.

## Development

Provider-specific helpers live beside their adapters under `crest/providers/`: [caesar_budget.py](crest/providers/caesar_budget.py), [caesar_metrics.py](crest/providers/caesar_metrics.py), [caesar_worker.py](crest/providers/caesar_worker.py), and [gpt_researcher_worker.py](crest/providers/gpt_researcher_worker.py). These are the canonical module paths; no old root-level aliases are provided. Shared cross-provider [config.py](crest/config.py), [budget.py](crest/budget.py), [costs.py](crest/costs.py), and [report.py](crest/report.py) intentionally remain under `crest/`.

```bash
python -m pytest
```

The master test command runs both packages' tests in parallel across all logical CPU cores. Use `-n 4` to limit workers or `-n 0` for serial debugging.

The current configuration passed the full offline regression and independent review. Offline checks do not establish live costs or answer quality.

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
