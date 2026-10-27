"""Usage: python stage2_judge.py RESULT_DIR [--config crest.yaml]."""
from crest.cli import stage_main

if __name__ == '__main__':
    raise SystemExit(stage_main('judge'))
