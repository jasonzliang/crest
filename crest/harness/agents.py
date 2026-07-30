"""Agent adapters for CREST entrants.

Run mode: LIVE provider-native web search — Anthropic's `web_search` tool, OpenAI's Responses
`web_search` / Deep Research API, and Gemini's `google_search` grounding — so a real run needs
only the model API keys (no Tavily/SerpAPI). This mirrors the native-search mode of
langchain-ai/open_deep_research. NB: live web search is NOT contamination-controlled; results are
time-indexed snapshots. A frozen shared index (fair, reproducible run) is future work — see
`FrozenIndex`, which deliberately raises until it is built.

Search-call budget: enforced where the provider exposes a cap (Anthropic `max_uses`); OpenAI and
Gemini native search are not directly cappable, so `budget` is advisory for them (report n_searches).

Model IDs are pinned per entrant in `_REGISTRY`. The authors' own entrant (cited prior work) is
one entrant among many; it must not be privileged and all findings must hold with it removed.
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
    """Dated, hashed shared corpus for the fair/reproducible run. FUTURE WORK: not built yet, so
    the constructor raises to prevent a live run being silently mislabeled as contamination-controlled."""
    def __init__(self, path: str | None):
        raise NotImplementedError(
            "frozen-index mode is future work; omit --index to run in LIVE provider-web-search mode")


class Agent:
    model_family: str = "unknown"     # used for leave-one-family-out judging
    model: str = ""
    def __init__(self, index: FrozenIndex | None = None, budget: int = 6, model: str | None = None):
        self.index, self.budget = index, budget
        if model:
            self.model = model
    def run(self, query: str) -> AgentOutput:
        raise NotImplementedError


# ---------------- Anthropic ----------------
class ClaudeDeepResearch(Agent):
    """Claude + server-side web_search tool."""
    model_family = "anthropic"
    model = "claude-sonnet-5"
    def run(self, query: str) -> AgentOutput:
        import anthropic
        client = anthropic.Anthropic(timeout=600)
        r = client.messages.create(
            model=self.model, max_tokens=9000, system=_DR_SYSTEM,
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


# ---------------- OpenAI ----------------
def _parse_openai(r) -> AgentOutput:
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


class OpenAIDeepResearch(Agent):
    """GPT (chat) + Responses `web_search` tool -- a lightweight deep-research config."""
    model_family = "openai"
    model = "gpt-5.6"
    def run(self, query: str) -> AgentOutput:
        from openai import OpenAI
        r = OpenAI(timeout=600).responses.create(
            model=self.model, tools=[{"type": "web_search"}],
            instructions=_DR_SYSTEM, input=query,
            reasoning={"effort": "low"}, max_output_tokens=9000,
        )
        return _parse_openai(r)


class OpenAIDeepResearchAPI(Agent):
    """OpenAI Deep Research API (o3-deep-research / o4-mini-deep-research) via the Responses API:
    a purpose-built, multi-step research agent (web_search_preview is required). Long-running --
    minutes per query -- so the client timeout is raised."""
    model_family = "openai"
    model = "o3-deep-research"
    def run(self, query: str) -> AgentOutput:
        from openai import OpenAI
        r = OpenAI(timeout=1800).responses.create(
            model=self.model, tools=[{"type": "web_search_preview"}],
            instructions=_DR_SYSTEM, input=query, max_output_tokens=12000,
        )
        return _parse_openai(r)


# ---------------- Google ----------------
class GeminiDeepResearch(Agent):
    """Gemini + google_search grounding. Gemini exposes no separate Deep Research *model* (Deep
    Research is an app feature), so grounded Gemini-Pro is the API deep-research equivalent."""
    model_family = "google"
    model = "gemini-3.1-pro-preview"
    def run(self, query: str) -> AgentOutput:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"),   # keep a ref (temporary gets GC'd)
                              http_options=types.HttpOptions(timeout=600_000))  # ms
        r = client.models.generate_content(
            model=self.model, contents=f"{_DR_SYSTEM}\n\nTASK:\n{query}",
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        cites, n_search = [], 0
        try:
            gm = r.candidates[0].grounding_metadata
            n_search = len(getattr(gm, "web_search_queries", None) or [])
            for ch in (getattr(gm, "grounding_chunks", None) or []):
                w = getattr(ch, "web", None)
                if w and getattr(w, "uri", None):
                    cites.append({"url": w.uri, "title": getattr(w, "title", "") or ""})
        except Exception:
            pass
        text = r.text or ""
        n_tok = getattr(getattr(r, "usage_metadata", None), "candidates_token_count", 0) or 0
        return AgentOutput(text, _merge_inline_urls(_dedup(cites), text),
                           n_tokens=n_tok, n_searches=n_search or len(cites))


# ---------------- future entrants (documented, not yet wired) ----------------
class OpenSourceAgent(Agent):
    """Open-weight agent on the frozen index = the permanently reproducible core. Future work."""
    model_family = "open_weight"
    def run(self, query): raise NotImplementedError("point at a hosted open-weight endpoint")

class AuthorEntrant(Agent):
    """The authors' own entrant (cited prior work). One entrant among many; must not be privileged
    and all findings must hold with it removed. Same family as the GPT judge -> excluded under LOFO."""
    model_family = "openai"
    def run(self, query): raise NotImplementedError("plug in the authors' system endpoint")


def _dedup(cites: list) -> list:
    seen, out = set(), []
    for c in cites:
        if c["url"] and c["url"] not in seen:
            seen.add(c["url"]); out.append(c)
    return out


_URL_RE = re.compile(r"https?://[^\s\)\]\}<>\"']+")

def _merge_inline_urls(cites: list, text: str) -> list:
    """Some agents write source URLs inline without emitting structured citations. Capture those
    too, so grounding isn't fooled by citation-surfacing differences across providers."""
    have = {c["url"] for c in cites}
    for u in _URL_RE.findall(text or ""):
        u = u.rstrip(".,;")
        if u not in have:
            have.add(u); cites.append({"url": u, "title": ""})
    return cites


# name -> (adapter class, pinned default model id)
_REGISTRY = {
    # frontier chat + native web search
    "claude_dr":                (ClaudeDeepResearch, "claude-sonnet-5"),
    "openai_dr":                (OpenAIDeepResearch, "gpt-5.6"),
    "gemini_dr":                (GeminiDeepResearch, "gemini-3.1-pro-preview"),
    # purpose-built deep-research APIs
    "openai_deepresearch":      (OpenAIDeepResearchAPI, "o3-deep-research"),
    "openai_deepresearch_mini": (OpenAIDeepResearchAPI, "o4-mini-deep-research"),
    # (Gemini has no separate Deep Research model; `gemini_dr` = grounded Pro IS the DR equivalent.)
    # future entrants
    "oss_dr":                   (OpenSourceAgent, ""),
    "author_entrant":           (AuthorEntrant, ""),
}

def build_agent(name: str, index: FrozenIndex | None = None, budget: int = 6, model: str | None = None) -> Agent:
    if name not in _REGISTRY:
        raise ValueError(f"unknown agent '{name}'; known: {sorted(_REGISTRY)}")
    cls, default_model = _REGISTRY[name]
    return cls(index=index, budget=budget, model=model or default_model or None)
