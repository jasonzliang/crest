"""The command-line entry point for the research pipeline."""
import argparse
import asyncio
import json
from pathlib import Path

from .config import DEFAULT_CONFIG, load_config
from .pipeline import Pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(description='CREST: cached research → binary pairwise judging → ranking')
    parser.add_argument('stage', choices=['plan', 'generate', 'judge', 'analyze', 'run'], nargs='?', default='plan')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--run', type=Path, help='Generation result directory; later stages default to latest run')
    parser.add_argument('--limit', type=int, help='First N questions for a new generation run')
    parser.add_argument('--agents', nargs='+', choices=['caesar', 'openai', 'gemini'])
    parser.add_argument('--judges', nargs='+', choices=['openai', 'gemini'])
    parser.add_argument('--dry-run', action='store_true', help='Plan only; no API calls or new run directories')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.agents:
            config['research'] = {k: config['research'][k] for k in dict.fromkeys(args.agents)}
        if args.judges:
            config['judges'] = {k: config['judges'][k] for k in dict.fromkeys(args.judges)}
        run = args.run
        if run and args.agents:
            raise ValueError('An existing run keeps its agent snapshot; use a new generation run to change agents')
        if not run and args.stage in {'judge', 'analyze'}:
            root = Path(config['output_dir'])
            latest = root / '.cache' / 'latest.json'
            if not latest.exists():
                latest = root / 'latest.json'
            if not latest.exists():
                raise ValueError('No generation run yet. Run python -m crest generate first or pass --run PATH')
            run = Path(json.loads(latest.read_text())['run_dir'])
        if args.limit is not None and run:
            raise ValueError('--limit applies only to a new generation run; existing runs keep their question snapshot')
        pipeline = Pipeline(config, run_dir=run, limit=args.limit)
        if args.stage == 'plan' or args.dry_run:
            result = pipeline.plan()
        elif args.stage == 'analyze':
            result = pipeline.analyze()
        else:
            pipeline.preflight(args.stage)
            result = asyncio.run(getattr(pipeline, args.stage)())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('failed', 0) or result.get('unavailable', 0) else 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f'crest: {exc}\n')
    except KeyboardInterrupt:
        print('Interrupted. Checkpoints are preserved; resume with --run PATH. Remote jobs may still be running.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
