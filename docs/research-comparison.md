# Open research agents, popularity, and costs

Checked 2026-10-25 UTC using unauthenticated, read-only GitHub repository API requests and current official provider documentation. No paid model calls or benchmark runs were performed. Stars measure repository interest, not installations, active users, quality, or adoption. This is a comparison of the inspected shortlist, not an exhaustive global ranking.

## Popularity depends on scope

The three most-starred inspected **OpenAI-capable, research-capable harnesses** are DeerFlow, Deep Agents, and GPT Researcher. Only GPT Researcher is primarily a turnkey research-report system; the first two are broader agent harnesses.

| Project | Stars / forks | OpenAI compatibility and research role | Cost model |
|---|---:|---|---|
| [DeerFlow](https://github.com/bytedance/deer-flow) | 84,399 / 11,808 | General long-horizon harness with research, tools, sandboxes, and subagents. Supports an OpenAI key and explicit Responses API routing. | Self-hosted code; pay all selected LLM calls, search/extraction services, and sandbox/hosting costs. No fixed credible per-report price. [Configuration](https://github.com/bytedance/deer-flow/blob/main/backend/docs/CONFIGURATION.md), [metrics](https://api.github.com/repos/bytedance/deer-flow). |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | 30,568 / 4,306 | Model-agnostic general harness; its README demonstrates OpenAI. Supply research/search tools; the harness alone is not a research service. | Selected LLM usage, chosen tools, and infrastructure; local use does not establish a fixed report price. [Metrics](https://api.github.com/repos/langchain-ai/deepagents). |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | 30,285 / 4,132 | Research-focused planner/executors/report synthesis, with recursive research and OpenAI support. Quickstart uses OpenAI plus Tavily keys. | LLMs plus retriever/context-filter choices and hosting. Its README's context-filter comparison reports roughly $0.115–$0.192/report for that specific experiment; these are author-reported figures, not measured Sol deep-research costs. [Metrics](https://api.github.com/repos/assafelovic/gpt-researcher). |

For **research-focused, model-swappable systems** the useful shortlist is GPT Researcher, [dzhng/deep-research](https://github.com/dzhng/deep-research) (19,826 stars / 2,009 forks), and [LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research) (12,676 / 1,858). dzhng is a small breadth/depth recursive loop using OpenAI and Firecrawl; its key is named `OPENAI_KEY`. LangChain has separate summarizer/research/compression/report models and configurable search. Both require LLM and tool bills; neither has a universal per-run cost. OpenAI-key support does not prove every model works unchanged: Sol tool calls require Responses API routing, and dzhng's checked provider code still defaults to an older model. [dzhng metrics](https://api.github.com/repos/dzhng/deep-research), [provider code](https://github.com/dzhng/deep-research/blob/main/src/ai/providers.ts), [LangChain metrics](https://api.github.com/repos/langchain-ai/open_deep_research).

Other checked projects explain exclusions: [Skywork DeepResearchAgent](https://github.com/SkyworkAI/DeepResearchAgent) has 3,562 stars / 455 forks and a broader hierarchical/evolving-agent scope, below these candidates. [Tongyi DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) has 20,078 stars, but its core is the Tongyi model; the documented OpenAI key supplies a page summarizer, not a turnkey OpenAI-backbone replacement. [Dexter](https://github.com/virattt/dexter), 27,713 stars, specializes in finance. Firecrawl itself, 195,134 stars, is primarily web-data infrastructure rather than this comparison's full research harness. MiroThinker 8,426; MiroFlow 3,119; Jina node-DeepResearch 5,240; nickscamara/open-deep-research 6,295; u14app/deep-research 4,688. Metrics can be reproduced with GitHub's `GET /repos/OWNER/REPO`; these secondary counts do not imply quality ordering.

## Published unit costs and native workflows

| Workflow | Verified pricing / distinction |
|---|---|
| Open-source harness with GPT-6.1 Sol | Standard, up to 272k prompt tokens: $2/M uncached input, $0.10/M cached input, $2.50/M cache writes, $10/M output. Larger prompts increase input/cache rates 2× and output 1.5×. Sum every internal call, including reasoning output; add external tools/infrastructure. [Official model/pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol). |
| Implemented OpenAI native workflow | Sol Responses API + required hosted web search + background execution, rather than an open-source loop. Same token rates plus $10/1,000 web-search calls and retrieved search-content input tokens. No fixed per-task USD price. [Official tool pricing](https://developers.openai.com/api/docs/pricing). |
| Dedicated OpenAI deep-research models | `o3-deep-research` and `o4-mini-deep-research` appear in an older guide, but the official deprecation schedule says their aliases/snapshots shut down July 23, 2026. Do not quote their old per-token prices as an available current alternative. The implemented Sol workflow must be labeled separately; it is not a claim of reproducing ChatGPT's complete product harness. [Official retirement schedule](https://developers.openai.com/api/docs/deprecations). |
| Gemini Deep Research | Managed Interactions API agent, billed by underlying model and tools. No stable current official per-task dollar estimate was verified across fresh page retrievals, and no costs were measured on these 50 questions. Google introduced these agents with Gemini 3.1 Pro; users cannot select an arbitrary underlying model. [Agent/cost guide](https://ai.google.dev/gemini-api/docs/deep-research), [launch announcement, April 21, 2026](https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/). |
| Gemini token/tool reference | Gemini 3.1 Pro: $2/M input and $12/M output including thinking at ≤200k prompt tokens; $4/$18 above it; cached input $0.20/$0.40. Search after the shared allowance is $14/1,000 individual queries. Actual managed-agent context tiers are hidden, so CREST labels its high-tier envelope estimate as estimated, not an invoice. [Official pricing](https://ai.google.dev/gemini-api/docs/pricing). |

External tools change open-source costs: Tavily pay-as-you-go is $0.008/credit, with request types consuming different credit counts; Firecrawl basic search uses 2 credits/10 results and a basic scrape 1/page, with plan-dependent dollar rates (Hobby $19/month for 5,000 credits; $16/month billed annually). These are tool unit/plan prices, not all-in report costs. [Tavily](https://www.tavily.com/pricing), [Firecrawl](https://www.firecrawl.dev/pricing).

Illustration only: 1M uncached input tokens across short Sol calls plus 200k billed output tokens costs $4 in model usage; 25 hosted searches add $0.25. This is arithmetic, not a measured task, expected workload, or promised price. A cheaper token tariff does not imply cheaper end-to-end research: loops, retries, sources, model effort, and final length differ. Credible quality/cost comparison requires running the same questions and retaining per-call usage.

## Caesar configuration actually selected for CREST

Keep Caesar's three main roles on Sol to compare its harness with native Sol research. These are target/guard settings, not a measured optimum:

```yaml
research:
  caesar:
    model: gpt-6.1-sol
    exploration_model: gpt-6.1-sol
    kb_model: gpt-6.1-sol
    budget_usd: 5.0
    handler_budget_usd: 4.0
    synthesis_reserve_usd: 1.5
    max_iterations: 30
    synthesis_drafts: 2
    synthesis_iterations: 5
    initial_concurrency: 1
    concurrency: 4
```

Worker defaults: low exploration/KB effort, medium synthesis; depth 6; three additional starting queries; five searches; eight retrieval chunks; reranking/images off; DDGS search. Sol Chat Completions remains valid for Caesar's text-only LLM calls because Python owns its web tools; native tool-calling harnesses should route Sol through Responses. Treat the $5 answer target as best effort and reserve headroom for judging. Fifty questions × three entrants gives a $750 generation target, with 600 judge calls additional; it is not a maximum authorized invoice or measured estimate.
