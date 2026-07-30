# crest/eval — per-entrant evaluation scripts

Thin wrappers that evaluate ONE entrant on CREST and write an immutable run directory under
`crest/result/runs/<run_id>/`. For a multi-agent, config-driven run, use **`crest/run_eval.py`**
with `crest/config/eval_config.yaml` instead.

Run from the repo root (the parent of `crest/`):

| Script | Entrant key | Model (pinned in `harness/agents.py`) | Mode |
|---|---|---|---|
| `eval_claude_sonnet.py` | `claude_dr` | `claude-sonnet-5` | chat + `web_search` tool |
| `eval_gpt56.py` | `openai_dr` | `gpt-5.6` | chat + Responses `web_search` |
| `eval_gemini3pro.py` | `gemini_dr` | `gemini-3.1-pro-preview` | chat + `google_search` grounding |
| `eval_openai_deepresearch.py` | `openai_deepresearch` | `o3-deep-research` | **OpenAI Deep Research API** |
| `eval_openai_deepresearch_mini.py` | `openai_deepresearch_mini` | `o4-mini-deep-research` | OpenAI Deep Research API (mini) |

Gemini has **no separate Deep Research model** in the API, so its DR-equivalent is grounded Pro —
i.e. `eval_gemini3pro.py` itself (no separate script).

```bash
python crest/eval/eval_claude_sonnet.py            # full 50-item run for one model
```
Each script takes optional subset args in-code (`run_one("claude_dr", per_category=2)`) for a cheap
balanced pilot before a full run.

Notes on model availability (verified on the current keys):
- `gpt-5.6` is callable via the Responses API. OpenAI Deep Research models `o3-deep-research` and
  `o4-mini-deep-research` exist and are the purpose-built DR agents (slow: minutes/query).
- **`gemini-3-pro` / `gemini-3-pro-preview` are deprecated** on the current key; the working Gemini-3
  Pro is **`gemini-3.1-pro-preview`**. Gemini has **no separate Deep Research model** — grounded Pro
  is the API equivalent.
- Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` in the environment.
