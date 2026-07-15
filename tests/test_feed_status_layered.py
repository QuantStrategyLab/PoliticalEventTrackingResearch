from __future__ import annotations

import pytest

from political_event_tracking_research.feed_primitives import (
    FetchResult,
    PrimitiveStatusError,
    build_fetch_result,
)


ROW = {
    "item_id": "a-1",
    "published_at": "2026-05-01T12:30:00Z",
    "source_type": "official",
    "source_url": "https://example.test/a",
    "author": "",
    "text": "event",
}


def record(
    feed_id: str,
    state: str,
    *,
    rows: list[dict[str, str]] | None = None,
    kind: str = "rss2",
    error_code: str | None = None,
) -> dict[str, object]:
    return {
        "feed_id": feed_id,
        "feed_url": f"https://example.test/{feed_id}",
        "kind": kind,
        "state": state,
        "rows": rows if rows is not None else ([ROW] if state == "accepted" else []),
        "error_code": error_code,
    }


def test_all_quarantine_is_canonical_incomplete_without_hard_failure() -> None:
    result = build_fetch_result([record("empty", "quarantined", error_code="zero_entries")])
    assert isinstance(result, FetchResult)
    assert result.hard_failure is False
    assert result.publication_eligible is False
    assert result.status["quarantined_feed_count"] == 1


@pytest.mark.parametrize(
    "records",
    [
        [record("bad", "failed", error_code="fetch_failed")],
        [record("bad", "failed", error_code="fetch_failed"), record("empty", "quarantined", error_code="zero_entries")],
        [record("good", "accepted"), record("bad", "failed", error_code="fetch_failed")],
    ],
)
def test_any_failed_feed_preserves_status_but_hard_fails(records: list[dict[str, object]]) -> None:
    result = build_fetch_result(records)
    assert result.hard_failure is True
    assert result.publication_eligible is False
    assert result.status["failed_feed_count"] >= 1


def test_accepted_and_quarantine_is_incomplete_without_hard_failure() -> None:
    result = build_fetch_result(
        [record("good", "accepted"), record("empty", "quarantined", error_code="zero_entries")]
    )
    assert result.hard_failure is False
    assert result.status["accepted_row_count"] == 1
    assert result.publication_eligible is False


def test_empty_configuration_is_invalid() -> None:
    with pytest.raises(PrimitiveStatusError, match="feed_config_empty"):
        build_fetch_result([])
