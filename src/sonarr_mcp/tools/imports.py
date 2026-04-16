"""Stuck-import detection and resolution.

This is the *headline feature* of sonarr-mcp. Stuck imports are
``/queue`` items whose download client says "done" but Sonarr couldn't
move into the library — usually because of a parsing failure, an
unknown series, or a quality/format rejection. They sit there forever
until a human clicks through the Sonarr UI.

Workflow we expose to the agent:

1. ``get_stuck_imports()`` — surface the problem: a unified list of
   queue items in warning/error state plus the matching ``/manualimport``
   candidates Sonarr has ready to act on.
2. ``suggest_import_resolution(file_path)`` — when Sonarr has *no* idea
   what a file is, do the fuzzy matching ourselves and return a ranked,
   confidence-scored list of (series, episode) candidates.
3. ``resolve_import(payload)`` — actually move the files. Sonarr's REST
   actions for this go through ``POST /command`` with a ``ManualImport``
   command body — see ``ManualImportCommand.cs`` in the Sonarr source.
4. ``blocklist_and_search`` / ``delete_stuck`` — give up on a download
   and tell Sonarr to find something else (or just clear it out).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from ..client import SonarrClient, is_error

# Episode tag regex: S01E02, s1e02, 1x02. Matches the most common forms.
_SXXEYY_RE = re.compile(r"[Ss](\d{1,2})[\s._-]?[Ee](\d{1,3})")
_NXM_RE = re.compile(r"\b(\d{1,2})x(\d{1,3})\b")

BAD_TRACKED_STATUSES = {"warning", "error"}


# ----------------------------------------------------------------------
# Pure helpers — kept module-level so tests can hit them directly.
# ----------------------------------------------------------------------
def slim_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Sonarr queue resource to fields the agent actually needs."""
    return {
        "queueId": item.get("id"),
        "downloadId": item.get("downloadId"),
        "title": item.get("title"),
        "seriesId": item.get("seriesId"),
        "episodeIds": list(item.get("episodeIds") or []),
        "size": item.get("size"),
        "sizeLeft": item.get("sizeLeft"),
        "status": item.get("status"),
        "trackedDownloadStatus": item.get("trackedDownloadStatus"),
        "trackedDownloadState": item.get("trackedDownloadState"),
        "errorMessage": item.get("errorMessage"),
        "statusMessages": [
            {"title": m.get("title"), "messages": m.get("messages")}
            for m in (item.get("statusMessages") or [])
        ],
        "outputPath": item.get("outputPath"),
        "downloadClient": item.get("downloadClient"),
        "indexer": item.get("indexer"),
        "protocol": item.get("protocol"),
        "quality": _slim_quality(item.get("quality")),
        "languages": _slim_languages(item.get("languages")),
    }


def slim_manual_import(item: dict[str, Any]) -> dict[str, Any]:
    """Reduce a ManualImportResource to fields the agent needs.

    See ``ManualImportResource.cs`` in Sonarr v5. We deliberately drop
    image arrays, custom format details, scene numbering and other
    fields the agent doesn't act on, to keep payloads compact.
    """
    series = item.get("series") or {}
    return {
        "id": item.get("id"),
        "path": item.get("path"),
        "relativePath": item.get("relativePath"),
        "folderName": item.get("folderName"),
        "size": item.get("size"),
        "quality": _slim_quality(item.get("quality")),
        "languages": _slim_languages(item.get("languages")),
        "series": {"id": series.get("id"), "title": series.get("title")} if series else None,
        "seasonNumber": item.get("seasonNumber"),
        "episodes": [
            {
                "id": ep.get("id"),
                "episodeNumber": ep.get("episodeNumber"),
                "seasonNumber": ep.get("seasonNumber"),
                "title": ep.get("title"),
            }
            for ep in (item.get("episodes") or [])
        ],
        "rejections": [
            {"reason": r.get("reason"), "type": r.get("type"), "message": r.get("message")}
            for r in (item.get("rejections") or [])
        ],
        "releaseGroup": item.get("releaseGroup"),
        "downloadId": item.get("downloadId"),
    }


def _slim_quality(quality: Any) -> dict[str, Any] | None:
    if not isinstance(quality, dict):
        return None
    inner = quality.get("quality") or {}
    return {"name": inner.get("name"), "id": inner.get("id")} if inner else None


def _slim_languages(languages: Any) -> list[dict[str, Any]]:
    if not isinstance(languages, list):
        return []
    return [{"id": l.get("id"), "name": l.get("name")} for l in languages if isinstance(l, dict)]


def parse_episode_tag(text: str) -> tuple[int, int] | None:
    """Pull ``(season, episode)`` out of a release/file name."""
    if not text:
        return None
    m = _SXXEYY_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _NXM_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def title_similarity(a: str, b: str) -> float:
    """Crude but predictable title similarity in [0, 1]."""
    if not a or not b:
        return 0.0
    norm_a = re.sub(r"[^a-z0-9 ]+", " ", a.lower()).strip()
    norm_b = re.sub(r"[^a-z0-9 ]+", " ", b.lower()).strip()
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def score_candidate(
    *,
    parsed_series_match: bool,
    fuzzy_title_score: float,
    parsed_episode: tuple[int, int] | None,
    candidate_episode: tuple[int, int] | None,
    has_parser_result: bool,
) -> float:
    """Confidence score for one (series, episode) candidate.

    Buckets (per the spec):

    * exact tvdb/series match + exact SxxEyy match → ``1.0``
    * fuzzy title match + matching episode         → ``0.7``
    * fallback parser result only                  → ``0.4``
    * nothing                                      → ``0.0``
    """
    episode_match = (
        parsed_episode is not None
        and candidate_episode is not None
        and parsed_episode == candidate_episode
    )
    if parsed_series_match and episode_match:
        return 1.0
    if fuzzy_title_score >= 0.6 and episode_match:
        return 0.7
    if has_parser_result:
        return 0.4
    return 0.0


def merge_stuck(
    queue_items: Sequence[dict[str, Any]],
    manual_imports_by_download_id: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Combine queue items + manual-import candidates into one view.

    Only includes queue items whose ``trackedDownloadStatus`` is
    ``warning`` or ``error`` (that's what "stuck" means in Sonarr UI
    terms). For each one, we attach the matching ``/manualimport``
    candidates indexed by downloadId.
    """
    out: list[dict[str, Any]] = []
    for item in queue_items:
        tds = (item.get("trackedDownloadStatus") or "").lower()
        if tds not in BAD_TRACKED_STATUSES:
            continue
        slim = slim_queue_item(item)
        download_id = slim.get("downloadId")
        candidates = manual_imports_by_download_id.get(download_id, []) if download_id else []
        slim["manualImportCandidates"] = candidates
        out.append(slim)
    return out


def guess_series_term(filename: str) -> str:
    """Best-effort series-title extraction from a filename for /series/lookup."""
    base = filename.rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0]
    # Strip everything from the SxxEyy / NxM tag onward.
    m = _SXXEYY_RE.search(base) or _NXM_RE.search(base)
    if m:
        base = base[: m.start()]
    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip(" -_")
    # Drop trailing year tokens like "(2017)" or "2017".
    base = re.sub(r"\s*\(?\d{4}\)?$", "", base).strip()
    return base


# ----------------------------------------------------------------------
# Tool implementations (async; call SonarrClient).
# ----------------------------------------------------------------------
async def get_stuck_imports(client: SonarrClient) -> dict[str, Any]:
    """Find queue items in warning/error and merge in manual-import candidates."""
    queue = await client.get(
        "/queue",
        params={
            "page": 1,
            "pageSize": 200,
            "includeUnknownSeriesItems": True,
            "includeSubresources": ["series", "episodes"],
        },
    )
    if is_error(queue):
        return queue
    records: list[dict[str, Any]] = (queue or {}).get("records", []) if isinstance(queue, dict) else []

    stuck_records = [
        r for r in records if (r.get("trackedDownloadStatus") or "").lower() in BAD_TRACKED_STATUSES
    ]

    download_ids = sorted({r["downloadId"] for r in stuck_records if r.get("downloadId")})
    candidates_by_dl: dict[str, list[dict[str, Any]]] = {}
    for dl_id in download_ids:
        result = await client.get("/manualimport", params={"downloadIds": dl_id})
        if is_error(result):
            candidates_by_dl[dl_id] = [{"_error": result}]
            continue
        candidates_by_dl[dl_id] = [slim_manual_import(c) for c in (result or [])]

    return {
        "count": len(stuck_records),
        "items": merge_stuck(stuck_records, candidates_by_dl),
    }


async def suggest_import_resolution(client: SonarrClient, file_path: str) -> dict[str, Any]:
    """Fuzzy-match a stuck file against series & episodes, return scored candidates.

    Strategy:

    1. Ask Sonarr's parser (``/parse``) what it thinks. If it's confident
       (returns a series + episodes), score that as 1.0 and we're done.
    2. Otherwise extract a title guess and call ``/series/lookup``.
    3. For each library series match, fetch its episodes and try to
       align by SxxEyy.
    """
    if not file_path:
        return {"error": "file_path is required", "status": 0}

    filename = file_path.rsplit("/", 1)[-1]
    parsed_episode = parse_episode_tag(filename)

    parse_result = await client.get("/parse", params={"title": filename})
    if is_error(parse_result):
        return parse_result

    candidates: list[dict[str, Any]] = []

    parsed_series = (parse_result or {}).get("series") if isinstance(parse_result, dict) else None
    parsed_episodes = (parse_result or {}).get("episodes") if isinstance(parse_result, dict) else None

    # Case 1: Sonarr's own parser linked it to a library series + episodes.
    if parsed_series and parsed_episodes:
        for ep in parsed_episodes:
            cand_ep = (ep.get("seasonNumber"), ep.get("episodeNumber"))
            confidence = score_candidate(
                parsed_series_match=True,
                fuzzy_title_score=1.0,
                parsed_episode=parsed_episode,
                candidate_episode=cand_ep if all(v is not None for v in cand_ep) else None,
                has_parser_result=True,
            )
            candidates.append(
                _build_candidate(
                    confidence=confidence,
                    file_path=file_path,
                    series=parsed_series,
                    episode=ep,
                    quality=(parse_result or {}).get("parsedEpisodeInfo", {}).get("quality")
                    or _quality_from_episodes(parsed_episodes),
                    languages=(parse_result or {}).get("languages") or [],
                    download_id=None,
                    source="parse",
                )
            )

    # Case 2: parser couldn't pin a series — fuzzy lookup against the library.
    if not candidates:
        term = guess_series_term(filename)
        if term:
            lookup = await client.get("/series/lookup", params={"term": term})
            if not is_error(lookup) and isinstance(lookup, list):
                # Restrict to *library* series — we only want things we already track.
                library = await client.get("/series")
                library_by_tvdb: dict[int, dict[str, Any]] = {}
                if isinstance(library, list):
                    library_by_tvdb = {s["tvdbId"]: s for s in library if s.get("tvdbId")}

                for hit in lookup[:10]:
                    tvdb_id = hit.get("tvdbId")
                    in_library = library_by_tvdb.get(tvdb_id) if tvdb_id else None
                    if not in_library:
                        continue
                    fuzzy = title_similarity(term, in_library.get("title") or "")
                    episodes = await client.get("/episode", params={"seriesId": in_library["id"]})
                    if is_error(episodes) or not isinstance(episodes, list):
                        continue
                    matched_eps = []
                    if parsed_episode:
                        season, ep_no = parsed_episode
                        matched_eps = [
                            ep
                            for ep in episodes
                            if ep.get("seasonNumber") == season and ep.get("episodeNumber") == ep_no
                        ]
                    if matched_eps:
                        for ep in matched_eps:
                            confidence = score_candidate(
                                parsed_series_match=False,
                                fuzzy_title_score=fuzzy,
                                parsed_episode=parsed_episode,
                                candidate_episode=(ep.get("seasonNumber"), ep.get("episodeNumber")),
                                has_parser_result=parsed_series is not None,
                            )
                            candidates.append(
                                _build_candidate(
                                    confidence=confidence,
                                    file_path=file_path,
                                    series=in_library,
                                    episode=ep,
                                    quality=None,
                                    languages=[],
                                    download_id=None,
                                    source="lookup",
                                )
                            )
                    else:
                        # Series matched but episode didn't — still useful as a 0.4 lead.
                        candidates.append(
                            _build_candidate(
                                confidence=score_candidate(
                                    parsed_series_match=False,
                                    fuzzy_title_score=fuzzy,
                                    parsed_episode=parsed_episode,
                                    candidate_episode=None,
                                    has_parser_result=True,
                                ),
                                file_path=file_path,
                                series=in_library,
                                episode=None,
                                quality=None,
                                languages=[],
                                download_id=None,
                                source="lookup-series-only",
                            )
                        )

    # Case 3: nothing matched — return the parser blob so the agent has *something*.
    if not candidates:
        candidates.append(
            {
                "confidence": 0.0,
                "source": "none",
                "filePath": file_path,
                "parsed": (parse_result or {}).get("parsedEpisodeInfo")
                if isinstance(parse_result, dict)
                else None,
                "submitPayload": None,
            }
        )

    candidates.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
    return {"filePath": file_path, "parsedEpisode": parsed_episode, "candidates": candidates}


def _quality_from_episodes(eps: list[dict[str, Any]]) -> Any:
    for ep in eps:
        ef = ep.get("episodeFile")
        if isinstance(ef, dict) and ef.get("quality"):
            return ef["quality"]
    return None


def _build_candidate(
    *,
    confidence: float,
    file_path: str,
    series: dict[str, Any],
    episode: dict[str, Any] | None,
    quality: Any,
    languages: list[Any],
    download_id: str | None,
    source: str,
) -> dict[str, Any]:
    """Shape one candidate + a ready-to-submit payload for ``resolve_import``."""
    submit_payload = {
        "path": file_path,
        "seriesId": series.get("id"),
        "episodeIds": [episode["id"]] if episode and episode.get("id") else [],
        "quality": quality,
        "languages": languages or [],
        "downloadId": download_id,
    }
    return {
        "confidence": round(confidence, 3),
        "source": source,
        "filePath": file_path,
        "series": {"id": series.get("id"), "title": series.get("title"), "tvdbId": series.get("tvdbId")},
        "episode": (
            {
                "id": episode.get("id"),
                "seasonNumber": episode.get("seasonNumber"),
                "episodeNumber": episode.get("episodeNumber"),
                "title": episode.get("title"),
            }
            if episode
            else None
        ),
        "submitPayload": submit_payload,
    }


async def resolve_import(
    client: SonarrClient,
    payload: list[dict[str, Any]] | dict[str, Any],
    *,
    import_mode: str = "auto",
) -> dict[str, Any]:
    """Submit one or more files via Sonarr's ``ManualImport`` command.

    Sonarr accepts a ``ManualImport`` command on ``POST /command`` whose
    body is a list of files (see ``ManualImportCommand.cs`` /
    ``ManualImportFile.cs``). Each file needs at minimum ``path``,
    ``seriesId``, and ``episodeIds``.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not payload:
        return {"error": "payload must be a non-empty list", "status": 0}

    files = []
    for item in payload:
        files.append(
            {
                "path": item.get("path"),
                "folderName": item.get("folderName"),
                "seriesId": item.get("seriesId"),
                "episodeIds": item.get("episodeIds") or [],
                "quality": item.get("quality"),
                "languages": item.get("languages") or [],
                "releaseGroup": item.get("releaseGroup"),
                "downloadId": item.get("downloadId"),
                "episodeFileId": item.get("episodeFileId"),
            }
        )
    body = {
        "name": "ManualImport",
        "files": files,
        "importMode": import_mode,
    }
    return await client.post("/command", json=body)


async def blocklist_and_search(
    client: SonarrClient, queue_id: int, *, skip_redownload: bool = False
) -> dict[str, Any]:
    """Blocklist a stuck queue item and let Sonarr search for a replacement."""
    result = await client.delete(
        f"/queue/{queue_id}",
        params={
            "removeFromClient": True,
            "blocklist": True,
            "skipRedownload": skip_redownload,
        },
    )
    if is_error(result):
        return result
    return {"ok": True, "queueId": queue_id, "blocklisted": True, "skipRedownload": skip_redownload}


async def delete_stuck(
    client: SonarrClient, queue_id: int, *, remove_from_client: bool = True
) -> dict[str, Any]:
    """Drop a queue item without blocklisting (useful for retrying)."""
    result = await client.delete(
        f"/queue/{queue_id}",
        params={"removeFromClient": remove_from_client, "blocklist": False},
    )
    if is_error(result):
        return result
    return {"ok": True, "queueId": queue_id, "removedFromClient": remove_from_client}


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------
def register(server: Any, client: SonarrClient) -> None:
    @server.tool(name="get_stuck_imports")
    async def _get_stuck_imports() -> dict[str, Any]:
        """List stuck imports (queue items in warning/error) with manual-import candidates merged in.

        This is the entry point for the "fix my Sonarr" workflow: it
        answers "what's broken right now and what does Sonarr already
        have ready to act on?".
        """
        return await get_stuck_imports(client)

    @server.tool(name="suggest_import_resolution")
    async def _suggest_import_resolution(file_path: str) -> dict[str, Any]:
        """Suggest series/episode matches for a stuck file, with confidence scores.

        Returns ranked candidates plus a ``submitPayload`` per candidate
        that can be passed straight into ``resolve_import``.
        """
        return await suggest_import_resolution(client, file_path)

    @server.tool(name="resolve_import")
    async def _resolve_import(
        payload: list[dict[str, Any]],
        import_mode: str = "auto",
    ) -> dict[str, Any]:
        """Resolve one or more stuck imports.

        ``payload`` is a list of items (typically the ``submitPayload``
        from ``suggest_import_resolution``). ``import_mode`` is one of
        ``auto``, ``move``, ``copy``.
        """
        return await resolve_import(client, payload, import_mode=import_mode)

    @server.tool(name="blocklist_and_search")
    async def _blocklist_and_search(
        queue_id: int, skip_redownload: bool = False
    ) -> dict[str, Any]:
        """Blocklist a queue item and trigger a search for a replacement."""
        return await blocklist_and_search(client, queue_id, skip_redownload=skip_redownload)

    @server.tool(name="delete_stuck")
    async def _delete_stuck(queue_id: int, remove_from_client: bool = True) -> dict[str, Any]:
        """Remove a stuck queue item (without blocklisting)."""
        return await delete_stuck(client, queue_id, remove_from_client=remove_from_client)


__all__ = [
    "BAD_TRACKED_STATUSES",
    "blocklist_and_search",
    "delete_stuck",
    "get_stuck_imports",
    "guess_series_term",
    "merge_stuck",
    "parse_episode_tag",
    "register",
    "resolve_import",
    "score_candidate",
    "slim_manual_import",
    "slim_queue_item",
    "suggest_import_resolution",
    "title_similarity",
]
