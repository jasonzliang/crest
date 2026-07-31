# Judge protocol — design intent vs implemented behaviour

> Moved out of `judge/judge_config.yaml` on 2026-07-31. That file was shaped like a config but was
> read by **no code path** (every caller defaults to `judge_config.live.yaml`), which made it a
> trap: `JudgePanel.from_config` loaded it happily with placeholder model IDs
> (`claude-opus-4-8-YYYYMMDD`), no `min_judges`, and no `leave_one_family_out` key — so pointing
> anything at it would silently revert LOFO to True. The live config is
> `judge/judge_config.live.yaml`; this file is documentation only and must never be loaded.

# CREST judge panel configuration.
# Multi-vendor + >=1 open-weight; leave-one-family-out is enforced in score.py.
# Pin dated model snapshots for reproducibility (record exact IDs at run time).

# WHICH KEYS ARE ACTUALLY READ. JudgePanel.from_config reads ONLY: judges, threshold_all_three,
# min_judges, leave_one_family_out. Everything else in this file is INTENT, not implemented
# behaviour, and is marked [NOT IMPLEMENTED] below. Shipping unimplemented controls in a config
# that a reviewer reads as evidence is how three of this project's claims became indefensible.
threshold_all_three: 6.0        # READ. min per-axis score for "creative" (all three required).
                                # NB not the primary endpoint any more -- see judge_config.live.yaml.
blind: true                     # DE FACTO TRUE, not a switch: _judge_prompt carries no agent name.
# randomize_answer_order: true  # [NOT IMPLEMENTED] and VACUOUS: scoring is single-answer, not
                                # pairwise, so there is no answer order to randomize. Removed rather
                                # than left asserting a control that does not exist.

judges:
  - id: judge_anthropic
    model: claude-opus-4-8-YYYYMMDD     # pin exact dated snapshot
    family: anthropic
  - id: judge_google
    model: gemini-3-pro-YYYYMMDD
    family: google
  - id: judge_openai
    model: gpt-5.2-YYYYMMDD              # dropped under LOFO when the entrant is OpenAI-family (e.g., Caesar)
    family: openai
  - id: judge_open_weight
    model: <open-weight-judge>-YYYYMMDD  # required: fewer shared blind spots than the frontier trio
    family: open_weight

reliability:
  report: [krippendorff_alpha, icc]     # IMPLEMENTED in analysis/stats.py::
                                        # reliability_report() -- ICC(1,1), ICC(1,k), Krippendorff
                                        # alpha (interval) and per-judge severity. Measured on the
                                        # NB run-specific: ICC(1,k) was .774/.746/.671 on run 111856Z but .527/.631/.445 on a later
                                        # run -- recompute per run, never quote a fixed figure.
  human_validation_required_categories: [C1, C2, C3, C4, C5]   # human panel validates all; primary on C1/C5

grounding_gate:
  metric: fact_precision                # [NOT IMPLEMENTED] the shipped gate is a regex cue-counter
                                        # (score.py::grounding_gate, honestly labelled a PILOT proxy
                                        # in code). This key declares a materially STRONGER gate
                                        # than the one that runs -- do not cite it as implemented.
  threshold: 0.8                        # below => creativity score = 0
