"""Activity history (grabs, imports, failures)."""

from __future__ import annotations

from typing import Any

from ..client import SonarrClient, is_error

# Sonarr's EpisodeHistoryEventType (V5):
# 1=grabbed, 2=seriesFolderImported, 3=downloadFolderImported,
# 4=downloadFailed, 5=episodeFileDeleted, 6=episodeFileRenamed,
# 7=downloadIgnored
EVENT_TYPES = {
    "grabbed": 1,
    "seriesFolderImported": 2,
    "downloadFolderImported": 3,
    "downloadFailed": 4,
    "episodeFileDeleted": 5,
    "episodeFileRenamed": 6,
    "downloadIgnored": 7,
}


def slim_history(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return item
    series = item.get("series") or {}
    episode = item.get("episode") or {}
    return {
        "id": item.get("id"),
        "date": item.get("date"),
        "eventType": item.get("eventType"),
        "sourceTitle": item.get("sourceTitle"),
        "downloadId": item.get("downloadId"),
        "qualityCutoffNotMet": item.get("qualityCutoffNotMet"),
        "series": (
            {"id": series.get("id"), "title": series.get("title"), "tvdbId": series.get("tvdbId")}
            if series
            else {"id": item.get("seriesId")}
        ),
        "episode": (
            {
                "id": episode.get("id"),
                "seasonNumber": episode.get("seasonNumber"),
                "episodeNumber": episode.get("episodeNumber"),
                "title": episode.get("title"),
            }
            if episode
            else {"id": item.get("episodeId")}
        ),
        "data": item.get("data"),
    }


async def list_history(
    client: SonarrClient,
    *,
    series_id: int | None = None,
    event_type: str | int | None = None,
    since: str | None = None,
    page: int = 1,
    page_size: int = 30,
) -> Any:
    """List recent activity. If ``since`` is given, uses ``/history/since``."""
    if event_type is not None and isinstance(event_type, str):
        event_type = EVENT_TYPES.get(event_type, event_type)

    if since:
        params: dict[str, Any] = {"date": since}
        if event_type is not None:
            params["eventType"] = event_type
        params["includeSubresources"] = ["series", "episode"]
        result = await client.get("/history/since", params=params)
        if is_error(result) or not isinstance(result, list):
            return result
        return [slim_history(h) for h in result]

    if series_id is not None:
        params = {"seriesId": series_id, "includeSubresources": ["series", "episode"]}
        if event_type is not None:
            params["eventType"] = event_type
        result = await client.get("/history/series", params=params)
        if is_error(result) or not isinstance(result, list):
            return result
        return [slim_history(h) for h in result]

    params = {
        "page": page,
        "pageSize": page_size,
        "sortKey": "date",
        "sortDirection": "descending",
        "includeSubresources": ["series", "episode"],
    }
    if event_type is not None:
        params["eventType"] = [event_type] if not isinstance(event_type, list) else event_type
    result = await client.get("/history", params=params)
    if is_error(result) or not isinstance(result, dict):
        return result
    return {
        "page": result.get("page"),
        "pageSize": result.get("pageSize"),
        "totalRecords": result.get("totalRecords"),
        "records": [slim_history(h) for h in result.get("records") or []],
    }


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="list_history")
    async def _list_history(
        series_id: int | None = None,
        event_type: str | None = None,
        since: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> Any:
        """List history (grabs / imports / failures).

        ``event_type`` accepts a name (``grabbed``, ``downloadFailed``,
        ``downloadFolderImported``, ...) or a Sonarr int id.
        ``since`` (ISO datetime) switches to the ``/history/since`` endpoint.
        """
        return await list_history(
            client,
            series_id=series_id,
            event_type=event_type,
            since=since,
            page=page,
            page_size=page_size,
        )
