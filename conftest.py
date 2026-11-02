"""Shared test fixtures. Tests are offline: no provider credential may reach an adapter."""
import os
from pathlib import Path

import pytest
import yaml

CREDENTIALS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
ROOT = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _no_live_credentials(monkeypatch):
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    assert not any(os.environ.get(name) for name in CREDENTIALS)


@pytest.fixture
def write_master_config(tmp_path):
    """Copy the master configuration with absolute paths, applying dotted overrides."""
    def write(**overrides):
        source = yaml.safe_load((ROOT / "crest/configs/crest.yaml").read_text())
        for key in ("questions", "rubric", "cache_dir", "output_dir"):
            source[key] = str(ROOT / "crest/configs" / source[key])
        source["research"]["caesar"]["rome_path"] = str(ROOT / "crest/configs" / source["research"]["caesar"]["rome_path"])
        for dotted, value in overrides.items():
            target = source
            *parents, last = dotted.split(".")
            for part in parents:
                target = target[part]
            target[last] = value
        path = tmp_path / "crest.yaml"
        path.write_text(yaml.safe_dump(source))
        return path
    return write
