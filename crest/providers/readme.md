# Provider adapters

Research generation, judging, and durable provider/worker integration.

- `openai.py`, `gemini.py`, `anthropic.py`: API adapters.
- `caesar.py`, `caesar_worker.py`: sibling Rome integration.
- `caesar_budget.py`, `caesar_metrics.py`: Caesar-specific planning and accounting.
- `gpt_researcher.py`, `gpt_researcher_worker.py`: isolated GPT Researcher integration.
- `research_tools.py`: bounded client-side public search and HTTP fetch.
- `http.py`, `__init__.py`: shared transport, retry, usage, and budget helpers.

Provider workers and Caesar helpers are canonical here; old root aliases are absent.
Cross-provider [config](../config.py), [budget](../budget.py), [costs](../costs.py), and [reports](../report.py) stay in the parent package.
Use the package CLI for runs; keep credentials in the environment, never in source or manifests.
Generation and judging can incur charges; preserve job checkpoints and accounting receipts.
