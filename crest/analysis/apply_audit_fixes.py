#!/usr/bin/env python3
"""Apply the staged old->new citation corrections from the live-web audit reports.

The five audit passes produced ~200 corrections, each with an `old` string the auditor verified to
occur EXACTLY ONCE in the item file so it applies as a literal find-and-replace. Doing that by hand
invites transcription errors in precisely the field where correctness now matters most: the S1 fix
(adding the rubric's missing "judge ONLY against this list, not your own knowledge" clause) removed
the judge's background knowledge as a second line of defence, so a wrong `known_answers` entry is no
longer catchable at score time.

Safety: nothing is written unless every requested `old` string is found exactly once. Already-applied
corrections are reported as such rather than counted as failures, since 24 were applied by hand
earlier. Ambiguous matches (>1 occurrence) are refused, not guessed.

Usage:
    python -m crest.analysis.apply_audit_fixes --dry-run
    python -m crest.analysis.apply_audit_fixes
"""
from __future__ import annotations
import argparse, json, re, shutil, sys, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# allow leading indentation (the C3 report indents its pairs by 3 spaces)
PAIR_RE = re.compile(r"^[ \t]*[-*]\s*OLD:\s*`(.+?)`[ \t]*$\n[ \t]*[-*]\s*NEW:\s*`(.*?)`[ \t]*$",
                     re.M | re.S)


def parse_reports(notes_dir: Path) -> tuple[list, list]:
    out, truncated = [], []
    for f in sorted(notes_dir.glob("audit_live_*.md")):
        for m in PAIR_RE.finditer(f.read_text()):
            old, new = m.group(1), m.group(2)
            if not old or old == new:
                continue
            # Auditors sometimes elide a long quote for display. Applying a truncated `old` would
            # silently corrupt the item, so refuse rather than guess.
            if old.rstrip().endswith("...") or new.rstrip().endswith("..."):
                truncated.append((f.name, old))
                continue
            out.append((f.name, old, new))
    return out, truncated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--challenges", default="crest/questions/crest_challenges.jsonl")
    ap.add_argument("--notes", default="crest/docs/notes")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    path = REPO / a.challenges
    pairs, truncated = parse_reports(REPO / a.notes)
    raw = path.read_text()

    applied, already, ambiguous, missing = [], [], [], []
    for src, old, new in pairs:
        n = raw.count(old)
        if n == 1:
            applied.append((src, old, new))
        elif n == 0:
            (already if (new and new in raw) else missing).append((src, old, new))
        else:
            ambiguous.append((src, old, new, n))

    print(f"staged corrections parsed: {len(pairs)}"
          f"  (+{len(truncated)} refused: `old` was elided with '...' for display)")
    print(f"  applicable (old found exactly once) : {len(applied)}")
    print(f"  already applied (new already present): {len(already)}")
    print(f"  NOT FOUND (old absent, new absent)   : {len(missing)}")
    print(f"  AMBIGUOUS (old occurs >1x, refused)  : {len(ambiguous)}")
    for src, old, new, n in ambiguous[:5]:
        print(f"    [{src}] x{n}: {old[:80]}")
    for src, old, new in missing[:8]:
        print(f"    [{src}] MISS: {old[:90]}")

    if a.dry_run:
        print("\n[dry-run] nothing written")
        return
    if not applied:
        print("\nnothing to apply")
        return

    shutil.copy(path, path.with_suffix(".jsonl.bak_auditfix"))
    for src, old, new in applied:
        raw = raw.replace(old, new, 1)
    # must still be valid JSONL, one object per line, 50 lines
    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) == 50, f"line count changed: {len(lines)}"
    for l in lines:
        json.loads(l)
    path.write_text(raw if raw.endswith("\n") else raw + "\n")
    by_src = collections.Counter(s for s, _, _ in applied)
    print(f"\napplied {len(applied)} correction(s): {dict(by_src)}")
    print(f"backup: {path.with_suffix('.jsonl.bak_auditfix').name}")


if __name__ == "__main__":
    main()
