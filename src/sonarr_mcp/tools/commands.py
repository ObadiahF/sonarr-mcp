"""Generic command trigger + the common search shortcuts."""

from __future__ import annotations

from typing import Any

from ..client import SonarrClient


async def run_command(client: SonarrClient, name: str, **body: Any) -> Any:
    """Trigger any Sonarr command.

    See ``CommandController.cs`` — the controller looks up a registered
    Command class by name (``RssSync``, ``RefreshSeries``,
    ``EpisodeSearch``, ``SeasonSearch``, ``SeriesSearch``,
    ``MissingEpisodeSearch``, ``Backup``, ...). Extra kwargs are merged
    into the command body.
    """
    payload: dict[str, Any] = {"name": name}
    payload.update(body)
    return await client.post("/command", json=payload)


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="run_command")
    async def _run_command(name: str, body: dict[str, Any] | None = None) -> Any:
        """Generic Sonarr ``/command`` trigger.

        Examples: ``run_command("RssSync")``,
        ``run_command("RefreshSeries", {"seriesId": 12})``.
        """
        return await run_command(client, name, **(body or {}))

    @server.tool(name="search_episode")
    async def _search_episode(episode_ids: list[int]) -> Any:
        """EpisodeSearch — kick off indexer searches for specific episodes."""
        return await run_command(client, "EpisodeSearch", episodeIds=list(episode_ids))

    @server.tool(name="search_season")
    async def _search_season(series_id: int, season_number: int) -> Any:
        """SeasonSearch — search for every episode in a season."""
        return await run_command(
            client, "SeasonSearch", seriesId=series_id, seasonNumber=season_number
        )

    @server.tool(name="search_series")
    async def _search_series(series_id: int) -> Any:
        """SeriesSearch — search for every monitored episode in a series."""
        return await run_command(client, "SeriesSearch", seriesId=series_id)

    @server.tool(name="rss_sync")
    async def _rss_sync() -> Any:
        """RssSync — pull new releases from configured indexers."""
        return await run_command(client, "RssSync")

    @server.tool(name="refresh_series")
    async def _refresh_series(series_id: int | None = None) -> Any:
        """RefreshSeries — refresh metadata for one series, or all if omitted."""
        if series_id is None:
            return await run_command(client, "RefreshSeries")
        return await run_command(client, "RefreshSeries", seriesId=series_id)
