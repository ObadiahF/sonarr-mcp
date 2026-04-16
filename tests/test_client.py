"""Tests for ``sonarr_mcp.client.SonarrClient`` (mocked with respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sonarr_mcp.client import SonarrClient, is_error
from sonarr_mcp.config import SonarrConfig

BASE = "http://sonarr.test:8989"
API_ROOT = f"{BASE}/api/v5"


@pytest.fixture
def cfg() -> SonarrConfig:
    return SonarrConfig(base_url=BASE, api_key="k")


@respx.mock
async def test_get_returns_parsed_json(cfg: SonarrConfig) -> None:
    respx.get(f"{API_ROOT}/system/status").mock(
        return_value=httpx.Response(200, json={"version": "5.0.0", "appName": "Sonarr"})
    )
    async with SonarrClient(cfg) as client:
        result = await client.get("/system/status")
    assert result == {"version": "5.0.0", "appName": "Sonarr"}


@respx.mock
async def test_sends_api_key_header(cfg: SonarrConfig) -> None:
    route = respx.get(f"{API_ROOT}/system/status").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with SonarrClient(cfg) as client:
        await client.get("/system/status")
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "k"


@respx.mock
async def test_204_returns_none(cfg: SonarrConfig) -> None:
    respx.delete(f"{API_ROOT}/queue/42").mock(return_value=httpx.Response(204))
    async with SonarrClient(cfg) as client:
        assert await client.delete("/queue/42") is None


@respx.mock
async def test_http_error_returned_as_dict(cfg: SonarrConfig) -> None:
    respx.get(f"{API_ROOT}/series/9999").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )
    async with SonarrClient(cfg) as client:
        result = await client.get("/series/9999")
    assert is_error(result)
    assert result["status"] == 404
    assert result["body"] == {"message": "not found"}


@respx.mock
async def test_transport_error_returned_as_dict(cfg: SonarrConfig) -> None:
    respx.get(f"{API_ROOT}/system/status").mock(side_effect=httpx.ConnectError("nope"))
    async with SonarrClient(cfg) as client:
        result = await client.get("/system/status")
    assert is_error(result)
    assert result["status"] == 0


@respx.mock
async def test_bool_params_become_lowercase_strings(cfg: SonarrConfig) -> None:
    route = respx.get(f"{API_ROOT}/queue").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with SonarrClient(cfg) as client:
        await client.get("/queue", params={"includeUnknownSeriesItems": True, "page": 1})
    qs = route.calls.last.request.url.params
    assert qs["includeUnknownSeriesItems"] == "true"
    assert qs["page"] == "1"


@respx.mock
async def test_none_params_dropped(cfg: SonarrConfig) -> None:
    route = respx.get(f"{API_ROOT}/calendar").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with SonarrClient(cfg) as client:
        await client.get("/calendar", params={"start": "2026-01-01", "end": None})
    qs = route.calls.last.request.url.params
    assert "end" not in qs
    assert qs["start"] == "2026-01-01"


@respx.mock
async def test_post_sends_json_body(cfg: SonarrConfig) -> None:
    route = respx.post(f"{API_ROOT}/command").mock(
        return_value=httpx.Response(201, json={"id": 1, "name": "RssSync"})
    )
    async with SonarrClient(cfg) as client:
        result = await client.post("/command", json={"name": "RssSync"})
    assert route.called
    import json as _json
    assert _json.loads(route.calls.last.request.read()) == {"name": "RssSync"}
    assert result == {"id": 1, "name": "RssSync"}
