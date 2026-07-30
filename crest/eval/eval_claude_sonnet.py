#!/usr/bin/env python3
"""Evaluate Claude Sonnet 5 (claude-sonnet-5 + web_search) on CREST.
    python crest/eval/eval_claude_sonnet.py
Add per_category=2 (below) for a cheap balanced 10-item pilot."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import run_one

if __name__ == "__main__":
    run_one("claude_dr")          # e.g. run_one("claude_dr", per_category=2)
