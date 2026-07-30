#!/usr/bin/env python3
"""Evaluate GPT-5.6 (gpt-5.6 + Responses web_search) on CREST.
    python crest/eval/eval_gpt56.py"""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import run_one

if __name__ == "__main__":
    run_one("openai_shallow")          # e.g. run_one("openai_shallow", per_category=2)
