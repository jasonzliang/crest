# Archived judging rubrics

[nus_pairwise_v1.txt](../../prompts/nus_pairwise_v1.txt) is the original New, Useful, and Surprising rubric, stored with the versioned prompts. Saved judge stages keep the exact rubric text they used, so earlier judgments remain reproducible from their saved stages. The active default is [NUS v3](../../prompts/nus_pairwise_v3.txt).

The [AIS v1 alias](../../../crest_ais/prompts/rubric_v1.txt) points to the canonical v1 prompt; the old `reference/nus_pairwise_v1.txt` copy is no longer present. Relocation did not change the prompt content, judgment keys, or saved results. Select the v1 prompt explicitly when recreating a v1 comparison. Do not substitute v2 into an earlier run's saved prompts or pool its judgments into that run's ranking.

## Why v2 replaced v1

- **Originality concerns the contribution.** V1 rewards the least recognizable component and excludes combinations from New. V2 assesses the central contribution, including meaningful combinations, and does not let an obscure peripheral detail determine originality.
- **Unfamiliarity is uncertainty.** V2 explicitly rejects failure to recall prior art as proof of historical novelty and requires support for named precedents.
- **Usefulness depends on the task.** V2 accepts stipulated fictional and counterfactual premises, distinguishes exploratory proposals from claimed results, and avoids demanding finished-product evidence from an early idea.
- **Surprise must contribute.** V2 does not treat incoherent or unsupported departures as sufficient evidence of creative quality.
- **Close comparisons need not invent differences.** V2 explains the existing protocol's forced-choice convention when no substantive preference is supported. Both answer orders are judged; the convention splits votes evenly if applied consistently and is not a substantive preference.

This is a design review, not an empirical validation. Agreement with human experts and robustness across question categories would require a separate evaluation. No rubric text was changed during archival.

Original v1 SHA-256:

```text
a70eba755b64d489c0872448476e6148c33e4b145506ea79bbe705b62db7d65e
```
