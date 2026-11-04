"""Behavior added with the master configuration: prompts, word limits, flags and budgets."""
import asyncio
import json

import pytest

from crest import caesar_worker, cli
from crest.config import load_config
from crest.costs import assess_cost
from crest.pipeline import Pipeline, _answer_words
from crest.providers import openai


@pytest.mark.parametrize("dotted, value, message", [
    ("answer_word_limit", 0, "answer_word_limit must be a positive integer"),
    ("answer_word_limit", None, "exactly when an answer_word_limit applies"),
    ("research.openai.answer_word_limit", 2.5, "research.openai.answer_word_limit"),
    ("research.caesar.use_research_prompt", "no", "use_research_prompt must be a boolean"),
    ("research.anthropic.effort", "ultra", "effort must be low, medium, high, xhigh or max"),
    ("research.openai.search_context_size", "huge", "search_context_size must be"),
    ("research.anthropic.web_fetch", 1, "web_fetch must be a boolean"),
    ("research.anthropic.max_web_searches", 0, "max_web_searches must be a positive integer"),
    ("research.caesar.budget_cap", "firm", "budget_cap must be hard, soft or auto"),
    ("research.gemini.budget_cap", "hard", "budget_cap must be soft"),
])
def test_master_config_rejects_invalid_flags(write_master_config, dotted, value, message):
    with pytest.raises(ValueError, match=message):
        load_config(write_master_config(**{dotted: value}))


def test_prompts_without_placeholders_are_allowed_only_when_no_limit_applies(write_master_config):
    config = load_config(write_master_config(**{"answer_word_limit": None, "research_prompt": "Q: {question}",
                                                "research_continuation_prompt": "Spent {spent} of {floor}-{ceiling}."}))
    assert all(settings["answer_word_limit"] is None for settings in config["research"].values())
    with pytest.raises(ValueError, match="continuation_prompt"):
        load_config(write_master_config(**{"answer_word_limit": None, "research_prompt": "Q: {question}"}))


def test_answer_words_ignores_the_appended_sources_block():
    assert _answer_words("one two three\n\nSources:\nhttps://a.example\nhttps://b.example") == 3
    assert _answer_words("Abstract\nfour words in all\n\nSources\n[1] https://a.example") == 5


def test_generation_records_word_counts_and_flags_long_answers(tmp_path, write_master_config):
    questions = tmp_path / "q.jsonl"
    questions.write_text(json.dumps({"query": "Q?"}) + "\n")
    config = load_config(write_master_config(**{"questions": str(questions), "answer_word_limit": 3,
                                                "cache_dir": str(tmp_path / "cache"), "output_dir": str(tmp_path / "out")}))
    config["research"] = {"openai": config["research"]["openai"], "caesar": config["research"]["caesar"]}
    class Provider:
        ADAPTER_VERSION = "fixture"
        def __init__(self, text): self.text, self.prompts = text, []
        async def generate(self, prompt, settings, job):
            self.prompts.append(prompt)
            return {"text": self.text, "citations": [{"url": "https://s.example", "title": "S"}], "model": "m",
                    "usage": {}, "cost_usd": .1, "cost_estimated": True, "warnings": [], "raw": {}}
    providers = {"openai": Provider("far too many words here"), "caesar": Provider("short")}
    pipeline = Pipeline(config, providers=providers)
    summary = asyncio.run(pipeline.generate())
    rows = {json.loads(line)["agent"]: json.loads(line)
            for line in (tmp_path / "out").rglob("answers.jsonl").__next__().read_text().splitlines()}
    assert rows["openai"]["result"]["word_count"] == 5 and rows["openai"]["result"]["word_limit_exceeded"] is True
    assert any("limit is 3" in w for w in rows["openai"]["result"]["warnings"])
    assert rows["caesar"]["result"]["word_count"] == 1 and "word_limit_exceeded" not in rows["caesar"]["result"]
    assert providers["caesar"].prompts == ["Q?"]
    assert providers["openai"].prompts[0].startswith("### QUERY\n\nQ?") and "at most 3 words" in providers["openai"].prompts[0]
    assert summary["completed"] == 2


def test_openai_payload_carries_the_search_context_size():
    payload = openai._payload("p", {"search_context_size": "high"}, False)
    assert payload["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert "search_context_size" not in openai._payload("p", {}, False)["tools"][0]


def test_caesar_worker_passes_the_word_limit_and_single_budget(tmp_path):
    config = caesar_worker.build_config("Q", {"answer_word_limit": 600, "budget_usd": 4.0}, tmp_path, "w")
    assert config["ArtifactSynthesizer"]["synthesis_max_length"] == 600
    assert config["LLMHandler"]["cost_limit"] == 4.0


def test_anthropic_results_are_priced_from_usage():
    details = assess_cost({"model": "claude-sonnet-5-5", "cost_usd": .3, "usage": {}, "raw": {}}, agent="anthropic")
    assert details["cost_basis"] == "usage_priced_estimate"
    assert details["pricing"]["tool_rates"]["web_search_per_request_usd"] == .01


def test_cli_rejects_unknown_agents_and_judges(write_master_config, capsys):
    path = write_master_config()
    with pytest.raises(SystemExit):
        cli.main(["plan", "--config", str(path), "--agents", "mystery"])
    assert "Unknown agents: mystery" in capsys.readouterr().err


@pytest.mark.parametrize("dotted, value, message", [
    ("research.openai.budget_floor_usd", 5.0, "at most budget_usd"),
    ("research.anthropic.budget_floor_usd", 0, "budget_floor_usd must be positive"),
    ("research.openai.continuation_prompt", "no placeholders here", "must contain"),
    ("research.openai.max_research_rounds", 0, "max_research_rounds must be a positive integer"),
])
def test_budget_range_flags_are_validated(write_master_config, dotted, value, message):
    with pytest.raises(ValueError, match=message):
        load_config(write_master_config(**{dotted: value}))


@pytest.mark.parametrize("cost, exceeded", [(3.75, False), (4.0, False), (4.25, True)])
def test_all_research_answers_complete_with_warnings_only_above_four_dollars(tmp_path, write_master_config, cost, exceeded):
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"query": "Design a new game."}) + "\n")
    config = load_config(write_master_config(**{
        "questions": str(questions), "cache_dir": str(tmp_path / "cache"),
        "output_dir": str(tmp_path / "results"),
    }))
    class Provider:
        ADAPTER_VERSION = "offline-budget-check"
        async def generate(self, prompt, settings, job):
            return {"text": "A complete answer.", "model": "offline", "cost_usd": cost,
                    "citations": [], "usage": {}, "raw": {}, "warnings": []}
    pipeline = Pipeline(config, providers={name: Provider() for name in config["research"]})
    summary = asyncio.run(pipeline.generate())
    assert summary["completed"] == 4
    answer_path = next((tmp_path / "results").rglob("answers.jsonl"))
    rows = [json.loads(line) for line in answer_path.read_text().splitlines()]
    assert {row["agent"] for row in rows} == {"caesar", "openai", "gemini", "anthropic"}
    for row in rows:
        result = row["result"]
        assert result.get("budget_exceeded", False) is exceeded, row["agent"]
        warnings = [warning for warning in result["warnings"] if "budget" in warning]
        assert bool(warnings) is exceeded
        if exceeded:
            assert "$4.00" in warnings[0] and "soft cap" in warnings[0]


def test_budget_range_defaults_apply_only_to_hosted_single_call_agents():
    config = load_config()
    for name in ("openai", "anthropic"):
        settings = config["research"][name]
        assert settings["budget_floor_usd"] == 3.0 and settings["budget_usd"] == 4.0
        assert settings["continuation_prompt"] == config["research_continuation_prompt"]
    for name in ("caesar", "gemini"):
        assert "budget_floor_usd" not in config["research"][name]


def test_another_round_must_land_near_the_floor_and_under_the_ceiling():
    from crest.providers import needs_more_research
    settings = {"budget_usd": 4.0, "budget_floor_usd": 3.0, "max_research_rounds": 6}
    assert needs_more_research(settings, 2, 0.98, 0.68)          # 1.66 projected: still short of the floor
    assert not needs_more_research(settings, 3, 2.78, 1.80)      # 4.58 projected: past the ceiling
    assert not needs_more_research(settings, 3, 2.40, 1.40)      # 3.80 projected overshoots 3.0 by more than the 0.60 shortfall
    assert needs_more_research(settings, 3, 2.80, 0.25)          # 3.05 projected: overshoot 0.05 within the 0.20 shortfall
    assert not needs_more_research(settings, 1, 3.2, 0.1)        # floor reached
    assert not needs_more_research(settings, 6, 1.0, 0.1)        # round cap
    assert not needs_more_research(settings, 1, None, 0.1)       # unknown cost never continues


def test_soft_cap_rounds_aim_at_the_floor_but_ignore_the_ceiling():
    from crest.providers import budget_is_hard, needs_more_research
    soft = {"budget_cap": "soft", "budget_usd": 3.0, "budget_floor_usd": 3.0, "max_research_rounds": 6}
    assert needs_more_research(soft, 3, 2.80, 0.25)           # 3.05 projected: over the ceiling, inside the aim's shortfall
    assert not needs_more_research({**soft, "budget_cap": "hard"}, 3, 2.80, 0.25)  # the hard cap stops at the ceiling
    assert not needs_more_research(soft, 3, 2.50, 1.20)       # 3.70 projected overshoots the aim by more than the 0.50 shortfall
    assert not needs_more_research(soft, 3, 3.05, 0.5)        # the floor is reached
    assert not needs_more_research(soft, 6, 1.0, 0.5)         # rounds exhausted
    assert not needs_more_research({**soft, "budget_floor_usd": None}, 1, 1.0, 0.5)  # no aim: one round
    assert budget_is_hard({"budget_cap": "auto"}) and budget_is_hard({}) and not budget_is_hard(soft)


def test_auto_cap_overrides_configured_depth_and_reports_every_override(write_master_config, capsys):
    from crest.budget import plan
    config = load_config(write_master_config(**{"research.caesar.budget_cap": "auto", "research.caesar.budget_usd": 3.5,
                                                "research.openai.budget_cap": "auto", "research.openai.budget_usd": 3.5}))
    caesar, hosted = config["research"]["caesar"], config["research"]["openai"]
    derived = plan("caesar", 3.5, {"max_completion_tokens": 10000})["settings"]
    assert {k: caesar[k] for k in derived} == derived and derived["max_iterations"] != 300  # 300/3/20 overridden
    assert (hosted["budget_floor_usd"], hosted["max_research_rounds"]) == (2.62, 6)
    changed = {(o["agent"], o["setting"]): (o["from"], o["to"]) for o in config["budget_overrides"]}
    assert changed[("caesar", "max_iterations")] == (300, derived["max_iterations"])
    assert changed[("caesar", "synthesis_iterations")] == (20, derived["synthesis_iterations"])
    assert ("caesar", "synthesis_drafts") not in changed  # unchanged values are not reported
    assert changed[("openai", "budget_floor_usd")] == (3.0, 2.62)
    err = capsys.readouterr().err
    assert f"budget_cap auto: research.caesar.max_iterations 300 -> {derived['max_iterations']} (derived from budget_usd 3.5 by crest/budget.py)" in err
    assert "research.openai.budget_floor_usd 3.0 -> 2.62" in err
    assert load_config()["budget_overrides"] == []  # soft caps override nothing


def test_soft_and_hard_caps_require_explicit_caesar_depth(write_master_config):
    with pytest.raises(ValueError, match="must be set when budget_cap is soft"):
        load_config(write_master_config(**{"research.caesar.max_iterations": None}))


def test_hard_caesar_cap_rejects_depth_above_the_budget_while_soft_keeps_it(write_master_config):
    with pytest.raises(ValueError, match="above budget_usd"):
        load_config(write_master_config(**{"research.caesar.budget_cap": "hard", "research.caesar.budget_usd": 2.0}))
    soft = load_config(write_master_config(**{"research.caesar.budget_usd": 2.0}))["research"]["caesar"]
    assert soft["max_iterations"] == 300 and soft["budget_cap"] == "soft"
