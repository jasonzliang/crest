# Question sets

Versioned research questions: one JSON object per line.

- [queries_n50_v1.jsonl](queries_n50_v1.jsonl): original set used by historical comparisons.
- [queries_n50_v2.jsonl](queries_n50_v2.jsonl): current default set, with generator provenance.

Each bundled set has 50 records with `query`, `category`, and `generated_by` fields.
The loader in [../config.py](../config.py) normalizes them into pipeline question records.
Select the input through `questions` in [../configs/crest.yaml](../configs/crest.yaml).

Preserve exact question text and version provenance; changes affect cache identities.
Create a new dataset version instead of rewriting inputs behind historical results.
