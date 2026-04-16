"""Entry point: ``python -m sonarr_mcp``."""

from __future__ import annotations

from .server import build_server


def main() -> None:
    """Run the FastMCP server over stdio."""
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
