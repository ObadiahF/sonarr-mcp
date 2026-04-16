"""Integration test for ``get_stuck_imports`` end-to-end (HTTP mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sonarr_mcp.client import SonarrClient
from sonarr_mcp.config import SonarrConfig
from sonarr_mcp.tools.imports import get_stuck_imports

BASE = "http://sonarr.test:8989"
API_ROOT = f"{BASE}/api/v5"


@pytest.fixture
def cfg() -> SonarrConfig:
    return SonarrConfig(base_url=BASE, api_key="k")


@respx.mock
async def test_merges_queue_and_manualimport(cfg: SonarrConfig) -> None:
    queue_payload = {
        "page": 1,
        "pageSize": 200,
        "totalRecords": 3,
        "records": [
            {
                "id": 100,
                "downloadId": "dl-warn",
                "title": "Show.S01E01",
                "trackedDownloadStatus": "warning",
                "statusMessages": [{"title": "Import failed", "messages": ["No matching series"]}],
                "quality": {"quality": {"id": 7, "name": "WEB-1080p"}},
                "languages": [{"id": 1, "name": "English"}],
            },
            {
                "id": 101,
                "downloadId": "dl-ok",
                "title": "Show.S01E02",
                "trackedDownloadStatus": "ok",
            },
            {
                "id": 102,
                "downloadId": "dl-err",
                "title": "Other.S02E01",
                "trackedDownloadStatus": "error",
                "statusMessages": [],
                "quality": None,
                "languages": [],
            },
        ],
    }
    manual_warn = [
        {
            "id": 1,
            "path": "/downloads/dl-warn/show.s01e01.mkv",
            "size": 12345,
            "series": None,
            "episodes": [],
            "rejections": [{"reason": "UnknownSeries", "type": "Permanent", "message": "?"}],
            "downloadId": "dl-warn",
        }
    ]
    manual_err: list[dict] = []  # Sonarr can return [] for some downloads

    respx.get(f"{API_ROOT}/queue").mock(return_value=httpx.Response(200, json=queue_payload))
    respx.get(f"{API_ROOT}/manualimport", params={"downloadIds": "dl-warn"}).mock(
        return_value=httpx.Response(200, json=manual_warn)
    )
    respx.get(f"{API_ROOT}/manualimport", params={"downloadIds": "dl-err"}).mock(
        return_value=httpx.Response(200, json=manual_err)
    )

    async with SonarrClient(cfg) as client:
        result = await get_stuck_imports(client)

    assert result["count"] == 2
    items = {item["queueId"]: item for item in result["items"]}
    assert set(items) == {100, 102}
    assert items[100]["manualImportCandidates"][0]["path"] == "/downloads/dl-warn/show.s01e01.mkv"
    assert items[102]["manualImportCandidates"] == []


@respx.mock
async def test_returns_error_dict_when_queue_fails(cfg: SonarrConfig) -> None:
    respx.get(f"{API_ROOT}/queue").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    async with SonarrClient(cfg) as client:
        result = await get_stuck_imports(client)
    assert result.get("status") == 500


@respx.mock
async def test_empty_queue_yields_zero_count(cfg: SonarrConfig) -> None:
    respx.get(f"{API_ROOT}/queue").mock(
        return_value=httpx.Response(200, json={"records": []})
    )
    async with SonarrClient(cfg) as client:
        result = await get_stuck_imports(client)
    assert result == {"count": 0, "items": []}
