"""Library management: list/get/add/update/delete series, lookup."""

from __future__ import annotations

from typing import Any

from ..client import SonarrClient, is_error


def slim_series(item: dict[str, Any]) -> dict[str, Any]:
    """Strip the heavy bits (images, alternate titles, full season images)."""
    if not isinstance(item, dict):
        return item
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "sortTitle": item.get("sortTitle"),
        "tvdbId": item.get("tvdbId"),
        "imdbId": item.get("imdbId"),
        "tmdbId": item.get("tmdbId"),
        "status": item.get("status"),
        "ended": item.get("ended"),
        "monitored": item.get("monitored"),
        "qualityProfileId": item.get("qualityProfileId"),
        "seasonFolder": item.get("seasonFolder"),
        "path": item.get("path"),
        "rootFolderPath": item.get("rootFolderPath"),
        "year": item.get("year"),
        "runtime": item.get("runtime"),
        "network": item.get("network"),
        "airTime": item.get("airTime"),
        "firstAired": item.get("firstAired"),
        "lastAired": item.get("lastAired"),
        "nextAiring": item.get("nextAiring"),
        "previousAiring": item.get("previousAiring"),
        "seriesType": item.get("seriesType"),
        "genres": item.get("genres"),
        "tags": list(item.get("tags") or []),
        "seasons": [
            {
                "seasonNumber": s.get("seasonNumber"),
                "monitored": s.get("monitored"),
                "statistics": s.get("statistics"),
            }
            for s in (item.get("seasons") or [])
        ],
        "statistics": item.get("statistics"),
        "added": item.get("added"),
    }


async def list_series(client: SonarrClient, *, monitored_only: bool = False) -> Any:
    result = await client.get("/series")
    if is_error(result) or not isinstance(result, list):
        return result
    items = [slim_series(s) for s in result]
    if monitored_only:
        items = [s for s in items if s.get("monitored")]
    return items


async def get_series(client: SonarrClient, series_id: int) -> Any:
    result = await client.get(f"/series/{series_id}")
    if is_error(result):
        return result
    return slim_series(result) if isinstance(result, dict) else result


async def lookup_series(client: SonarrClient, term: str) -> Any:
    result = await client.get("/series/lookup", params={"term": term})
    if is_error(result) or not isinstance(result, list):
        return result
    return [slim_series(s) for s in result]


async def add_series(
    client: SonarrClient,
    *,
    tvdb_id: int,
    quality_profile_id: int,
    root_folder_path: str,
    season_folder: bool = True,
    monitor: str = "all",
    title: str | None = None,
    series_type: str = "standard",
    search_for_missing_episodes: bool = True,
) -> Any:
    """Add a new series to the library.

    ``monitor`` controls what gets monitored on add. Sonarr accepts
    values like ``all``, ``future``, ``missing``, ``existing``,
    ``firstSeason``, ``latestSeason``, ``pilot``, ``none``.
    """
    if not title:
        # Resolve via lookup so we send a complete-enough payload to the add endpoint.
        lookups = await client.get("/series/lookup", params={"term": f"tvdb:{tvdb_id}"})
        if is_error(lookups):
            return lookups
        match = next(
            (s for s in (lookups or []) if isinstance(s, dict) and s.get("tvdbId") == tvdb_id),
            None,
        )
        if not match:
            return {"error": f"No tvdb match for {tvdb_id}", "status": 0}
        body = dict(match)
    else:
        body = {"title": title, "tvdbId": tvdb_id}

    body.update(
        {
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "seasonFolder": season_folder,
            "monitored": monitor != "none",
            "seriesType": series_type,
            "addOptions": {
                "monitor": monitor,
                "searchForMissingEpisodes": search_for_missing_episodes,
                "ignoreEpisodesWithFiles": False,
                "ignoreEpisodesWithoutFiles": False,
            },
        }
    )
    return await client.post("/series", json=body)


async def update_series_monitoring(
    client: SonarrClient, series_id: int, monitored: bool
) -> Any:
    current = await client.get(f"/series/{series_id}")
    if is_error(current) or not isinstance(current, dict):
        return current
    current["monitored"] = monitored
    return await client.put(f"/series/{series_id}", json=current)


async def delete_series(
    client: SonarrClient, series_id: int, *, delete_files: bool = False
) -> Any:
    return await client.delete(
        f"/series/{series_id}",
        params={"deleteFiles": delete_files, "addImportListExclusion": False},
    )


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="list_series")
    async def _list_series(monitored_only: bool = False) -> Any:
        """List every series in the library (slim payload)."""
        return await list_series(client, monitored_only=monitored_only)

    @server.tool(name="get_series")
    async def _get_series(series_id: int) -> Any:
        """Fetch a single series by Sonarr id."""
        return await get_series(client, series_id)

    @server.tool(name="lookup_series")
    async def _lookup_series(term: str) -> Any:
        """Search TVDB / Sonarr indexers for series matching ``term``."""
        return await lookup_series(client, term)

    @server.tool(name="add_series")
    async def _add_series(
        tvdb_id: int,
        quality_profile_id: int,
        root_folder_path: str,
        season_folder: bool = True,
        monitor: str = "all",
        title: str | None = None,
        series_type: str = "standard",
        search_for_missing_episodes: bool = True,
    ) -> Any:
        """Add a series. ``monitor`` ∈ {all, future, missing, existing, firstSeason, latestSeason, pilot, none}."""
        return await add_series(
            client,
            tvdb_id=tvdb_id,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            season_folder=season_folder,
            monitor=monitor,
            title=title,
            series_type=series_type,
            search_for_missing_episodes=search_for_missing_episodes,
        )

    @server.tool(name="update_series_monitoring")
    async def _update_series_monitoring(series_id: int, monitored: bool) -> Any:
        """Toggle monitoring on a series."""
        return await update_series_monitoring(client, series_id, monitored)

    @server.tool(name="delete_series")
    async def _delete_series(series_id: int, delete_files: bool = False) -> Any:
        """Delete a series. ``delete_files=True`` also removes media on disk."""
        return await delete_series(client, series_id, delete_files=delete_files)
