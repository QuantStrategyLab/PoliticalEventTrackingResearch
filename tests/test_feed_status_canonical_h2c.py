from __future__ import annotations

import hashlib
import json

import pytest

from political_event_tracking_research.feed_status_canonical_h2c import (
    EMPTY_DIGEST,
    MAX_ROWS_PER_FEED,
    DecisionContractError,
    DecisionKind,
    build_decision,
    read_status,
)


ROW = {
    "item_id": "a-1",
    "published_at": "2026-05-01T12:30:00Z",
    "source_type": "official",
    "source_url": "https://example.test/a",
    "author": "",
    "text": "event",
}


def outcome(
    feed_id: str,
    state: str,
    *,
    kind: str = "rss2",
    rows: list[dict[str, str]] | None = None,
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


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_builder_and_reader_keep_nonempty_digest_for_accepted_rows() -> None:
    result = build_decision([outcome("a", "accepted")])
    payload = read_status(result.status_bytes)
    assert result.decision.kind is DecisionKind.SUCCESS
    assert payload["accepted_row_count"] == 1
    assert payload["feeds"][0]["row_digest"] != EMPTY_DIGEST
    assert payload["aggregate_row_digest"] != EMPTY_DIGEST


def test_zero_count_and_nonaccepted_digest_are_exact_empty_digest() -> None:
    result = build_decision([outcome("empty", "quarantined", error_code="zero_entries")])
    payload = read_status(result.status_bytes)
    assert payload["accepted_row_count"] == 0
    assert payload["aggregate_row_digest"] == EMPTY_DIGEST
    assert payload["feeds"][0]["row_digest"] == EMPTY_DIGEST


@pytest.mark.parametrize("field", ["row_digest", "aggregate_row_digest"])
def test_nonempty_count_with_empty_digest_is_rejected(field: str) -> None:
    result = build_decision([outcome("a", "accepted")])
    payload = json.loads(result.status_bytes)
    if field == "row_digest":
        payload["feeds"][0][field] = EMPTY_DIGEST
    else:
        payload[field] = EMPTY_DIGEST
    with pytest.raises(DecisionContractError, match="empty_digest"):
        read_status(canonical(payload))


def test_zero_count_with_nonempty_aggregate_digest_is_rejected() -> None:
    result = build_decision([outcome("empty", "quarantined", error_code="zero_entries")])
    payload = json.loads(result.status_bytes)
    payload["aggregate_row_digest"] = hashlib.sha256(b"tampered").hexdigest()
    with pytest.raises(DecisionContractError, match="empty_digest"):
        read_status(canonical(payload))


def test_count_sum_max_rows_and_rejected_zero_are_rechecked() -> None:
    result = build_decision([outcome("a", "accepted")])
    payload = json.loads(result.status_bytes)
    payload["feeds"][0]["accepted_row_count"] = MAX_ROWS_PER_FEED + 1
    with pytest.raises(DecisionContractError, match="counter"):
        read_status(canonical(payload))

    payload = json.loads(result.status_bytes)
    payload["accepted_row_count"] = 0
    with pytest.raises(DecisionContractError, match="counter"):
        read_status(canonical(payload))

    payload = json.loads(result.status_bytes)
    payload["feeds"][0]["rejected_row_count"] = 1
    with pytest.raises(DecisionContractError, match="rejected"):
        read_status(canonical(payload))


def test_feeds_empty_is_impossible_and_rejected() -> None:
    result = build_decision([outcome("a", "accepted")])
    payload = json.loads(result.status_bytes)
    payload["feeds"] = []
    payload["feed_count"] = 0
    payload["configured_feed_count"] = 0
    with pytest.raises(DecisionContractError, match="feed"):
        read_status(canonical(payload))
