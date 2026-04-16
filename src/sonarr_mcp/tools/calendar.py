"""Calendar (upcoming) + wanted/missing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..client import SonarrClient, is_error
from .episodes import slim_episode


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _plus_days_iso(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


async def list_calendar(
    client: SonarrClient,
    *,
    start: str | None = None,
    end: str | None = None,
    include_series: bool = True,
    include_unmonitored: bool = False,
) -> Any:
    params: dict[str, Any] = {
        "start": start or _today_iso(),
        "end": end or _plus_days_iso(7),
        "includeUnmonitored": include_unmonitored,
    }
    if include_series:
        params["includeSubresources"] = ["series"]
    result = await client.get("/calendar", params=params)
    if is_error(result) or not isinstance(result, list):
        return result

    out = []
    for ep in result:
        slim = slim_episode(ep)
        if include_series and isinstance(ep.get("series"), dict):
            s = ep["series"]
            slim["series"] = {"id": s.get("id"), "title": s.get("title"), "tvdbId": s.get("tvdbId")}
        out.append(slim)
    return out


async def list_wanted_missing(
    client: SonarrClient, *, page: int = 1, page_size: int = 20, monitored: bool = True
) -> Any:
    result = await client.get(
        "/wanted/missing",
        params={
            "page": page,
            "pageSize": page_size,
            "monitored": monitored,
            "sortKey": "episodes.airDateUtc",
            "sortDirection": "descending",
            "includeSubresources": ["series"],
        },
    )
    if is_error(result) or not isinstance(result, dict):
        return result
    records = result.get("records") or []
    return {
        "page": result.get("page"),
        "pageSize": result.get("pageSize"),
        "totalRecords": result.get("totalRecords"),
        "records": [
            {
                **slim_episode(r),
                "series": (
                    {
                        "id": r["series"].get("id"),
                        "title": r["series"].get("title"),
                        "tvdbId": r["series"].get("tvdbId"),
                    }
                    if isinstance(r.get("series"), dict)
                    else None
                ),
            }
            for r in records
        ],
    }


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="list_calendar")
    async def _list_calendar(
        start: str | None = None,
        end: str | None = None,
        include_series: bool = True,
        include_unmonitored: bool = False,
    ) -> Any:
        """Upcoming episodes between ``start`` and ``end`` (ISO dates).

        Defaults: today through +7 days.
        """
        return await list_calendar(
            client,
            start=start,
            end=end,
            include_series=include_series,
            include_unmonitored=include_unmonitored,
        )

    @server.tool(name="list_wanted_missing")
    async def _list_wanted_missing(
        page: int = 1, page_size: int = 20, monitored: bool = True
    ) -> Any:
        """List monitored episodes Sonarr is still searching for."""
        return await list_wanted_missing(client, page=page, page_size=page_size, monitored=monitored)
