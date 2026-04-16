"""Queue inspection (separate from the stuck-import workflow in imports.py)."""

from __future__ import annotations

from typing import Any

from ..client import SonarrClient, is_error
from .imports import slim_queue_item


async def queue_status(client: SonarrClient) -> Any:
    """Lightweight queue summary (counts + warning/error flags)."""
    return await client.get("/queue/status")


async def list_queue(
    client: SonarrClient,
    *,
    include_unknown: bool = True,
    page: int = 1,
    page_size: int = 50,
) -> Any:
    result = await client.get(
        "/queue",
        params={
            "page": page,
            "pageSize": page_size,
            "includeUnknownSeriesItems": include_unknown,
            "includeSubresources": ["series", "episodes"],
        },
    )
    if is_error(result) or not isinstance(result, dict):
        return result
    records = result.get("records") or []
    return {
        "page": result.get("page"),
        "pageSize": result.get("pageSize"),
        "totalRecords": result.get("totalRecords"),
        "records": [slim_queue_item(r) for r in records],
    }


def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="queue_status")
    async def _queue_status() -> Any:
        """Counts of queued/pending items, plus warning/error flags."""
        return await queue_status(client)

    @server.tool(name="list_queue")
    async def _list_queue(
        include_unknown: bool = True, page: int = 1, page_size: int = 50
    ) -> Any:
        """Paginated queue listing (slim payloads)."""
        return await list_queue(
            client, include_unknown=include_unknown, page=page, page_size=page_size
        )
