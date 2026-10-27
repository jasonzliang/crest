"""Prepare, freeze, judge, and report the released-paper comparison."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sys
import uuid

import yaml

from crest.cache import write_json
from crest.config import DEFAULT_CONFIG as CREST_DEFAULT_CONFIG
from .catalog import DEFAULT_AGENTS, prepare_catalog
from .pipeline import create_cohort_extension, create_extension, load_results, run_judging, save_plan
from .protocol import make_plan

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_ROOT / "configs" / "config.json"


def load_config(path: Path | None = None, *, data_root: Path | None = None) -> dict:
    """Resolve explicit config paths; credentials are never read from files."""
    path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    root = Path(data_root).expanduser().resolve() if data_root else (base / config.get("data_root", ".")).resolve()
    config["data_root"] = root
    config["output_dir"] = (root / config.get("output_dir", "results")).resolve()
    config["rubric"] = (base / config.get("rubric", "rubric.txt")).resolve()
    inheritance = (base / config.get("inherit_judges", CREST_DEFAULT_CONFIG)).resolve()
    inherited = yaml.safe_load(inheritance.read_text(encoding="utf-8"))
    judges = inherited.get("judges", {})
    overrides = config.get("judges", {})
    if set(judges) != {"openai", "gemini"} or set(overrides) - set(judges):
        raise ValueError("Judges must be exactly openai and gemini")
    resolved = {}
    for name, settings in sorted(judges.items()):
        from importlib import import_module
        adapter = import_module("crest_ais.providers." + name)
        merged = {**settings, **overrides.get(name, {})}
        merged.update(concurrency=min(2, max(1, int(merged.get("concurrency", 2)))),
                      initial_concurrency=min(2, max(1, int(merged.get("initial_concurrency", 2)))),
                      timeout_seconds=900, poll_interval_seconds=5,
                      _adapter_version=adapter.ADAPTER_VERSION)
        resolved[name] = merged
    config["judges"] = resolved
    return config


def _new_plan(config, args):
    root = config["data_root"]
    catalog = prepare_catalog(root, agents=list(DEFAULT_AGENTS))
    agents = {}
    for name in DEFAULT_AGENTS:
        manifest = json.loads((root / "data" / name / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("agent_id") != name:
            raise ValueError(f"Collection identity differs from expected scientist: {name}")
        agents[name] = manifest.get("display_name", name)
    rubric = config["rubric"].read_text(encoding="utf-8")
    return make_plan(catalog, agents, config["judges"], root, rubric,
                     pairs_per_matchup=args.pairs_per_matchup if args.pairs_per_matchup is not None else config.get("pairs_per_matchup", 10),
                     seed=args.seed if args.seed is not None else config.get("seed", 2026))


def _run_path(config, args, *, create=False):
    if args.run_dir:
        return Path(args.run_dir).expanduser().resolve()
    output = config["output_dir"]
    if create:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        return output / (stamp + "-" + uuid.uuid4().hex[:8])
    latest = output / "latest.json"
    if not latest.exists():
        raise ValueError("No planned run exists; run the plan command first or provide --run-dir")
    return Path(json.loads(latest.read_text(encoding="utf-8"))["run_dir"]).resolve()


def _report(plan, run_dir, root, destination):
    from .analysis import analyze
    from .report import write_report
    report = analyze(plan, load_results(run_dir))
    # Analysis operates on successful verdicts only. Include every observed paid
    # failure when presenting run-level accounting, without fabricating votes.
    accounting_path = run_dir / "judging.json"
    if accounting_path.exists():
        accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
        successful_known = report["costs"]["known_usd"]
        successful_unknown = report["costs"]["unknown_jobs"]
        failures_path = run_dir / "failures.json"
        failures = json.loads(failures_path.read_text(encoding="utf-8")) if failures_path.exists() else []
        failed_known = sum(failure["cost_usd"] for failure in failures if failure.get("cost_usd") is not None)
        report["costs"].update(successful_known_usd=successful_known, successful_unknown_jobs=successful_unknown,
                              failed_known_usd=failed_known,
                              failed_unknown_jobs=sum(failure.get("cost_usd") is None for failure in failures),
                              accounting_note="Run-wide estimates use recorded provider usage, including failed paid outputs; unknown usage remains unavailable.")
        report["costs"]["known_usd"] = accounting["known_usd"]
        report["costs"]["unknown_jobs"] = accounting["unknown_cost_jobs"]
        if accounting["failed_jobs"]:
            report["limitations"].append(f"{accounting['failed_jobs']} judging jobs failed; paid failures are retained in the run audit and included in observed cost accounting (${failed_known:.6f} known failed-output cost).")
    prior_path = run_dir / "prior_costs.json"
    if prior_path.exists():
        from .pipeline import _money
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        prior_known = _money(prior.get("known_usd"))
        prior_unknown, prior_jobs = prior.get("unknown_jobs"), prior.get("job_count")
        if prior_known is None or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                                      for value in (prior_unknown, prior_jobs)):
            raise ValueError("prior_costs.json requires nonnegative known_usd and integer unknown_jobs/job_count")
        costs = report["costs"]
        costs.update(current_run_known_usd=costs["known_usd"], current_run_unknown_jobs=costs["unknown_jobs"],
                     prior_excluded_jobs=prior_jobs, prior_excluded_known_usd=prior_known,
                     prior_excluded_unknown_jobs=prior_unknown, prior_source_run=prior.get("source_run"))
        costs["known_usd"] += prior_known
        costs["unknown_jobs"] += prior_unknown
        costs["accounting_note"] = "Total estimates include current-run usage and prior excluded judging attempts; excluded attempts contribute no ranking decisions."
        costs["prior_exclusion_reason"] = prior.get("reason", "")
        report["limitations"].append(f"{prior_jobs} prior judging attempts were excluded from rankings; their known cost ${prior_known:.6f} and {prior_unknown} unknown-cost attempts remain included in total accounting.")
    imports_path = run_dir / "imported_results.json"
    if plan.get("extension") and imports_path.exists():
        imported_keys = {row["key"] for row in json.loads(imports_path.read_text(encoding="utf-8"))}
        retained = sum(row["key"] in imported_keys for row in report["judgments"])
        saved = report["coverage"]["completed_jobs"]
        report["limitations"].append(f"The {saved} saved overall judgments include {retained} retained from the previous run and {saved - retained} additional judgments. All use the same overall-judgment protocol.")
    write_json(run_dir / "analysis.json", report)
    write_report(report, destination, data_root=root)
    return report


def _add_options(parser, *, suppressed=False):
    default = argparse.SUPPRESS if suppressed else None
    parser.add_argument("--config", type=Path, default=default)
    parser.add_argument("--data-root", type=Path, default=default)
    parser.add_argument("--run-dir", "--run", dest="run_dir", type=Path, default=default)
    parser.add_argument("--source-run", type=Path, default=default, help="completed frozen parent run for extend/add-agent")
    parser.add_argument("--agent", type=str, default=default, help="new collection id for add-agent")
    parser.add_argument("--pairs-per-matchup", type=int, default=default)
    parser.add_argument("--seed", type=int, default=default)
    parser.add_argument("--max-spend-usd", type=float, default=default)
    parser.add_argument("--workers-per-judge", type=int, choices=range(1, 17), default=default,
                        help="operational worker count per judge (1-16); frozen requests remain unchanged")
    parser.add_argument("--report-path", type=Path, default=default)
    parser.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS if suppressed else False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    _add_options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "plan", "extend", "add-agent", "judge", "report", "run"):
        sub = subparsers.add_parser(name)
        _add_options(sub, suppressed=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"extend", "add-agent"}:
            if args.source_run is None:
                raise ValueError("extend/add-agent requires --source-run pointing to a completed frozen overall run")
            # Storage paths come from config; sampling, content, rubric, and
            # judge settings come entirely from the frozen parent snapshot.
            config_path = args.config.expanduser().resolve() if args.config else DEFAULT_CONFIG
            storage = json.loads(config_path.read_text(encoding="utf-8"))
            root = args.data_root.expanduser().resolve() if args.data_root else (config_path.parent / storage.get("data_root", ".")).resolve()
            output = (root / storage.get("output_dir", "results")).resolve()
            run_dir = _run_path({"output_dir": output}, args, create=True)
            source = args.source_run.expanduser().resolve()
            if args.command == "add-agent":
                if args.agent is None or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", args.agent):
                    raise ValueError("add-agent requires --agent with a collection id")
                parent = json.loads((source / "plan.json").read_text(encoding="utf-8"))
                if args.agent in parent["agents"]:
                    raise ValueError("Added agent already exists in the frozen parent cohort")
                manifest = json.loads((root / "data" / args.agent / "manifest.json").read_text(encoding="utf-8"))
                if manifest.get("agent_id") != args.agent:
                    raise ValueError("New collection identity differs from --agent")
                new_catalog = prepare_catalog(root, agents=[args.agent],
                    output_dir=root / "results" / "prepared" / "add-agent" / args.agent)
                plan = create_cohort_extension(source, run_dir, root, new_catalog=new_catalog,
                    new_agents={args.agent: manifest.get("display_name", args.agent)},
                    pairs_per_matchup=args.pairs_per_matchup, addition_seed=args.seed if args.seed is not None else 2026)
            else:
                plan = create_extension(source, run_dir, root,
                    pairs_per_matchup=args.pairs_per_matchup if args.pairs_per_matchup is not None else 10,
                    extension_seed=args.seed if args.seed is not None else 2026)
            write_json(output / "latest.json", {"run_dir": str(run_dir), "created_at": plan["created_at"]})
            print(json.dumps({"run_dir": str(run_dir), "expected_jobs": len(plan["jobs"]),
                              "sampled_pairs": plan["selection"]["sampled_pairs"], "selected_papers": len(plan["papers"]),
                              "imported_jobs": plan["extension"]["original_pairs"] * 4,
                              "additional_jobs": plan["extension"]["additional_pairs"] * 4}, indent=2))
            return 0
        config = load_config(args.config, data_root=args.data_root)
        root = config["data_root"]
        if args.command == "prepare":
            catalog = prepare_catalog(root)
            print(json.dumps({"catalog": str(root / "results" / "prepared" / "catalog.json"),
                              "downloaded_papers": len(catalog),
                              "eligible_papers": sum(paper["eligible_primary"] for paper in catalog)}, indent=2))
            return 0
        create = args.command in {"plan", "run"}
        run_dir = _run_path(config, args, create=create)
        if create and not (run_dir / "plan.json").exists():
            plan = _new_plan(config, args)
            save_plan(plan, run_dir)
            write_json(config["output_dir"] / "latest.json", {"run_dir": str(run_dir), "created_at": plan["created_at"]})
        else:
            plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        if args.command in {"judge", "run"}:
            asyncio.run(run_judging(plan, run_dir, progress=not args.quiet,
                                   max_spend_usd=args.max_spend_usd if args.max_spend_usd is not None else config.get("max_spend_usd", 100),
                                   workers_per_judge=args.workers_per_judge))
        summary = {"run_dir": str(run_dir), "expected_jobs": len(plan["jobs"]),
                   "sampled_pairs": plan["selection"]["sampled_pairs"], "selected_papers": len(plan["papers"])}
        if args.command in {"report", "run"}:
            destination = args.report_path.expanduser().resolve() if args.report_path else PACKAGE_ROOT.parent / "docs" / "ai-scientist-creativity.html"
            report = _report(plan, run_dir, root, destination)
            summary.update(report=str(destination), status=report["status"], completed_jobs=report["coverage"]["completed_jobs"])
        print(json.dumps(summary, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        # Credentials are never included in CLI error output.
        from .pipeline import _safe_error
        print(_safe_error(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
