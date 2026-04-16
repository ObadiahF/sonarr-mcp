"""Shared fixtures for the sonarr-mcp test suite."""

from __future__ import annotations

import httpx
import pytest

from sonarr_mcp.client import SonarrClient
from sonarr_mcp.config import SonarrConfig

BASE_URL = "http://sonarr.test:8989"
API_KEY = "test-key-12345"


@pytest.fixture
def config() -> SonarrConfig:
    return SonarrConfig(base_url=BASE_URL, api_key=API_KEY)


@pytest.fixture
async def client(config: SonarrConfig):
    """A real ``SonarrClient`` whose underlying httpx client is intercepted by respx."""
    transport = httpx.AsyncHTTPTransport()
    http = httpx.AsyncClient(
        base_url=config.api_root,
        headers={"X-Api-Key": config.api_key, "Accept": "application/json"},
        transport=transport,
    )
    c = SonarrClient(config, client=http)
    try:
        yield c
    finally:
        await c.close()
        await http.aclose()
