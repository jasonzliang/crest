# Judging prompts

Versioned pairwise rubrics, selected by `rubric` in [crest.yaml](../configs/crest.yaml).

- [nus_pairwise_v2.txt](nus_pairwise_v2.txt): current default New, Useful, and Surprising rubric.
- [nus_pairwise_v1.txt](nus_pairwise_v1.txt): original NUS wording, retained here for reproduction.
- [aut_pairwise_v1.txt](aut_pairwise_v1.txt): alternative AUT-inspired creativity rubric.

Each asks for one overall A/B winner and a comparative explanation, not criterion scores.
Research and continuation instructions are separate settings in the master YAML.

Keep historical rubric wording fixed; put revised instruments in a new versioned file.
Changing a rubric changes judgment-cache keys; the saved answers can still be reused.
