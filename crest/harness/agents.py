"""Agent adapters for CREST entrants.

TWO DISTINCT ARMS — do not conflate them:

  1. SHALLOW research (`*_shallow`): a chat model + provider-native web search in ONE turn
     (Anthropic `web_search`, OpenAI Responses `web_search`, Gemini `google_search` grounding).
     A handful of searches, no managed research loop. These are NOT deep-research agents, which
     is why they are named `shallow` — an earlier `*_dr` naming overstated what they do.
  2. DEEP research (`*_deepresearch*`): a managed, multi-step, background research loop —
     Google's turnkey Deep Research agent on the Interactions API, and OpenAI's current
     deep-research *pattern* (general reasoning model + web_search + background, dialed by
     reasoning effort / max_tool_calls). Minutes and dollars per call, tens of searches.

Provider landscape as of 2026-07-30 (re-verify; it moves fast):
  * OpenAI's dedicated `o3-deep-research` / `o4-mini-deep-research` were deprecated 2026-04-22 and
    SHUT DOWN 2026-07-23. They still appear in `models.list()` but every Responses call 404s, so
    deep research is now the general-model pattern above (`gpt-5.6-sol`).
  * Google DOES ship a turnkey deep-research agent (`deep-research-preview-04-2026` /
    `-max-preview-04-2026`), correcting this repo's earlier claim that grounded Gemini-Pro was the
    only Gemini equivalent. Interactions API only, `background=True` required.
  * Anthropic ships NO turnkey deep-research endpoint — a deep arm for Claude would be DIY
    (agent loop over `web_search`/`web_fetch`); `claude_shallow` is therefore shallow-only, and
    the deep arm is intentionally OpenAI+Google until that loop is built.

Run mode is LIVE provider search, so a real run needs only the model API keys (no Tavily/SerpAPI).
NB: live web search is NOT contamination-controlled; results are time-indexed snapshots. A frozen
shared index (fair, reproducible run) is future work — see `FrozenIndex`, which deliberately raises.

Search-call budget — READ THIS BEFORE COMPARING ARMS. It is NOT uniformly enforced, and the
asymmetry is large enough to invalidate a naive depth comparison:
  * Anthropic shallow: `max_uses=budget` (6) — enforced.
  * OpenAI SHALLOW: **no cap passed at all**. It performs ~2.9 searches only because
    `_RESEARCH_SYSTEM` asks for "at least TWO" — a prompt suggestion, not a limit.
  * OpenAI DEEP: `max_tool_calls=40`, but measured max was 23 and 0/49 items reached the cap, so
    the dial NEVER BOUND. The realised contrast is 10.8 vs 2.9 searches (3.8x), not 40 vs 6.
  * Gemini DEEP (max agent): ~76 searches median — a 117x contrast against gemini_shallow's 0.65.
So the two "deep" arms are not comparable manipulations to each other, and the OpenAI depth contrast
is far weaker than its configuration suggests. Report realised n_searches, never the configured dial.

A further asymmetry the metric cannot see: the OpenAI deep arm's main purchased resource is
REASONING tokens (~13.8k vs ~2.5k), and `_judge_prompt` receives only `report.text`. The judge never
sees what the extra money bought.

Model IDs are pinned per entrant in `_REGISTRY`. The authors' own entrant (cited prior work) is
one entrant among many; it must not be privileged and all findings must hold with it removed.
"""
from __future__ import annotations
import dataclasses, os, re

_RESEARCH_SYSTEM = (
    "You are a research agent. Before writing, do REAL web search: issue at least TWO "
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


_TRANSIENT = ("rate limit", "rate_limit", "429", "500", "502", "503", "504", "overloaded",
              "timeout", "timed out", "connection", "temporarily",
              # Anthropic's spend-rate cap: "You have reached your specified API usage limits.
              # You will regain access on <date>". Despite the wording this recovers in minutes
              # under load, so back off and retry rather than losing the task.
              "usage limits", "regain access")

def _retry(fn, what: str, attempts: int = 4, base_sleep: float = 5.0):
    """Retry `fn` on TRANSIENT failures only (429 / 5xx / connection), with exponential backoff.

    Deliberately narrow: auth, quota-exhausted and 404-model errors are NOT transient and must fail
    fast so the caller's circuit breaker can disable a dead provider instead of retrying into the
    void. Used ONLY around job *creation* and *polling* — never around a whole deep-research run,
    because re-running a completed background job would pay for it twice."""
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            msg = str(e).lower()
            if i == attempts - 1 or not any(k in msg for k in _TRANSIENT):
                raise
            sleep = base_sleep * (2 ** i)
            print(f"  [retry {i+1}/{attempts-1} {what} in {sleep:.0f}s: {type(e).__name__}: {str(e)[:90]}]")
            time.sleep(sleep)


class Agent:
    model_family: str = "unknown"     # used for leave-one-family-out judging
    model: str = ""
    def __init__(self, index: FrozenIndex | None = None, budget: int = 6, model: str | None = None):
        self.index, self.budget = index, budget
        if model:
            self.model = model
    def run(self, query: str) -> AgentOutput:
        raise NotImplementedError


# Output-token ceiling for the Anthropic entrant. Raised 9000 -> 32000 because 11 of 49 answers in
# the 2026-07-31 run came back COMPLETELY EMPTY (0 chars) with searches having fired: server-side
# web_search results plus reasoning consumed the whole budget before the model emitted a single text
# block, so the response contained tool-use blocks and no prose. Exactly the failure that a
# max_tokens=2000 ceiling caused on the judge side, where thinking ate the budget and returned
# stop_reason=max_tokens with no text. Cost is unaffected for normal answers (billing is on tokens
# actually produced; the median answer is ~3.4k chars); this only removes a ceiling that was
# truncating to nothing.
_ANTHROPIC_MAX_TOKENS = 32000


# ---------------- Anthropic ----------------
class ClaudeShallowResearch(Agent):
    """Claude + server-side web_search tool in one turn -- the SHALLOW arm, not deep research."""
    model_family = "anthropic"
    model = "claude-sonnet-5"
    def run(self, query: str) -> AgentOutput:
        import anthropic
        from crest.harness.keys import call_anthropic
        # Anthropic runs web_search server-side and may need SEVERAL turns. On a long turn it returns
        # stop_reason == "pause_turn" with only partial content, and the caller must resend the
        # assistant message UNCHANGED to resume. Not handling that is why 24 of 50 claude_shallow
        # records in the 2026-07-30 run had a MEDIAN ANSWER OF 134 CHARS and zero citations while
        # n_searches averaged 5.3: the model was mid-work and we recorded the fragment as its final
        # answer, then scored it (N/U/S = 1/1/1) and read the result as low creativity.
        msgs = [{"role": "user", "content": query}]
        blocks, guard, turns_used = [], 0, 1
        while True:
            r = _retry(lambda: call_anthropic(lambda k: anthropic.Anthropic(api_key=k, timeout=600)
                .messages.create(
                    model=self.model, max_tokens=_ANTHROPIC_MAX_TOKENS, system=_RESEARCH_SYSTEM,
                    tools=[{"type": "web_search_20250305", "name": "web_search",
                            "max_uses": self.budget}],
                    messages=msgs,
                ), "entrant"), f"anthropic entrant ({self.model})")
            blocks.extend(r.content)
            if getattr(r, "stop_reason", None) != "pause_turn":
                break
            guard += 1
            turns_used = guard + 1
            if guard >= 8:                      # bounded: never loop forever on a stuck turn
                print(f"  [WARNING: {self.model} still pause_turn after {guard} continuations; "
                      f"returning what it produced so far]")
                break
            msgs = msgs + [{"role": "assistant", "content": r.content}]
        text, cites, n_search = [], [], 0
        for b in blocks:
            if b.type == "text":
                text.append(b.text)
                for c in (getattr(b, "citations", None) or []):
                    u = getattr(c, "url", None)
                    if u:
                        cites.append({"url": u, "title": getattr(c, "title", "") or ""})
            elif b.type == "server_tool_use":
                n_search += 1
        full = "".join(text)
        if not full.strip():
            # never return a silent empty answer: it reads downstream as "the agent had nothing to
            # say" when it actually means the call produced no text block at all.
            print(f"  [WARNING: {self.model} returned NO TEXT after {turns_used} turn(s), "
                  f"{n_search} search(es), stop_reason={getattr(r, 'stop_reason', '?')} -- "
                  f"raise _ANTHROPIC_MAX_TOKENS or inspect the response]")
        return AgentOutput(full, _merge_inline_urls(_dedup(cites), full),
                           n_tokens=r.usage.output_tokens, n_searches=n_search)


# ---------------- OpenAI ----------------
def _parse_openai(r) -> AgentOutput:
    # A truncated answer must not pass silently as a finished one: 5 of 49 shallow records sat at
    # exactly max_output_tokens=9000 with 4 ending mid-sentence, and were scored as complete.
    if getattr(r, "status", None) == "incomplete":
        why = getattr(getattr(r, "incomplete_details", None), "reason", "?")
        print(f"  [WARNING: OpenAI response INCOMPLETE (reason={why}); the answer is truncated "
              f"and will be scored as if finished -- raise max_output_tokens]")
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


class OpenAIShallowResearch(Agent):
    """GPT (chat) + Responses `web_search` tool in one turn -- the SHALLOW arm, not deep research."""
    model_family = "openai"
    model = "gpt-5.6"
    def run(self, query: str) -> AgentOutput:
        from openai import OpenAI
        r = OpenAI(timeout=600).responses.create(
            model=self.model, tools=[{"type": "web_search"}],
            instructions=_RESEARCH_SYSTEM, input=query,
            reasoning={"effort": "low"}, max_output_tokens=9000,
        )
        return _parse_openai(r)


class OpenAIDeepResearchAPI(Agent):
    """OpenAI deep research as the CURRENT PATTERN, not a dedicated SKU.

    The purpose-built `o3-deep-research` / `o4-mini-deep-research` models were deprecated
    2026-04-22 and SHUT DOWN 2026-07-23 (verified: they still appear in `models.list()` but every
    Responses call 404s "Model not found"). OpenAI folded deep research into the general models, so
    the supported configuration is now: a general reasoning model + >=1 data-source tool +
    `background=True`, with depth dialed by `reasoning.effort` and `max_tool_calls`.

    Notes: the tool string is `web_search` (`web_search_preview` is the retired-era name);
    `background=True` is required in practice because these runs take minutes, so we poll to
    completion. Depth (effort / max_tool_calls) is the cost dial -- see
    docs/notes/deep_research_apis.md."""
    model_family = "openai"
    model = "gpt-5.6-sol"
    effort = "high"
    max_tool_calls = 40
    POLL_S, MAX_WAIT_S = 10, 3600

    def run(self, query: str) -> AgentOutput:
        import time
        from openai import OpenAI
        client = OpenAI(timeout=1800)
        r = _retry(lambda: client.responses.create(
            model=self.model, tools=[{"type": "web_search"}],
            instructions=_RESEARCH_SYSTEM, input=query,
            reasoning={"effort": self.effort},
            max_tool_calls=self.max_tool_calls,
            background=True,
        ), f"openai-dr create ({self.model})")
        terminal, waited = {"completed", "failed", "incomplete", "cancelled"}, 0
        while r.status not in terminal:
            if waited >= self.MAX_WAIT_S:
                raise TimeoutError(f"openai deep research still {r.status} after {waited}s (id={r.id})")
            time.sleep(self.POLL_S); waited += self.POLL_S
            r = _retry(lambda: client.responses.retrieve(r.id), f"openai-dr poll ({r.id[:16]})")
        if r.status != "completed":
            raise RuntimeError(f"openai deep research ended status={r.status} (id={r.id})")
        return _parse_openai(r)


class OpenAIDeepResearchMini(OpenAIDeepResearchAPI):
    """Cheaper/faster depth setting of the same pattern (the o4-mini-DR replacement)."""
    model = "gpt-5.6-sol"
    effort = "medium"
    max_tool_calls = 15


# ---------------- Google ----------------
class GeminiShallowResearch(Agent):
    """Gemini + google_search grounding: the lightweight `chat + native search` arm, matching
    claude_shallow / openai_shallow. NB this is NOT Google's deep-research agent -- that is a real,
    separate turnkey API (see GeminiDeepResearchAPI below); keep both as distinct entrants."""
    model_family = "google"
    model = "gemini-3.1-pro-preview"
    def run(self, query: str) -> AgentOutput:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"),   # keep a ref (temporary gets GC'd)
                              http_options=types.HttpOptions(timeout=600_000))  # ms
        r = client.models.generate_content(
            model=self.model, contents=f"{_RESEARCH_SYSTEM}\n\nTASK:\n{query}",
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
        except Exception as e:
            # was a bare `except: pass`. With no log, a zero-search record could mean the model
            # chose not to search OR the grounding-metadata parse blew up -- indistinguishable, and
            # 39 of 49 records in the 2026-07-31 run were zero-search.
            print(f"  [WARNING: {self.model} grounding-metadata parse failed "
                  f"({type(e).__name__}: {str(e)[:80]}); n_searches/citations may be undercounted]")
        text = r.text or ""
        if n_search == 0:
            print(f"  [NOTE: {self.model} reported ZERO web searches; any citations below are "
                  f"scraped from the answer text and are NOT verified grounding chunks]")
        n_tok = getattr(getattr(r, "usage_metadata", None), "candidates_token_count", 0) or 0
        return AgentOutput(text, _merge_inline_urls(_dedup(cites), text),
                           n_tokens=n_tok, n_searches=n_search or len(cites))


class GeminiDeepResearchAPI(Agent):
    """Google's TURNKEY Deep Research agent (Interactions API) -- a managed multi-step research
    loop in one call, the closest thing any vendor ships to a 'deep research API'.

    Agents: `deep-research-preview-04-2026` (fast/standard) and `deep-research-max-preview-04-2026`
    (max: ~160 searches, up to ~30 min). Deep Research is available ONLY on the Interactions API
    and REQUIRES background=True, so we poll to completion. Citations arrive as `url_citation`
    annotations on `model_output` steps (char offsets, title often absent -- read defensively).

    This corrects an earlier assumption in this repo that Gemini had no deep-research API and that
    grounded Gemini-Pro was its equivalent; both now run as separate entrants."""
    model_family = "google"
    model = "deep-research-preview-04-2026"
    # 5400s not 3900s: one task in the full50 run timed out at 3900s while still
    # 'in_progress'. Google documents a 60-min hard cap on the RUN, so queue delay stacks on
    # top of it; 90min absorbs that without masking a genuine runaway.
    POLL_S, MAX_WAIT_S = 15, 5400

    def run(self, query: str) -> AgentOutput:
        import time
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"),
                              http_options=types.HttpOptions(timeout=600_000))   # ms
        it = _retry(lambda: client.interactions.create(
            agent=self.model,
            # The deep-research agents REJECT `system_instruction` (400: "not supported for the
            # deep-research-* agent"), even though the field exists on interactions.create for
            # ordinary models. So the shared prompt is prepended to the input instead. Safe: the
            # parser reads `model_output` steps only, so the echoed prompt in the `user_input`
            # step never reaches the grounding check or the judges.
            input=f"{_RESEARCH_SYSTEM}\n\nTASK:\n{query}",
            agent_config={"type": "deep-research", "thinking_summaries": "auto",
                          "collaborative_planning": False},   # never block on a plan approval
            background=True,                                  # REQUIRED for agents
        ), f"gemini-dr create ({self.model})")
        iid, waited = it.id, 0
        while True:
            it = _retry(lambda: client.interactions.get(iid),  # positional id; no .name on Interaction
                        f"gemini-dr poll ({iid[:16]})")
            st = str(getattr(it, "status", "")).lower()
            if "complet" in st:
                break
            if any(k in st for k in ("fail", "cancel", "budget_exceeded", "error")):
                raise RuntimeError(f"gemini deep research {st}")
            if waited >= self.MAX_WAIT_S:
                raise TimeoutError(f"gemini deep research still {st} after {waited}s")
            time.sleep(self.POLL_S); waited += self.POLL_S
        return _parse_gemini_interaction(it)


def _parse_gemini_interaction(it) -> AgentOutput:
    """Pull report text, citations and counters off a completed Interaction.

    Verified against a live completed interaction (google-genai 2.2.0, 2026-07-30):
      * there is NO `output_text` convenience accessor on this SDK version (it is None) -- the
        report must be assembled from steps;
      * `steps` contains the ECHOED PROMPT as a `user_input` step alongside `model_output`, so we
        take text from `model_output` ONLY. Reading every text item would prepend our own system
        prompt to the answer and corrupt both the grounding check and the judges' view;
      * counters live on `it.usage`: `total_output_tokens` and `grounding_tool_count`
        ([GroundingToolCount(count=N, type='google_search')]), not on `usage_metadata`.
    Still defensive: this surface is preview and field presence varies."""
    parts, cites = [], []
    for step in (getattr(it, "steps", None) or []):
        if str(getattr(step, "type", "")) != "model_output":
            continue                                    # skip user_input echo & tool-trace steps
        for item in (getattr(step, "content", None) or []):
            if str(getattr(item, "type", "")) == "text":
                parts.append(getattr(item, "text", "") or "")
            for ann in (getattr(item, "annotations", None) or []):
                if str(getattr(ann, "type", "")) == "url_citation" and getattr(ann, "url", None):
                    cites.append({"url": ann.url, "title": getattr(ann, "title", "") or ""})
    text = "".join(parts) or (getattr(it, "output_text", None) or "")
    u = getattr(it, "usage", None) or getattr(it, "usage_metadata", None)
    n_tok = (getattr(u, "total_output_tokens", None) or getattr(u, "output_tokens", None)
             or getattr(u, "candidates_token_count", None) or 0)
    n_search = sum(getattr(g, "count", 0) or 0
                   for g in (getattr(u, "grounding_tool_count", None) or []))
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
    "claude_shallow":           (ClaudeShallowResearch, "claude-sonnet-5"),
    "openai_shallow":           (OpenAIShallowResearch, "gpt-5.6"),
    "gemini_shallow":           (GeminiShallowResearch, "gemini-3.1-pro-preview"),
    # deep-research agents (background/managed multi-step loops; minutes + $$ per call)
    # NB o3-deep-research / o4-mini-deep-research were SHUT DOWN 2026-07-23 -- OpenAI deep research
    # is now the general-model pattern below, dialed by reasoning effort + max_tool_calls.
    "openai_deepresearch":      (OpenAIDeepResearchAPI, "gpt-5.6-sol"),          # effort=high, 40 calls
    "openai_deepresearch_mini": (OpenAIDeepResearchMini, "gpt-5.6-sol"),         # effort=medium, 15 calls
    "gemini_deepresearch":      (GeminiDeepResearchAPI, "deep-research-preview-04-2026"),
    "gemini_deepresearch_max":  (GeminiDeepResearchAPI, "deep-research-max-preview-04-2026"),
    # future entrants
    "oss_dr":                   (OpenSourceAgent, ""),
    "author_entrant":           (AuthorEntrant, ""),
}

def build_agent(name: str, index: FrozenIndex | None = None, budget: int = 6, model: str | None = None) -> Agent:
    if name not in _REGISTRY:
        raise ValueError(f"unknown agent '{name}'; known: {sorted(_REGISTRY)}")
    cls, default_model = _REGISTRY[name]
    return cls(index=index, budget=budget, model=model or default_model or None)
