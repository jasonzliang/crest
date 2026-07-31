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

echo "== claims the repo cannot instantiate (p2 body only; p3 is not submission-ready)"
# a gate that silently passes when its input is gone is worse than no gate: deleting the sections
# directory previously turned three checks green
if ! ls crest/paper/p2_benchmark_only/sections/*.tex >/dev/null 2>&1; then
  echo "  FAIL p2 sections not found -- claims checks cannot run"; fail=1
fi
# These are ASSERTION patterns, not vocabulary. Grepping the single token "human-validated" left
# 04_judge_validation.tex free to assert the study in present tense and different words -- "We
# validate the panel against a human-expert consensus panel across all five categories", "the human
# panel is the primary scorer", a reliability verdict per category -- while the gate stayed green
# because the only literal match was the abstract's negated one. No human study has been run.
for pat in "human-validated" "human-expert consensus panel" "human panel is the primary scorer" \
           "judge--human agreement" "(OSF, timestamped)" "contamination-controlled"; do
  hits=$(grep -o ".\{0,14\}$pat" crest/paper/p2_benchmark_only/sections/*.tex 2>/dev/null \
         | grep -v 'not..\{0,8\}'"$pat" | grep -v 'not.\{0,12\}'"$pat" | wc -l | tr -d ' ')
  if [ "$hits" != "0" ]; then echo "  FAIL '$pat' asserted (not negated) x$hits"; fail=1;
  else echo "  OK '$pat' absent or negated"; fi
done
echo "== canary claim vs data"
# count, do not merely detect: one item containing the word passed a claim that EVERY item carries one
n_canary=$(python -c "
import json,sys
rows=[json.loads(l) for l in open('crest/questions/crest_challenges.jsonl') if l.strip()]
print(sum(1 for r in rows if 'canary' in json.dumps(r).lower()), len(rows))
")
set -- $n_canary; have=$1; total=$2
if [ "$have" = "$total" ] && [ "$have" != "0" ]; then echo "  OK canaries present in all $total items";
else
  # ALLOWLIST, not a hedge denylist. Two earlier versions of this check were green for the wrong
  # reason. First it grepped datasheet.md whole-file for "NOT IMPLEMENTED", which 13 unrelated
  # markers always satisfied, making the FAIL branch unreachable. Then it excluded lines carrying
  # any hedge word -- but "planned" and "would be" are exactly the words that accompany a REAL
  # canary claim ("carries a canary GUID, so reproduction WOULD BE evidence of contamination"
  # passed). So a canary line is honest only if it explicitly states the canaries are ABSENT.
  # "unqualified" is allowed because the datasheet sentence describing this very check is not
  # itself a canary claim. Scope adds readme.md, which was previously unchecked.
  ok_re="NOT IMPLEMENTED|no canar|zero .*canar|not present|not shipped|never shipped|unqualified"
  if grep -rhiE "canar(y|ies)" crest/readme.md crest/docs/datasheet.md \
        crest/paper/p2_benchmark_only/sections/*.tex 2>/dev/null \
     | grep -qivE "$ok_re"; then
    echo "  FAIL canary claimed in docs but only $have/$total items contain one"; fail=1
  else echo "  OK no unqualified canary claim (0/50 items, correctly disclosed)"; fi
  # p3 is not submission-ready, so its claims do not block a release -- but they must not be
  # invisible either. Counted and reported, never silently skipped.
  n_p3=$(grep -rhiE "canar(y|ies)" crest/paper/p3_*/sections/*.tex 2>/dev/null | grep -icvE "$ok_re")
  [ "${n_p3:-0}" != "0" ] && echo "  NOTE $n_p3 unqualified canary claim(s) in p3 (not gated: p3 is not submission-ready)"
fi

echo; [ "$fail" = 0 ] && echo "PRE-RELEASE GATE: PASS" || echo "PRE-RELEASE GATE: FAIL"
exit $fail
