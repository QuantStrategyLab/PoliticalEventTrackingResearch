from __future__ import annotations

import json

import pytest

from political_event_tracking_research.feed_primitives import (
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


def test_status_binds_rows_and_is_canonical() -> None:
    status = build_status([feed("b"), feed("a")])
    wire = serialize_status(status)
    assert parse_status_bytes(wire) == status
    assert status_for_rows(wire, [feed("a"), feed("b")]) == status
    assert status["accepted_row_count"] == 2
    assert status["publication_complete"] is True


def test_feed_input_order_is_not_semantic() -> None:
    left = build_status([feed("a"), feed("b")])
    right = build_status([feed("b"), feed("a")])
    assert left == right
    assert serialize_status(left) == serialize_status(right)


def test_row_order_is_producer_semantic() -> None:
    other = {**ROW, "item_id": "feed-a-2"}
    assert build_status([feed("a", rows=[ROW, other])]) != build_status([feed("a", rows=[other, ROW])])


@pytest.mark.parametrize(
    "record",
    [
        feed("a", state="failed", rows=[], error_code=None),
        feed("a", state="failed", error_code="network"),
        feed("a", state="quarantined", rows=[], error_code=None),
        feed("a", state="accepted", rows=[], error_code=None),
        feed("a", state="accepted", error_code="unexpected"),
        feed("a", state="stale", error_code="old"),
    ],
)
def test_state_contract_is_closed(record: dict[str, object]) -> None:
    with pytest.raises(PrimitiveStatusError):
        build_status([record])


def test_failed_and_quarantined_are_not_eligible() -> None:
    status = build_status([feed("good"), feed("bad", state="failed", rows=[], error_code="network")])
    assert status["publication_complete"] is False
    assert status["eligible_for_live_publication"] is False
    assert status["failed_feed_count"] == 1

    empty = build_status([feed("empty", state="quarantined", rows=[], error_code="zero_entries")])
    assert empty["accepted_row_count"] == 0
    assert empty["publication_complete"] is False


def test_status_digest_mismatch_is_rejected() -> None:
    status = build_status([feed("a")])
    wire = json.loads(serialize_status(status))
    wire["feeds"][0]["row_digest"] = "0" * 64
    with pytest.raises(PrimitiveStatusError, match="status_integrity_mismatch"):
        status_for_rows(serialize_status(wire), [feed("a")])


def test_malformed_mapping_generator_and_stateful_rows_are_sanitized() -> None:
    with pytest.raises(PrimitiveStatusError, match="feed_shape_invalid"):
        build_status([{"feed_id": "a"}])

    def records():
        yield feed("a")

    assert build_status(records())["feed_count"] == 1

    class DivergingRows:
        def __iter__(self):
            yield ROW
            yield {**ROW, "item_id": "changed"}

    record = feed("a")
    record["rows"] = DivergingRows()
    with pytest.raises(PrimitiveStatusError, match="status_integrity_mismatch"):
        status_for_rows(serialize_status(build_status([feed("a")])), [record])


def test_unknown_keys_duplicate_wire_and_unsafe_types_fail_closed() -> None:
    status = build_status([feed("a")])
    payload = json.loads(serialize_status(status))
    payload["unknown"] = True
    with pytest.raises(PrimitiveStatusError):
        serialize_status(payload)

    payload = json.loads(serialize_status(status))
    payload["feed_count"] = True
    with pytest.raises(PrimitiveStatusError):
        serialize_status(payload)

    duplicate = serialize_status(status).replace(b'"status_version":', b'"status_version":')
    with pytest.raises(PrimitiveStatusError):
        parse_status_bytes(duplicate[:-1] + b',"status_version":"other"}')
