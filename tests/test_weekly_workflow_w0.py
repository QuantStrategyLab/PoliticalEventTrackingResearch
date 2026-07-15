from __future__ import annotations

from pathlib import Path

import pytest

from political_event_tracking_research.rss_source_fetch import FetchStatusError, validate_fetch_status
from political_event_tracking_research.workflow_boundary import PathBoundaryError, validate_source_paths


def status(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": "2026-07-16T00:00:00Z",
        "feed_count": 2,
        "successful_feed_count": 2,
        "failed_feed_count": 0,
        "item_count": 1,
        "feeds": [
            {"feed_id": "a", "feed_url": "https://a.example/feed", "ok": True, "item_count": 1, "error": ""},
            {"feed_id": "b", "feed_url": "https://b.example/feed", "ok": True, "item_count": 0, "error": ""},
        ],
    }
    payload.update(overrides)
    return payload


def test_fetch_status_validation_returns_complete_state() -> None:
    assert validate_fetch_status(status()) is True
    assert validate_fetch_status(status(failed_feed_count=1, successful_feed_count=1, feeds=[
        {"feed_id": "a", "feed_url": "https://a.example/feed", "ok": True, "item_count": 1, "error": ""},
        {"feed_id": "b", "feed_url": "https://b.example/feed", "ok": False, "item_count": 0, "error": "blocked"},
    ])) is False


@pytest.mark.parametrize("change", [{"complete": False}, {"failed_feed_count": 1}, {"unknown": 1}, {"feeds": []}])
def test_fetch_status_shape_or_incompleteness_fails_closed(change: dict[str, object]) -> None:
    with pytest.raises(FetchStatusError):
        validate_fetch_status({**status(), **change})


@pytest.mark.parametrize("value", ["config/other.csv", "../config/free_rss_feeds.csv", "/tmp/feeds.csv", "config\\feeds.csv", ""])
def test_manual_source_paths_are_canonical_only(value: str) -> None:
    with pytest.raises(PathBoundaryError):
        validate_source_paths(value, "config/core_us_equity_aliases.csv", "data/live/political_watchlist.csv")


def test_workflow_orders_debug_upload_gate_and_live_push() -> None:
    workflow = Path(__file__).parents[1].joinpath(".github/workflows/rss_source_pipeline.yml").read_text(encoding="utf-8")
    assert workflow.index("Validate canonical workflow inputs") < workflow.index("actions/checkout@")
    assert workflow.index("Upload RSS source artifact") < workflow.index("Validate feed completeness")
    assert workflow.index("Validate feed completeness") < workflow.index("Publish live CSV outputs")
    assert "git push origin HEAD:refs/heads/main" in workflow
    assert "git rev-parse HEAD" in workflow
    assert "weekly" not in workflow.lower()
