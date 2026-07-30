"""CREST evaluation core.

Runs each entrant agent on the CREST challenges via LIVE provider-native web search (a frozen
shared index for a contamination-controlled run is future work; see agents.FrozenIndex), applies
the factual-grounding check, scores creativity with a leave-one-family-out judge panel, and writes
an immutable per-run result directory (records.jsonl + transcripts.jsonl + manifest + summary; see
harness/results.py).

`evaluate()` is the reusable core; both this module's CLI and the top-level `run_eval.py`
config-driven entry point call it.

CLI (single ad-hoc run):
    python -m crest.harness.run_crest --agents claude_dr openai_dr gemini_dr --subset adhoc
For config-driven, multi-agent runs, prefer:  python crest/run_eval.py
"""
from __future__ import annotations
import argparse, json, dataclasses, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from crest.harness.agents import build_agent, FrozenIndex
from crest.harness import results as R
from crest.judge.score import JudgePanel, grounding_gate


@dataclasses.dataclass
class Challenge:
    id: str; category: str; domain: str; query: str
    axis_isolated: str; time_sensitivity: str
    known_answers: list; hard_rules: list; expert_baseline: str
    predicted_direction: str; rationale: str = ""

    @staticmethod
    def from_json(d: dict) -> "Challenge":
        f = {k: d.get(k) for k in Challenge.__dataclass_fields__}
        f["hard_rules"] = d.get("hard_rules") or []
        return Challenge(**f)


def load_challenges(path: str) -> list[Challenge]:
    return [Challenge.from_json(json.loads(l)) for l in open(path) if l.strip()]


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


def _judges_list(per_judge: dict) -> list:
    """per_judge {judge_id: {new,useful,surprising,...}} -> list-of-objects (LOFO-safe; ready for a
    rater random effect via json_normalize(record_path=['creativity','judges']))."""
    return [{"judge_id": jid, **vals} for jid, vals in per_judge.items()]


def _one_task(ch, name, agent, panel, run_id):
    """Run one (challenge, agent): agent -> grounding check -> LOFO judge panel. Returns
    (record, transcript). Judges run concurrently inside panel.score()."""
    rid = f"{run_id}:{ch.id}:{name}"
    report = agent.run(ch.query)                              # may raise -> handled by caller
    gate = grounding_gate(report, ch)
    scores = panel.score(dataclasses.asdict(ch), report,
                         exclude_family=agent.model_family) if gate.passed else None
    rec = {
        "schema_version": R.RECORD_SCHEMA_VERSION,
        "record_id": rid, "run_id": run_id,
        "challenge_id": ch.id, "category": ch.category, "domain": ch.domain,
        "axis": ch.axis_isolated, "predicted_direction": ch.predicted_direction,
        "agent": name, "model": agent.model, "model_family": agent.model_family,
        "output_len_tokens": report.n_tokens, "n_searches": report.n_searches,
        "grounding": dataclasses.asdict(gate),
        "creativity": None if scores is None else {
            "new": scores.new, "useful": scores.useful, "surprising": scores.surprising,
            "creative_all_three": scores.creative_all_three,
            "n_judges": scores.n_judges, "judges": _judges_list(scores.per_judge),
        },
    }
    tr = {"record_id": rid, "challenge_id": ch.id, "agent": name,
          "output_text": report.text, "citations": report.citations}
    return rec, tr, gate, scores, report


def evaluate(challenges, agents: dict, panel: JudgePanel, run_dir, run_id, concurrency=4, verbose=True) -> list:
    """Core loop. Generation runs CONCURRENTLY across independent (challenge, agent) tasks (bounded
    by `concurrency`); each task's judge panel also scores concurrently. Writes run_dir/records.jsonl
    (analysis-grade) + run_dir/transcripts.jsonl (heavy output text + citations). Returns records."""
    run_dir = Path(run_dir)
    tasks = [(ch, name, agent) for ch in challenges for name, agent in agents.items()]
    if verbose:
        print(f"running {len(challenges)} challenges x {len(agents)} agents = {len(tasks)} tasks "
              f"(LIVE web, concurrency={concurrency}); dir={run_dir}")
    records, lock = [], threading.Lock()
    with (run_dir / "records.jsonl").open("w") as fo, (run_dir / "transcripts.jsonl").open("w") as ft:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
            futs = {ex.submit(_one_task, ch, name, agent, panel, run_id): (ch, name)
                    for (ch, name, agent) in tasks}
            for fut in as_completed(futs):
                ch, name = futs[fut]
                try:
                    rec, tr, gate, scores, report = fut.result()
                except Exception as e:
                    print(f"  [{ch.id}/{name}] AGENT FAILED: {type(e).__name__}: {str(e)[:140]}")
                    continue
                with lock:                                    # thread-safe append (crash-safe JSONL)
                    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
                    ft.write(json.dumps(tr, ensure_ascii=False) + "\n"); ft.flush()
                    records.append(rec)
                if verbose:
                    if scores is None:
                        print(f"  [{ch.id}/{name}] grounding FAIL (cites={gate.n_citations}) -> creativity 0")
                    else:
                        print(f"  [{ch.id}/{name}] cites={gate.n_citations} tok={report.n_tokens} "
                              f"N/U/S={scores.new:.0f}/{scores.useful:.0f}/{scores.surprising:.0f} "
                              f"creative={scores.creative_all_three} judges={scores.n_judges}")
    print(f"wrote {run_dir}/records.jsonl  ({len(records)} records)")
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
                    "budget": budget, "model_id_note": "alias; pin a dated snapshot for camera-ready"}
                   for k, a in agents.items()],
        "judges": [{"id": j["id"], "model": j["model"], "family": j["family"]} for j in panel.judges],
        "judge_protocol": "leave-one-family-out; blind; median aggregation",
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
    recs = evaluate(challenges, agents, panel, run_dir, run_id, concurrency=args.concurrency)
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
    p.add_argument("--out-root", dest="out_root", default="crest/result")
    run(p.parse_args())


if __name__ == "__main__":
    main()
