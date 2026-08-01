#!/usr/bin/env bash
# CREST pre-release gate. Runs every mechanical check that would otherwise be caught by a reviewer
# in one command. Non-zero exit = do not release.
#
# Each check exists because something shipped broken:
#   quarantine  -- an item under an auditor verdict of "do not release" shipped in the 50 with this
#                  gate GREEN, because the gate read `quarantined:` and ignored `watch_list:`
#   items       -- items contradicted themselves (rules permitting and banning the same element;
#                  a baseline violating its own numeric rule; a "new" mechanism already in the list)
#   min_judges  -- a 3-judge panel silently scored records with 2 and labelled them "scored"
#   billing     -- cache hits wrote empty token fields, making cost unanswerable on the normal path
#   claims      -- papers/datasheet asserted artifacts that do not exist (canary strings, a frozen
#                  index, an OSF registration, order randomization, human validation)
#   PDFs        -- both PDFs sat 2 days behind their sources, re-asserting withdrawn claims
#   judge stamp -- mixing records across judge-prompt versions silently corrupts scores
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
fail=0

# ---------------------------------------------------------------------------------------------
# TRIMMED 2026-07-31 to the checks that are JUSTIFIED AND NECESSARY. Every check kept below caught a
# real, release-blocking defect in this project. Three were removed as unjustified, and the reasoning
# is recorded here rather than lost, because an un-explained removal is indistinguishable from an
# oversight and someone will re-add them:
#
#   schema + loader validation  REMOVED as provably redundant. run_eval.py:126 calls the same
#       load_challenges() on every run, and `--dry-run` does it for free BEFORE any money moves. A
#       gate check that duplicates the program's own startup adds a line of green and no information.
#
#   sidecar id bijection        REMOVED as not release-blocking. NO code reads item_design.jsonl --
#       it is documentation. Drift means an item lacks a rationale note, which is visible in git and
#       cannot corrupt a result, a score, or a claim. It was guarding tidiness, not correctness.
#
#   second item file (aiml)     REMOVED as out of scope. No paper claims crest_aiml_challenges.jsonl
#       (grep finds zero mentions in either) and readme.md says it is not part of the release. Its
#       own run validates it on load. The one-time value -- discovering it was ungated -- is banked.
#
# What was NOT removed, and why the temptation should be resisted: the canary allow-list. Its
# docstring records that THREE successive grep heuristics preceded it and each passed a real
# affirmative claim. Replacing it with a pattern would re-open a documented failure. It was NARROWED
# instead (see that check) -- same mechanism, 42% less surface.
# ---------------------------------------------------------------------------------------------

echo "== quarantine (a benchmark shipping 49/50 must say so)"
python - <<'PY2' || fail=1
import sys, yaml, pathlib, re
q=(yaml.safe_load(pathlib.Path("crest/question/quarantine.yaml").read_text()) or {})
rc=0
items=q.get("quarantined") or {}
if items:
    print(f"  FAIL {len(items)} item(s) quarantined -> not release-ready: {sorted(items)}")
    for k,v in items.items():
        print(f"    {k}: {str(v.get('reason','')).strip().splitlines()[0][:100]}...")
    rc=1
else:
    print("  OK no quarantined items")
# The watch_list was read by NOTHING. This gate checked only `quarantined:`, so an item carrying an
# explicit auditor verdict of "do not release" sat in the shipped 50 with the release gate GREEN --
# the exact failure mode this script exists to prevent, one level up. A verdict recorded in a YAML
# file that no check reads is a comment, not a control. Watch-list entries are NOT automatically
# blocking (thin-but-shippable is a real category), but a do-not-release verdict is.
watch=q.get("watch_list") or {}
BLOCKING=re.compile(r"do\s+not\s+release", re.I)
# An entry may legitimately QUOTE the verdict while recording that it has been dealt with, so a
# resolved entry needs a way to say so without the gate reading its own history as a live blocker.
# The convention is a leading "RESOLVED <date>"; anything else mentioning do-not-release blocks.
RESOLVED=re.compile(r"^\s*RESOLVED\s+\d{4}-\d{2}-\d{2}", re.I)
blockers={k:str(v) for k,v in watch.items()
          if BLOCKING.search(str(v)) and not RESOLVED.match(str(v))}
resolved=[k for k,v in watch.items() if RESOLVED.match(str(v))]
if resolved:
    print(f"  OK {len(resolved)} watch-list item(s) marked RESOLVED with a date: {sorted(resolved)}")
if blockers:
    print(f"  FAIL {len(blockers)} watch-list item(s) carry a DO-NOT-RELEASE verdict but are still "
          f"shipped and NOT quarantined: {sorted(blockers)}")
    for k,v in blockers.items():
        print(f"    {k}: {' '.join(v.split())[:220]}...")
    print("    -> Resolve explicitly: fix the item, move it to `quarantined:`, or record why the")
    print("       verdict is overridden. Do not leave it shipped with the gate green.")
    rc=1
elif watch:
    print(f"  OK {len(watch)} watch-list item(s), none carrying a do-not-release verdict: {sorted(watch)}")
else:
    print("  OK no watch-list items")
sys.exit(rc)
PY2

echo "== item self-consistency"
python -m crest.analysis.validate_items >/tmp/ci_items.log 2>&1 \
  && echo "  OK no mechanical contradictions" \
  || { echo "  FAIL $(grep -c BLOCKING /tmp/ci_items.log) contradiction(s):"; grep BLOCKING /tmp/ci_items.log | sed 's/^/    /'; fail=1; }

echo "== min_judges covers the whole panel, and no run hides a thinned one"
# min_judges was 2 against a 3-judge panel, so losing exactly ONE vendor left n_judges=2 >= 2 and the
# record was labelled "scored". That is not theoretical: it happened to judge_google (invalid
# thinking_budget) and again to judge_anthropic (spend-rate cap, 11 of 31 records in run
# 2026-07-31T180746Z). One missing vendor shifts a score by more than the between-entrant spread it
# is meant to measure, so a config that permits it silently is a defect, not a preference.
python - <<'PY2' || fail=1
import sys, yaml, json, glob, os, collections
rc = 0
cfg = yaml.safe_load(open("crest/judge/judge_config.live.yaml")) or {}
n_j, mj = len(cfg.get("judges") or []), cfg.get("min_judges")
if mj is None:
    print(f"  FAIL judge_config.live.yaml has no min_judges; it must be set to {n_j}"); rc = 1
elif mj < n_j:
    print(f"  FAIL min_judges={mj} is below the {n_j} configured judges -- losing a vendor would "
          f"pass as 'scored' and enter the headline means"); rc = 1
else:
    print(f"  OK min_judges={mj} covers all {n_j} configured judges")
# And catch runs already on disk whose records claim "scored" on a thinned panel.
for path in sorted(glob.glob("crest/result/runs/*/records.jsonl")):
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not recs:
        continue
    name = os.path.basename(os.path.dirname(path))[:44]
    thin = collections.Counter()
    for r in recs:
        js = (r.get("creativity") or {}).get("judges") or []
        if r.get("scoring_status") == "scored" and 0 < len(js) < n_j:
            for j in {x.get("judge_id") for x in js} ^ {x["id"] for x in cfg["judges"]}:
                thin[j] += 1
    if thin:
        complete = os.path.exists(os.path.join(os.path.dirname(path), "run_manifest.json"))
        tag = "FAIL" if complete else "WARN(in-progress)"
        print(f"  {tag} {name}: record(s) labelled 'scored' with a THINNED panel, missing "
              f"{dict(thin)} -- these carry a systematic severity shift")
        if complete:
            rc = 1
sys.exit(rc)
PY2

echo "== billing fields are actually populated (schema >= 1.2.0 runs)"
# WHY THIS CHECK EXISTS: adding a field is not the same as getting the data. `answer_chars` is
# written by current code and is still 0/250 in the shipped run, because a schema-version gap
# dropped it and nothing checked -- so a length covariate is uncomputable from a run that looks
# complete. The billing fields would regress identically and just as silently. A field nothing
# verifies is a field that will be empty when someone finally needs it.
# Scoped to runs at record_schema_version >= 1.2.0: older runs legitimately have no tokens block,
# and that state is reported as NOT MEASURED rather than as zero cost -- different claims.
python - <<'PY2' || fail=1
import json, sys, glob, os, collections
runs = sorted(glob.glob("crest/result/runs/*/records.jsonl"))
if not runs:
    print("  OK no runs on disk to check")
    sys.exit(0)
bad = 0
for path in runs:
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not recs:
        continue
    name = os.path.basename(os.path.dirname(path))[:44]
    ver = str(recs[0].get("schema_version") or "")
    try:  # "crest-record/1.2.0" -> (1,2,0)
        tup = tuple(int(x) for x in ver.split("/")[-1].split("."))
    except ValueError:
        tup = (0,)
    if tup < (1, 2, 0):
        print(f"  NOTE {name}: schema {ver or '?'} predates 1.2.0, so it carries NO billing fields. "
              f"Cost is NOT MEASURED for this run (which is not the same as zero).")
        continue
    # A run with no manifest is still WRITING. Its records are a partial sample, so a defect there
    # must be reported but must NOT fail a PRE-RELEASE gate -- an unfinished run is not releasable
    # anyway, and failing on it would leave the gate red for hours during every run. Still checked
    # rather than skipped: this is how the cache-hit regression below was caught, one minute in.
    complete = os.path.exists(os.path.join(os.path.dirname(path), "run_manifest.json"))
    per = collections.defaultdict(lambda: {"n": 0, "in0": 0, "nocalls": 0, "bad": 0})
    for r in recs:
        s = per[r.get("agent", "?")]
        s["n"] += 1
        tk = r.get("tokens") or {}
        if not int(tk.get("input") or 0):
            s["in0"] += 1
        if not (r.get("calls") or []):
            s["nocalls"] += 1
        # output_total must be TOTAL BILLABLE OUTPUT, i.e. reasoning-inclusive. Providers disagree
        # natively -- OpenAI's output_tokens includes reasoning, Google's candidates_token_count
        # excludes it -- and this shipped wrong once, recording Google output 7.9x low. Cheap
        # invariant that catches the whole class.
        if int(tk.get("output_reasoning") or 0) > int(tk.get("output_total") or 0):
            s["bad"] += 1
    tag = "FAIL" if complete else "WARN(in-progress)"
    def flag(msg):
        global bad          # module scope in this heredoc, not an enclosing function
        print(f"  {tag} {name}: {msg}")
        if complete:
            bad = 1
    for agent, s in sorted(per.items()):
        if s["in0"] == s["n"]:
            flag(f"{agent} has tokens.input == 0 on ALL {s['n']} record(s) -- the billing capture "
                 f"is not reaching this adapter, so cost is unanswerable for it")
        elif s["in0"]:
            print(f"  WARN {name}: {agent} has tokens.input == 0 on {s['in0']}/{s['n']} record(s)")
        if s["nocalls"] == s["n"]:
            flag(f"{agent} has an empty calls[] on ALL {s['n']} record(s)")
        if s["bad"]:
            flag(f"{agent} has output_reasoning > output_total on {s['bad']}/{s['n']} record(s) -- "
                 f"output_total is not reasoning-inclusive for this provider, so cost is "
                 f"under-counted. Recompute from usage_raw.")
    if not bad:
        print(f"  OK {name}: billing fields populated for all {len(per)} entrant(s)")
sys.exit(bad)
PY2

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
           `# "releasing everything" REMOVED: it cannot distinguish "WE release everything" from` \
           `# "THEY released everything", and p3's related-work paragraph legitimately describes what` \
           `# accepted benchmark papers did. It cost a prose rewrite and guarded nothing a specific` \
           `# artifact pattern below does not already cover.` \
           "per-judge scores" "grading reproducible" "Croissant" \
           `# All 250 records carry judge_prompt_version: null, so nothing is versioned.` \
           "scoring input is fixed and versioned" \
           `# expert_baseline is JUDGE-HIDDEN (schema.json; score.py does not send it), so any` \
           `# sentence putting it judge-side or scoring Surprising against it is false.` \
           "expert baselines held judge-side" "against expert expectation" \
           "expert's expected answer" \
           `# "registered" evades the "pre-register" pattern; no ablation protocol is registered.` \
           `# TRIMMED: "recorded per record" and "does hold" removed. Both are ordinary English` \
           `# fragments rather than claim signatures, so they fire on prose that asserts nothing --` \
           `# "does hold" hit my own corrected text. The principle now applied to this whole list:` \
           `# keep a pattern only if it NAMES A SPECIFIC ARTIFACT (a frozen index, a signed manifest,` \
           `# Croissant, an OSF registration, a per-claim FACT verifier), because such a phrase can` \
           `# only appear AS the claim. Generic phrases cannot be negation-checked reliably and their` \
           `# false positives are paid in contorted prose every time someone edits a paragraph.` \
           `# The two real defects they caught -- length "recorded per record" when 0/250 carry it,` \
           `# and the backwards dated-known-answers argument -- are fixed, and both papers now state` \
           `# the correct version, so a regression would have to be written in deliberately.` \
           "registered design"; do
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
  # NARROWED 2026-07-31: doc/misc/** excluded. Those are internal working notes, not release
  # content -- iclr_metareview.md and paper_comparison.md alone held 11 of the 26 matching lines, and
  # every edit to one cost a byte-identical re-approval for no release risk. Scope is now the
  # RELEASE-FACING docs only: readme, doc/*.md (datasheet, best-practices) and both papers. The
  # mechanism is unchanged, and deliberately so: its own header records that three grep heuristics
  # preceded it and each passed a real affirmative claim.
  # The exclusion must be an :(exclude) PATHSPEC, not a narrower glob. git pathspec wildcards match
  # `/` by default, so 'crest/doc/*.md' still matched crest/doc/misc/*.md and the narrowing was
  # silently a no-op -- 26 lines before and after. Measured: that glob returns 20 files, its
  # :(glob)-prefixed form 7.
  globs=('crest/*.md' 'crest/**/*.md' 'crest/**/*.tex' ':(exclude)crest/doc/misc/*')
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
