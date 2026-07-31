> **HISTORICAL (pre-2026-07-30).** Refers to entrant keys (`*_dr`) and item fields
> (`predicted_direction`, `category_name`) that no longer exist. Retained for the
> reasoning, not as a description of the current artifact.

# Which deep-research agents to run — selection & rationale

**Requirement:** open-source, on GitHub, drives the **Anthropic or OpenAI API**, produces
long **cited** research reports, and is runnable with the keys available here
(Anthropic ✓, OpenAI ✓, Google ✓; **no Tavily/SerpAPI**).

## Ranked recommendation (download-and-run)
1. **LangChain `open_deep_research`** — `github.com/langchain-ai/open_deep_research`. **Best fit.**
   Supports **OpenAI and Anthropic** via `init_chat_model()`, and — decisively — has a **native
   web-search mode for Anthropic/OpenAI**, so it runs with **no separate search key**. LangGraph
   agent; actively maintained. Run: `uv sync` → set `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` →
   `langgraph dev`. (Confirm license in-repo before release.)
2. **GPT Researcher** — `github.com/assafelovic/gpt-researcher`. Apache-2, most mature/popular OSS
   deep-research agent. **OpenAI-native** (Anthropic via config/MCP). **Needs `TAVILY_API_KEY`**
   (or another configured retriever) — so it is *not* immediately runnable here without adding a
   search key. Best once a Tavily key is available. `pip install gpt-researcher`.
3. **HuggingFace `smolagents/open_deep_research`** — `github.com/huggingface/smolagents`
   (examples). Apache-2, **LiteLLM** backend (OpenAI/Anthropic), replicates OpenAI Deep Research,
   strong on GAIA. Uses a search tool (Serper/DuckDuckGo).
4. **STORM** — `github.com/stanford-oval/storm`. MIT; OpenAI/Anthropic; article-generation flavor;
   needs a retriever (You.com/Bing).

## What we actually ran, and why
For the first live run we used **provider-native web-search agents built into the harness** —
`claude_dr` (Claude + Anthropic `web_search` tool) and `openai_dr` (GPT + OpenAI Responses
`web_search` tool). This is the **same native-search mode `open_deep_research` uses**, and it was
the right first choice because it:
- runs with **only the keys we have** (no Tavily), and
- gives exactly **one Anthropic + one OpenAI agent**, as required, and
- avoids standing up the LangGraph server + retriever for a first end-to-end test.

Both were smoke-tested and return real text **with citations** (verified: Anthropic returned
source URLs; OpenAI accepted the `web_search` tool).

## The adapter point
`harness/agents.py` defines a uniform `Agent.run(query) -> AgentOutput(text, citations, n_tokens)`.
Dropping in a full OSS agent = implementing **one** `run()` that calls its API and returns an
`AgentOutput`. So `open_deep_research` / GPT Researcher plug in without touching the judge,
grounding check, or stats.

## For the paper's real leaderboard (not this pilot)
Run **(a)** the commercial deep-research products (OpenAI, Gemini, Claude, Perplexity) via API as
time-indexed snapshots, **plus (b)** ≥1 OSS agent (`open_deep_research`) **and** ≥1 **open-weight**
agent on the **frozen shared index** — the open-weight-on-frozen-index run is the permanently
reproducible core (see the paper's Limitations). LOFO judging requires the entrant's model family
to be excluded from the judge panel, which the harness enforces automatically.
