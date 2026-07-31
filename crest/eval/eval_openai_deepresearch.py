#!/usr/bin/env python3
"""Evaluate the OpenAI Deep Research API (o3-deep-research) on CREST.
    python crest/eval/eval_openai_deepresearch.py
Purpose-built multi-step research agent (web_search_preview). SLOW + costly: minutes per query;
start with a small subset (e.g. per_category=1) before a full 50-item run."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import cli

if __name__ == "__main__":
    cli("openai_deepresearch", per_category=1)   # start small; override with --per-category
