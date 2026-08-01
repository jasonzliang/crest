#!/usr/bin/env python3
"""Item self-consistency validator — catches an item contradicting itself, mechanically.

Motivation: four verified cases where an item's own reference answer or its own rules defeat the
item. These are not citation slips; they make the item unsatisfiable or invert its novelty gate, and
a judge consulting the baseline would CONFIRM the error rather than catch it.

  1. C1_materials_chemistry_01 -- R4 requires mu in [0.40, 0.90]; the item's own expert_baseline
     reports mu~0.39-0.42, and the rule says it was widened "to admit sulfide perovskites" which all
     fall below 0.40. The rule excludes the class it was written to admit.
  2. C1_materials_chemistry_01 -- R6 permits "a chalcogenide (S, Se)"; R9 "deliberately bans ... Se".
  3. C3_economistics_business_14 -- lists writhe among "invariants"; writhe is not an ambient-isotopy
     invariant, and the baseline uses it, breaching the item's own no-misstated-maths rule.
  4. C4_engineering_45 -- a hard rule offers "a software-lock/parts-pairing penalty" as its example
     of a genuinely NEW mechanism, but iFixit (in the item's own known_answers) already applies a
     global parts-pairing penalty. Novelty is awarded for reproducing published prior art.

WHAT THIS CAN AND CANNOT DO. Full "does the baseline satisfy every rule" is a semantic judgement and
is NOT mechanically decidable. This checks TWO DECIDABLE classes; they cover cases 1 and 2 above.
Cases 3 and 4 are tracked BY HAND in question/quarantine.yaml's watch_list. A phrase matcher for
case 4 shipped and was deleted rather than re-tuned: "the mechanism offered as NEW is already in
known_answers" is indistinguishable, without semantics, from C4_materials_chemistry_43 legitimately
offering "a supply-criticality-weighted atom economy" (novel in the weighting; its head noun is
listed prior art), and the ratio cap that rejected 43 could never fire on 45 -- 4 regex hits on the
live corpus, offered examples 13-21 words, best phrase/offer ratio 0.25 against a 0.6 cap, so zero of
19 candidate phrases survived. The semantic residue needs an LLM pass (`--llm` is deliberately left
unimplemented rather than faked) or human review. Treat a clean run as "no mechanical contradiction
found", never as "the item is consistent".

Usage:
    python -m crest.analysis.validate_items                       # exits 1 if any violation
    python -m crest.analysis.validate_items --challenges <path> --quiet
"""
from __future__ import annotations
import argparse, json, re, sys, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# quantity symbol -> how it may be written in prose
_RANGE_RE = re.compile(r"\b(mu|tau|t|SEA|Isp|band ?gap|gap)\b[^.\[\]]{0,60}?\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]", re.I)
# \b on every alternative: without it `bans?` matched inside "band gap", "bank", "DrugBank" and
# "urban" -- 12 of 79 ban-matches in the live corpus (15%), each opening a bogus 240-char ban clause.
# No live false positive only because exactly one item has a non-empty permitted set. Suffixes are
# enumerated rather than written `bans?` so that "banned"/"banning" are not silently dropped, and
# forbid/forbidden (5 hits in the science corpus's hard_rules) and disallowed (6) were missing from
# the vocabulary entirely, so class 2's coverage was thinner than this module implied.
_BAN_RE = re.compile(r"\bban(?:s|ned|ning)?\b|\bexclude[ds]?\b|\bexcluding\b|\bdisqualif\w+"
                     r"|\bforbid(?:s|den|ding)?\b|\bdisallow(?:s|ed|ing)?\b"
                     r"|\bmust NOT\b|\bmay not\b", re.I)
_PERMIT_RE = re.compile(r"may be|is allowed|are allowed|permitted|X may be", re.I)
# element-ish / short capitalised tokens worth colliding on
_TOK_RE = re.compile(r"\b(?:[A-Z][a-z]?)\b")
_STOP = {"A", "I", "R", "S", "The", "It", "In", "On", "Of", "To", "And", "Or", "No", "If", "As", "At",
         "Be", "By", "Do", "So", "Up", "We", "An", "Is", "Ce"}
# formula placeholders, not real species: ABX3 / A2BX6 notation collides spuriously
_PLACEHOLDER = {"X", "A", "B", "M", "L", "E", "D", "N", "Y", "Z", "T", "P", "Q"}


def _standalone_symbols(clause: str) -> set:
    """Element symbols appearing as FREE-STANDING list items, not inside a compound.

    A bare-symbol collision produced a false positive on a red CI gate: an item banned
    "single-crystal Si" while permitting "a-Si:H", which is not a contradiction but the whole point
    of a no-crystallinity counterfactual. Requiring the symbol to be delimited by whitespace or
    list punctuation excludes hyphenated/colonated compounds (a-Si:H, LiCoO2-style contexts) while
    still catching genuine list membership like "(S, Se)" vs "bans ... Te, Se, Bi"."""
    out = set()
    for m in _TOK_RE.finditer(clause):
        t = m.group(0)
        if t in _STOP or t in _PLACEHOLDER or len(t) > 2:
            continue
        before = clause[m.start() - 1] if m.start() else " "
        after = clause[m.end()] if m.end() < len(clause) else " "
        if before in "-:/" or after in "-:/":     # part of a compound term, not a listed element
            continue
        out.add(t)
    return out


def _num_near(text: str, sym: str) -> list[float]:
    """Numbers stated for `sym` in prose, e.g. 'mu~0.39-0.42' -> [0.39, 0.42]."""
    out = []
    for m in re.finditer(rf"\b{re.escape(sym)}\s*[~=:]?\s*([0-9.]+)(?:\s*[-–]\s*([0-9.]+))?", text, re.I):
        for g in m.groups():
            if g:
                try:
                    out.append(float(g))
                except ValueError:
                    pass
    return out


def check_item(it: dict) -> list[dict]:
    v = []
    rules = it.get("hard_rules") or []
    eb = it.get("expert_baseline") or ""

    # --- class 1: a rule states a numeric range; the item's own baseline reports a value outside it
    for rule in rules:
        for m in _RANGE_RE.finditer(rule):
            sym, lo, hi = m.group(1), float(m.group(2)), float(m.group(3))
            for val in _num_near(eb, sym):
                if not (lo <= val <= hi):
                    v.append({"kind": "baseline_violates_own_numeric_rule", "severity": "BLOCKING",
                              "detail": f"rule requires {sym} in [{lo}, {hi}] but expert_baseline "
                                        f"reports {sym}={val}", "rule": rule.split()[0]})

    # --- class 2: one rule permits a token another rule EXPLICITLY BANS.
    # Tightened after a first pass produced 8 false positives out of 10 hits: colliding every short
    # capitalised token in any ban-matching rule caught elements mentioned incidentally (Cl, Br, Fe)
    # and formula placeholders (X, A, B). Now the ban side is read only from the ban CLAUSE -- the
    # text after the ban keyword -- and placeholders are excluded.
    permitted, banned = set(), set()
    for rule in rules:
        if _PERMIT_RE.search(rule):
            for m in _PERMIT_RE.finditer(rule):
                permitted |= _standalone_symbols(rule[m.end():m.end() + 200])
        for m in _BAN_RE.finditer(rule):
            banned |= _standalone_symbols(rule[m.end():m.end() + 240])   # enumerated ban list only
    for t in sorted(permitted & banned):
        v.append({"kind": "rules_permit_and_ban_same_token", "severity": "BLOCKING",
                  "detail": f"one hard rule permits '{t}' while another bans it"})
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--challenges", default="crest/question/crest_challenges.jsonl")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--llm", action="store_true",
                    help="NOT IMPLEMENTED: the semantic residue needs a model pass; left explicit "
                         "rather than silently pretending mechanical checks are exhaustive")
    a = ap.parse_args()
    if a.llm:
        sys.exit("--llm is not implemented; run the mechanical checks and review the residue by hand")
    path = Path(a.challenges) if Path(a.challenges).is_absolute() else REPO / a.challenges
    items = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    total, by_kind = 0, collections.Counter()
    for it in items:
        vs = check_item(it)
        if vs:
            print(f"\n{it['id']}")
            for x in vs:
                print(f"  [{x['severity']}] {x['kind']}: {x['detail']}")
                by_kind[x["kind"]] += 1
                total += 1
    print(f"\n{len(items)} items checked; {total} mechanical contradiction(s)")
    for k, n in by_kind.most_common():
        print(f"  {n}x {k}")
    print("\nNB a clean result means NO MECHANICAL CONTRADICTION FOUND, not that items are "
          "consistent -- semantic rule/baseline conflicts are not decidable here.")
    raise SystemExit(1 if total else 0)


if __name__ == "__main__":
    main()
