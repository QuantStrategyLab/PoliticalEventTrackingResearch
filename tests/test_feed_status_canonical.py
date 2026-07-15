from __future__ import annotations

import hashlib
import json

import pytest

from political_event_tracking_research.feed_status_canonical import (
    DecisionContractError,
    DecisionKind,
    build_decision,
    read_status,
    status_digest,
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


def test_build_returns_only_canonical_bytes_and_explicit_decision() -> None:
    result = build_decision([outcome("empty", "quarantined", error_code="zero_entries")])
    assert type(result.status_bytes) is bytes
    assert result.decision.kind is DecisionKind.QUARANTINE
    assert json.loads(result.status_bytes)["eligible_for_live_publication"] is False


def test_read_status_is_json_native_and_mutation_isolated() -> None:
    result = build_decision([outcome("a", "accepted")])
    first = read_status(result.status_bytes)
    assert isinstance(first, dict)
    json.dumps(first)
    first["feed_count"] = 99
    first["feeds"][0]["feed_id"] = "changed"
    second = read_status(result.status_bytes)
    assert second["feed_count"] == 1
    assert second["feeds"][0]["feed_id"] == "a"


def test_digest_only_depends_on_status_bytes() -> None:
    result = build_decision([outcome("a", "accepted")])
    assert status_digest(result.status_bytes) == hashlib.sha256(result.status_bytes).hexdigest()
    assert status_digest(result.status_bytes) == status_digest(bytes(result.status_bytes))


@pytest.mark.parametrize(
    "records,kind",
    [
        ([outcome("a", "accepted")], DecisionKind.SUCCESS),
        ([outcome("empty", "quarantined", error_code="zero_entries")], DecisionKind.QUARANTINE),
        ([outcome("bad", "failed", kind="unknown", error_code="fetch_failed")], DecisionKind.HARD_FAIL),
        (
            [
                outcome("bad", "failed", kind="unknown", error_code="fetch_failed"),
                outcome("empty", "quarantined", error_code="zero_entries"),
            ],
            DecisionKind.HARD_FAIL,
        ),
    ],
)
def test_decision_status_combinations(records: list[dict[str, object]], kind: DecisionKind) -> None:
    assert build_decision(records).decision.kind is kind


def test_tampered_duplicate_and_noncanonical_bytes_fail_closed() -> None:
    result = build_decision([outcome("a", "accepted")])
    tampered = result.status_bytes.replace(b'"feed_count":1', b'"feed_count":2')
    with pytest.raises(DecisionContractError, match="status_"):
        read_status(tampered)
    duplicate = result.status_bytes.replace(b'"feed_count":1', b'"feed_count":1,"feed_count":1')
    with pytest.raises(DecisionContractError, match="duplicate"):
        read_status(duplicate)
    with pytest.raises(DecisionContractError, match="noncanonical"):
        read_status(result.status_bytes + b"\n")
