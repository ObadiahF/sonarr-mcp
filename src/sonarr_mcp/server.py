"""FastMCP server wiring for sonarr-mcp."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .client import SonarrClient
from .config import SonarrConfig, load_config
from .tools import register_all

log = logging.getLogger("sonarr_mcp")


def build_server(config: SonarrConfig | None = None) -> FastMCP:
    """Construct a FastMCP server with all sonarr tools registered.

    The Sonarr HTTP client is created here and held for the life of the
    process — we deliberately don't expose a per-request client to the
    tool layer to keep call sites tidy and to share the connection pool.
    """
    cfg = config or load_config()
    client = SonarrClient(cfg)

    server = FastMCP(
        name="sonarr-mcp",
        instructions=(
            "Tools for managing a Sonarr v5 instance. The headline use case "
            "is resolving stuck imports: start with `get_stuck_imports`, then "
            "for each unresolved file call `suggest_import_resolution` and "
            "feed the top candidate's `submitPayload` into `resolve_import`. "
            "If a download is unrecoverable, use `blocklist_and_search`."
        ),
    )

    register_all(server, client)

    log.debug("Registered tools against Sonarr at %s", cfg.base_url)
    return server


__all__ = ["build_server"]
