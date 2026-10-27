"""Usage: python stage3_analyze.py RESULT_DIR [--config crest.yaml]."""
from crest.cli import stage_main

if __name__ == '__main__':
    raise SystemExit(stage_main('analyze'))
