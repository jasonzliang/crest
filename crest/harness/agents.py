"""Agent adapters + the frozen shared search index.

Two modes:
  * LIVE (implemented, default for the pilot): each agent uses its provider's NATIVE
    server-side web search -- Anthropic's `web_search` tool and OpenAI's Responses
    `web_search` tool -- so a real deep-research run needs ONLY the model API keys
    (no Tavily/SerpAPI). This mirrors the native-search mode of langchain-ai/open_deep_research.
    NB: live web search is NOT the contamination-controlled benchmark run; results are
    time-indexed snapshots (see Limitations). The frozen-index mode below is the fair,
    reproducible run and is future work.
  * FROZEN (stub): all agents retrieve from one shared, dated, hashed corpus for fairness
    (objection O15) and reproducibility (O9). Ship as URLs+timestamps+SHA-256 (datasheet, O12).

Every entrant is wrapped in a uniform Agent interface with a matched search-call budget.
Closed frontier agents are pinned by dated model IDs. The authors' own entrant (Caesar) is
one entrant among many, must not be privileged, and all findings must hold with it removed (O6).
"""
from __future__ import annotations
import dataclasses, os, re

_DR_SYSTEM = (
    "You are a deep-research agent. Before writing, do REAL web search: issue at least TWO "
    "distinct search queries to gather current, primary evidence. Do this on EVERY task, "
    "INCLUDING invention/design tasks -- there you must still ground the FACTUAL SCAFFOLDING "
    "(definitions, prior work, data, constraints) with sources even though the core idea is "
    "your own invention. Then write a thorough, well-structured answer that follows every "
    "instruction and hard rule in the task EXACTLY. Support every load-bearing FACTUAL claim "
    "with an inline source URL in the answer text (write the full https://... URL), so "
    "grounding stays visible even if structured citations are dropped. Be genuinely original "
    "where the task asks for novelty; do not merely restate common knowledge. NEVER fabricate "
    "sources, URLs, or facts -- if you cannot find a source, say so instead of inventing one."
)


@dataclasses.dataclass
class AgentOutput:
    text: str
    citations: list                 # [{"url": str, "title": str}]
    n_tokens: int = 0
    n_searches: int = 0
    trace: dict = dataclasses.field(default_factory=dict)


class FrozenIndex:
    """Dated, hashed corpus served through one shared search API (future fair-run mode)."""
    def __init__(self, path: str | None):
        self.path = path
        self.snapshot_date = None
    def search(self, query: str, k: int = 10) -> list:
        raise NotImplementedError("wire to the frozen index server (fair-run mode)")
    def fetch(self, url: str) -> str:
        raise NotImplementedError("return frozen snapshot content by hash")


class Agent:
    model_family: str = "unknown"     # used for leave-one-family-out judging (O7)
    model: str = ""
    def __init__(self, index: FrozenIndex | None = None, budget: int = 6, model: str | None = None):
        self.index, self.budget = index, budget
        if model:
            self.model = model
    def run(self, query: str, seeds: int = 1) -> AgentOutput:
        raise NotImplementedError


class ClaudeDeepResearch(Agent):
    model_family = "anthropic"
    model = "claude-sonnet-5"
    def run(self, query: str, seeds: int = 1) -> AgentOutput:
        import anthropic
        client = anthropic.Anthropic()
        r = client.messages.create(
            model=self.model, max_tokens=6000, system=_DR_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": self.budget}],
            messages=[{"role": "user", "content": query}],
        )
        text, cites, n_search = [], [], 0
        for b in r.content:
            if b.type == "text":
                text.append(b.text)
                for c in (getattr(b, "citations", None) or []):
                    u = getattr(c, "url", None)
                    if u:
                        cites.append({"url": u, "title": getattr(c, "title", "") or ""})
            elif b.type == "server_tool_use":
                n_search += 1
        full = "".join(text)
        return AgentOutput(full, _merge_inline_urls(_dedup(cites), full),
                           n_tokens=r.usage.output_tokens, n_searches=n_search)


class OpenAIDeepResearch(Agent):
    model_family = "openai"
    model = "gpt-5"
    def run(self, query: str, seeds: int = 1) -> AgentOutput:
        from openai import OpenAI
        client = OpenAI()
        r = client.responses.create(
            model=self.model, tools=[{"type": "web_search"}],
            instructions=_DR_SYSTEM, input=query,
            reasoning={"effort": "low"}, max_output_tokens=9000,
        )
        cites, n_search = [], 0
        for item in (r.output or []):
            itype = getattr(item, "type", "")
            if itype in ("web_search_call", "web_search"):
                n_search += 1
            if itype == "message":
                for part in (getattr(item, "content", None) or []):
                    for ann in (getattr(part, "annotations", None) or []):
                        if getattr(ann, "type", "") == "url_citation":
                            cites.append({"url": getattr(ann, "url", "") or "",
                                          "title": getattr(ann, "title", "") or ""})
        n_tok = getattr(getattr(r, "usage", None), "output_tokens", 0) or 0
        full = r.output_text or ""
        return AgentOutput(full, _merge_inline_urls(_dedup(cites), full), n_tokens=n_tok, n_searches=n_search)


class GeminiDeepResearch(Agent):
    model_family = "google"
    model = "gemini-2.5-pro"
    def run(self, query: str, seeds: int = 1) -> AgentOutput:
        from google import genai
        from google.genai import types
        client = genai.Client()
        r = client.models.generate_content(
            model=self.model, contents=f"{_DR_SYSTEM}\n\nTASK:\n{query}",
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        cites = []
        try:
            gm = r.candidates[0].grounding_metadata
            for ch in (getattr(gm, "grounding_chunks", None) or []):
                w = getattr(ch, "web", None)
                if w and getattr(w, "uri", None):
                    cites.append({"url": w.uri, "title": getattr(w, "title", "") or ""})
        except Exception:
            pass
        return AgentOutput(r.text or "", _dedup(cites), n_searches=len(cites))


class PerplexityDeepResearch(Agent):
    model_family = "perplexity"
    def run(self, query, seeds=1): raise NotImplementedError("needs PERPLEXITY_API_KEY (unset)")

class OpenSourceAgent(Agent):
    """Open-weight agent on the frozen index = permanently reproducible core (Limitations)."""
    model_family = "open_weight"
    def run(self, query, seeds=1): raise NotImplementedError("point at a hosted open-weight endpoint")

class CaesarEntrant(Agent):
    """Authors' own entrant (cited prior work). One entrant among many; must not be privileged,
    must not top the board by construction, findings must hold with it removed (O6). Method not
    described here -- see the cited preprint. Same family as the GPT judge -> excluded under LOFO."""
    model_family = "openai"
    def run(self, query, seeds=1): raise NotImplementedError("plug in the Caesar system endpoint")


def _dedup(cites: list) -> list:
    seen, out = set(), []
    for c in cites:
        if c["url"] and c["url"] not in seen:
            seen.add(c["url"]); out.append(c)
    return out


_URL_RE = re.compile(r"https?://[^\s\)\]\}<>\"']+")

def _merge_inline_urls(cites: list, text: str) -> list:
    """Fallback: some agents write source URLs inline in the answer text without emitting
    structured citation objects. Capture those too, so the grounding check isn't fooled by
    citation-surfacing differences across providers."""
    have = {c["url"] for c in cites}
    for u in _URL_RE.findall(text or ""):
        u = u.rstrip(".,;")
        if u not in have:
            have.add(u); cites.append({"url": u, "title": ""})
    return cites


_REGISTRY = {
    "openai_dr": OpenAIDeepResearch, "gemini_dr": GeminiDeepResearch,
    "claude_dr": ClaudeDeepResearch, "perplexity_dr": PerplexityDeepResearch,
    "oss_dr": OpenSourceAgent, "caesar": CaesarEntrant,
}

def build_agent(name: str, index: FrozenIndex | None = None, budget: int = 6, model: str | None = None) -> Agent:
    if name not in _REGISTRY:
        raise ValueError(f"unknown agent '{name}'; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name](index=index, budget=budget, model=model)
