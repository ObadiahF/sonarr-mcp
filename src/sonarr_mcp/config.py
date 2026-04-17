"""Configuration loading for sonarr-mcp.

Reads JSON from ``~/.openclaw/.sonarr-creds.json`` by default. Override the
path with the ``SONARR_CONFIG`` env var, or supply individual values via
``SONARR_BASE_URL`` / ``SONARR_API_KEY``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".openclaw" / ".sonarr-creds.json"


class ConfigError(RuntimeError):
    """Raised when sonarr-mcp can't load a usable config."""


@dataclass(frozen=True)
class SonarrConfig:
    base_url: str
    api_key: str

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ConfigError("baseUrl is required")
        if not self.api_key:
            raise ConfigError("apiKey is required")

    @property
    def api_root(self) -> str:
        """Sonarr v3 API base URL (no trailing slash)."""
        return f"{self.base_url.rstrip('/')}/api/v3"


def _resolve_path(override: str | os.PathLike[str] | None) -> Path:
    if override is not None:
        return Path(override).expanduser()
    env = os.environ.get("SONARR_CONFIG")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: str | os.PathLike[str] | None = None) -> SonarrConfig:
    """Load a :class:`SonarrConfig`.

    Resolution order:

    1. Explicit ``path`` argument.
    2. ``SONARR_CONFIG`` env var.
    3. ``~/.openclaw/.sonarr-creds.json``.

    Env vars ``SONARR_BASE_URL`` and ``SONARR_API_KEY`` always override
    file contents (handy for containers and CI).
    """
    resolved = _resolve_path(path)
    data: dict[str, str] = {}

    if resolved.is_file():
        try:
            data = json.loads(resolved.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid JSON in {resolved}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Config in {resolved} must be a JSON object")

    base_url = os.environ.get("SONARR_BASE_URL") or data.get("baseUrl") or ""
    api_key = os.environ.get("SONARR_API_KEY") or data.get("apiKey") or ""

    if not base_url or not api_key:
        raise ConfigError(
            "Missing Sonarr credentials. Create "
            f"{resolved} with {{\"baseUrl\": \"...\", \"apiKey\": \"...\"}} "
            "or set SONARR_BASE_URL and SONARR_API_KEY."
        )

    return SonarrConfig(base_url=base_url, api_key=api_key)
