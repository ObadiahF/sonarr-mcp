"""Tests for ``sonarr_mcp.config``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sonarr_mcp.config import ConfigError, SonarrConfig, load_config


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_loads_from_explicit_path(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "creds.json",
        {"baseUrl": "http://sonarr:8989", "apiKey": "abc"},
    )
    cfg = load_config(cfg_path)
    assert cfg.base_url == "http://sonarr:8989"
    assert cfg.api_key == "abc"
    assert cfg.api_root == "http://sonarr:8989/api/v5"


def test_strips_trailing_slash_from_base_url() -> None:
    cfg = SonarrConfig(base_url="http://sonarr:8989/", api_key="abc")
    assert cfg.api_root == "http://sonarr:8989/api/v5"


def test_env_override_for_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "via-env.json",
        {"baseUrl": "http://from-env:8989", "apiKey": "envkey"},
    )
    monkeypatch.setenv("SONARR_CONFIG", str(cfg_path))
    monkeypatch.delenv("SONARR_BASE_URL", raising=False)
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    cfg = load_config()
    assert cfg.base_url == "http://from-env:8989"
    assert cfg.api_key == "envkey"


def test_env_vars_override_file_contents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path / "creds.json",
        {"baseUrl": "http://from-file:8989", "apiKey": "filekey"},
    )
    monkeypatch.setenv("SONARR_BASE_URL", "http://from-env:8989")
    monkeypatch.setenv("SONARR_API_KEY", "envkey")
    cfg = load_config(cfg_path)
    assert cfg.base_url == "http://from-env:8989"
    assert cfg.api_key == "envkey"


def test_missing_creds_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SONARR_BASE_URL", raising=False)
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    monkeypatch.setenv("SONARR_CONFIG", str(tmp_path / "does-not-exist.json"))
    with pytest.raises(ConfigError):
        load_config()


def test_invalid_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "creds.json"
    bad.write_text("{not valid json")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_empty_values_rejected() -> None:
    with pytest.raises(ConfigError):
        SonarrConfig(base_url="", api_key="abc")
    with pytest.raises(ConfigError):
        SonarrConfig(base_url="http://x", api_key="")
