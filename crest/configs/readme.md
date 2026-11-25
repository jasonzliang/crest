# Run configuration

[crest.yaml](crest.yaml) is the master configuration for the research pipeline.
Defaults and validation live in [../config.py](../config.py).

- Select question sets, judging rubrics, output/cache paths, and provider settings here.
- Configure models, prompts, budgets, depth, and concurrency here rather than in adapters.
- Relative paths resolve from the selected YAML file's directory.
- Credentials come from the environment; never put secret values in YAML.

From the repository root, `python -m crest plan` previews work without paid calls.
Generation and judging can make paid calls; review settings before running them.
Existing runs retain their frozen generation settings.
Changing judges or rubrics can create new judging stages without regenerating answers.
Transport settings (concurrency, retries, and the Anthropic judge's `refusal_substitute`) are not part of cache keys and apply when a run resumes.
See the [pipeline guide](../../docs/research-pipeline.html) for overrides and resuming.
