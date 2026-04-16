"""Health, disk space, system info, root folders, quality profiles."""

from __future__ import annotations

from typing import Any

from ..client import SonarrClient, is_error


def _bytes_to_gb(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(value / (1024**3), 2)


async def health_summary(client: SonarrClient) -> dict[str, Any]:
    """Combine /health + /diskspace + /system/status into one snapshot."""
    health = await client.get("/health")
    diskspace = await client.get("/diskspace")
    status = await client.get("/system/status")

    return {
        "status": status if not is_error(status) else status,
        "health": (
            [
                {
                    "source": h.get("source"),
                    "type": h.get("type"),
                    "message": h.get("message"),
                    "wikiUrl": h.get("wikiUrl"),
                }
                for h in health
            ]
            if isinstance(health, list)
            else health
        ),
        "diskspace": (
            [
                {
                    "path": d.get("path"),
                    "label": d.get("label"),
                    "freeSpaceGb": _bytes_to_gb(d.get("freeSpace")),
                    "totalSpaceGb": _bytes_to_gb(d.get("totalSpace")),
                }
                for d in diskspace
            ]
            if isinstance(diskspace, list)
            else diskspace
        ),
    }


async def list_root_folders(client: SonarrClient) -> Any:
    result = await client.get("/rootfolder")
    if is_error(result) or not isinstance(result, list):
        return result
    return [
        {
            "id": r.get("id"),
            "path": r.get("path"),
            "accessible": r.get("accessible"),
            "freeSpaceGb": _bytes_to_gb(r.get("freeSpace")),
            "unmappedFolders": r.get("unmappedFolders") or [],
        }
        for r in result
    ]


async def list_quality_profiles(client: SonarrClient) -> Any:
    result = await client.get("/qualityprofile")
    if is_error(result) or not isinstance(result, list):
        return result
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "upgradeAllowed": p.get("upgradeAllowed"),
            "cutoff": p.get("cutoff"),
        }
        for p in result
    ]


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="health_summary")
    async def _health_summary() -> dict[str, Any]:
        """One-shot system overview: status + health checks + disk space."""
        return await health_summary(client)

    @server.tool(name="list_root_folders")
    async def _list_root_folders() -> Any:
        """Root folders configured in Sonarr (with free space)."""
        return await list_root_folders(client)

    @server.tool(name="list_quality_profiles")
    async def _list_quality_profiles() -> Any:
        """Quality profiles — needed when adding a new series."""
        return await list_quality_profiles(client)
