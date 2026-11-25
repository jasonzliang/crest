# Provider adapters

Research generation, judging, and durable provider/worker integration.

- `openai.py`, `gemini.py`, `anthropic.py`: API adapters.
- `caesar.py`, `caesar_worker.py`: sibling Rome integration.
- `caesar_budget.py`, `caesar_metrics.py`: Caesar-specific planning and accounting.
- `gpt_researcher.py`, `gpt_researcher_worker.py`: isolated GPT Researcher integration.
- `research_tools.py`: bounded client-side public search and HTTP fetch.
- `http.py`, `__init__.py`: shared transport, retry, usage, and budget helpers.

Transport retries:

- `anthropic.py` treats connect, TLS, and pool errors raised before a request is sent as not sent, so it retries them; an interrupted attempt records its `error_type`.
- `caesar_worker.py` retries dropped connections and timeouts within `retry_attempts` (default 4) per request and at most 8 per run, except inside synthesis writes; each failed call's reservation stays as unknown cost.
- `gpt_researcher_worker.py` retries HTTP 5xx up to 3 times, keeping each failed attempt's reservation as unknown cost; `gpt_researcher.py` checks that those are the receipt's only unknown charges.

Retry rules are not part of `ADAPTER_VERSION`, so they do not change cache identities.

Provider workers and Caesar helpers are canonical here; old root aliases are absent.
Cross-provider [config](../config.py), [budget](../budget.py), [costs](../costs.py), and [reports](../report.py) stay in the parent package.
Use the package CLI for runs; keep credentials in the environment, never in source or manifests.
Generation and judging can incur charges; preserve job checkpoints and accounting receipts.
