# crest/eval — per-entrant evaluation scripts

Thin wrappers that evaluate ONE entrant on CREST and write an immutable run directory under
`crest/result/runs/<run_id>/`. For a multi-agent, config-driven run, use **`crest/run_eval.py`**
with `crest/config/eval_config.yaml` instead.

Run from the repo root (the parent of `crest/`):

```bash
python crest/eval/eval_claude_sonnet.py --dry-run         # resolve + preflight keys, spend nothing
python crest/eval/eval_claude_sonnet.py --per-category 2  # cheap balanced 10-item pilot
python crest/eval/eval_claude_sonnet.py                   # full 50-item run for one entrant
```

Every script shares one front door, `_common.py::cli()`, so each has the same guards as
`run_eval.py`: `--dry-run`, `--yes`, API-key preflight and the cost guard, plus `--per-category`,
`--limit`, `--categories`, `--budget`, `--concurrency`, `--override-cache` (`--help` for all).
The two deep-research scripts default to `--per-category 1` because they cost dollars per task.

| Script | Entrant key | Model (pinned in `harness/agents.py`) | Arm |
|---|---|---|---|
| `eval_claude_sonnet.py` | `claude_shallow` | `claude-sonnet-5` | shallow: chat + `web_search` |
| `eval_gpt56.py` | `openai_shallow` | `gpt-5.6` | shallow: chat + Responses `web_search` |
| `eval_gemini3pro.py` | `gemini_shallow` | `gemini-3.1-pro-preview` | shallow: chat + `google_search` grounding |
| `eval_openai_deepresearch.py` | `openai_deepresearch` | `gpt-5.6-sol` (effort=high, `max_tool_calls`=40) | **deep**: background Responses loop |
| `eval_openai_deepresearch_mini.py` | `openai_deepresearch_mini` | `gpt-5.6-sol` (effort=medium, 15 calls) | deep: cheaper depth setting |
| *(no script yet)* | `gemini_deepresearch` / `gemini_deepresearch_max` | `deep-research-preview-04-2026` / `-max-preview-04-2026` | **deep**: Google Interactions API |

There is **no `--resume`**: a run dir is immutable, so every invocation mints a fresh `run_id` and
already-paid-for answers are served from the cross-run generation cache (`harness/cache.py`, keyed on
challenge text + agent + model + adapter fingerprint). A re-run therefore pays only for judging;
`--override-cache` forces fresh generation and RE-PAYS.

The `*_dr` entrant keys were renamed `*_shallow` (single-turn search-augmented chat, not deep
research), so any result recorded under `claude_dr` / `openai_dr` / `gemini_dr` is a shallow-arm number.

Model availability (verified on the current keys, 2026-07-30):
- The purpose-built OpenAI Deep Research models `o3-deep-research` / `o4-mini-deep-research` were
  deprecated 2026-04-22 and **shut down 2026-07-23**: both still appear in `models.list()` but every
  Responses call 404s. OpenAI deep research is now a *pattern* — a general reasoning model +
  `web_search` + `background=True`, depth dialed by `reasoning.effort` and `max_tool_calls`.
- **`gemini-3-pro` / `gemini-3-pro-preview` are deprecated** on the current key; the working Gemini-3
  Pro is **`gemini-3.1-pro-preview`**.
- Google **does** ship a turnkey deep-research agent (`deep-research-preview-04-2026`,
  `deep-research-max-preview-04-2026`), so grounded Gemini Pro is *not* its deep-research equivalent.
  Interactions API only, `background=True` required.
- Anthropic ships no turnkey deep-research endpoint, so the deep arm has no Anthropic entrant — an
  asymmetry to disclose, not a null result for Claude.
- Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` in the environment
  (`ANTHROPIC_API_KEYS` pools several Anthropic keys — see `harness/keys.py`).

See `crest/docs/notes/deep_research_apis.md` for the live-probed provider landscape and per-task costs.
