"""CREST evaluation core.

Runs each entrant agent on the CREST challenges via LIVE provider-native web search (a frozen
shared index for a contamination-controlled run is future work; see agents.FrozenIndex), applies
the factual-grounding check, scores creativity with a leave-one-family-out judge panel, and writes
an immutable per-run result directory (records.jsonl + transcripts.jsonl + manifest + summary; see
harness/results.py).

`evaluate()` is the reusable core; both this module's CLI and the top-level `run_eval.py`
config-driven entry point call it.

CLI (single ad-hoc run):
    python -m crest.harness.run_crest --agents claude_shallow openai_shallow gemini_shallow --subset adhoc
For config-driven, multi-agent runs, prefer:  python crest/run_eval.py
"""
from __future__ import annotations
import argparse, json, dataclasses, threading, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from crest.harness.agents import build_agent, FrozenIndex
from crest.harness import results as R
from crest.judge.score import JudgePanel, grounding_gate
from crest.harness.cache import GenerationCache, query_sha


@dataclasses.dataclass
class Challenge:
    id: str; category: str; domain: str; query: str
    axis_isolated: str; time_sensitivity: str
    known_answers: list; hard_rules: list; expert_baseline: str
    predicted_direction: str | None; rationale: str = ""

    @staticmethod
    def from_json(d: dict) -> "Challenge":
        """Build a Challenge, FAILING LOUDLY on missing judge-side machinery.

        Previously every field came from `d.get(k)`, so a missing `known_answers` became None and the
        judge silently received "(none provided)" as the novelty baseline -- the two fields the design
        calls load-bearing were the two that failed silently, with no error and no scoring_status
        flag. An item that cannot be scored must not be scored."""
        missing = [k for k in ("id", "query", "known_answers", "expert_baseline") if not d.get(k)]
        if missing:
            raise ValueError(f"challenge {d.get('id', '<no id>')!r} is missing required "
                             f"scoring machinery: {missing}. Refusing to score it.")
        f = {k: d.get(k) for k in Challenge.__dataclass_fields__}
        f["hard_rules"] = d.get("hard_rules") or []
        return Challenge(**f)


_SCHEMA = Path(__file__).resolve().parents[1] / "questions/schema.json"
_PREREG = Path(__file__).resolve().parents[1] / "analysis/preregistration.yaml"
_QUARANTINE = Path(__file__).resolve().parents[1] / "questions/quarantine.yaml"


def _quarantined() -> dict:
    """{item_id: reason} for items excluded because a known defect makes their scores
    uninterpretable. See questions/quarantine.yaml for why this exists rather than deleting the items
    or loosening the schema."""
    try:
        import yaml
        return (yaml.safe_load(_QUARANTINE.read_text()) or {}).get("quarantined", {}) or {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  [WARNING: could not read {_QUARANTINE.name} ({type(e).__name__}); "
              f"NO items quarantined this run]")
        return {}


def _prereg_directions() -> dict:
    """Per-category predicted directions, read from analysis/preregistration.yaml.

    They used to be a `predicted_direction` field on every item -- one value per category copied 50
    times, in an editable file, so it could evidence nothing about ordering. Records still carry the
    direction (so downstream analysis is unchanged) but it is now sourced from the registration."""
    try:
        import yaml
        return (yaml.safe_load(_PREREG.read_text()) or {}).get("predictions", {}) or {}
    except Exception as e:
        print(f"  [WARNING: could not read {_PREREG.name} ({type(e).__name__}); "
              f"predicted_direction will be null]")
        return {}


def load_challenges(path: str, validate: bool = True) -> list[Challenge]:
    """Load and (by default) VALIDATE against questions/schema.json.

    The schema shipped for months without ever being applied -- `grep -rn jsonschema` returned
    nothing -- so its `required` list was decorative and undeclared fields passed silently. Wiring it
    in here means a malformed item fails at load, not at score time. Soft-fails with a warning if
    jsonschema is not installed, so validation is never silently skipped without saying so."""
    raw = [json.loads(l) for l in open(path) if l.strip()]
    quar = _quarantined()
    if quar:
        dropped = [d["id"] for d in raw if d.get("id") in quar]
        raw = [d for d in raw if d.get("id") not in quar]
        if dropped:
            print(f"  [QUARANTINE: excluding {len(dropped)} item(s) with known defects: {dropped}. "
                  f"See questions/quarantine.yaml. These block a public release.]")
    if validate:
        try:
            import jsonschema
            schema = json.loads(_SCHEMA.read_text())
            v = jsonschema.Draft202012Validator(schema)
            errs = [f"{d.get('id','<no id>')}: {'/'.join(str(x) for x in e.path) or '<root>'}: {e.message}"
                    for d in raw for e in v.iter_errors(d)]
            if errs:
                raise ValueError(f"{len(errs)} schema violation(s) in {path}:\n  "
                                 + "\n  ".join(errs[:12])
                                 + (f"\n  ... and {len(errs)-12} more" if len(errs) > 12 else ""))
        except ImportError:
            print(f"  [WARNING: jsonschema not installed -- {_SCHEMA.name} NOT enforced this run]")
    directions = _prereg_directions()
    out = []
    for d in raw:
        ch = Challenge.from_json(d)
        ch.predicted_direction = directions.get(ch.category)   # from the registration, not the item
        out.append(ch)
    return out


def subset(challenges, per_category=None, limit=None, categories=None):
    """Balanced/limited slice for cheap pilots. categories: keep only these (e.g. ['C2','C3'])."""
    if categories:
        challenges = [c for c in challenges if c.category in set(categories)]
    if per_category:
        seen, sub = {}, []
        for ch in challenges:
            if seen.get(ch.category, 0) < per_category:
                sub.append(ch); seen[ch.category] = seen.get(ch.category, 0) + 1
        return sub
    return challenges[:limit] if limit else challenges


def _judges_list(per_judge: dict, panel=None, entrant_family: str | None = None) -> list:
    """per_judge {judge_id: {new,useful,surprising,...}} -> list-of-objects (ready for a rater random
    effect via json_normalize(record_path=['creativity','judges'])).

    Stamps `same_family` per judge so self-preference can be modelled as a COVARIATE instead of
    being excluded by fiat. Under LOFO this is always False (those judges were dropped); with the
    full panel it marks exactly the rows LOFO would have removed, which is what makes the two
    protocols directly comparable on one dataset."""
    fam = {j["id"]: j["family"] for j in (panel.judges if panel else [])}
    return [{"judge_id": jid, "same_family": bool(entrant_family and fam.get(jid) == entrant_family),
             **vals} for jid, vals in per_judge.items()]


_TERMINAL_ERR = ("insufficient_quota", "invalid_api_key", "authentication", "permission",
                 "credit balance", "quota", " 401", " 403", "billing")


def _one_task(ch, name, agent, panel, run_id, cb, cache=None):
    """Run one (challenge, agent): cache lookup -> circuit-breaker check -> agent -> grounding check
    -> LOFO panel. Judges score concurrently inside panel.score(). Returns (record, transcript,
    gate, scores, report, status). Raises to the caller on agent failure (or if circuit-broken).

    A cache HIT reuses a stored generation from any prior run keyed by (challenge text, agent,
    model), so re-scoring never re-pays for generation. Judging always runs fresh -- the panel or
    rubric may have changed since, and judge calls are the cheap part."""
    rid = f"{run_id}:{ch.id}:{name}"
    q_sha = query_sha(ch.query)
    report = cache.get(ch.id, name, agent.model, q_sha) if cache else None
    cached = report is not None
    if not cached:
        if name in cb["dead"]:                                # provider disabled -> skip cheaply
            raise RuntimeError(f"circuit_open:{name}")
        report = agent.run(ch.query)                          # may raise -> handled by caller
    gate = grounding_gate(report, ch)
    scores = panel.score(dataclasses.asdict(ch), report,
                         exclude_family=agent.model_family) if gate.passed else None
    if scores is None:
        # empty_answer is an ADAPTER failure, not a grounding failure -- keep them distinguishable
        status = ("empty_answer" if getattr(gate, "empty_answer", False)
                  else "grounding_fail") if not gate.passed else "judge_error"
    elif scores.n_judges < getattr(panel, "min_judges", 2):
        status = "judge_degraded"      # scored, but by too few judges to be a real LOFO panel
    else:
        status = "scored"
    rec = {
        "schema_version": R.RECORD_SCHEMA_VERSION,
        "record_id": rid, "run_id": run_id,
        "challenge_id": ch.id, "category": ch.category, "domain": ch.domain,
        "axis": ch.axis_isolated, "predicted_direction": ch.predicted_direction,
        "time_sensitivity": ch.time_sensitivity,   # was never written, so the pre/post-cutoff
                                                   # split it exists for was not computable
                                                   # even in principle from records.jsonl
        "agent": name, "model": agent.model, "model_family": agent.model_family,
        "query_sha": q_sha,                    # content address: invalidates if the prompt is edited
        "generation_cached": cached,           # True => generation reused, not re-paid for
        "cache_source_run": getattr(report, "source_run", None) if cached else None,
        # NB output_len_tokens is the provider's BILLED output count, which for reasoning models
        # INCLUDES invisible reasoning tokens. Measured tokens-per-visible-word: openai_shallow 2.0,
        # openai_deepresearch 6.1, gemini_deepresearch_max 10.0, claude_shallow 13.8 -- so it is NOT
        # a length measure and NOT comparable across arms. Using it as the length covariate gives
        # r=+0.05 with score and hides the real confound; visible words give r=+0.47, reproducing
        # the r=0.47 the source paper reported. Always length-control on answer_chars/answer_words.
        "output_len_tokens": report.n_tokens, "n_searches": report.n_searches,
        "answer_chars": len(report.text or ""),
        "answer_words": len((report.text or "").split()),
        "scoring_status": status,   # scored | judge_degraded | empty_answer | grounding_fail | judge_error
        "grounding": dataclasses.asdict(gate),
        "creativity": None if scores is None else {           # null on BOTH fail paths (never a fake 0)
            "new": scores.new, "useful": scores.useful, "surprising": scores.surprising,
            "creative_all_three": scores.creative_all_three,
            "n_judges": scores.n_judges,
            "judge_protocol": panel.protocol,
            "judges": _judges_list(scores.per_judge, panel, agent.model_family),
        },
    }
    tr = {"record_id": rid, "challenge_id": ch.id, "agent": name,
          "output_text": report.text, "citations": report.citations}
    return rec, tr, gate, scores, report, status


def evaluate(challenges, agents: dict, panel: JudgePanel, run_dir, run_id, concurrency=4,
             verbose=True, cache=None) -> list:
    """Core loop. Generation runs CONCURRENTLY across independent (challenge, agent) tasks (bounded
    by `concurrency`); each task's judge panel also scores concurrently. Degrades gracefully:
      - a failed task is logged to errors.jsonl (not silently dropped) and skipped;
      - a total judge-panel failure (e.g. judges out of quota) -> scoring_status='judge_error',
        creativity=null -- NEVER a fake 0 folded into results;
      - after >=3 auth/quota ('out of money') failures for an agent it is circuit-broken so a dead
        provider stops burning the rest of the task list.
    Cost control is the generation CACHE, not resumption: a task whose (challenge text, agent,
    model) was generated in any earlier run reuses that stored answer instead of re-paying, so every
    run is a complete, self-contained, immutable run_id. Writes records/transcripts/errors.jsonl."""
    run_dir = Path(run_dir)
    tasks = [(ch, name, agent) for ch in challenges for name, agent in agents.items()]
    records, mode = [], "w"
    if verbose:
        n_cached = sum(1 for ch, name, a in tasks
                       if cache and cache.get(ch.id, name, a.model, query_sha(ch.query))) if cache else 0
        print(f"running {len(challenges)} challenges x {len(agents)} agents = {len(tasks)} tasks "
              f"({n_cached} served from cache, {len(tasks)-n_cached} to generate; "
              f"concurrency={concurrency}); dir={run_dir}")
    cb = {"lock": threading.Lock(), "fails": collections.Counter(), "dead": set()}
    n_err, wlock = 0, threading.Lock()
    with (run_dir / "records.jsonl").open(mode) as fo, (run_dir / "transcripts.jsonl").open(mode) as ft, \
         (run_dir / "errors.jsonl").open(mode) as fe:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
            futs = {ex.submit(_one_task, ch, name, agent, panel, run_id, cb, cache): (ch, name)
                    for (ch, name, agent) in tasks}
            for fut in as_completed(futs):
                ch, name = futs[fut]
                try:
                    rec, tr, gate, scores, report, status = fut.result()
                except Exception as e:
                    msg = str(e)
                    if msg.startswith("circuit_open"):
                        continue                              # agent already disabled; skip quietly
                    with cb["lock"]:
                        cb["fails"][name] += 1
                        if any(k in msg.lower() for k in _TERMINAL_ERR) and cb["fails"][name] >= 3 \
                                and name not in cb["dead"]:
                            cb["dead"].add(name)
                            print(f"  [circuit] disabling '{name}' after repeated auth/quota failures")
                    with wlock:
                        fe.write(json.dumps({"record_id": f"{run_id}:{ch.id}:{name}", "challenge_id": ch.id,
                                             "agent": name, "status": "agent_error",
                                             "error_type": type(e).__name__, "error": msg[:200]},
                                            ensure_ascii=False) + "\n"); fe.flush()
                        n_err += 1
                    print(f"  [{ch.id}/{name}] AGENT FAILED: {type(e).__name__}: {msg[:120]}")
                    continue
                with wlock:                                   # thread-safe append (crash-safe JSONL)
                    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
                    ft.write(json.dumps(tr, ensure_ascii=False) + "\n"); ft.flush()
                    records.append(rec)
                if verbose:
                    tag = " CACHED" if rec.get("generation_cached") else ""
                    if status == "scored":
                        print(f"  [{ch.id}/{name}]{tag} cites={gate.n_citations} tok={report.n_tokens} "
                              f"N/U/S={scores.new:.0f}/{scores.useful:.0f}/{scores.surprising:.0f} "
                              f"creative={scores.creative_all_three} judges={scores.n_judges}")
                    elif status == "judge_degraded":
                        print(f"  [{ch.id}/{name}] JUDGE DEGRADED: only {scores.n_judges} judge(s) "
                              f"survived (< min_judges) -> flagged, excluded from headline numbers")
                    elif status == "judge_error":
                        print(f"  [{ch.id}/{name}] JUDGE ERROR (all judges failed) -> unscored")
                    else:
                        print(f"  [{ch.id}/{name}] grounding FAIL (cites={gate.n_citations}) -> unscored")
    print(f"wrote {run_dir}/records.jsonl  ({len(records)} records, {n_err} task errors)")
    return records


def make_manifest(run_id, created_at, benchmark, agents: dict, panel, budget, config_desc=None) -> dict:
    """Provenance manifest (finalize_run augments it with totals/env/outputs)."""
    return {
        "run_id": run_id, "created_at": created_at, "status": "completed",
        "code": R.git_info(Path(__file__).resolve().parents[2]),
        "config": config_desc or {"source": "cli"},
        "benchmark": benchmark,
        "execution_mode": {
            "retrieval_mode": "live_web", "contamination_controlled": False,
            "effective_corpus_date": created_at[:10],
            "contamination_caveat": ("Agents used LIVE web search; the open web may contain material "
                                     "about these challenges, so scores are NOT contamination-controlled. "
                                     "A frozen, date-bounded index is future work."),
        },
        "agents": [{"key": k, "model": a.model, "family": a.model_family,
                    "arm": "deep" if "deepresearch" in k else "shallow",
                    # Record the depth knob that ACTUALLY applies to this entrant. The global
                    # `budget` is the shallow-arm search cap (Anthropic max_uses) and is meaningless
                    # for the deep entrants -- reporting it for them would misstate how much search
                    # each agent was allowed, which is a live confound in cross-arm comparisons.
                    "depth": ({"reasoning_effort": a.effort, "max_tool_calls": a.max_tool_calls}
                              if hasattr(a, "max_tool_calls") else
                              {"managed_agent": a.model, "search_budget": "provider-managed (not cappable)"}
                              if "deepresearch" in k else
                              {"search_budget": budget}),
                    "model_id_note": "alias; pin a dated snapshot for camera-ready"}
                   for k, a in agents.items()],
        "depth_caveat": ("Deep- and shallow-arm entrants were NOT given equal search budgets (the "
                         "providers expose different, partly uncappable dials), so a cross-arm "
                         "difference confounds agent quality with evidence volume. Compare within "
                         "arm; treat depth as a factor, not as noise."),
        "judges": [{"id": j["id"], "model": j["model"], "family": j["family"]} for j in panel.judges],
        # Read from the PANEL, never hardcoded: this string said "leave-one-family-out" while the run
        # was full-panel, so the manifest -- the provenance record a reviewer trusts -- misdescribed
        # its own protocol.
        "judge_protocol": (f"{panel.protocol}; blind; "
                           f"{'median' if len(panel.judges) % 2 else 'mean-of-even-panel'} aggregation"),
    }


def run(args) -> None:
    from datetime import datetime, timezone
    challenges = subset(load_challenges(args.challenges), args.per_category, args.limit, args.categories)
    if args.index:
        FrozenIndex(args.index)   # raises (future work)
    agents = {name: build_agent(name, budget=args.budget) for name in args.agents}
    panel = JudgePanel.from_config(args.judge_config)
    repo_root = Path(__file__).resolve().parents[2]
    run_id, run_dir = R.new_run(args.out_root, args.subset, repo_root)
    created_at = datetime.now(timezone.utc).isoformat()
    cache = GenerationCache(args.out_root, enabled=not args.override_cache)
    recs = evaluate(challenges, agents, panel, run_dir, run_id,
                    concurrency=args.concurrency, cache=cache)
    manifest = make_manifest(run_id, created_at,
                             {"name": "crest", "challenges_file": args.challenges,
                              "item_count": len(challenges), "subset": args.subset,
                              "categories": sorted({c.category for c in challenges})},
                             agents, panel, args.budget)
    R.finalize_run(args.out_root, run_dir, run_id, recs, manifest)
    print(f"run dir: {run_dir}")
    print("next: python -m crest.analysis.stats --run", run_dir / "records.jsonl")


def main():
    p = argparse.ArgumentParser(description="Run the CREST creativity benchmark (ad-hoc CLI).")
    p.add_argument("--challenges", default="crest/questions/crest_challenges.jsonl")
    p.add_argument("--agents", nargs="+", required=True)
    p.add_argument("--index", default=None,
                   help="frozen shared index (contamination-controlled run). FUTURE WORK: raises. "
                        "Omit for LIVE provider-web-search mode.")
    p.add_argument("--judge_config", default="crest/judge/judge_config.live.yaml")
    p.add_argument("--budget", type=int, default=6, help="per-agent web-search cap (where the provider supports it)")
    p.add_argument("--concurrency", type=int, default=4, help="parallel (challenge, agent) tasks")
    p.add_argument("--per-category", type=int, default=None, dest="per_category")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--categories", nargs="+", default=None, help="keep only these categories, e.g. C2 C3")
    p.add_argument("--subset", default="adhoc", help="label for the run_id (e.g. pilot5cat, full50)")
    p.add_argument("--override-cache", action="store_true",
                   help="ignore cached generations from prior runs and re-generate them (RE-PAYS)")
    p.add_argument("--out-root", dest="out_root", default="crest/result")
    run(p.parse_args())


if __name__ == "__main__":
    main()
