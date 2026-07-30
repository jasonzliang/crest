#!/usr/bin/env python3
"""Evaluate the Gemini "deep research" configuration on CREST.
    python crest/eval/eval_gemini_deepresearch.py
NB: Gemini exposes no separate Deep Research *model* via the API (Deep Research is an app feature),
so the API deep-research equivalent is grounded Gemini-Pro (gemini-3.1-pro-preview + google_search)
-- identical to eval_gemini3pro.py. Kept as a distinct entry for parity with the OpenAI DR script."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import run_one

if __name__ == "__main__":
    run_one("gemini_deepresearch")
