"""Creativity scoring: a factual-grounding check + a leave-one-family-out judge panel.

Two pieces:
  1. FACTUAL-GROUNDING CHECK (`grounding_gate`): "is the answer backed by real cited
     sources, or is it confident fabrication?" An answer must PASS this before it can earn
     any creativity score -- otherwise a model could win New/Surprising just by making things
     up (novelty-by-hallucination). "Grounding" = the standard term for whether generated
     claims are attributable to their cited sources (ALCE, AIS, FActScore). Fail => creativity 0.
  2. JUDGE PANEL (`JudgePanel`): scores New/Useful/Surprising 1-10, blind to agent identity
     (the prompt carries no agent name) and optionally LEAVE-ONE-FAMILY-OUT. Per-axis scores are
     returned separately (a profile, not one number).
     NB there is NO answer-order randomization: scoring is single-answer, not pairwise, so there is
     no order to randomize. Earlier docs and judge_config.yaml claimed this control; the claim was
     vacuous and has been removed rather than left as an unimplemented assertion.
"""
from __future__ import annotations
import dataclasses, json, re, statistics, sys, yaml
from concurrent.futures import ThreadPoolExecutor


@dataclasses.dataclass
class GroundingResult:
    passed: bool
    empty_answer: bool = False      # LITERALLY nothing: the agent returned "". Distinguishes an
                                    # ADAPTER problem from "the agent fabricated" (a GROUNDING
                                    # problem) -- conflating them mislabelled a 22% Anthropic
                                    # adapter failure as Claude being ungrounded.
    too_short: bool = False         # non-empty but below _MIN_SUBSTANTIVE_CHARS. Kept SEPARATE from
                                    # empty_answer, which briefly meant "under 1000 chars" -- so the
                                    # console printed "empty answer" for 470-char preambles and
                                    # n_empty_answer counted them. Same adapter root cause, but the
                                    # threshold is a judgement call and the emptiness is not.
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

# Minimum length for an answer to be scoreable at all. Was 40 chars, which admitted 10 records of
# 90-349 chars -- bare research-plan preambles produced by a truncating adapter -- that judges then
# scored 1/1/1. They are the SAME adapter failure as the 0-char answers, just above the old floor,
# and excluding them moved one entrant's composite 3.08 -> 3.71 while no other agent moved. A
# deep-research answer that is shorter than this is a failure to answer, not a bad answer.
_MIN_SUBSTANTIVE_CHARS = 1000


def _count_factual_claims(text: str) -> int:
    """Lightweight proxy for the number of *verifiable external factual claims* an answer
    makes -- sentences referencing a dated fact, statistic, named source, or study. A
    pure-invention creative artifact scores near 0; a report piling up external facts
    scores high. A cue counter, not a fact extractor."""
    return sum(1 for s in _SENT_SPLIT_RE.split(text) if _FACT_CUE_RE.search(s))


def grounding_gate(report) -> GroundingResult:
    """Factual-grounding check (see module docstring). PILOT implementation: a lightweight
    proxy that targets an answer's FACTUAL SCAFFOLDING, not its creative proposal. We
    estimate how many verifiable external factual claims the answer makes (dated facts,
    statistics, named sources) and require that they be backed:

      * an empty answer FAILS as `empty_answer`, a sub-1000-char one as `too_short`;
      * an answer carrying >=1 real source URL PASSES (its scaffolding is attributable);
      * a pure-invention answer that makes few verifiable external factual claims PASSES
        even with zero citations -- a creative artifact is not punished for lacking
        sources (the old `>= min_citations` floor wrongly zeroed the invent tasks C1/C5);
      * an answer that piles up many external factual claims with no citation FAILS, so
        obvious fabrication cannot earn creativity by construction.

    Honest-proxy limits: this counts citation-worthy *cues*, not atomic facts, and does not
    verify that a citation actually supports a given claim. The PRODUCTION version swaps this
    for a per-claim FACT verifier (decompose -> verify each against its cited source).

    MEASURED CONTRIBUTION (2026-07-31, 245 records, measured when the floor was 40 chars): the
    anti-fabrication clause fired ZERO times. 234 answers passed; all 11 rejections were EMPTY
    strings, not unsourced prose. Raising the floor to 1000 adds a `too_short` class that would have
    caught 10 more, all from the same truncating adapter and all now fixed. Of 10 substantive
    zero-citation answers, none exceeded the uncited-claim tolerance. Every entrant except
    claude_shallow had no uncited records at all (median citations 6-52). So on THIS field of
    entrants -- all using provider-native web search -- the gate contributes nothing beyond an
    empty-answer check, and the paper must not claim it as a working control. It is retained as a
    cheap guard that would fire against an untooled or confabulating entrant, and because removing
    a safety property because it has not yet triggered is a bad trade."""
    cites = getattr(report, "citations", []) or []
    n = len(cites)
    text = getattr(report, "text", "") or ""
    # crude density: citations per ~600 chars of answer, saturating at 1.0
    density = min(1.0, n / max(1.0, len(text) / 600.0)) if text else 0.0
    n_factual = _count_factual_claims(text)
    substantive = len(text.strip()) >= _MIN_SUBSTANTIVE_CHARS
    grounded = n >= 1                                   # >=1 real source URL backs the scaffolding
    pure_invention = n_factual <= _MAX_UNCITED_CLAIMS   # few external facts to cite
    passed = substantive and (grounded or pure_invention)
    return GroundingResult(passed=passed, citation_density=round(density, 3), n_citations=n,
                           empty_answer=not text.strip(),
                           too_short=bool(text.strip()) and not substantive)


# ---------------- judge panel ----------------

# The judge must see the WHOLE answer. A previous 12,000-char cap silently discarded a mean 18k
# chars from 66% of answers -- the judge saw a median 43% of a long answer while seeing 100% of the
# (never-truncated) known_answers. Hard rules demanding terminal content ("state every oxidation
# state", "supply a worked example") are satisfied precisely in the discarded tail, so the cap
# manufactured violations, and violations cap Useful <=3. This ceiling is a runaway guard only: the
# longest answer observed is 57,282 chars, so it should never fire -- and if it does, it says so
# loudly rather than truncating in silence.
_JUDGE_MAX_ANSWER_CHARS = 400_000

# Cap on prior-art entries shown to the judge. Raised from 40 to 200 because the audit identified
# 21+ missing prior-art families for C5_materials_chemistry_25 (33 entries) and ~60 for
# C5_arts_humanities_49 (21 entries) -- adding them crosses 40, and a silent cut would have kept the
# instruction header (entry 0 in 20 items) while discarding real prior art. This is now a runaway
# guard only, and it warns rather than truncating in silence.
_MAX_KNOWN_ANSWERS = 200

# keys `ablate` accepts; an unrecognised key used to be silently ignored
_ABLATABLE = frozenset({"known_answers", "restore_expert_baseline"})

# Bump whenever _judge_prompt's WORDING changes. Stamped into every record so a scored run can be
# matched to the rubric text that produced it -- the entrant side has had `adapter_fp` since gen/2,
# but the judge side had nothing, so a prompt edit silently made old and new scores incomparable.
#   v1  the original rubric.
#   v2  2026-07-31. Three changes to the Surprising instruction, all of which move scores:
#       (a) dropped "EXPLORATORY -- reported but not a primary endpoint" (it IS a primary axis);
#       (b) dropped "an ablation showed it moved this axis by -0.02" and "correlates with novelty at
#           r~0.95" -- telling a rater that two axes it is about to score are redundant, and then
#           citing the resulting correlation as evidence about those axes, is circular;
#       (c) the instruction now matches whether an expert baseline is actually supplied, so the
#           restore_expert_baseline arm can reproduce the pre-withdrawal condition it measures.
# Run 2026-07-31T040653Z was scored under v1. Its numbers are NOT comparable to v2 scores and must
# not be mixed with them; re-judge from stored transcripts (harness/rejudge.py) before quoting any
# New-vs-Surprising correlation, which is the figure (b) contaminated.
JUDGE_PROMPT_VERSION = "v2"


def _fit_answer(text: str) -> str:
    text = text or ""
    if len(text) <= _JUDGE_MAX_ANSWER_CHARS:
        return text
    print(f"  [WARNING: answer of {len(text)} chars exceeds the judge ceiling "
          f"({_JUDGE_MAX_ANSWER_CHARS}); scoring a truncated answer]", file=sys.stderr)
    return text[:_JUDGE_MAX_ANSWER_CHARS]


def _judge_prompt(ch: dict, report_text: str, ablate=frozenset()) -> str:
    """`ablate` omits judge-side fields so their causal effect on scores can be MEASURED rather
    than assumed. Neither `known_answers` nor `expert_baseline` had ever been ablated, so there was
    no evidence either moved a score -- and the only dose-response measured for known_answers ran
    the wrong way (more prior-art entries -> HIGHER novelty awards)."""
    _ka = ch.get("known_answers") or []
    if len(_ka) > _MAX_KNOWN_ANSWERS:          # loud, not silent: see _MAX_KNOWN_ANSWERS
        print(f"  [WARNING: {ch.get('id')} has {len(_ka)} known_answers; only the first "
              f"{_MAX_KNOWN_ANSWERS} reach the judge -- the novelty baseline is being truncated]",
              file=sys.stderr)
    ka = "\n".join(f"- {a}" for a in _ka[:_MAX_KNOWN_ANSWERS]) or "(none provided)"
    if "known_answers" in ablate:
        ka = "(ABLATED: no novelty baseline supplied for this run)"
    # expert_baseline is NOT sent to the judge by default (ablation: withholding it moved Surprising
    # by -0.02, and in 7 items it carried the author's enumeration of the intended surprises). Set
    # "restore_expert_baseline" in `ablate` to reproduce the OLD behaviour -- previously this was a
    # `_ = ablate` no-op, which silently made two of ablate_fields.py's four arms duplicates of the
    # other two while the tool reported them as independent measurements.
    unknown = set(ablate) - _ABLATABLE
    if unknown:
        raise ValueError(f"unknown ablate key(s) {sorted(unknown)}; valid: {sorted(_ABLATABLE)}")
    # The Surprising instruction must MATCH whether a baseline is actually supplied. It previously
    # said "a baseline was supplied here previously" unconditionally, so under the restore arm the
    # judge was told the baseline was absent while reading it -- meaning that arm could not
    # reproduce the pre-withdrawal condition it exists to measure.
    eb_block = ""
    if "restore_expert_baseline" in ablate:
        eb_block = f"\n\nEXPERT BASELINE (surprise baseline):\n{ch.get('expert_baseline')}"
        surprising_line = ("- Surprising: non-obviousness conditioned on correctness, judged against "
                           "the EXPERT BASELINE below -- how far the answer departs from what that "
                           "baseline says a domain expert would predict. Do NOT reward nonsense.")
    else:
        surprising_line = ("- Surprising: non-obviousness conditioned on correctness, judged against "
                           "your own sense of what a domain expert would predict. Do NOT reward "
                           "nonsense.")
    hr = "\n".join(f"- {r}" for r in (ch.get("hard_rules") or [])) or "(none)"
    return f"""You are an expert judge scoring the CREATIVITY of a deep-research answer. Score three axes 1-10:
- New: novelty of the answer relative to the DATED KNOWN ANSWERS below. Scored ONLY against that list, NOT against the web or your own background knowledge: content absent from the set counts as non-redundant even if you believe you have seen it, and content present in the set does not, even if it looks fresh. Restating an entry => 1-3; recombining entries with minor extension => 4-6; a synthesis or connection not reducible to the entries => 7-10.
- Useful: is the idea sound, workable, and appropriate? Every HARD RULE must be satisfied; a violated hard rule caps Useful at <=3. Judge on merit, not on how many citations there are.
{surprising_line}

Return ONLY a JSON object, no prose:
{{"new": <int 1-10>, "useful": <int 1-10>, "surprising": <int 1-10>, "hard_rules_violated": [<strings>], "rationale": "<=40 words"}}

TASK:
{ch.get('query')}

DATED KNOWN ANSWERS (novelty baseline; judge ONLY against this list, not the web):
{ka}

HARD RULES (usefulness gate):
{hr}

{eb_block}
ANSWER TO SCORE (author identity withheld):
{_fit_answer(report_text)}
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
    # Scan EVERY balanced {...} and return the first that parses AND carries the three axes.
    # Committing to the first one lost real verdicts: a reply opening with "<thinking>hmm {maybe}"
    # raised JSONDecodeError, and one opening with a scratch object returned that object, whose
    # missing "new" key surfaced four attempts and 28s of backoff later as a dropped judge. Both
    # fire on VERBOSE replies, so the panel thinned non-randomly -- the same bias shape as the
    # max_tokens bug this module already documents.
    best = None
    for start in (i for i, c in enumerate(t) if c == "{"):
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
                    try:
                        obj = json.loads(t[start:i + 1])
                    except Exception:
                        break
                    if isinstance(obj, dict):
                        if all(k in obj for k in ("new", "useful", "surprising")):
                            return obj
                        if best is None:
                            best = obj      # fall back only if nothing better turns up
                    break
    if best is not None:
        return best
    raise ValueError("no JSON object with new/useful/surprising found in judge response")


# Token budget for a judge call. Must cover the model's THINKING plus the JSON verdict; a budget
# that only covers the verdict yields an empty response on long prompts (see _judge_completion).
_JUDGE_MAX_TOKENS = 8000


def _judge_completion(family: str, model: str, prompt: str) -> str:
    """One raw judge call; returns the response text (possibly empty)."""
    if family == "anthropic":
        import anthropic
        from crest.harness.keys import call_anthropic
        # Pooled: judge_anthropic is the hottest path in a run (LOFO excludes it only for the
        # Anthropic entrant), so it trips this account's spend-rate cap first. Spread across every
        # funded key before giving up and losing the judge.
        # max_tokens must leave room for BOTH the thinking block and the JSON verdict. These are
        # reasoning models: on a long judge prompt (known_answers can run to 33 entries, ~15k chars)
        # a 2000-token budget was fully consumed by thinking, returning stop_reason='max_tokens'
        # with NO text block -- an "empty judge response" that silently dropped this judge. Because
        # it failed on the LONGEST prompts, the panel thinned preferentially on the most complex
        # items, biasing which records kept a full panel.
        r = call_anthropic(lambda k: anthropic.Anthropic(api_key=k, timeout=300).messages.create(
            model=model, max_tokens=_JUDGE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}]), "judge")
        return "".join(b.text for b in r.content if b.type == "text")
    elif family in ("openai", "open_weight"):
        from openai import OpenAI
        r = OpenAI(timeout=300).responses.create(
            model=model, input=prompt, reasoning={"effort": "low"},
            max_output_tokens=_JUDGE_MAX_TOKENS)      # same reasoning-budget trap as above
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
    import time
    last_err: Exception = RuntimeError("judge produced no result")
    for attempt in range(4):
        if attempt:
            time.sleep(4.0 * (2 ** (attempt - 1)))   # 4s, 8s, 16s: ride out a provider spend-rate cap
        try:
            d = _parse_json(_judge_completion(family, model, prompt))
            v = {ax: float(d[ax]) for ax in ("new", "useful", "surprising")}
            # Range-check so the existing retry fires. An off-scale reply (a judge answering on
            # 0-100, or emitting -3) was written through verbatim with scoring_status "scored", and
            # with min_judges=2 the median of two IS the mean, so one bad reply moves the record.
            bad = {ax: s for ax, s in v.items() if not 1.0 <= s <= 10.0}
            if bad:
                raise ValueError(f"judge {model} returned out-of-range score(s) {bad}; expected 1-10")
            return {**v, "hard_rules_violated": d.get("hard_rules_violated", []),
                    "rationale": d.get("rationale", "")}
        except Exception as e:
            last_err = e
    raise last_err


class JudgePanel:
    def __init__(self, judges: list, threshold_all_three: float = 6.0, min_judges: int = 2,
                 lofo: bool = True, ablate=frozenset()):
        self.judges = judges                      # [{"id","model","family"}]
        self.threshold = threshold_all_three
        # LOFO (leave-one-family-out) drops the judge sharing the entrant's family. Defensible as a
        # self-preference control, but with only 3 vendors it has real costs: judge identity becomes
        # perfectly CONFOUNDED with entrant family (each entrant is scored by a different pair, so
        # cross-entrant comparisons carry a judge-severity confound), n drops 3->2, and median-of-2
        # degenerates to the mean (no outlier robustness).
        #
        # It is also not uniformly warranted. In the source paper's own bias table the same-family
        # effect was judge-specific and SIGN-INCONSISTENT: Gemini +2.47/+0.78/+0.67, GPT
        # +0.35/+0.02/+0.47, Claude +0.30/-1.78/-1.57. For the OpenAI judge LOFO spends a whole
        # judge to remove a ~0.0-0.5 effect; for the Anthropic judge it removes a judge that was
        # HARSHER on its own family, which pushes Anthropic entrants up.
        #
        # lofo=False scores every entrant with the full panel, keeping the instrument constant and
        # letting same-family enter the model as a covariate (analysis/stats.py runs MixedLM), so the
        # bias is MEASURED per run rather than assumed. LOFO then remains available post-hoc as a
        # robustness check by filtering same-family rows.
        self.lofo = lofo
        self.ablate = frozenset(ablate)   # judge-side fields withheld (ablation arms)
        # A single surviving judge is NOT a panel: median-of-one, no cross-family diversity, and
        # the self-preference defence that LOFO exists to provide is gone. Scores below this many
        # judges are recorded but flagged 'judge_degraded' so they can be excluded from headline
        # numbers instead of silently diluting them (this fires when a vendor is down or unfunded).
        self.min_judges = min_judges

    @classmethod
    def from_config(cls, path: str) -> "JudgePanel":
        cfg = yaml.safe_load(open(path))
        return cls(cfg["judges"], cfg.get("threshold_all_three", 6.0), cfg.get("min_judges", 2),
                   cfg.get("leave_one_family_out", True))

    @property
    def protocol(self) -> str:
        return "leave-one-family-out" if self.lofo else "full-panel (same-family as covariate)"

    def _active(self, exclude_family: str | None) -> list:
        """Judges that will score this entrant. Under LOFO, drop any sharing its model family;
        otherwise use the full panel and let the analysis adjust for same-family scoring."""
        if not self.lofo:
            return list(self.judges)
        active = [j for j in self.judges if j["family"] != exclude_family]
        if not active:
            raise ValueError(f"LOFO removed all judges for family={exclude_family}; add another vendor")
        return active

    def _judge_one(self, judge: dict, challenge: dict, report) -> dict:
        return _call_judge(judge["family"], judge["model"],
                           _judge_prompt(challenge, getattr(report, "text", ""), self.ablate))

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
        agg = {ax: statistics.median([v[ax] for v in per.values()])
               for ax in ("new", "useful", "surprising")}
        all_three = all(agg[ax] >= self.threshold for ax in ("new", "useful", "surprising"))
        return CreativityScore(agg["new"], agg["useful"], agg["surprising"], all_three, per, len(per))


