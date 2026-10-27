#!/usr/bin/env python3
"""Evaluate `claude_shallow` (claude-sonnet-5 + web_search) on CREST -- shallow arm.
Run from the repo root; --help for the subset/cost flags, readme.md for the entrant table."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import cli

if __name__ == "__main__":
    cli("claude_shallow")
