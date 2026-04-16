"""Tool modules for sonarr-mcp.

Each submodule exposes a ``register(server, client)`` function called by
:mod:`sonarr_mcp.server` to wire its tools into the FastMCP app.
"""

from . import (  # noqa: F401  (re-export for explicit registration)
    calendar,
    commands,
    episodes,
    history,
    imports,
    queue,
    series,
    system,
)

ALL_MODULES = (
    imports,
    series,
    episodes,
    calendar,
    queue,
    history,
    commands,
    system,
)


def register_all(server, client) -> None:  # type: ignore[no-untyped-def]
    """Register every tool module's tools on ``server``."""
    for module in ALL_MODULES:
        module.register(server, client)
