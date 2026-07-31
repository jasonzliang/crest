#!/usr/bin/env python3
"""Evaluate the OpenAI Deep Research API, mini (o4-mini-deep-research) on CREST — faster/cheaper
than o3-deep-research.
    python crest/eval/eval_openai_deepresearch_mini.py"""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import cli

if __name__ == "__main__":
    cli("openai_deepresearch_mini", per_category=1)   # start small; override with --per-category
