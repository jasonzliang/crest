"""Master configuration: validation, word limits, prompts and question loading.

Also checks that configured flags reach generation jobs and provider payloads.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from crest import cli
from crest.config import load_config, load_questions
from crest.pipeline import Pipeline, _answer_words
from crest.providers import caesar_worker, continuation_prompt, openai


CAPPED_RESEARCH_PROMPT = "### QUERY\n\n{question}\n\nThe final response must be at most {max_words} words."
CAPPED_CONTINUATION_PROMPT = "Spent ${spent} of ${floor}-${ceiling}; keep the response to at most {max_words} words."
AGENTS = {"caesar", "openai", "gemini", "anthropic", "gpt_researcher"}


def offline_config(tmp_path, write_master_config, **overrides):
    """The master config with one question and every write under tmp_path."""
    questions = tmp_path / "q.jsonl"
    questions.write_text(json.dumps({"query": "Q?"}) + "\n")
    return load_config(write_master_config(**{
        "questions": str(questions), "cache_dir": str(tmp_path / "cache"),
        "output_dir": str(tmp_path / "out"), **overrides}))


def answer_rows(tmp_path):
    path = next((tmp_path / "out").rglob("answers.jsonl"))
    return {row["agent"]: row for row in map(json.loads, path.read_text().splitlines())}


class FixedProvider:
    ADAPTER_VERSION = "offline-fixture"

    def __init__(self, text, citations=()):
        self.text, self.citations, self.prompts = text, list(citations), []

    async def generate(self, prompt, settings, job):
        self.prompts.append(prompt)
        return {"text": self.text, "model": "offline", "cost_usd": .1, "citations": self.citations,
                "usage": {}, "raw": {}, "warnings": []}


@pytest.mark.parametrize("dotted, value, message", [
    ("answer_word_limit", 0, "answer_word_limit must be a positive integer"),
    ("answer_word_limit", 600, "exactly when an answer_word_limit applies"),
    ("research.openai.answer_word_limit", 2.5, "research.openai.answer_word_limit"),
    ("research.caesar.use_research_prompt", "no", "use_research_prompt must be a boolean"),
    ("research.anthropic.effort", "ultra", "effort must be low, medium, high, xhigh or max"),
    ("research.openai.search_context_size", "huge", "search_context_size must be"),
    ("research.anthropic.web_fetch", 1, "web_fetch must be a boolean"),
    ("research.anthropic.max_web_searches", 0, "max_web_searches must be a positive integer"),
    ("research.caesar.budget_cap", "firm", "budget_cap must be hard, soft or auto"),
    ("research.gemini.budget_cap", "hard", "budget_cap must be soft"),
    ("research.openai.budget_floor_usd", 5.0, "at most budget_usd"),
    ("research.anthropic.budget_floor_usd", 0, "budget_floor_usd must be positive"),
    ("research.openai.continuation_prompt", "no placeholders here", "must contain"),
    ("research.openai.max_research_rounds", 0, "max_research_rounds must be a positive integer"),
    # Only the Anthropic sections take model_pricing, and every rate there must be finite and nonnegative.
    *[(f"{section}.anthropic.model_pricing", {model: {**rates, "output": bad}}, "nonnegative finite")
      for section, model, rates in [
          ("research", "claude-opus-5-5", {"input": 4.4, "cached_input": .22, "cache_write_5m": 5.5, "web_search": 0}),
          ("judges", "claude-opus-5-5", {"input": 4.4, "cached_input": .22, "cache_write_5m": 5.5, "web_search": .01})]
      for bad in (float("nan"), float("inf"), -1, "11")],
    *[(f"{section}.{name}.model_pricing", {"gpt-6.1-sol": {"input": float("nan"), "output": 10}},
       "Unknown configuration field: model_pricing")
      for section, name in [("research", "caesar"), ("research", "gpt_researcher"), ("research", "openai"),
                            ("research", "gemini"), ("judges", "openai"), ("judges", "gemini")]],
])
def test_master_config_rejects_invalid_flags(write_master_config, dotted, value, message):
    with pytest.raises(ValueError, match=message):
        load_config(write_master_config(**{dotted: value}))


@pytest.mark.parametrize("limit", [None, 750])
@pytest.mark.parametrize("capped_research", [False, True])
@pytest.mark.parametrize("capped_continuation", [False, True])
def test_prompt_placeholders_must_match_the_effective_limit(
        write_master_config, limit, capped_research, capped_continuation):
    path = write_master_config(**{
        "answer_word_limit": limit,
        "research_prompt": CAPPED_RESEARCH_PROMPT if capped_research else "Q: {question}",
        "research_continuation_prompt": (CAPPED_CONTINUATION_PROMPT if capped_continuation
                                         else "Spent {spent} of {floor}-{ceiling}."),
    })
    if capped_research != (limit is not None):
        with pytest.raises(ValueError, match="research_prompt must contain.*exactly when"):
            load_config(path)
    elif capped_continuation != (limit is not None):
        with pytest.raises(ValueError, match="continuation_prompt must contain.*exactly when"):
            load_config(path)
    else:
        config = load_config(path)
        assert all(settings["answer_word_limit"] == limit for settings in config["research"].values())


def test_custom_numeric_limits_render_for_every_agent(tmp_path, write_master_config):
    config = offline_config(tmp_path, write_master_config, **{
        "answer_word_limit": 750,
        "research_prompt": CAPPED_RESEARCH_PROMPT,
        "research_continuation_prompt": CAPPED_CONTINUATION_PROMPT,
        "research.openai.answer_word_limit": 900,
        "research.gpt_researcher.answer_word_limit": 1200,
        "research.caesar.answer_word_limit": 300,
    })
    pipeline = Pipeline(config, limit=1, providers={name: object() for name in config["research"]})
    limits = {"caesar": 300, "openai": 900, "gemini": 750, "anthropic": 750, "gpt_researcher": 1200}
    for task in pipeline.generation_jobs():
        name, settings = task["agent"], task["settings"]
        assert settings["answer_word_limit"] == limits[name]
        if name == "caesar":
            assert task["prompt"] == pipeline.questions[0]["text"]
        else:
            assert f"at most {limits[name]} words" in task["prompt"]
            assert "{max_words}" not in task["prompt"]
        if settings.get("continuation_prompt") is not None:
            assert f"at most {limits[name]} words" in continuation_prompt(settings, 1.25)


@pytest.mark.parametrize("source", ["python_defaults", "master_yaml"])
def test_default_generation_accepts_uncapped_long_answers_for_every_agent(
        tmp_path, write_master_config, source):
    questions = tmp_path / "q.jsonl"
    questions.write_text(json.dumps({"query": "Q?"}) + "\n")
    overrides = {"questions": str(questions), "cache_dir": str(tmp_path / "cache"),
                 "output_dir": str(tmp_path / "out")}
    if source == "master_yaml":
        path = write_master_config(**overrides)
    else:
        path = tmp_path / "defaults.yaml"
        path.write_text(json.dumps(overrides))
    config = load_config(path)
    answer = " ".join(["evidence"] * 750)
    pipeline = Pipeline(config, providers={name: FixedProvider(answer) for name in config["research"]})
    summary = asyncio.run(pipeline.generate())
    assert summary["completed"] == 5 and summary["failed"] == 0
    rows = answer_rows(tmp_path)
    assert set(rows) == AGENTS
    for name, row in rows.items():
        result = row["result"]
        assert result["text"] == answer and result["word_count"] == 750
        assert "word_limit_exceeded" not in result, name
        assert result["warnings"] == [], name
    assert config["answer_word_limit"] is None
    for task in pipeline.generation_jobs():
        assert task["settings"]["answer_word_limit"] is None, task["agent"]
        assert "{max_words}" not in task["prompt"] and "at most 600 words" not in task["prompt"]
    for name in ("openai", "anthropic"):
        prompt = continuation_prompt(config["research"][name], 1.25)
        assert "$1.25 of a $4.00 research budget" in prompt
        assert "{" not in prompt and "None" not in prompt and "words" not in prompt


def test_answer_words_ignores_the_appended_sources_block():
    assert _answer_words("one two three\n\nSources:\nhttps://a.example\nhttps://b.example") == 3
    assert _answer_words("Abstract\nfour words in all\n\nSources\n[1] https://a.example") == 5


def test_generation_records_word_counts_and_flags_long_answers(tmp_path, write_master_config):
    config = offline_config(tmp_path, write_master_config, **{
        "answer_word_limit": 3, "research_prompt": CAPPED_RESEARCH_PROMPT,
        "research_continuation_prompt": CAPPED_CONTINUATION_PROMPT})
    config["research"] = {"openai": config["research"]["openai"], "caesar": config["research"]["caesar"]}
    source = [{"url": "https://s.example", "title": "S"}]
    providers = {"openai": FixedProvider("far too many words here", source), "caesar": FixedProvider("short", source)}
    summary = asyncio.run(Pipeline(config, providers=providers).generate())
    assert summary["completed"] == 2
    rows = answer_rows(tmp_path)
    assert rows["openai"]["result"]["word_count"] == 5 and rows["openai"]["result"]["word_limit_exceeded"] is True
    assert any("limit is 3" in w for w in rows["openai"]["result"]["warnings"])
    assert rows["caesar"]["result"]["word_count"] == 1 and "word_limit_exceeded" not in rows["caesar"]["result"]
    assert providers["caesar"].prompts == ["Q?"]
    prompt = providers["openai"].prompts[0]
    assert prompt.startswith("### QUERY\n\nQ?") and "at most 3 words" in prompt


def test_openai_payload_carries_the_search_context_size():
    payload = openai._payload("p", {"search_context_size": "high"}, False)
    assert payload["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert "search_context_size" not in openai._payload("p", {}, False)["tools"][0]


@pytest.mark.parametrize("limit", [None, 600, 1200])
def test_caesar_worker_passes_the_word_limit_and_single_budget(tmp_path, limit):
    config = caesar_worker.build_config("Q", {"answer_word_limit": limit, "budget_usd": 4.0}, tmp_path, "w")
    assert config["ArtifactSynthesizer"]["synthesis_max_length"] == limit
    assert config["LLMHandler"]["cost_limit"] == 4.0


def test_cli_rejects_unknown_agents(write_master_config, capsys):
    path = write_master_config()
    with pytest.raises(SystemExit):
        cli.main(["plan", "--config", str(path), "--agents", "mystery"])
    assert "Unknown agents: mystery" in capsys.readouterr().err


def test_hosted_agents_run_a_fixed_number_of_follow_ups_without_a_floor():
    config = load_config()
    for name, rounds in (("openai", 5), ("anthropic", 7)):
        settings = config["research"][name]
        assert settings["budget_floor_usd"] is None and settings["max_research_rounds"] == rounds
        assert settings["budget_usd"] == 4.0
        assert settings["continuation_prompt"] == config["research_continuation_prompt"]
        assert "{floor}" not in settings["continuation_prompt"]
    for name in ("caesar", "gemini"):
        assert "budget_floor_usd" not in config["research"][name]


def test_a_single_round_needs_no_continuation_prompt(write_master_config):
    settings = load_config(write_master_config(**{"research.openai.max_research_rounds": 1}))["research"]["openai"]
    assert settings["continuation_prompt"] is None


def test_an_explicit_floor_still_opts_in_to_follow_up_rounds(write_master_config):
    settings = load_config(write_master_config(**{
        "research.openai.budget_floor_usd": 3.0,
        "research.openai.continuation_prompt": "Spent {spent} of {floor}-{ceiling}."}))["research"]["openai"]
    assert continuation_prompt(settings, 1.25) == "Spent 1.25 of 3.00-4.00."


@pytest.mark.parametrize("cap", ["soft", "hard"])
def test_soft_and_hard_caps_require_explicit_caesar_depth(write_master_config, cap):
    with pytest.raises(ValueError, match=f"must be set when budget_cap is {cap}"):
        load_config(write_master_config(**{"research.caesar.max_iterations": None,
                                         "research.caesar.budget_cap": cap}))


def test_hard_caesar_cap_rejects_depth_above_the_budget_while_soft_keeps_it(write_master_config):
    with pytest.raises(ValueError, match="above budget_usd"):
        load_config(write_master_config(**{"research.caesar.budget_cap": "hard", "research.caesar.budget_usd": 2.0}))
    soft = load_config(write_master_config(**{"research.caesar.budget_usd": 2.0,
                                            "research.caesar.budget_cap": "soft"}))["research"]["caesar"]
    assert soft["max_iterations"] == 300 and soft["budget_cap"] == "soft"


@pytest.mark.parametrize('metadata', [{}, {'category': 'Cross-Domain Synthesis'}])
def test_questions_retain_optional_category_without_changing_text_or_id(tmp_path, metadata):
    path = tmp_path / 'questions.jsonl'
    path.write_text(json.dumps({'id': 'given-id', 'query': '  exact question?  ', **metadata}) + '\n')
    assert load_questions(path) == [{'id': 'given-id', 'text': '  exact question?  ', **metadata}]


def test_category_metadata_does_not_change_derived_id_prompt_or_generation_key(tmp_path):
    path = tmp_path / 'questions.jsonl'
    row = {'query': '  exact question?  '}
    path.write_text(json.dumps(row) + '\n')
    config = {
        'questions': str(path), 'cache_dir': str(tmp_path / 'cache'),
        'research_prompt': 'QUESTION:\n{question}', 'research': {'openai': {}},
    }
    providers = {'openai': SimpleNamespace(ADAPTER_VERSION='fixture-v1')}
    original = Pipeline(config, providers=providers)
    original_jobs = original.generation_jobs()

    row['category'] = 'Cross-Domain Synthesis'
    path.write_text(json.dumps(row) + '\n')
    categorized = Pipeline(config, providers=providers)

    assert categorized.questions[0]['category'] == 'Cross-Domain Synthesis'
    assert categorized.questions[0]['id'] == original.questions[0]['id']
    assert categorized.generation_jobs() == original_jobs
    assert original_jobs[0]['prompt'] == 'QUESTION:\n  exact question?  '


@pytest.mark.parametrize("value, ok", [
    (None, True),
    ({"model": "claude-sonnet-5-5", "rates": {"input": 2.2, "cached_input": 0.11, "cache_write_5m": 2.75,
                                               "output": 11.0, "web_search": 0.0}}, True),
    ({"model": "", "rates": {}}, False),
    ({"model": "claude-sonnet-5-5"}, False),
    ({"model": "claude-sonnet-5-5", "rates": {"input": -1, "cached_input": 0, "cache_write_5m": 0,
                                               "output": 0, "web_search": 0}}, False),
])
def test_judge_refusal_substitute_needs_a_model_and_its_rates(write_master_config, value, ok):
    path = write_master_config(**{"judges.anthropic.refusal_substitute": value})
    if ok:
        assert load_config(path)["judges"]["anthropic"]["refusal_substitute"] == value
    else:
        with pytest.raises(ValueError, match="refusal_substitute"):
            load_config(path)
