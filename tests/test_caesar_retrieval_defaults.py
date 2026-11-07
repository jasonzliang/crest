"""Keep Caesar retrieval defaults and main-text word accounting explicit."""
from pathlib import Path

import pytest
import yaml

from crest.caesar_worker import build_config, extract_result
from crest.config import load_config
from crest.pipeline import _answer_words

ROOT = Path(__file__).resolve().parents[1]


def assert_retrieval(config, top_k, top_n, *, reranking=True):
    assert config["ArtifactSynthesizer"]["synthesis_top_k"] == top_k
    assert config["ArtifactSynthesizer"]["synthesis_top_n"] == top_n
    kb = config["ChromaClientManager"]
    assert kb["enable_reranking"] is reranking
    assert kb["top_k"] == kb["rerank_top_k"] == top_k
    assert kb["rerank_top_n"] == top_n


def test_shipped_preset_uses_fifty_ten(tmp_path):
    settings = yaml.safe_load((ROOT / "crest/configs/crest.yaml").read_text())["research"]["caesar"]
    assert settings["enable_reranking"] is True
    assert_retrieval(build_config("Question", settings, tmp_path, "preset"), 50, 10)


def test_python_config_defaults_use_fifty_ten(tmp_path):
    from crest.config import DEFAULTS

    settings = DEFAULTS["research"]["caesar"]
    assert settings["enable_reranking"] is True
    assert_retrieval(build_config("Question", settings, tmp_path, "python-defaults"), 50, 10)


def test_direct_worker_uses_fifty_ten_when_omitted(tmp_path):
    assert_retrieval(build_config("Question", {}, tmp_path, "defaults"), 50, 10)


@pytest.mark.parametrize("top_k,top_n", [(15, 10), (32, 7)])
def test_explicit_retrieval_overrides_are_preserved(tmp_path, top_k, top_n):
    settings = {"synthesis_top_k": top_k, "synthesis_top_n": top_n}
    assert_retrieval(build_config("Question", settings, tmp_path, "override"), top_k, top_n)


@pytest.mark.parametrize("enabled", [True, False])
def test_reranking_flag_is_forwarded_without_forcing_it_on(tmp_path, enabled):
    config = build_config("Question", {"enable_reranking": enabled}, tmp_path, "flag")
    assert_retrieval(config, 50, 10, reranking=enabled)


@pytest.mark.parametrize("bad", ["false", 0, 1, None])
def test_worker_rejects_nonboolean_reranking_flag(tmp_path, bad):
    with pytest.raises(ValueError, match="enable_reranking.*boolean"):
        build_config("Question", {"enable_reranking": bad}, tmp_path, "invalid")


@pytest.mark.parametrize("bad", ["false", 0, 1, None])
def test_config_rejects_nonboolean_reranking_flag(tmp_path, bad):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"research": {"caesar": {"enable_reranking": bad}}}))
    with pytest.raises(ValueError, match="enable_reranking.*boolean"):
        load_config(path)


def test_loaded_config_preserves_explicit_disabled_mode(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("research:\n  caesar:\n    enable_reranking: false\n")
    settings = load_config(path)["research"]["caesar"]
    assert_retrieval(build_config("Question", settings, tmp_path, "disabled"), 50, 10, reranking=False)


def test_reranking_does_not_restore_a_removed_answer_word_target(tmp_path):
    config = build_config("Question", {"answer_word_limit": None}, tmp_path, "uncapped")
    assert_retrieval(config, 50, 10)
    assert config["ArtifactSynthesizer"]["synthesis_max_length"] is None


@pytest.mark.parametrize("body_words", [600, 601])
def test_word_accounting_excludes_abstract_and_appended_sources(tmp_path, body_words):
    main_text = " ".join(["body"] * body_words)
    abstract = " ".join(["abstract"] * 100)
    artifact = {
        "abstract": abstract,
        "artifact": main_text,
        "sources": {f"https://example.test/paper-{i}": i for i in range(1, 6)},
        "num_drafts": 3,
        "metadata": {"synthesis_queries": 20},
    }
    usage = {"successful_calls": 1, "unknown_cost": False, "cost_usd": 0.0}
    result = extract_result(artifact, "fixture-model", usage, expected_iterations=20)
    config = build_config("Question", {"answer_word_limit": 600}, tmp_path, "word-limit")

    assert config["ArtifactSynthesizer"]["synthesis_max_length"] == 600
    assert result["raw"]["artifact"]["abstract"] == abstract
    assert abstract not in result["text"]
    assert result["text"].startswith(main_text + "\n\nSources\n")
    assert len(result["text"].split()) > body_words
    assert _answer_words(result["text"]) == body_words
    assert (_answer_words(result["text"]) > 600) is (body_words > 600)
