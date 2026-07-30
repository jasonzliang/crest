"""Shared helper for the per-entrant eval scripts in this dir.

Each `eval_*.py` script is a thin wrapper that evaluates ONE entrant on CREST (handy for running
a single model, or a cheap per-category pilot of it) and writes an immutable run dir under
crest/result/runs/<run_id>/. For a multi-agent run driven by a config file, use crest/run_eval.py.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]      # .../rome
sys.path.insert(0, str(REPO))

from crest.harness.run_crest import load_challenges, subset, evaluate, make_manifest
from crest.harness.agents import build_agent
from crest.harness import results as R
from crest.judge.score import JudgePanel


def run_one(agent_key, per_category=None, limit=None, categories=None, budget=6):
    """Evaluate a single entrant on CREST (optionally a subset). Returns the run dir Path."""
    challenges = subset(load_challenges(str(REPO / "crest/questions/crest_challenges.jsonl")),
                        per_category, limit, categories)
    panel = JudgePanel.from_config(str(REPO / "crest/judge/judge_config.live.yaml"))
    agents = {agent_key: build_agent(agent_key, budget=budget)}
    out_root = REPO / "crest/result"
    run_id, run_dir = R.new_run(out_root, agent_key, REPO)
    created = datetime.now(timezone.utc).isoformat()
    print(f"evaluating {agent_key} ({agents[agent_key].model}) on {len(challenges)} challenges -> {run_dir}")
    recs = evaluate(challenges, agents, panel, run_dir, run_id)
    R.finalize_run(out_root, run_dir, run_id, recs, make_manifest(
        run_id, created,
        {"name": "crest", "challenges_file": "crest/questions/crest_challenges.jsonl",
         "item_count": len(challenges), "subset": agent_key,
         "categories": sorted({c.category for c in challenges})},
        agents, panel, budget))
    print(f"run dir: {run_dir}")
    return run_dir
