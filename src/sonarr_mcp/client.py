"""Async httpx wrapper for the Sonarr v5 REST API.

Keep this thin: the MCP tool layer is responsible for shaping responses.
This module's job is auth, transport, and turning HTTP errors into
agent-friendly ``{"error": ..., "status": ...}`` dicts so a tool call
returns *data* rather than raising.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import httpx

from .config import SonarrConfig

DEFAULT_TIMEOUT = 30.0


class SonarrClient:
    """Thin async wrapper around the Sonarr v5 API.

    Intended lifecycle: construct once, hold for the life of the MCP
    server, ``await close()`` on shutdown. ``request()`` is the only
    primitive — every helper goes through it so error handling stays
    in one place.
    """

    def __init__(
        self,
        config: SonarrConfig,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.api_root,
            headers={
                "X-Api-Key": config.api_key,
                "Accept": "application/json",
                "User-Agent": "sonarr-mcp/0.1",
            },
            timeout=timeout,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "SonarrClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Core request primitive
    # ------------------------------------------------------------------
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Issue a request and return parsed JSON (or ``{"error": ...}``)."""
        try:
            response = await self._client.request(
                method,
                path,
                params=_clean_params(params),
                json=json,
            )
        except httpx.TimeoutException as exc:
            return {"error": f"timeout: {exc}", "status": 0}
        except httpx.HTTPError as exc:
            return {"error": f"transport error: {exc}", "status": 0}

        if response.status_code >= 400:
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text
            return {
                "error": f"HTTP {response.status_code}",
                "status": response.status_code,
                "body": body,
            }

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return {"error": "non-JSON response", "status": response.status_code, "body": response.text}

    # ------------------------------------------------------------------
    # Convenience verbs
    # ------------------------------------------------------------------
    async def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None, params: Mapping[str, Any] | None = None) -> Any:
        return await self.request("POST", path, json=json, params=params)

    async def put(self, path: str, *, json: Any = None, params: Mapping[str, Any] | None = None) -> Any:
        return await self.request("PUT", path, json=json, params=params)

    async def delete(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return await self.request("DELETE", path, params=params)


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values; expand iterables (httpx already handles lists)."""
    if not params:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple, set)):
            cleaned[key] = [_stringify(v) for v in value if v is not None]
        else:
            cleaned[key] = _stringify(value)
    return cleaned or None


def _stringify(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def is_error(result: Any) -> bool:
    """True if a client result is an ``{"error": ...}`` dict."""
    return isinstance(result, dict) and "error" in result and "status" in result


def collect_errors(results: Iterable[Any]) -> list[Any]:
    """Useful when fanning out multiple requests."""
    return [r for r in results if is_error(r)]
