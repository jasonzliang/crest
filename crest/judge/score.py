"""Creativity scoring: a factual-grounding check + a leave-one-family-out judge panel.

Two pieces:
  1. FACTUAL-GROUNDING CHECK (`grounding_gate`): "is the answer backed by real cited
     sources, or is it confident fabrication?" An answer must PASS this before it can earn
     any creativity score -- otherwise a model could win New/Surprising just by making things
     up (novelty-by-hallucination). "Grounding" = the standard term for whether generated
     claims are attributable to their cited sources (ALCE, AIS, FActScore). Fail => creativity 0.
  2. JUDGE PANEL (`JudgePanel`): scores New/Useful/Surprising 1-10, blind to agent identity,
     order-randomized, and LEAVE-ONE-FAMILY-OUT -- a model never judges an entrant of its own
     model family, which defuses self-preference bias (O7). Per-axis scores are returned
     separately (a profile, not one number).
"""
from __future__ import annotations
import dataclasses, json, re, sys, yaml
from concurrent.futures import ThreadPoolExecutor


@dataclasses.dataclass
class GroundingResult:
    passed: bool
    citation_density: float = 0.0   # citations per ~600 chars (a proxy, NOT FACT precision); see docstring
    n_citations: int = 0            # count of source URLs found (structured + inline)

@dataclasses.dataclass
class CreativityScore:
    new: float; useful: float; surprising: float
    creative_all_three: bool
    per_judge: dict
    n_judges: int


# Cues that mark a *verifiable external factual claim* (something that ought to carry a
# source): dated facts, statistics, currency/scaled quantities, named studies/sources.
# Deliberately narrow -- it must NOT fire on incidental numbers in a creative proposal
# ("3 ideas", "step 1"), which is what wrongly zeroed the invent-style tasks (C1/C5).
_FACT_CUE_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"                                       # calendar years
    r"|\d+\s*%|\bpercent\b"                                     # percentages
    r"|\$\s?\d"                                                 # currency amounts
    r"|\b\d[\d,]*\s*(?:thousand|million|billion|trillion)\b"    # scaled quantities
    r"|\b(?:according to|cited|study|studies|research(?:ers)?|reported|reports|survey|"
    r"data|statistics?|published|journal|et al|founded|established|revenue|dataset|"
    r"benchmark|patent(?:ed)?|acquired|census|GDP|documented|measured|recorded)\b",
    re.IGNORECASE,
)
_SENT_SPLIT_RE = re.compile(r"[.!?\n]+")

# A pure-invention answer may still drop a couple of incidental facts; tolerate this many
# UNCITED verifiable-factual-claim sentences before demanding a source. Beyond it, zero
# citations reads as unsupported fabrication and fails the gate.
_MAX_UNCITED_CLAIMS = 2


def _count_factual_claims(text: str) -> int:
    """Lightweight proxy for the number of *verifiable external factual claims* an answer
    makes -- sentences referencing a dated fact, statistic, named source, or study. A
    pure-invention creative artifact scores near 0; a report piling up external facts
    scores high. A cue counter, not a fact extractor."""
    return sum(1 for s in _SENT_SPLIT_RE.split(text) if _FACT_CUE_RE.search(s))


def grounding_gate(report, challenge: dict) -> GroundingResult:
    """Factual-grounding check (see module docstring). PILOT implementation: a lightweight
    proxy that targets an answer's FACTUAL SCAFFOLDING, not its creative proposal. We
    estimate how many verifiable external factual claims the answer makes (dated facts,
    statistics, named sources) and require that they be backed:

      * an empty / near-empty answer FAILS (no substantive content);
      * an answer carrying >=1 real source URL PASSES (its scaffolding is attributable);
      * a pure-invention answer that makes few verifiable external factual claims PASSES
        even with zero citations -- a creative artifact is not punished for lacking
        sources (the old `>= min_citations` floor wrongly zeroed the invent tasks C1/C5);
      * an answer that piles up many external factual claims with no citation FAILS, so
        obvious fabrication cannot earn creativity by construction.

    Honest-proxy limits: this counts citation-worthy *cues*, not atomic facts, and does not
    verify that a citation actually supports a given claim. The PRODUCTION version swaps this
    for a per-claim FACT verifier (decompose -> verify each against its cited source).
    Fail => the answer scores 0 creativity."""
    cites = getattr(report, "citations", []) or []
    n = len(cites)
    text = getattr(report, "text", "") or ""
    # crude density: citations per ~600 chars of answer, saturating at 1.0
    density = min(1.0, n / max(1.0, len(text) / 600.0)) if text else 0.0
    n_factual = _count_factual_claims(text)
    substantive = len(text.strip()) >= 40
    grounded = n >= 1                                   # >=1 real source URL backs the scaffolding
    pure_invention = n_factual <= _MAX_UNCITED_CLAIMS   # few external facts to cite
    passed = substantive and (grounded or pure_invention)
    return GroundingResult(passed=passed, citation_density=round(density, 3), n_citations=n)


# ---------------- judge panel ----------------

def _judge_prompt(ch: dict, report_text: str) -> str:
    ka = "\n".join(f"- {a}" for a in (ch.get("known_answers") or [])[:40]) or "(none provided)"
    hr = "\n".join(f"- {r}" for r in (ch.get("hard_rules") or [])) or "(none)"
    return f"""You are an expert judge scoring the CREATIVITY of a deep-research answer. Score three axes 1-10:
- New: novelty vs the DATED KNOWN ANSWERS below. Restating anything already known => 1-3; recombination with minor extension => 4-6; a genuinely new synthesis/connection not in the list => 7-10.
- Useful: is the idea sound, workable, and appropriate? Every HARD RULE must be satisfied; a violated hard rule caps Useful at <=3. Judge on merit, not on how many citations there are.
- Surprising: expectation-violation vs the EXPERT BASELINE, CONDITIONED ON CORRECTNESS. Merely reproducing the expected expert answer => low; a correct-but-non-obvious result that violates a well-calibrated prior => high. Do NOT reward nonsense.

Return ONLY a JSON object, no prose:
{{"new": <int 1-10>, "useful": <int 1-10>, "surprising": <int 1-10>, "hard_rules_violated": [<strings>], "rationale": "<=40 words"}}

TASK CATEGORY: {ch.get('category')} (isolated axis: {ch.get('axis_isolated')})
TASK:
{ch.get('query')}

DATED KNOWN ANSWERS (novelty baseline):
{ka}

HARD RULES (usefulness gate):
{hr}

EXPERT BASELINE (surprise baseline):
{ch.get('expert_baseline')}

ANSWER TO SCORE (author identity withheld):
{report_text[:12000]}
"""


def _parse_json(s: str) -> dict:
    """Harden JSON extraction from a judge reply: reject empty text, strip ```json fences,
    then pull out the first balanced {...} object (brace-matched, string-aware) before
    parsing. Raises on empty / unparseable input so the caller can retry."""
    if not s or not s.strip():
        raise ValueError("empty judge response")
    t = s.strip()
    if t.startswith("```"):                        # strip ```json ... ``` (or bare ```) fences
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")                            # first balanced {...}, ignoring braces in strings
    if start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(t[start:i + 1])
    raise ValueError("no JSON object found in judge response")


def _judge_completion(family: str, model: str, prompt: str) -> str:
    """One raw judge call; returns the response text (possibly empty)."""
    if family == "anthropic":
        import anthropic
        r = anthropic.Anthropic(timeout=300).messages.create(
            model=model, max_tokens=2000, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text")
    elif family in ("openai", "open_weight"):
        from openai import OpenAI
        r = OpenAI(timeout=300).responses.create(
            model=model, input=prompt, reasoning={"effort": "low"}, max_output_tokens=2500)
        return r.output_text or ""
    elif family == "google":
        import os
        from google import genai
        from google.genai import types as gt
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"),   # keep a ref (temporary gets GC'd)
                              http_options=gt.HttpOptions(timeout=300_000))  # ms
        r = client.models.generate_content(model=model, contents=prompt)
        return r.text or ""
    else:
        raise ValueError(f"unknown judge family {family}")


def _call_judge(family: str, model: str, prompt: str) -> dict:
    """Call a judge and parse its JSON verdict. Retries up to 2 attempts when the response
    text is empty or JSON parsing fails (a known intermittent failure that otherwise drops
    the judge); only raises -- letting JudgePanel drop the judge -- after both are exhausted."""
    last_err: Exception = RuntimeError("judge produced no result")
    for _ in range(2):
        try:
            d = _parse_json(_judge_completion(family, model, prompt))
            return {"new": float(d["new"]), "useful": float(d["useful"]),
                    "surprising": float(d["surprising"]),
                    "hard_rules_violated": d.get("hard_rules_violated", []),
                    "rationale": d.get("rationale", "")}
        except Exception as e:
            last_err = e
    raise last_err


class JudgePanel:
    def __init__(self, judges: list, threshold_all_three: float = 6.0):
        self.judges = judges                      # [{"id","model","family"}]
        self.threshold = threshold_all_three

    @classmethod
    def from_config(cls, path: str) -> "JudgePanel":
        cfg = yaml.safe_load(open(path))
        return cls(cfg["judges"], cfg.get("threshold_all_three", 6.0))

    def _active(self, exclude_family: str | None) -> list:
        """Leave-one-family-out: drop any judge sharing the entrant's model family."""
        active = [j for j in self.judges if j["family"] != exclude_family]
        if not active:
            raise ValueError(f"LOFO removed all judges for family={exclude_family}; add another vendor")
        return active

    def _judge_one(self, judge: dict, challenge: dict, report) -> dict:
        return _call_judge(judge["family"], judge["model"], _judge_prompt(challenge, getattr(report, "text", "")))

    def score(self, challenge, report, exclude_family=None) -> "CreativityScore | None":
        """Score with the active (leave-one-family-out) panel. Judges are independent, so they run
        CONCURRENTLY; a failing judge is dropped so the panel stays robust. Author identity is
        withheld by construction (the prompt carries no agent name)."""
        active = self._active(exclude_family)
        per = {}
        with ThreadPoolExecutor(max_workers=max(1, len(active))) as ex:
            futs = {ex.submit(self._judge_one, j, challenge, report): j for j in active}
            for fut in futs:
                j = futs[fut]
                try:
                    per[j["id"]] = fut.result()
                except Exception as e:             # keep the panel robust; drop a failing judge
                    print(f"  [judge {j['id']} failed: {type(e).__name__}: {str(e)[:120]}]", file=sys.stderr)
        if not per:
            return None   # NO judge succeeded (e.g. judges out of quota) -> UNSCORED, not a real 0.
                          # Caller must record this as a judge error, not fold a fake 0 into results.
        agg = {ax: _median([v[ax] for v in per.values()]) for ax in ("new", "useful", "surprising")}
        all_three = all(agg[ax] >= self.threshold for ax in ("new", "useful", "surprising"))
        return CreativityScore(agg["new"], agg["useful"], agg["surprising"], all_three, per, len(per))


def _median(xs: list[float]) -> float:
    xs = sorted(xs); n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
