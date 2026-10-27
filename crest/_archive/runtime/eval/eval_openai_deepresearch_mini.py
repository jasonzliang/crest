#!/usr/bin/env python3
"""Evaluate `openai_deepresearch_mini` on CREST -- deep arm, cheaper depth setting (~$2-4/task).

Same pattern and model as `openai_deepresearch` (gpt-5.6-sol, background=True) with effort=medium
and max_tool_calls=15; it replaces the shut-down o4-mini-deep-research. Still minutes per query,
hence the per_category=1 default -- pilot before widening with --per-category / --limit."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import cli

if __name__ == "__main__":
    cli("openai_deepresearch_mini", per_category=1)
