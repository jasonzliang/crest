"""Find items whose NOVELTY GATE IS INVERTED: a hard rule demands a mechanism absent from the
prior-art set, while offering as its worked example something that prior-art set already contains.

This is the check that did not exist when C4_engineering_45 shipped. That item's rule (d) said "add
>=1 decision variable ... absent from every listed framework (e.g., a software-lock/parts-pairing
penalty as a hard multiplier)" while its own known_answers[1] was iFixit, whose published rubric
already applies exactly that penalty globally. An agent following the item's own hint reproduced
published prior art and was scored as NOVEL, and the expert_baseline asserted the opposite, so a
judge would confirm the false positive rather than catch it. Nothing mechanical looked for that.

KNOWN LIMIT, MEASURED, STATED UP FRONT: run against the pre-fix science set this check does NOT
flag C4_engineering_45 -- the very item it was written for. That is not a tuning problem, it is
structural. The item's prior-art entry is the bare NAME "iFixit Repairability Score"; the fact that
iFixit's rubric applies a global parts-pairing penalty lives in iFixit's published methodology, not
anywhere in the item text. No lexical method can see it. Detecting that defect class requires reading
the cited frameworks, which is what the live-web audits (doc/misc/audit_live_*.md) did by hand.

So this catches a NARROWER subclass: a novelty rule whose example reuses wording that appears in the
item's own prior-art text. Useful, cheap, and NOT a substitute for a semantic audit. A clean result
here is not evidence the gates are sound, and the docstring says so because a green check that
implies more coverage than it has is how C4_engineering_45 shipped in the first place.

It flags for review and does not fail a build: judging whether a rule's example is truly implemented
by a listed framework needs domain knowledge. Worth running before paying for a generation, because
scores on an inverted item are uninterpretable.

Usage:
  python -m crest.analysis.audit_novelty_gate --challenges crest/question/crest_aiml_challenges.jsonl
  python -m crest.analysis.audit_novelty_gate            # defaults to the science set
"""
from __future__ import annotations
import argparse, json, re, sys, collections

# Rules that demand novelty. Only these can be INVERTED -- a reproducibility or scoping rule cannot.
_NOVELTY_RE = re.compile(
    r"\bNEW MECHANISM\b|\bnovel\b|\bnot in\b|\babsent from\b|\bbeyond\b|\bgo beyond\b"
    r"|\bnot already\b|\bunlike\b|\bno[nt]-obvious\b", re.I)
# Where worked examples live.
_EG_RE = re.compile(r"\((?:e\.?g\.?|for example|such as|for instance)[:,]?\s*(.+?)\)\s*$|"
                    r"(?:e\.?g\.?|for example|such as|for instance)[:,]?\s*(.+?)(?:;|\.|$)", re.I)

_STOP = set("""a an the of for to in on and or with as by from at is are be that this those these
it its their his her not no non any all each per via using use used than then so such other another
into over under more most less least new novel absent beyond already if when where which who whom
one two three add adds added least exactly least both either neither also only just same different
e g eg ie i.e. e.g. example examples instance stage rule variable variables aggregation output
decision""".split())


def _terms(text: str, n_min=2, n_max=4):
    """Content n-grams, stopwords stripped. n>=2 so single generic words cannot match."""
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9\-/']*", (text or "").lower())
             if w not in _STOP and len(w) > 2]
    out = set()
    for n in range(n_min, n_max + 1):
        for i in range(len(words) - n + 1):
            out.add(" ".join(words[i:i + n]))
    return out


def _named(text: str):
    """Proper-noun-ish tokens: named frameworks, standards, acronyms. High-signal."""
    return {m for m in re.findall(r"\b(?:[A-Z][A-Za-z0-9]{2,}(?:\s+[A-Z][A-Za-z0-9]{2,})*"
                                  r"|[A-Z]{2,}[0-9]*|EN\s?\d+|ISO\s?\d+)\b", text or "")
            if m.lower() not in _STOP and len(m) > 2}


def audit(path: str) -> list:
    items = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    findings = []
    for it in items:
        ka = it.get("known_answers") or []
        # skip the leading "Dated as of ..." preamble: a header, not prior art
        ka_body = [k for k in ka if not re.match(r"\s*dated as of", str(k), re.I)]
        ka_text = " ; ".join(str(k) for k in ka_body)
        ka_terms = _terms(ka_text)
        ka_named = {n.lower() for n in _named(ka_text)}

        for ri, rule in enumerate(it.get("hard_rules") or []):
            rule = str(rule)
            if not _NOVELTY_RE.search(rule):
                continue
            # pull the worked example(s) out of the novelty rule
            egs = [g for m in _EG_RE.finditer(rule) for g in m.groups() if g]
            for eg in egs:
                # POLARITY. An example the rule DISQUALIFIES is correct design, not a defect -- it is
                # the item telling the agent "this does not count". Both flags this check produced on
                # its first run were of exactly that kind ("is scored as NOT new", "does NOT count as
                # a new modality"), i.e. 100% false positives. Only a rule PRESCRIBING an example
                # that its own prior art already contains is inverted.
                if re.search(r"\b(?:does\s+)?NOT\b[^.]{0,40}$|\bnot\s+(?:new|count|qualify|novel)\b"
                             r"|\bis\s+scored\s+as\s+NOT\b|\bdisqualif|\bdo\s+NOT\s+qualify\b",
                             eg, re.I):
                    continue
                shared = sorted(_terms(eg) & ka_terms)
                shared_named = sorted({n.lower() for n in _named(eg)} & ka_named)
                if not shared and not shared_named:
                    continue
                # which prior-art entries actually contain the overlap
                hits = []
                for k in ka_body:
                    kt = _terms(str(k))
                    kn = {n.lower() for n in _named(str(k))}
                    ov = sorted(set(shared) & kt) + sorted(set(shared_named) & kn)
                    if ov:
                        hits.append((str(k)[:90], ov[:4]))
                if hits:
                    findings.append({
                        "id": it.get("id"), "category": it.get("category"),
                        "rule_index": ri, "rule": rule[:150], "example": eg.strip()[:150],
                        "strength": "STRONG" if shared_named else "weak",
                        "overlap": (shared_named or shared)[:5], "prior_art_hits": hits[:3],
                    })
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--challenges", default="crest/question/crest_challenges.jsonl")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    f = audit(a.challenges)
    n_items = sum(1 for l in open(a.challenges, encoding="utf-8") if l.strip())
    strong = [x for x in f if x["strength"] == "STRONG"]
    print(f"== inverted novelty-gate audit: {a.challenges}")
    print(f"   {n_items} items, {len(f)} flag(s) ({len(strong)} STRONG) across "
          f"{len({x['id'] for x in f})} item(s)")
    if not f:
        print("   OK no novelty rule offers an example that overlaps its own prior-art set.")
        print("   NB heuristic: absence of a lexical overlap is NOT proof the gate is sound.")
        return 0
    print()
    for x in sorted(f, key=lambda y: (y["strength"] != "STRONG", y["id"])):
        print(f"   [{x['strength']}] {x['id']} ({x['category']}) rule #{x['rule_index']}")
        print(f"       rule:    {x['rule']}")
        print(f"       example: {x['example']}")
        print(f"       overlap: {x['overlap']}")
        for src, ov in x["prior_art_hits"]:
            print(f"       prior art already contains it -> {src!r} via {ov}")
        print()
    print("   Each flag needs a HUMAN read: lexical overlap is suggestive, not proof. A STRONG flag")
    print("   (shared named framework/standard) is the C4_engineering_45 signature.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
