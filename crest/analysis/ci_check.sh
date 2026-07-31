#!/usr/bin/env bash
# CREST pre-release gate. Runs every mechanical check that would otherwise be caught by a reviewer
# in one command. Non-zero exit = do not release.
#
# Each check exists because something shipped broken:
#   schema      -- schema.json was never applied (no jsonschema import anywhere in the repo)
#   items       -- items contradicted themselves (rules permitting and banning the same element;
#                  a baseline violating its own numeric rule; a "new" mechanism already in the list)
#   claims      -- papers/datasheet asserted artifacts that do not exist (canary strings, a frozen
#                  index, an OSF registration, order randomization, human validation)
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
fail=0

echo "== schema + loader validation (all 50 items)"
python -c "
import sys; sys.path.insert(0,'.')
from crest.harness.run_crest import load_challenges
n=len(load_challenges('crest/questions/crest_challenges.jsonl'))
print(f'  OK {n} items load and validate')
" || fail=1

echo "== sidecar id bijection (rationale lives in item_design.jsonl)"
python - <<'PY2' || fail=1
import json, sys
a={json.loads(l)["id"] for l in open("crest/questions/crest_challenges.jsonl") if l.strip()}
b={json.loads(l).get("id") for l in open("crest/questions/item_design.jsonl") if l.strip()} - {None}
if a != b:
    print(f"  FAIL sidecar drift: {len(a-b)} item(s) missing design notes {sorted(a-b)[:5]}, "
          f"{len(b-a)} orphaned {sorted(b-a)[:5]}")
    sys.exit(1)
print(f"  OK {len(a)} items, exact id bijection with item_design.jsonl")
PY2

echo "== quarantine (a benchmark shipping 49/50 must say so)"
python - <<'PY2' || fail=1
import sys, yaml, pathlib
q=(yaml.safe_load(pathlib.Path("crest/questions/quarantine.yaml").read_text()) or {})
items=q.get("quarantined") or {}
if items:
    print(f"  FAIL {len(items)} item(s) quarantined -> not release-ready: {sorted(items)}")
    for k,v in items.items():
        print(f"    {k}: {str(v.get('reason','')).strip().splitlines()[0][:100]}...")
    sys.exit(1)
print("  OK no quarantined items")
PY2

echo "== item self-consistency"
python -m crest.analysis.validate_items >/tmp/ci_items.log 2>&1 \
  && echo "  OK no mechanical contradictions" \
  || { echo "  FAIL $(grep -c BLOCKING /tmp/ci_items.log) contradiction(s):"; grep BLOCKING /tmp/ci_items.log | sed 's/^/    /'; fail=1; }

echo "== second item file: crest_aiml_challenges.jsonl"
# This 50-item AI/ML set was entirely OUTSIDE the gate -- 0 references to it in this script -- so its
# items could rot silently, and its 9 most recent items had never been mechanically checked at all.
# It is deliberately held to a LOWER bar than crest_challenges.jsonl, because no paper claims it:
# grep finds zero mentions across both papers, and readme.md says it is "NOT ... run or scored".
# So it gets the two checks that apply to ANY item file (it must load, and it must not contradict
# itself) but NOT the release-artifact checks (design sidecar, quarantine), which would fail on it.
# PROMOTION CONDITION: the moment any paper, the readme's release list, or the datasheet claims this
# file as released content, add the item_design.jsonl bijection and quarantine checks for it too --
# it has NO design sidecar today (0 of its 50 ids appear in item_design.jsonl, vs 50 of 50 for the
# science set), so that promotion is real work, not a one-line edit.
AIML=crest/questions/crest_aiml_challenges.jsonl
if [ ! -s "$AIML" ]; then
  echo "  FAIL $AIML is missing or empty -- it is referenced by readme.md and the datasheet"; fail=1
else
  python -c "
import sys; sys.path.insert(0,'.')
from crest.harness.run_crest import load_challenges
n=len(load_challenges('$AIML'))
print(f'  OK {n} items load and validate')
" || fail=1
  python -m crest.analysis.validate_items --challenges "$AIML" >/tmp/ci_aiml.log 2>&1 \
    && echo "  OK no mechanical contradictions" \
    || { echo "  FAIL $(grep -c BLOCKING /tmp/ci_aiml.log) contradiction(s):"; grep BLOCKING /tmp/ci_aiml.log | sed 's/^/    /'; fail=1; }
  # Not a release check, just visibility: neither item file cites sources for its known-answers
  # lists, so "dated known-answers" rests on author assertion in BOTH sets, not on citations.
  python -c "
import json
n=sum(1 for l in open('$AIML',encoding='utf-8') if l.strip() and (json.loads(l).get('citations') or json.loads(l).get('sources')))
print(f'  NOTE {n}/50 aiml items cite sources for known_answers (the science set is also 0/50)')
" || true
fi

echo "== claims the repo cannot instantiate (BOTH papers)"
# a gate that silently passes when its input is gone is worse than no gate: deleting the sections
# directory previously turned three checks green
# BOTH papers. Scoping this to p2 "because p3 is not submission-ready" let p3 accumulate seven
# non-negated human-validation assertions plus a frozen index, an open-weight judge and an
# order-randomised panel -- and p3 is one `compile.sh` away from being postable. An adversarial
# review also found that correcting p2/p3 section-by-section left BOTH papers internally
# contradictory, with the unrevised sections asserting exactly what the revised ones withdraw. A
# gate that reads only half a paper cannot see that.
PAPER_TEX=$(ls crest/paper/p2_benchmark_only/sections/*.tex crest/paper/p3_caesar_hybrid/sections/*.tex \
              crest/paper/p2_benchmark_only/main.tex crest/paper/p3_caesar_hybrid/main.tex 2>/dev/null)
if [ -z "$PAPER_TEX" ]; then
  echo "  FAIL no paper .tex found -- claims checks cannot run"; fail=1
fi
# These are ASSERTION patterns, not vocabulary. Grepping the single token "human-validated" left
# 04_judge_validation.tex free to assert the study in present tense and different words -- "We
# validate the panel against a human-expert consensus panel across all five categories", "the human
# panel is the primary scorer", a reliability verdict per category -- while the gate stayed green
# because the only literal match was the abstract's negated one. No human study has been run.
for pat in "human-validated" "human-expert consensus panel" "human panel is the primary scorer" \
           "judge--human agreement" "(OSF, timestamped)" "contamination-controlled" \
           "open-weight fourth" "order-randomized" "order-randomised" "pre-register" \
           "frozen shared index" "frozen retrieval snapshot" "signed manifest" \
           "matched tool and compute budget" "matched tool/compute budget" \
           "human study" "mechanism-driven" \
           `# Round 2. Each pattern below is here because a real sentence asserted it while the` \
           `# 17 patterns above stayed green. p2 sections/06 and 07 were NEVER revised and were` \
           `# still \input by main.tex: s06 claimed human faithfulness labels, a per-claim FACT` \
           `# verifier, a per-agent firing rate and a with/without sensitivity analysis for a gate` \
           `# that fired 0/250, and creativity=0 for a failing answer (the harness records` \
           `# 'unscored'); s07 reported component ablations of an entrant with 0 of 250 records.` \
           "human faithfulness labels" "per-agent firing rate" "with/without-check" \
           "per-claim FACT verifier" "we ablate the components" \
           `# NOT the bare phrase "component ablation": p3 sections 4/5 legitimately DESCRIBE the` \
           `# ablation protocol that would test the mechanism, and p3 sections 0/1/7/8 legitimately` \
           `# withdraw it, so a bare match fires 9x on honest text. "we ablate the components" is` \
           `# what p2 section 07 actually asserted as done.` \
           "disqualified for creativity" "zero-inflates" \
           `# Release claims: result/runs/ is gitignored, so per-record judge rows never ship;` \
           `# there is no croissant.json; and grading is not reproducible from a fresh clone.` \
           "per-judge scores" "grading reproducible" "Croissant" "releasing everything" \
           `# All 250 records carry judge_prompt_version: null, so nothing is versioned.` \
           "scoring input is fixed and versioned" \
           `# expert_baseline is JUDGE-HIDDEN (schema.json; score.py does not send it), so any` \
           `# sentence putting it judge-side or scoring Surprising against it is false.` \
           "expert baselines held judge-side" "against expert expectation" \
           "expert's expected answer" \
           `# "registered" evades the "pre-register" pattern; no ablation protocol is registered.` \
           "registered design" \
           `# Length was never recorded: 0/250 records carry answer_chars or answer_words, so the` \
           `# honest sentence is "not recorded" and this cannot be negated away.` \
           "recorded per record" \
           `# Catches the "the one property that DOES hold" family. Dating the known-answers list` \
           `# does not bound what counts as new -- the judge is told absent content is` \
           `# non-redundant, so fresher retrieval is a route INTO a high New score.` \
           "does hold"; do
  # The capture window MUST be wider than the negation regex's own lookbehind allowance. It was 14
  # against an allowance of 24, so any negation sitting 15-24 characters before the pattern was
  # truncated out of the captured text and could never match -- the documented 24 was unreachable,
  # and "entrants do \textbf{not} receive a matched tool/compute budget" (negation 15 chars out)
  # failed the gate while being a correct disclaimer. 40 > 24, so the allowance now actually applies.
  # The negation tokens are word-bounded: an unbounded "no" matches inside "known", "novel" and
  # "cannot", which would have let "per-item dated known-answers ... matched tool budget" pass.
  hits=$(grep -o ".\{0,40\}$pat" $PAPER_TEX 2>/dev/null \
         | grep -viE "(\bnot\b|\bno\b|\bnever\b|withdrawn|future work|NOT PERFORMED|NOT IMPLEMENTED)[^.]{0,24}$(printf '%s' "$pat" | sed 's/[][\\.*^$(){}?+|/]/\\&/g')" \
         | wc -l | tr -d ' ')
  if [ "$hits" != "0" ]; then echo "  FAIL '$pat' asserted (not negated) x$hits"; fail=1;
  else echo "  OK '$pat' absent or negated"; fi
done
echo "== compiled PDFs are not stale"
# The papers' PDFs sat two days behind their sources while every honesty correction landed in the
# .tex files. The PDF is what circulates, so a stale one silently re-asserts withdrawn claims.
for d in crest/paper/p2_benchmark_only crest/paper/p3_caesar_hybrid; do
  pdf="$d/main.pdf"
  if [ ! -f "$pdf" ]; then echo "  OK $d has no PDF (nothing to go stale)"; continue; fi
  newest=$(find "$d" crest/paper/_shared -name '*.tex' -o -name '*.bib' 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
  if [ -n "$newest" ] && [ "$newest" -nt "$pdf" ]; then
    echo "  FAIL $pdf is older than $newest -- recompile (crest/paper/compile.sh) before release"; fail=1
  else
    echo "  OK $(basename $d)/main.pdf is newer than its sources"
  fi
done

echo "== judge prompt stamp vs prompt"
# The prompt version is a hand-bumped literal, checked HERE rather than auto-computed at import.
# Three auto-invalidating designs were each wrong in a different way (source hash under- and
# over-fired; a rendered hash was blind to the branch 250/250 answers take), and computing it at
# import made six modules unimportable if _judge_prompt raised. A build-time comparison gets the one
# property that matters -- if the prompt changed, do not mix records -- with no import-time risk.
python - <<'PY2' || fail=1
import sys; sys.path.insert(0,'.')
from crest.judge.score import JUDGE_PROMPT_VERSION, JUDGE_PROMPT_VERSION_HASH, prompt_hash
h = prompt_hash()
if h != JUDGE_PROMPT_VERSION_HASH:
    print(f"  FAIL judge prompt changed ({JUDGE_PROMPT_VERSION_HASH} -> {h}) but "
          f"JUDGE_PROMPT_VERSION is still {JUDGE_PROMPT_VERSION!r}. Bump the version AND the hash, "
          f"or scores from old and new runs will be mixed silently.")
    sys.exit(1)
print(f"  OK judge prompt matches stamp {JUDGE_PROMPT_VERSION} ({h})")
PY2

echo "== canary claims are human-approved"
# NOT a count of canaries in the item file: that count gated nothing, and the ground truth (0 of 50)
# is recorded in the allow file's header. The check below runs UNCONDITIONALLY -- it used to sit inside
# the `else` of "do all items carry a canary?", so adding canaries to all 50 items would have silently
# retired it, and it polices more than a count (an OSF registration, a frozen index, "reproduction
# would be evidence of contamination").
{
  # APPROVAL LIST, not prose-matching: prose is not parseable by regex, so every line mentioning a
  # canary must be BYTE-IDENTICAL to a line a human approved in canary_claims.allow, and editing one
  # costs a re-read -- which is the actual control wanted. (Three grep heuristics preceded this and
  # were each green for the wrong reason; `git log -- crest/analysis/ci_check.sh` has them.) Scope is
  # EVERY tracked .md and .tex under crest/, enumerated with git ls-files rather than a hand-listed
  # glob -- that glob covered 43 files and missed 7, including both papers' main.tex, judge/rubric.md
  # and result/readme.md.
  allow="crest/analysis/canary_claims.allow"
  globs=('crest/*.md' 'crest/**/*.md' 'crest/**/*.tex')
  # Fail CLOSED on anything that leaves the gate with no input, because each such case printed OK:
  # `grep -f` on a missing pattern file matches nothing, `git ls-files` prints nothing outside a repo,
  # and BSD xargs skips grep entirely on an empty list. (An EMPTY allow file already fails closed, and
  # a blank line inside it is harmless: -x anchors the empty pattern to empty lines only.)
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "  FAIL not a git repository -- cannot enumerate docs, so the canary gate cannot run"; fail=1
  elif [ ! -s "$allow" ]; then
    echo "  FAIL $allow is missing or empty -- the canary gate cannot run"; fail=1
  else
  # NUL-delimited end to end, and `git ls-files` deliberately runs TWICE -- once to count, once to
  # grep -- because a NUL-separated list cannot be held in a shell variable (bash strips NULs) and the
  # file list IS this gate's coverage, so its emptiness has to be asserted separately. -z also
  # disables git's path QUOTING: without it a path containing a newline reached grep as a literal
  # quoted string, grep said "No such file", and that file's canary lines never reached the gate.
  # stderr is NOT discarded, so an unreadable file is loud rather than silently skipped.
  n_docs=$(git ls-files -z --cached --others --exclude-standard "${globs[@]}" \
             | tr -dc '\0' | wc -c | tr -d ' ')
  if [ "${n_docs:-0}" = "0" ]; then
    echo "  FAIL no crest .md/.tex files enumerated -- the canary gate has no coverage"; fail=1
    bad_lines=""
  else
    bad_lines=$(git ls-files -z --cached --others --exclude-standard "${globs[@]}" \
                | xargs -0 grep -hiE "canar(y|ies)" \
                | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sort -u \
                | grep -vxFf "$allow")
  fi
  n_bad=$(printf '%s' "$bad_lines" | grep -c . | tr -d ' ')
  if [ "${n_bad:-0}" != "0" ]; then
    echo "  FAIL $n_bad canary line(s) not approved in $allow."
    echo "       Re-read each, then add it verbatim to the allow file if it is honest:"
    printf '%s\n' "$bad_lines" | cut -c1-110 | sed 's/^/         /'
    fail=1
  else echo "  OK all canary mentions are human-approved"; fi
  fi
}

echo; [ "$fail" = 0 ] && echo "PRE-RELEASE GATE: PASS" || echo "PRE-RELEASE GATE: FAIL"
exit $fail
