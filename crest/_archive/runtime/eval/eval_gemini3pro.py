#!/usr/bin/env python3
"""Evaluate `gemini_shallow` (gemini-3.1-pro-preview + google_search grounding) on CREST.

Shallow arm. This is NOT Gemini's deep-research equivalent: Google ships deep research as a separate
turnkey agent (entrants `gemini_deepresearch` / `_max`). NB gemini-3-pro and gemini-3-pro-preview are
deprecated on the current key; gemini-3.1-pro-preview is the working Gemini-3 Pro."""
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crest.eval._common import cli

if __name__ == "__main__":
    cli("gemini_shallow")
