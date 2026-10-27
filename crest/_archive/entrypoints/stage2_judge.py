"""Usage: python crest/stage2_judge.py RESULT_DIR [--config PATH]."""
if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crest.cli import stage_main

if __name__ == '__main__':
    raise SystemExit(stage_main('judge'))
