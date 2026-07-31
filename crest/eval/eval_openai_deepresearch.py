#!/usr/bin/env python3
"""Evaluate `openai_deepresearch` on CREST -- deep arm, ~$9/task.

gpt-5.6-sol + `web_search` + background=True, effort=high, max_tool_calls=40. Not a dedicated SKU:
o3-deep-research was shut down 2026-07-23, so OpenAI deep research is now this pattern with depth
dialed by reasoning effort + tool-call cap. SLOW (minutes per query) and costly, hence the
per_category=1 default -- pilot before widening with --per-category / --limit."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import cli

if __name__ == "__main__":
    cli("openai_deepresearch", per_category=1)
