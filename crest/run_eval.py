#!/usr/bin/env python3
"""CREST evaluation entry point (config-driven).

    python crest/run_eval.py                          # uses crest/config/eval_config.yaml
    python crest/run_eval.py --config <path>

Edit crest/config/eval_config.yaml to choose which benchmark(s) + subset, which agents, and the
judge panel. Each benchmark produces an immutable run directory under <out_root>/runs/<run_id>/
(records.jsonl + transcripts.jsonl + run_manifest.json + summary.json); see crest/result/readme.md.
Runnable from any cwd.
"""
import argparse, sys, shutil
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]      # .../rome  -> makes `import crest...` work anywhere
sys.path.insert(0, str(REPO))

import yaml
from crest.harness.run_crest import load_challenges, subset, evaluate, make_manifest
from crest.harness.agents import build_agent
from crest.harness import results as R
from crest.judge.score import JudgePanel


def _p(path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (REPO / p)


def _label(bench, n) -> str:
    if bench.get("per_category"): return f"per{bench['per_category']}cat"
    if bench.get("limit"):        return f"first{bench['limit']}"
    if bench.get("categories"):   return "cats-" + "-".join(bench["categories"])
    return f"full{n}"


def main():
    ap = argparse.ArgumentParser(description="Run CREST from a config file.")
    ap.add_argument("--config", default=str(REPO / "crest/config/eval_config.yaml"))
    ap.add_argument("--dry-run", action="store_true", help="resolve config + agents + challenges, but do not call any model")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(_p(args.config)))
    budget = cfg.get("budget", 6)
    out_root = _p(cfg.get("out_root", "crest/result"))
    panel = JudgePanel.from_config(str(_p(cfg["judge_config"])))
    agents = {k: build_agent(k, budget=budget) for k in cfg["agents"]}
    print(f"config: {args.config}")
    print(f"agents: {[(k, a.model) for k, a in agents.items()]}")
    print(f"judges: {[(j['id'], j['model']) for j in panel.judges]}")

    for bench in cfg["benchmarks"]:
        chs = subset(load_challenges(str(_p(bench["challenges"]))),
                     bench.get("per_category"), bench.get("limit"), bench.get("categories"))
        label = bench.get("subset_label") or _label(bench, len(chs))
        print(f"\n=== benchmark '{bench['name']}': {len(chs)} challenges x {len(agents)} agents (subset={label})")
        if args.dry_run:
            print("  [dry-run] would evaluate; no model calls made.")
            continue
        run_id, run_dir = R.new_run(out_root, label, REPO)
        shutil.copy(_p(args.config), run_dir / "config.snapshot.yaml")   # literal config as-run
        created = datetime.now(timezone.utc).isoformat()
        recs = evaluate(chs, agents, panel, run_dir, run_id, concurrency=cfg.get("concurrency", 4))
        manifest = make_manifest(run_id, created,
            {"name": bench["name"], "challenges_file": bench["challenges"],
             "item_count": len(chs), "subset": label,
             "categories": sorted({c.category for c in chs})},
            agents, panel, budget, config_desc={"source": str(args.config)})
        R.finalize_run(out_root, run_dir, run_id, recs, manifest)
        print(f"  run_id={run_id}")
        print(f"  analyze: python -m crest.analysis.stats --run {run_dir / 'records.jsonl'}")


if __name__ == "__main__":
    main()
