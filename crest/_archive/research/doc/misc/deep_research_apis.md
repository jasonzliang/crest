# Deep-research APIs: what actually exists (verified 2026-07-30)

Live-probed against this project's own API keys while wiring the CREST entrant set. Supersedes the
earlier assumption in `harness/agents.py` / `eval/readme.md` that the OpenAI Deep Research API was
the only turnkey deep-research option and that Gemini had none.

## The two arms CREST now runs

| Arm | Entrant keys | What it is |
|---|---|---|
| **Shallow** | `claude_shallow`, `openai_shallow`, `gemini_shallow` | chat model + provider-native web search, ONE turn, a handful of searches |
| **Deep** | `openai_deepresearch`(`_mini`), `gemini_deepresearch`(`_max`) | managed multi-step background research loop, tens of searches, minutes per call |

The old `*_dr` names implied all three frontier entrants were deep-research agents. They are not —
they are single-turn search-augmented chat. Renamed to `*_shallow` so the benchmark's claims match
what was actually run. **Any earlier result recorded under `claude_dr` / `openai_dr` / `gemini_dr`
is a shallow-arm number and must not be described as deep research.**

## Provider-by-provider

### OpenAI — deep research is a PATTERN, not a model
`o3-deep-research` and `o4-mini-deep-research` were deprecated 2026-04-22 and **shut down
2026-07-23**. Verified failure mode: both IDs (and their dated snapshots) still appear in
`models.list()`, but every Responses call returns
`404 {'message': 'Model not found o3-deep-research'}`. A `models.list()` membership check is
therefore **not** a valid availability check — call the model.

Current supported configuration: general reasoning model + >=1 data-source tool +
`background=True`, depth dialed by `reasoning.effort` and `max_tool_calls`. We use `gpt-5.6-sol`
(also live on this key: `gpt-5.6-luna`, `gpt-5.6-terra`). Tool string is `web_search`;
`web_search_preview` was the retired-era name. Runs take minutes, so we poll to terminal status.

### Google — a real turnkey deep-research agent (this repo previously said there was none)
Available **only** on the Interactions API (`client.interactions`), `background=True` **required**.
Agents live on this key: `deep-research-preview-04-2026` (standard),
`deep-research-max-preview-04-2026` (max, ~160 searches, up to ~30 min), and an older
`deep-research-pro-preview-12-2025`.

Parsing gotchas, all confirmed against a completed interaction on `google-genai==2.2.0`:
* **no `output_text`** on this SDK version — it is `None`; assemble the report from `steps`;
* `steps` includes the echoed prompt as a `user_input` step next to `model_output`. Reading every
  text item prepends our own system prompt to the "answer" — which would corrupt the grounding
  check and everything the judges see. Read `model_output` only;
* counters are on `it.usage` (`total_output_tokens`, `total_thought_tokens`,
  `grounding_tool_count=[GroundingToolCount(count=N, type='google_search')]`), **not**
  `usage_metadata`;
* `interactions.get(id)` takes a **positional** id; an `Interaction` has no `.name`;
* `create()` accepts `system_instruction`, so the shared research prompt is delivered the same way
  as Anthropic's `system=` and OpenAI's `instructions=` — prompt parity across entrants.

### Anthropic — no turnkey endpoint
There is no managed deep-research API. A Claude deep arm would be DIY: an agent loop over the
`web_search` / `web_fetch` server tools (or the Claude Agent SDK), handling
`stop_reason == "pause_turn"` by resending the assistant message unchanged. Not built, so the deep
arm is OpenAI + Google only. **This is an asymmetry to disclose in the paper**: the deep-arm
comparison has no Anthropic entrant, and `claude_shallow` must not be read as Claude's deep-research
ceiling.

## Cost / run-time per task (for the cost guard)

| Entrant | ~$/task | Wall-clock | 50 items |
|---|---|---|---|
| `*_shallow` (any vendor) | ~$0.05–0.20 | seconds | ~$3–10 each |
| `gemini_deepresearch` (std) | ~$2.6 (Google says $1–3) | several min | ~$130 |
| `gemini_deepresearch_max` | ~$6.1 (Google says $3–7) | 10–30 min | ~$300 |
| `openai_deepresearch` (effort=high, 40 calls) | ~$9 ceiling (~$8 expected) | minutes | ~$450 |
| `openai_deepresearch_mini` (effort=medium, 15 calls) | ~$2–4 | minutes | ~$100–200 |

Output/reasoning tokens dominate OpenAI cost (~65–75%); search fees are a major Google line.
Levers: `max_tool_calls` / `reasoning.effort` (OpenAI), std-vs-max agent (Google).

## Sources
Rates and retirement dates from `science_moonshot/documentation/caesar/`
(`deep_research_api_code_examples.md`, `deep_research_api_cost_model.md`, verified 2026-07-27),
plus live probing of `models.list()`, `responses.create`, and `interactions.create/get` on
2026-07-30. Fast-moving surface — re-verify before a camera-ready run.
