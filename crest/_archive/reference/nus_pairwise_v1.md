# Archived judging rubrics

`nus_pairwise_v1.txt` is the original New, Useful, and Surprising rubric. Its text is retained byte-for-byte for reproducing earlier judgments. The active default remains `../../prompts/nus_pairwise_v2.txt`.

The AIS path `../../../crest_ais/prompts/rubric_v1.txt` remains a compatibility link directly to this archived file. The former `../../prompts/nus_pairwise_v1.txt` shortcut has been removed. Archiving did not change the prompt content, judgment keys, or saved results. Select the archived file explicitly when recreating a v1 comparison. Do not substitute v2 into an earlier run's saved prompts or pool its judgments into that run's ranking.

## Why v2 is the default

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
