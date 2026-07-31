"""Shared helper for the per-entrant eval scripts in this dir.

Each `eval_*.py` script is a thin wrapper that evaluates ONE entrant on CREST (handy for running
a single model, or a cheap per-category pilot of it) and writes an immutable run dir under
crest/result/runs/<run_id>/. For a multi-agent run driven by a config file, use crest/run_eval.py.

Every script goes through `cli()`, which gives it the SAME front door as run_eval.py: --dry-run,
--yes, key preflight and the cost guard. Without it these were five zero-argument scripts that went
straight from import to spending -- `eval_claude_sonnet.py --help` silently started a real 50-item
run and ignored the flag.
"""
import argparse, sys
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]      # .../rome
sys.path.insert(0, str(REPO))

from crest.harness.run_crest import load_challenges, subset, evaluate, make_manifest
from crest.harness.agents import build_agent
from crest.harness import results as R
from crest.harness.cache import GenerationCache
from crest.judge.score import JudgePanel


def run_one(agent_key, per_category=None, limit=None, categories=None, budget=6, concurrency=4,
            override_cache=False):
    """Evaluate a single entrant on CREST (optionally a subset). Resumes an interrupted run for the
    same entrant by default (skip already-done pairs). Returns the run dir Path."""
    challenges = subset(load_challenges(str(REPO / "crest/questions/crest_challenges.jsonl")),
                        per_category, limit, categories)
    panel = JudgePanel.from_config(str(REPO / "crest/judge/judge_config.live.yaml"))
    agents = {agent_key: build_agent(agent_key, budget=budget)}
    out_root = REPO / "crest/result"
    # --resume was removed: a run is immutable and prior work is reused through the cross-run
    # GENERATION CACHE instead (keyed on challenge text + agent + model + adapter fingerprint), so
    # every run mints a fresh run_id. These scripts previously called R.find_resumable /
    # R.completed_pairs, which no longer exist -- so all five eval/*.py entry points raised
    # AttributeError before making a single API call.
    run_id, run_dir = R.new_run(out_root, agent_key, REPO)
    created = datetime.now(timezone.utc).isoformat()
    print(f"evaluating {agent_key} ({agents[agent_key].model}) on {len(challenges)} challenges -> {run_dir}")
    cache = GenerationCache(out_root, enabled=not override_cache)
    recs = evaluate(challenges, agents, panel, run_dir, run_id, concurrency=concurrency,
                    cache=cache)
    R.finalize_run(out_root, run_dir, run_id, recs, make_manifest(
        run_id, created,
        {"name": "crest", "challenges_file": "crest/questions/crest_challenges.jsonl",
         "item_count": len(challenges), "subset": agent_key,
         "categories": sorted({c.category for c in challenges})},
        agents, panel, budget))
    print(f"run dir: {run_dir}")
    return run_dir


def cli(agent_key: str, **defaults):
    """Argument-parsing front door for a single-entrant eval script. Runs the same preflight and
    cost guard as run_eval.py before anything is spent."""
    from crest.run_eval import preflight, confirm_cost           # same guards, one definition
    ap = argparse.ArgumentParser(description=f"Evaluate {agent_key} on CREST.")
    ap.add_argument("--per-category", type=int, default=defaults.get("per_category"),
                    help="N challenges per category (cheap balanced pilot)")
    ap.add_argument("--limit", type=int, default=defaults.get("limit"))
    ap.add_argument("--categories", nargs="+", default=defaults.get("categories"))
    ap.add_argument("--budget", type=int, default=defaults.get("budget", 6))
    ap.add_argument("--concurrency", type=int, default=defaults.get("concurrency", 4))
    ap.add_argument("--override-cache", action="store_true",
                    help="re-generate instead of reusing prior runs' answers (RE-PAYS)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve challenges + preflight keys; make no model calls")
    ap.add_argument("--yes", action="store_true", help="confirm a large or costly run")
    a = ap.parse_args()

    challenges = subset(load_challenges(str(REPO / "crest/questions/crest_challenges.jsonl")),
                        a.per_category, a.limit, a.categories)
    panel = JudgePanel.from_config(str(REPO / "crest/judge/judge_config.live.yaml"))
    agents = {agent_key: build_agent(agent_key, budget=a.budget)}
    preflight(agents, panel, enforce=not a.dry_run)
    print(f"{agent_key} ({agents[agent_key].model}) x {len(challenges)} challenges "
          f"x {len(panel.judges)} judges")
    if a.dry_run:
        print("[dry-run] nothing spent")
        return None
    confirm_cost(len(challenges), [agent_key], a.yes)
    return run_one(agent_key, per_category=a.per_category, limit=a.limit, categories=a.categories,
                   budget=a.budget, concurrency=a.concurrency, override_cache=a.override_cache)
