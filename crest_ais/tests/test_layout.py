"""Path behavior of the organized AIS package, without provider calls."""
from pathlib import Path
import json
import runpy
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_default_config_resolves_package_data_results_and_prompt_from_any_cwd(tmp_path, monkeypatch):
    from crest_ais.cli import load_config
    from crest.config import DEFAULT_CONFIG
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config["data_root"] == ROOT
    assert config["output_dir"] == ROOT / "results"
    assert config["rubric"] == ROOT / "prompts" / "rubric.txt"
    inherited = yaml.safe_load(DEFAULT_CONFIG.read_text())
    for judge in ("openai", "gemini"):
        assert config["judges"][judge]["model"] == inherited["judges"][judge]["model"]
        assert config["judges"][judge]["concurrency"] == 2
        assert config["judges"][judge]["timeout_seconds"] == 900


def test_explicit_config_keeps_paths_relative_to_its_own_directory(tmp_path, monkeypatch):
    from crest_ais.cli import load_config
    directory = tmp_path / "configs"
    directory.mkdir()
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "rubric.txt").write_text("Unchanged comparison guidance")
    inherited = {"judges": {name: {"model": f"fixture-{name}", "concurrency": 8}
                             for name in ("openai", "gemini")}}
    (tmp_path / "judges.yaml").write_text(yaml.safe_dump(inherited))
    config_path = directory / "custom.json"
    config_path.write_text(json.dumps({"data_root": "../dataset", "output_dir": "runs",
                                      "rubric": "../prompts/rubric.txt", "inherit_judges": "../judges.yaml"}))
    monkeypatch.chdir(prompts)
    config = load_config(config_path)
    assert config["data_root"] == tmp_path / "dataset"
    assert config["output_dir"] == tmp_path / "dataset" / "runs"
    assert config["rubric"].read_text() == "Unchanged comparison guidance"
    assert config["judges"]["openai"]["model"] == "fixture-openai"
    assert config["judges"]["gemini"]["model"] == "fixture-gemini"
    overridden = load_config(config_path, data_root=tmp_path / "alternate")
    assert overridden["output_dir"] == tmp_path / "alternate" / "runs"


def test_default_extension_uses_relocated_storage_config_without_reloading_judges(tmp_path, monkeypatch):
    from crest_ais import cli
    directory = tmp_path / "configs"
    directory.mkdir()
    config = directory / "config.json"
    config.write_text(json.dumps({"data_root": "..", "output_dir": "results"}))
    monkeypatch.setattr(cli, "DEFAULT_CONFIG", config)
    monkeypatch.setattr(cli, "load_config", lambda *a, **kw: pytest.fail("Extension must keep frozen judge settings"))
    received = []
    def extend(source, destination, root, **kwargs):
        received.append((source, destination, root, kwargs))
        return {"created_at": "2026-10-27T00:00:00+00:00", "jobs": [], "papers": [],
                "selection": {"sampled_pairs": 0}, "extension": {"original_pairs": 0, "additional_pairs": 0}}
    monkeypatch.setattr(cli, "create_extension", extend)
    source = tmp_path / "frozen-run"
    destination = tmp_path / "extension"
    assert cli.main(["extend", "--source-run", str(source), "--run-dir", str(destination)]) == 0
    assert received == [(source, destination, tmp_path, {"pairs_per_matchup": 10, "extension_seed": 2026})]
    assert json.loads((tmp_path / "results" / "latest.json").read_text())["run_dir"] == str(destination)


def test_python_module_entrypoint_keeps_the_existing_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["crest_ais", "--help"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("crest_ais", run_name="__main__")
    assert stopped.value.code == 0
    help_text = capsys.readouterr().out
    assert "prepare,plan,extend,add-agent,judge,report,run" in help_text
