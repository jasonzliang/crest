#!/usr/bin/env python3
"""Evaluate Gemini 3 Pro (gemini-3.1-pro-preview + google_search grounding) on CREST.
    python crest/eval/eval_gemini3pro.py
NB: gemini-3-pro / -preview are deprecated on the current key; gemini-3.1-pro-preview is the
working Gemini-3 Pro. This grounded config is also Gemini's deep-research equivalent."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import run_one

if __name__ == "__main__":
    run_one("gemini_dr")          # e.g. run_one("gemini_dr", per_category=2)
