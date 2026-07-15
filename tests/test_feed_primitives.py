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
        "kind": "rss2",
        "state": state,
        "rows": rows if rows is not None else [ROW],
        "error_code": error_code,
    }


def test_quarantine_has_zero_rows_and_no_accepted_digest_contribution() -> None:
    empty = feed("empty", state="quarantined", rows=[], error_code="zero_entries")
    status = build_status([feed("good"), empty])
    good_only = build_status([feed("good")])
    assert status["accepted_row_count"] == good_only["accepted_row_count"]
    assert status["aggregate_row_digest"] == good_only["aggregate_row_digest"]
    assert status["publication_complete"] is False
    assert status["eligible_for_live_publication"] is False


def test_quarantine_with_rows_and_failed_rows_are_rejected() -> None:
    with pytest.raises(PrimitiveStatusError, match="feed_state_invalid"):
        build_status([feed("empty", state="quarantined", error_code="zero_entries")])
    status = build_status([feed("bad", state="failed", rows=[], error_code="fetch_failed")])
    assert status["accepted_row_count"] == 0
    assert status["publication_complete"] is False


def test_status_roundtrip_and_feed_order_are_canonical() -> None:
    status = build_status([feed("b"), feed("a")])
    wire = serialize_status(status)
    assert parse_status_bytes(wire) == status
    payload = json.loads(wire)
    payload["feeds"] = list(reversed(payload["feeds"]))
    with pytest.raises(PrimitiveStatusError, match="feed_order_invalid"):
        serialize_status(payload)


def test_status_digest_binds_one_snapshot() -> None:
    status = build_status([feed("a")])
    assert status_for_rows(serialize_status(status), [feed("a")]) == status
    changed = {**ROW, "item_id": "changed"}
    with pytest.raises(PrimitiveStatusError, match="status_integrity_mismatch"):
        status_for_rows(serialize_status(status), [feed("a", rows=[changed])])


def test_safe_integer_and_bool_are_rejected() -> None:
    payload = json.loads(serialize_status(build_status([feed("a")])))
    payload["feed_count"] = MAX_SAFE_JSON_INTEGER + 1
    with pytest.raises(PrimitiveStatusError, match="status_counter_invalid"):
        serialize_status(payload)
    payload["feed_count"] = True
    with pytest.raises(PrimitiveStatusError, match="status_counter_invalid"):
        serialize_status(payload)
