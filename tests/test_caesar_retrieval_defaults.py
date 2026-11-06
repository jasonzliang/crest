"""Keep Caesar retrieval defaults and main-text word accounting explicit."""
from pathlib import Path

import pytest
import yaml

from crest.caesar_worker import build_config, extract_result
from crest.pipeline import _answer_words

ROOT = Path(__file__).resolve().parents[1]


def assert_retrieval(config, top_k, top_n):
    assert config["ArtifactSynthesizer"]["synthesis_top_k"] == top_k
    assert config["ArtifactSynthesizer"]["synthesis_top_n"] == top_n
    assert config["ChromaClientManager"]["top_k"] == top_k
    assert config["ChromaClientManager"]["enable_reranking"] is False


def test_shipped_preset_uses_fifty_ten(tmp_path):
    settings = yaml.safe_load((ROOT / "crest/configs/crest.yaml").read_text())["research"]["caesar"]
    assert_retrieval(build_config("Question", settings, tmp_path, "preset"), 50, 10)


def test_python_config_defaults_use_fifty_ten(tmp_path):
    from crest.config import DEFAULTS

    settings = DEFAULTS["research"]["caesar"]
    assert_retrieval(build_config("Question", settings, tmp_path, "python-defaults"), 50, 10)


def test_direct_worker_uses_fifty_ten_when_omitted(tmp_path):
    assert_retrieval(build_config("Question", {}, tmp_path, "defaults"), 50, 10)


@pytest.mark.parametrize("top_k,top_n", [(15, 10), (32, 7)])
def test_explicit_retrieval_overrides_are_preserved(tmp_path, top_k, top_n):
    settings = {"synthesis_top_k": top_k, "synthesis_top_n": top_n}
    assert_retrieval(build_config("Question", settings, tmp_path, "override"), top_k, top_n)


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
