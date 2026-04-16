"""Minimal end-to-end smoke test against a live Sonarr.

Usage:
    python scripts/smoke_test.py            # uses ~/.openclaw/.sonarr-creds.json
    SONARR_CONFIG=~/my.json python scripts/smoke_test.py

Hits ``/system/status`` plus a few read-only endpoints and prints a
short report. Exits 0 on success, non-zero if anything errored.
"""

from __future__ import annotations

import asyncio
import json
import sys

from sonarr_mcp.client import SonarrClient, is_error
from sonarr_mcp.config import ConfigError, load_config


async def _main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2

    print(f"[config] base_url={cfg.base_url}")

    async with SonarrClient(cfg) as client:
        checks = {
            "system/status": await client.get("/system/status"),
            "queue/status": await client.get("/queue/status"),
            "rootfolder": await client.get("/rootfolder"),
            "qualityprofile": await client.get("/qualityprofile"),
            "health": await client.get("/health"),
        }

    rc = 0
    for label, result in checks.items():
        if is_error(result):
            rc = 1
            print(f"  [FAIL] /{label}: {result.get('error')} (status={result.get('status')})")
        else:
            summary: object
            if isinstance(result, list):
                summary = f"list[{len(result)}]"
            elif isinstance(result, dict):
                # Pull a couple of the most useful fields.
                interesting = {
                    k: result[k]
                    for k in ("version", "appName", "totalCount", "count", "errors", "warnings")
                    if k in result
                }
                summary = json.dumps(interesting) if interesting else "<dict>"
            else:
                summary = repr(result)
            print(f"  [ ok ] /{label}: {summary}")
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
