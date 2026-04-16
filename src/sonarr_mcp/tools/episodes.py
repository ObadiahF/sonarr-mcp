"""Episode listing + monitor toggling."""

from __future__ import annotations

from typing import Any

from ..client import SonarrClient, is_error


def slim_episode(ep: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ep, dict):
        return ep
    return {
        "id": ep.get("id"),
        "seriesId": ep.get("seriesId"),
        "tvdbId": ep.get("tvdbId"),
        "seasonNumber": ep.get("seasonNumber"),
        "episodeNumber": ep.get("episodeNumber"),
        "absoluteEpisodeNumber": ep.get("absoluteEpisodeNumber"),
        "title": ep.get("title"),
        "airDate": ep.get("airDate"),
        "airDateUtc": ep.get("airDateUtc"),
        "overview": ep.get("overview"),
        "monitored": ep.get("monitored"),
        "hasFile": ep.get("hasFile"),
        "episodeFileId": ep.get("episodeFileId"),
        "finaleType": ep.get("finaleType"),
    }


async def list_episodes(
    client: SonarrClient, series_id: int, season_number: int | None = None
) -> Any:
    params: dict[str, Any] = {"seriesId": series_id}
    if season_number is not None:
        params["seasonNumber"] = season_number
    result = await client.get("/episode", params=params)
    if is_error(result) or not isinstance(result, list):
        return result
    return [slim_episode(e) for e in result]


async def monitor_episodes(
    client: SonarrClient, episode_ids: list[int], monitored: bool
) -> Any:
    return await client.put(
        "/episode/monitor",
        json={"episodeIds": list(episode_ids), "monitored": monitored},
    )


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="list_episodes")
    async def _list_episodes(series_id: int, season_number: int | None = None) -> Any:
        """List episodes for a series, optionally filtered by season."""
        return await list_episodes(client, series_id, season_number)

    @server.tool(name="monitor_episodes")
    async def _monitor_episodes(episode_ids: list[int], monitored: bool) -> Any:
        """Bulk-toggle monitoring on a set of episode ids."""
        return await monitor_episodes(client, episode_ids, monitored)
