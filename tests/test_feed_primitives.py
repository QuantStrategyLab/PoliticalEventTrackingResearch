from __future__ import annotations

import json

import pytest

from political_event_tracking_research.feed_primitives import (
    PrimitiveStatusError,
    build_status,
    parse_status_bytes,
    serialize_status,
)


ROW = {
    "item_id": "feed-a-1",
    "published_at": "2026-05-01T12:30:00Z",
    "source_type": "official",
    "source_url": "https://example.test/item/1",
    "author": "Example",
    "text": "Policy mention",
}


def record(
    feed_id: str,
    *,
    kind: str = "rss2",
    state: str = "accepted",
    rows: list[dict[str, str]] | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    return {
        "feed_id": feed_id,
        "feed_url": f"https://example.test/{feed_id}",
        "kind": kind,
        "state": state,
        "rows": rows if rows is not None else [ROW],
        "error_code": error_code,
    }


def test_unknown_kind_is_only_valid_for_failed_feed() -> None:
    failed = build_status([record("bad", kind="unknown", state="failed", rows=[], error_code="fetch_failed")])
    assert failed["feeds"][0]["kind"] == "unknown"
    for state in ("accepted", "quarantined"):
        with pytest.raises(PrimitiveStatusError, match="feed_kind_invalid|feed_state_invalid"):
            build_status([record("bad", kind="unknown", state=state, rows=[], error_code="zero_entries")])


def test_quarantined_feed_has_no_rows_or_digest_contribution() -> None:
    quarantined = record("empty", state="quarantined", rows=[], error_code="zero_entries")
    status = build_status([record("good"), quarantined])
    baseline = build_status([record("good")])
    assert status["accepted_row_count"] == baseline["accepted_row_count"]
    assert status["aggregate_row_digest"] == baseline["aggregate_row_digest"]
    assert status["publication_complete"] is False
    assert status["eligible_for_live_publication"] is False


def test_wire_rejects_unknown_kind_for_accepted_or_quarantined() -> None:
    status = build_status([record("good")])
    payload = json.loads(serialize_status(status))
    payload["feeds"][0]["kind"] = "unknown"
    with pytest.raises(PrimitiveStatusError, match="feed_kind_invalid|feed_state_invalid"):
        serialize_status(payload)


def test_wire_roundtrip_is_canonical() -> None:
    status = build_status([record("a"), record("empty", state="quarantined", rows=[], error_code="zero_entries")])
    wire = serialize_status(status)
    assert parse_status_bytes(wire) == status
    assert not wire.endswith(b"\n")
