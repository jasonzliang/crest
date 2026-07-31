"""Creativity scoring: a factual-grounding check + a leave-one-family-out judge panel.

Two pieces:
  1. FACTUAL-GROUNDING CHECK (`grounding_gate`): "is the answer backed by real cited
     sources, or is it confident fabrication?" An answer must PASS this before it can earn
     any creativity score -- otherwise a model could win New/Surprising just by making things
     up (novelty-by-hallucination). "Grounding" = the standard term for whether generated
     claims are attributable to their cited sources (ALCE, AIS, FActScore). Fail => UNSCORED
     (the harness writes creativity=null, never a fake 0).
  2. JUDGE PANEL (`JudgePanel`): scores New/Useful/Surprising 1-10, blind to agent identity
     (the prompt carries no agent name) and optionally LEAVE-ONE-FAMILY-OUT. Per-axis scores are
     returned separately (a profile, not one number). There is NO answer-order randomization:
     scoring is single-answer, not pairwise, so there is no order to randomize.
"""
from __future__ import annotations
import dataclasses, json, re, statistics, sys, yaml
from concurrent.futures import ThreadPoolExecutor


@dataclasses.dataclass
class GroundingResult:
    passed: bool
    empty_answer: bool = False      # LITERALLY nothing: the agent returned "". An ADAPTER problem,
                                    # not fabrication (a GROUNDING problem); conflating the two
                                    # mislabelled a 22% Anthropic adapter failure as Claude being
                                    # ungrounded.
    too_short: bool = False         # non-empty but below _MIN_SUBSTANTIVE_CHARS. SEPARATE from
                                    # empty_answer: same adapter root cause, but this threshold is a
                                    # judgement call and emptiness is not.
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
# Sentence terminators, Latin AND CJK. The count is the numerator of the grounding verdict, so the CJK
# set is load-bearing: without it a 2,542-char Chinese answer holding 40 dated statistics split into ONE
# sentence, counting 1 where the same content in English counts 40 (ratio 1.0, passes). Still
# English-CALIBRATED regardless: the cue regex above matches English keywords, so a non-English answer
# is under-counted.
_SENT_SPLIT_RE = re.compile(r"[.!?\n\u3002\uff01\uff1f]+")   # fullwidth ; EXCLUDED as a clause
                            # separator: including it over-split CJK relative to Latin, where ASCII
                            # ";" is likewise not a terminator.

# A pure-invention answer may still drop a couple of incidental facts; tolerate this many
# UNCITED verifiable-factual-claim sentences before demanding a source. Beyond it, zero
# citations reads as unsupported fabrication and fails the gate.
_MAX_UNCITED_CLAIMS = 2

# Ceiling on dated/statistical claims per citation before an answer reads as unsupported. Calibrated
# on run 040653Z: 250 substantive answers run median 0.8, p95 3.8, max 8.0 claims per citation, while
# a synthetic answer of 60 fabricated dated statistics behind one URL sits at 60.0.
_MAX_CLAIMS_PER_CITATION = 20

# Minimum length for an answer to be scoreable at all. Was 40 chars, which admitted 10 records of
# 90-349 chars -- bare research-plan preambles produced by a truncating adapter -- that judges then
# scored 1/1/1. They are the SAME adapter failure as the 0-char answers, just above the old floor,
# and excluding them moved one entrant's composite 3.08 -> 3.71 while no other agent moved. A
# deep-research answer that is shorter than this is a failure to answer, not a bad answer.
_MIN_SUBSTANTIVE_CHARS = 1000


def _count_factual_claims(text: str) -> int:
    """Lightweight proxy for the number of *verifiable external factual claims* an answer makes --
    sentences referencing a dated fact, statistic, named source, or study. A pure-invention creative
    artifact scores near 0, a report piling up external facts scores high. A cue counter, not a
    fact extractor."""
    return sum(1 for s in _SENT_SPLIT_RE.split(text) if _FACT_CUE_RE.search(s))


def grounding_gate(report) -> GroundingResult:
    """Factual-grounding check (see module docstring). PILOT implementation: a lightweight
    proxy that targets an answer's FACTUAL SCAFFOLDING, not its creative proposal. We
    estimate how many verifiable external factual claims the answer makes (dated facts,
    statistics, named sources) and require that they be backed:

      * an empty answer FAILS as `empty_answer`, a sub-1000-char one as `too_short`;
      * an answer making at most _MAX_UNCITED_CLAIMS verifiable external factual claims PASSES even
        with zero citations -- a pure-invention creative artifact is not punished for lacking sources
        (the old `>= min_citations` floor wrongly zeroed the invent tasks C1/C5);
      * otherwise it PASSES only if its dated/statistical claims outnumber its citations by no more
        than _MAX_CLAIMS_PER_CITATION. A RATIO deliberately: OR'ing "has >=1 citation" against the
        uncited-claim tolerance let one unverified URL carry 60 fabricated dated statistics, so >=1
        citation is NOT a free pass. Still only a proxy -- the ratio says nothing about whether a
        citation SUPPORTS the claim beside it, so a fabricator who also emits plausible URLs beats it.

    Honest-proxy limits: it counts citation-worthy *cues*, not atomic facts. The PRODUCTION version
    swaps this for a per-claim FACT verifier (decompose -> verify each against its cited source).

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
    # Do NOT collapse to `n >= 1 or n_factual <= _MAX_UNCITED_CLAIMS`. That OR consults the
    # uncited-claim test only at ZERO citations, so a 3,109-char probe of 60 fabricated dated
    # statistics failed at 0 citations and PASSED at 1, that URL never checked for reachability,
    # relevance or support. Re-measured 2026-07-31 over all 250 shipped records: the collapsed form
    # flips 0 of them, but the ratio clause is the DECIDING clause for 234/250 (those with
    # n_factual > _MAX_UNCITED_CLAIMS) and still rejects the probe the collapsed form admits -- so
    # "has never fired" is not "unreachable", and dropping it restores a measured defect.
    # A per-citation ALLOWANCE (_MAX_UNCITED_CLAIMS x n) is worse than either: it newly gates 32 of
    # the 250, incl. a 38k-char report with 26 citations and 140 dated claims. Long sourced reports
    # restate each source many times, so a linear budget punishes thoroughness; a ratio does not.
    # `n >= 1 and` rather than `max(1, n)`: the guard is the CONDITION, not arithmetic. max(1, n)
    # divides a zero-citation answer by 1, allowing 20 dated claims instead of 2 -- a 10x loosening
    # of the one branch the 250-record calibration cannot test (0 of 250 have zero citations).
    passed = substantive and (n_factual <= _MAX_UNCITED_CLAIMS
                             or (n >= 1 and n_factual / n <= _MAX_CLAIMS_PER_CITATION))
    return GroundingResult(passed=passed, citation_density=round(density, 3), n_citations=n,
                           empty_answer=not text.strip(),
                           too_short=bool(text.strip()) and not substantive)


# ---------------- judge panel ----------------

# The judge must see the WHOLE answer. A previous 12,000-char cap silently discarded a mean 18k chars
# from 66% of answers (the judge saw a median 43% of a long answer, but 100% of the never-truncated
# known_answers); hard rules demanding terminal content ("state every oxidation state", "supply a
# worked example") are satisfied precisely in the discarded tail, so the cap manufactured violations,
# and a violation caps Useful <=3. A runaway guard only: the longest answer observed is 57,282 chars,
# so it should never fire -- and warns loudly rather than truncating in silence if it does.
_JUDGE_MAX_ANSWER_CHARS = 400_000

# Cap on prior-art entries shown to the judge. Raised 40 -> 200: the audit found 21+ missing prior-art
# families for C5_materials_chemistry_25 (33 entries) and ~60 for C5_arts_humanities_49 (21) -- adding
# them crosses 40, and a silent cut would have kept the instruction header (entry 0 in 20 items) while
# discarding real prior art. A runaway guard only; warns rather than truncating in silence.
_MAX_KNOWN_ANSWERS = 200

# keys `ablate` accepts; validated in _judge_prompt (ablate_fields.py imports this to check its ARMS)
_ABLATABLE = frozenset({"known_answers", "restore_expert_baseline"})


def render_prompt_for_fingerprint() -> str:
    """The judge prompt rendered over fixed inputs, for the CI staleness gate in analysis/ci_check.sh.

    Deliberately NOT called at import and NOT auto-hashed into the version. Three auto-invalidating
    designs were each wrong in a different way: a SOURCE hash missed _MAX_KNOWN_ANSWERS and
    _JUDGE_MAX_ANSWER_CHARS (read inside _judge_prompt, declared outside it) and fired on comment-only
    edits; a RENDERED hash taken on an over-limit dummy was blind to the _fit_answer early return that
    250/250 real answers take, while firing on ceilings that never bind -- 750 needless paid judge
    calls; and either one computed at import made six modules unimportable whenever _judge_prompt
    raised. The only property needed is "if the prompt changed, do not mix records", which a
    build-time comparison gets with no import-time risk.

    Two dummies: one shaped like the real distribution (short answer, few known answers, populated
    lists), covering the branches every run takes; one over both ceilings, covering truncation."""
    import contextlib, io
    real = {"id": "FP", "query": "q" * 64, "category": "C1", "domain": "engineering",
            "known_answers": [f"ka{i}" for i in range(5)], "hard_rules": ["r1", "r2"],
            "expert_baseline": "b" * 256}
    over = {**real, "known_answers": [f"ka{i}" for i in range(_MAX_KNOWN_ANSWERS + 5)],
            "hard_rules": [], "expert_baseline": ""}
    parts = []
    with contextlib.redirect_stderr(io.StringIO()):   # the over-limit dummy trips truncation warnings
        for ch, ans in ((real, "a" * 500), (over, "a" * (_JUDGE_MAX_ANSWER_CHARS + 10))):
            for ab in (frozenset(), frozenset({"restore_expert_baseline"}),
                       frozenset({"known_answers"})):
                parts.append(_judge_prompt(ch, ans, ablate=ab))
    # Shape PINNED as (openai, anthropic-sorted, google, max_tokens): the hash must stay stable across
    # a pure refactor of these constants, since a spurious bump makes rejudge treat all 250 records as
    # an upgrade and re-buys the panel. Append new settings; never reorder.
    parts.append(repr((_JUDGE_REASONING["openai"], sorted(_JUDGE_REASONING["anthropic"].items()),
                       _JUDGE_REASONING["google"], _JUDGE_MAX_TOKENS)))
    return "\x00".join(parts)


def prompt_hash() -> str:
    import hashlib
    return hashlib.sha256(render_prompt_for_fingerprint().encode()).hexdigest()[:8]


# Bump BOTH of these whenever _judge_prompt's WORDING or the reasoning settings change. Stamped into
# every record so a scored run can be matched to the rubric text that produced it (the entrant side has
# had `adapter_fp` since gen/2; the judge side had nothing, so a prompt edit silently made old and new
# scores incomparable). ci_check.sh recomputes prompt_hash() and fails the build on disagreement, so
# the bump cannot be forgotten -- a build-time check, not an import-time computation.
#   v1  the original rubric.
#   v2  2026-07-31. Three changes to the Surprising instruction, all of which move scores:
#       (a) dropped "EXPLORATORY -- reported but not a primary endpoint" (it IS a primary axis);
#       (b) dropped "an ablation showed it moved this axis by -0.02" and "correlates with novelty at
#           r~0.95" -- telling a rater that two axes it is about to score are redundant, and then
#           citing the resulting correlation as evidence about those axes, is circular;
#       (c) the instruction now matches whether an expert baseline is actually supplied, so the
#           restore_expert_baseline arm can reproduce the pre-withdrawal condition it measures.
# Run 2026-07-31T040653Z predates the stamp: all 250 records and its manifest store
# judge_prompt_version=None, so ablate_fields already aborts on it and rejudge already treats every
# record as an upgrade. Its numbers must NOT be mixed with v2; re-judge from stored transcripts
# (harness/rejudge.py) before quoting any New-vs-Surprising correlation -- the figure (b) contaminated.
JUDGE_PROMPT_VERSION = "v2"
JUDGE_PROMPT_VERSION_HASH = "e2ce119c"


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
    unknown = set(ablate) - _ABLATABLE      # fail before doing any work; used to be silently ignored
    if unknown:
        raise ValueError(f"unknown ablate key(s) {sorted(unknown)}; valid: {sorted(_ABLATABLE)}")
    _ka = ch.get("known_answers") or []
    if len(_ka) > _MAX_KNOWN_ANSWERS:          # loud, not silent: see _MAX_KNOWN_ANSWERS
        print(f"  [WARNING: {ch.get('id')} has {len(_ka)} known_answers; only the first "
              f"{_MAX_KNOWN_ANSWERS} reach the judge -- the novelty baseline is being truncated]",
              file=sys.stderr)
    ka = "\n".join(f"- {a}" for a in _ka[:_MAX_KNOWN_ANSWERS]) or "(none provided)"
    if "known_answers" in ablate:
        ka = "(ABLATED: no novelty baseline supplied for this run)"
    # expert_baseline is NOT sent to the judge by default (ablation: withholding it moved Surprising by
    # -0.02, and in 7 items it carried the author's enumeration of the intended surprises).
    # "restore_expert_baseline" reproduces the OLD behaviour; it used to be a `_ = ablate` no-op, which
    # silently made two of ablate_fields.py's four arms duplicates of the other two while the tool
    # reported them as independent measurements.
    # The Surprising instruction must MATCH whether a baseline is actually supplied: an unconditional
    # "a baseline was supplied here previously" told the restore arm's judge the baseline was absent
    # while it was reading it, so that arm could not reproduce the condition it exists to measure.
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
    """Harden JSON extraction from a judge reply: reject empty text, strip ```json fences, then return
    the first balanced {...} object (brace-matched, string-aware) that parses AND carries the three
    axes. Raises on empty / unparseable / axis-less input so the caller can retry."""
    if not s or not s.strip():
        raise ValueError("empty judge response")
    t = s.strip()
    if t.startswith("```"):                        # strip ```json ... ``` (or bare ```) fences
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    # Scan EVERY balanced {...} and return the first that parses AND carries the three axes.
    # NO bare `json.loads(t)` fast path: it returned any parseable object unchecked, so a wrapped
    # verdict {"scores": {...}} yielded the OUTER dict and KeyError'd in _call_judge 4 paid calls and
    # 28s of backoff later -- while the SAME payload behind one word of prose parsed first try, the
    # fast path having failed and this scan unwrapped it. And NOT committing to the first brace: a
    # reply opening "<thinking>hmm {maybe}" raised JSONDecodeError, one opening with a scratch object
    # returned it axis-less. All three failures track per-model wrapping/verbosity habits, so the
    # panel thinned by JUDGE IDENTITY rather than at random. The scan subsumes the bare case
    # (start=0, balanced, has the axes).
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
                    if isinstance(obj, dict) and all(k in obj for k in ("new", "useful", "surprising")):
                        return obj
                    break
    # No "best effort" fallback: returning a merely-PARSEABLE dict only moved the failure to
    # _call_judge's float(d["new"]) one frame later, as a bare KeyError with the same four retries.
    raise ValueError("no JSON object with new/useful/surprising found in judge response")


# Token budget for a judge call. Must cover the model's THINKING plus the JSON verdict; a budget
# that only covers the verdict yields an empty response on long prompts (see _judge_completion).
_JUDGE_MAX_TOKENS = 8000

# Reasoning budget, pinned as low as each vendor ALLOWS -- one dict keyed by family, because these are
# three DIFFERENT vendor knobs, not three copies of one setting, which is exactly why the values are NOT
# interchangeable. Unpinned they ran at three levels: anthropic omitted `thinking`, so claude-sonnet-5
# used ADAPTIVE thinking at default effort "high"; openai was pinned "low"; google had no token cap and
# no thinking config at all. judge_config.live.yaml calls judge severity the dominant measured confound
# and leans on the full panel as a CONSTANT instrument -- but with one judge deliberating hard, one
# minimally and one unconfigured, part of the reported spread was a configuration artefact rather than a
# property of the models. Scoring a JSON verdict against an explicit rubric needs no deliberation.
#
# LITERAL PARITY IS NOT ACHIEVABLE, and "harmonising" these cost a judge. gemini-2.5-pro CANNOT disable
# thinking (accepted range 128-32768, or -1 for dynamic). Setting 0, to match Anthropic's "disabled",
# passes google-genai's client -- which does no range validation -- then 400s SERVER-SIDE on every call,
# near-invisibly: _call_judge burns 4 retries and 28s of backoff per record, the panel drops to 2
# judges, n_judges=2 >= min_judges=2 so the record is still labelled "scored", and
# "invalid_argument"/"400" are absent from run_crest's _TERMINAL_ERR so the circuit breaker never fires.
# The run completes reporting 250/250 scored, having computed every score WITHOUT judge_google -- the
# documented severity outlier, the only Google-family judge, and the same_family covariate that replaced
# LOFO. So 128 is Pro's FLOOR, not "off"; the three arms are APPROXIMATELY comparable, no more.
# NB changing any value changes scores: each is folded into the prompt fingerprint above, so a run
# scored under the old settings is not silently compared with a new one.
_JUDGE_REASONING = {"anthropic": {"type": "disabled"},  # thinking=       accepted on claude-sonnet-5
                    "openai": "low",                    # reasoning.effort
                    "google": 128}                      # thinking_budget; 0 rejected server-side


def _judge_completion(family: str, model: str, prompt: str) -> str:
    """One raw judge call; returns the response text (possibly empty)."""
    if family == "anthropic":
        import anthropic
        from crest.harness.keys import call_anthropic
        # Pooled: judge_anthropic is the hottest path in a run (LOFO excludes it only for the
        # Anthropic entrant), so it trips this account's spend-rate cap first -- spread across every
        # funded key before losing the judge.
        # max_tokens must cover BOTH the thinking block and the JSON verdict: on a long judge prompt
        # (known_answers runs to 33 entries, ~15k chars) a 2000-token budget was fully consumed by
        # thinking, returning stop_reason='max_tokens' with NO text block -- an "empty judge response"
        # that silently dropped this judge on the LONGEST prompts, so the panel thinned preferentially
        # on the most complex items.
        r = call_anthropic(lambda k: anthropic.Anthropic(api_key=k, timeout=300).messages.create(
            model=model, max_tokens=_JUDGE_MAX_TOKENS, thinking=_JUDGE_REASONING["anthropic"],
            messages=[{"role": "user", "content": prompt}]), "judge")
        txt = "".join(b.text for b in r.content if b.type == "text")
        # DISTINGUISH exhaustion from an outage; raising the budget alone left the two failures
        # byte-identical. A budget-exhausted reply is a thinking block with an empty text block, so
        # `txt` is "" and _parse_json raises the same "empty judge response" a real outage produces --
        # and the prompt is built once, so all four retries re-sent identical bytes, burning 4 paid
        # calls and 28s on a deterministic failure before dropping the judge.
        if not txt and getattr(r, "stop_reason", None) == "max_tokens":
            raise RuntimeError(
                f"judge {model} spent the whole max_tokens={_JUDGE_MAX_TOKENS} budget without "
                f"emitting text (prompt {len(prompt)} chars). This is NOT an outage and retrying is "
                f"futile: raise _JUDGE_MAX_TOKENS or shorten the prompt.")
        return txt
    elif family in ("openai", "open_weight"):
        from openai import OpenAI
        r = OpenAI(timeout=300).responses.create(
            model=model, input=prompt, reasoning={"effort": _JUDGE_REASONING["openai"]},
            max_output_tokens=_JUDGE_MAX_TOKENS)
        if not (r.output_text or "") and getattr(r, "status", None) == "incomplete":
            raise RuntimeError(f"judge {model} returned incomplete (likely max_output_tokens="
                               f"{_JUDGE_MAX_TOKENS} spent on reasoning); retrying is futile.")
        return r.output_text or ""
    elif family == "google":
        import os
        from google import genai
        from google.genai import types as gt
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"),   # keep a ref (temporary gets GC'd)
                              http_options=gt.HttpOptions(timeout=300_000))  # ms
        r = client.models.generate_content(
            model=model, contents=prompt,
            config=gt.GenerateContentConfig(max_output_tokens=_JUDGE_MAX_TOKENS,
                                            thinking_config=gt.ThinkingConfig(
                                                thinking_budget=_JUDGE_REASONING["google"])))
        # Same exhaustion check as the other two arms, and this arm needs it MOST: it is the one model
        # whose thinking cannot be turned off. GenerateContentResponse.text is Optional and None for a
        # thoughts-only candidate, so without this a budget-exhausted reply is indistinguishable from
        # an outage -- retried 4x, judge dropped.
        if not (r.text or ""):
            # FIRST candidate, to match r.text: keeping the LAST one turned candidates
            # [MAX_TOKENS, STOP] into STOP, so the check never fired and the caller burned 4 retries.
            cands = getattr(r, "candidates", None) or []
            fr = getattr(cands[0], "finish_reason", None) if cands else None
            if fr is not None and "MAX_TOKENS" in str(fr).upper():
                raise RuntimeError(
                    f"judge {model} hit max_output_tokens={_JUDGE_MAX_TOKENS} with thinking_budget="
                    f"{_JUDGE_REASONING['google']} and emitted no text; retrying is futile.")
        return r.text or ""
    else:
        raise ValueError(f"unknown judge family {family}")


def _call_judge(family: str, model: str, prompt: str) -> dict:
    """Call a judge and parse its JSON verdict. Up to 4 attempts when the response text is empty,
    unparseable, or out of range (known intermittent failures that otherwise drop the judge); only
    raises -- letting JudgePanel drop the judge -- once all four are exhausted."""
    import time
    last_err: Exception = RuntimeError("judge produced no result")
    for attempt in range(4):
        if attempt:
            time.sleep(4.0 * (2 ** (attempt - 1)))   # 4s, 8s, 16s: ride out a provider spend-rate cap
        try:
            d = _parse_json(_judge_completion(family, model, prompt))
            # bool is a subclass of int, so float(True) == 1.0 would sail through the range
            # check below and be written as a legitimate score of 1.
            raw = {ax: d[ax] for ax in ("new", "useful", "surprising")}
            if any(isinstance(x, bool) for x in raw.values()):
                raise ValueError(f"judge {model} returned boolean score(s) {raw}; expected 1-10")
            v = {ax: float(x) for ax, x in raw.items()}
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
        # LOFO (leave-one-family-out) drops the judge sharing the entrant's family -- defensible as a
        # self-preference control, but with only 3 vendors it CONFOUNDS judge identity with entrant
        # family (each entrant is scored by a different pair, so cross-entrant comparisons carry a
        # judge-severity confound), drops n 3->2, and degenerates median-of-2 to the mean.
        # Nor is it uniformly warranted: in the source paper's own bias table the same-family effect
        # was judge-specific and SIGN-INCONSISTENT (Gemini +2.47/+0.78/+0.67, GPT +0.35/+0.02/+0.47,
        # Claude +0.30/-1.78/-1.57), so for the OpenAI judge LOFO spends a whole judge to remove a
        # ~0.0-0.5 effect, and for the Anthropic judge it removes a judge that was HARSHER on its own
        # family, pushing Anthropic entrants up.
        # lofo=False scores everyone with the full panel, keeping the instrument constant and letting
        # same-family enter as a covariate (analysis/stats.py runs MixedLM), so the bias is MEASURED
        # per run rather than assumed; LOFO stays available post-hoc by filtering same-family rows.
        self.lofo = lofo
        self.ablate = frozenset(ablate)   # judge-side fields withheld (ablation arms)
        # A single surviving judge is NOT a panel: median-of-one, no cross-family diversity, and the
        # self-preference defence LOFO exists to provide is gone. Records below this many judges are
        # kept but flagged 'judge_degraded' so they can be excluded from headline numbers instead of
        # silently diluting them (fires when a vendor is down or unfunded).
        # Validate HERE, in __init__, because from_config runs in main() before any money moves: a
        # present-but-EMPTY `min_judges:` in the YAML yields None (.get's default fires only on an
        # ABSENT key), and the resulting `scores.n_judges < None` TypeError lands in run_crest.py's
        # status branch, DOWNSTREAM of its "JUDGE PANEL ERROR (agent was fine)" guard. So every task
        # was logged as an agent_error and discarded after generation AND all judge calls were paid:
        # 250 fully-paid tasks, 0 records, 250 rows blaming healthy entrants -- and the message is not
        # auth/quota, so the circuit breaker never fired and the run burned to completion. bool is
        # excluded explicitly: it is an int subclass, so `True` would otherwise pass as min_judges=1.
        if isinstance(min_judges, bool) or not isinstance(min_judges, int) or min_judges < 1:
            raise ValueError(f"min_judges must be a positive int, got {min_judges!r} "
                             f"(a blank `min_judges:` in the YAML parses as None)")
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

