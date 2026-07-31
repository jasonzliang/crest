# crest/eval — per-entrant evaluation scripts

Thin wrappers that evaluate ONE entrant on CREST and write an immutable run directory under
`crest/result/runs/<run_id>/`. For a multi-agent, config-driven run, use **`crest/run_eval.py`**
with `crest/config/eval_config.yaml` instead.

> **BROKEN as of 2026-07-30 — do not use these scripts yet.** `_common.py::run_one` still calls
> `results.find_resumable` / `results.completed_pairs` and passes `resume=` to `evaluate()`. All
> three were deleted when `--resume` was replaced by the cross-run generation cache, so every script
> here raises `AttributeError` before it makes a single API call. Until `_common.py` is ported to
> `GenerationCache`, run a single entrant with the ad-hoc CLI, which is fully supported:
> ```bash
> python -m crest.harness.run_crest --agents claude_shallow --subset adhoc
> python -m crest.harness.run_crest --agents claude_shallow --per-category 2 --subset pilot5cat
> ```

Run from the repo root (the parent of `crest/`):

| Script | Entrant key | Model (pinned in `harness/agents.py`) | Arm |
|---|---|---|---|
| `eval_claude_sonnet.py` | `claude_shallow` | `claude-sonnet-5` | shallow: chat + `web_search` |
| `eval_gpt56.py` | `openai_shallow` | `gpt-5.6` | shallow: chat + Responses `web_search` |
| `eval_gemini3pro.py` | `gemini_shallow` | `gemini-3.1-pro-preview` | shallow: chat + `google_search` grounding |
| `eval_openai_deepresearch.py` | `openai_deepresearch` | `gpt-5.6-sol` (effort=high, `max_tool_calls`=40) | **deep**: background Responses loop |
| `eval_openai_deepresearch_mini.py` | `openai_deepresearch_mini` | `gpt-5.6-sol` (effort=medium, 15 calls) | deep: cheaper depth setting |
| *(no script yet)* | `gemini_deepresearch` / `gemini_deepresearch_max` | `deep-research-preview-04-2026` / `-max-preview-04-2026` | **deep**: Google Interactions API |

The `*_dr` entrant keys were renamed `*_shallow` (single-turn search-augmented chat, not deep
research). Any result recorded under `claude_dr` / `openai_dr` / `gemini_dr` is a shallow-arm number.
The two deep-research scripts' own docstrings still name `o3-deep-research` / `o4-mini-deep-research`
— stale text; the entrant keys resolve through `_REGISTRY` to `gpt-5.6-sol`.

```bash
python crest/eval/eval_claude_sonnet.py            # full 50-item run for one model (once fixed)
```
Each script takes optional subset args in-code (`run_one("claude_shallow", per_category=2)`) for a
cheap balanced pilot before a full run. Generation is served from the cross-run cache
(`harness/cache.py`) where a matching answer already exists, so a re-run pays only for judging;
there is no `--resume`.

Notes on model availability (verified on the current keys, 2026-07-30):
- `gpt-5.6` is callable via the Responses API. The purpose-built OpenAI Deep Research models
  `o3-deep-research` and `o4-mini-deep-research` were deprecated 2026-04-22 and **shut down
  2026-07-23**: both still appear in `models.list()` but every Responses call 404s. OpenAI deep
  research is now a *pattern* — a general reasoning model + `web_search` + `background=True`, with
  depth dialed by `reasoning.effort` and `max_tool_calls`.
- **`gemini-3-pro` / `gemini-3-pro-preview` are deprecated** on the current key; the working Gemini-3
  Pro is **`gemini-3.1-pro-preview`**.
- Google **does** ship a turnkey deep-research agent (`deep-research-preview-04-2026`,
  `deep-research-max-preview-04-2026`), correcting this file's earlier claim that grounded Pro was
  Gemini's only deep-research equivalent. Interactions API only, `background=True` required.
- Anthropic ships no turnkey deep-research endpoint, so the deep arm has no Anthropic entrant.
- Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` in the environment
  (`ANTHROPIC_API_KEYS` pools several Anthropic keys — see `harness/keys.py`).

See `docs/notes/deep_research_apis.md` for the live-probed provider landscape and per-task costs.
