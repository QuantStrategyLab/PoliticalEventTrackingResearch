from __future__ import annotations

import json

import pytest

from political_event_tracking_research.feed_primitives import (
    MAX_SAFE_JSON_INTEGER,
    PrimitiveStatusError,
    build_status,
    parse_status_bytes,
    serialize_status,
    status_for_rows,
)


ROW = {
    "item_id": "feed-a-1",
    "published_at": "2026-05-01T12:30:00Z",
    "source_type": "official_remarks",
    "source_url": "https://example.test/item/1",
    "author": "Example",
    "text": "Policy mention",
}


def feed(
    feed_id: str,
    *,
    state: str = "accepted",
    rows: list[dict[str, str]] | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    return {
        "feed_id": feed_id,
        "feed_url": f"https://example.test/{feed_id}",
        "kind": "rss",
        "state": state,
        "rows": rows if rows is not None else [ROW],
        "error_code": error_code,
    }


def test_quarantine_contributes_no_rows_or_digest() -> None:
    status = build_status([feed("empty", state="quarantined", rows=[], error_code="zero_entries")])
    other = build_status([feed("other", state="quarantined", rows=[], error_code="zero_entries")])
    assert status["accepted_row_count"] == 0
    assert status["aggregate_row_digest"] == other["aggregate_row_digest"]
    assert status["publication_complete"] is False
    assert status["eligible_for_live_publication"] is False
    mixed = build_status([feed("good"), feed("empty", state="quarantined", rows=[], error_code="zero_entries")])
    good_only = build_status([feed("good")])
    assert mixed["accepted_row_count"] == good_only["accepted_row_count"]
    assert mixed["aggregate_row_digest"] == good_only["aggregate_row_digest"]


def test_quarantine_with_rows_is_rejected() -> None:
    with pytest.raises(PrimitiveStatusError, match="feed_state_invalid"):
        build_status([feed("empty", state="quarantined", error_code="entry_invalid")])


def test_failed_rows_are_excluded_and_mixed_status_is_not_complete() -> None:
    status = build_status([feed("good"), feed("bad", state="failed", rows=[], error_code="fetch_failed")])
    assert status["accepted_row_count"] == 1
    assert status["failed_feed_count"] == 1
    assert status["publication_complete"] is False
    assert status_for_rows(
        serialize_status(status),
        [feed("bad", state="failed", rows=[], error_code="fetch_failed"), feed("good")],
    ) == status


def test_digest_matches_emitted_row_order() -> None:
    late = {**ROW, "item_id": "feed-a-2", "published_at": "2026-05-02T12:30:00Z"}
    status = build_status([feed("a", rows=[late, ROW])])
    assert status["aggregate_row_digest"] == build_status([feed("a", rows=[ROW, late])])["aggregate_row_digest"]


def test_canonical_roundtrip_and_order_are_strict() -> None:
    status = build_status([feed("b"), feed("a")])
    wire = serialize_status(status)
    assert parse_status_bytes(wire) == status
    payload = json.loads(wire)
    payload["feeds"] = list(reversed(payload["feeds"]))
    with pytest.raises(PrimitiveStatusError, match="feed_order_invalid"):
        serialize_status(payload)


def test_integer_bounds_are_strict() -> None:
    status = build_status([feed("a")])
    payload = json.loads(serialize_status(status))
    payload["feed_count"] = MAX_SAFE_JSON_INTEGER + 1
    with pytest.raises(PrimitiveStatusError, match="status_counter_invalid"):
        serialize_status(payload)
    payload["feed_count"] = True
    with pytest.raises(PrimitiveStatusError, match="status_counter_invalid"):
        serialize_status(payload)
