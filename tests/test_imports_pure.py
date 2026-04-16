"""Pure-logic tests for ``sonarr_mcp.tools.imports``: scoring + merging."""

from __future__ import annotations

from sonarr_mcp.tools.imports import (
    BAD_TRACKED_STATUSES,
    guess_series_term,
    merge_stuck,
    parse_episode_tag,
    score_candidate,
    slim_manual_import,
    slim_queue_item,
    title_similarity,
)


# --- parse_episode_tag --------------------------------------------------
def test_parse_episode_tag_sxxeyy() -> None:
    assert parse_episode_tag("Show.Name.S01E02.1080p.WEB.mkv") == (1, 2)


def test_parse_episode_tag_lowercase() -> None:
    assert parse_episode_tag("some.show.s12e04.foo.mkv") == (12, 4)


def test_parse_episode_tag_nxm() -> None:
    assert parse_episode_tag("Show 2x05 - Title.mkv") == (2, 5)


def test_parse_episode_tag_no_match() -> None:
    assert parse_episode_tag("Some Random File.mkv") is None
    assert parse_episode_tag("") is None


# --- title_similarity ---------------------------------------------------
def test_title_similarity_identical() -> None:
    assert title_similarity("Severance", "Severance") == 1.0


def test_title_similarity_close_match() -> None:
    score = title_similarity("the.bear", "The Bear")
    assert score > 0.8


def test_title_similarity_unrelated() -> None:
    assert title_similarity("Severance", "Breaking Bad") < 0.5


def test_title_similarity_empty_inputs() -> None:
    assert title_similarity("", "Show") == 0.0
    assert title_similarity("Show", "") == 0.0


# --- score_candidate ----------------------------------------------------
def test_score_exact_series_and_episode() -> None:
    assert score_candidate(
        parsed_series_match=True,
        fuzzy_title_score=1.0,
        parsed_episode=(1, 2),
        candidate_episode=(1, 2),
        has_parser_result=True,
    ) == 1.0


def test_score_fuzzy_title_with_episode_match() -> None:
    assert score_candidate(
        parsed_series_match=False,
        fuzzy_title_score=0.85,
        parsed_episode=(1, 2),
        candidate_episode=(1, 2),
        has_parser_result=True,
    ) == 0.7


def test_score_fallback_parser_only() -> None:
    assert score_candidate(
        parsed_series_match=False,
        fuzzy_title_score=0.2,
        parsed_episode=None,
        candidate_episode=None,
        has_parser_result=True,
    ) == 0.4


def test_score_zero_when_nothing_matches() -> None:
    assert score_candidate(
        parsed_series_match=False,
        fuzzy_title_score=0.1,
        parsed_episode=(1, 2),
        candidate_episode=(3, 4),
        has_parser_result=False,
    ) == 0.0


def test_score_episode_mismatch_demotes_exact_series() -> None:
    # Exact series match but wrong episode shouldn't get the 1.0 bucket.
    score = score_candidate(
        parsed_series_match=True,
        fuzzy_title_score=1.0,
        parsed_episode=(1, 2),
        candidate_episode=(1, 3),
        has_parser_result=True,
    )
    assert score < 1.0


# --- guess_series_term --------------------------------------------------
def test_guess_series_term_strips_episode_tag() -> None:
    assert guess_series_term("The.Bear.S02E05.1080p.WEB.mkv") == "The Bear"


def test_guess_series_term_strips_year() -> None:
    assert guess_series_term("Doctor.Who.2005.S01E01.mkv").lower().startswith("doctor who")


def test_guess_series_term_handles_path() -> None:
    assert guess_series_term("/downloads/Show.Name.S01E02.mkv") == "Show Name"


# --- merge_stuck --------------------------------------------------------
def test_merge_stuck_filters_to_bad_statuses() -> None:
    queue = [
        {"id": 1, "downloadId": "abc", "trackedDownloadStatus": "ok"},
        {"id": 2, "downloadId": "def", "trackedDownloadStatus": "warning"},
        {"id": 3, "downloadId": "ghi", "trackedDownloadStatus": "ERROR"},
    ]
    out = merge_stuck(queue, {})
    ids = sorted(item["queueId"] for item in out)
    assert ids == [2, 3]


def test_merge_stuck_attaches_candidates_by_download_id() -> None:
    queue = [{"id": 5, "downloadId": "xyz", "trackedDownloadStatus": "warning"}]
    candidates = {"xyz": [{"id": 99, "path": "/x/y.mkv"}]}
    out = merge_stuck(queue, candidates)
    assert out[0]["manualImportCandidates"] == [{"id": 99, "path": "/x/y.mkv"}]


def test_merge_stuck_handles_missing_download_id() -> None:
    queue = [{"id": 7, "trackedDownloadStatus": "warning"}]
    out = merge_stuck(queue, {"xyz": [{"id": 1}]})
    assert out[0]["manualImportCandidates"] == []


def test_bad_statuses_constant_is_lowercase_set() -> None:
    assert BAD_TRACKED_STATUSES == {"warning", "error"}


# --- slim_* -------------------------------------------------------------
def test_slim_queue_item_picks_only_useful_fields() -> None:
    queue_item = {
        "id": 1,
        "downloadId": "abc",
        "title": "Show.S01E01",
        "size": 1024,
        "trackedDownloadStatus": "warning",
        "statusMessages": [
            {"title": "Failed", "messages": ["x"], "irrelevant": "drop me"}
        ],
        "quality": {"quality": {"id": 7, "name": "WEB-1080p"}},
        "languages": [{"id": 1, "name": "English"}],
        "internalSecret": "should-not-leak",
    }
    slim = slim_queue_item(queue_item)
    assert "internalSecret" not in slim
    assert slim["quality"] == {"id": 7, "name": "WEB-1080p"}
    assert slim["languages"] == [{"id": 1, "name": "English"}]
    assert slim["statusMessages"] == [{"title": "Failed", "messages": ["x"]}]


def test_slim_manual_import_drops_heavy_fields() -> None:
    item = {
        "id": 42,
        "path": "/data/show.mkv",
        "size": 2_000_000,
        "series": {"id": 9, "title": "Show", "images": [1, 2, 3]},
        "episodes": [{"id": 100, "episodeNumber": 1, "seasonNumber": 1, "title": "Pilot", "images": []}],
        "rejections": [{"reason": "Unknown", "type": "Permanent", "message": "foo"}],
        "customFormats": [{"id": 1, "name": "x265"}],
        "downloadId": "dl",
    }
    slim = slim_manual_import(item)
    assert slim["series"] == {"id": 9, "title": "Show"}
    assert "customFormats" not in slim
    assert slim["episodes"][0] == {
        "id": 100,
        "episodeNumber": 1,
        "seasonNumber": 1,
        "title": "Pilot",
    }
    assert slim["rejections"][0]["reason"] == "Unknown"
