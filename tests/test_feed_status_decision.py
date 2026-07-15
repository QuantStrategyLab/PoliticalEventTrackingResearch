from __future__ import annotations

import json

import pytest

from political_event_tracking_research.feed_status_decision import (
    DecisionContractError,
    DecisionKind,
    StatusDecision,
    build_status_decision,
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


def test_all_quarantined_returns_evidence_and_quarantine_decision() -> None:
    result = build_status_decision([outcome("empty", "quarantined", error_code="zero_entries")])
    assert isinstance(result, StatusDecision)
    assert result.decision.kind is DecisionKind.QUARANTINE
    assert result.evidence.status["publication_complete"] is False
    assert result.evidence.status["eligible_for_live_publication"] is False
    assert result.evidence.status["accepted_row_count"] == 0


def test_failed_and_mixed_failed_return_evidence_without_raising() -> None:
    for records in (
        [outcome("bad", "failed", kind="unknown", error_code="fetch_failed")],
        [
            outcome("bad", "failed", kind="unknown", error_code="fetch_failed"),
            outcome("empty", "quarantined", error_code="zero_entries"),
        ],
        [outcome("good", "accepted"), outcome("bad", "failed", kind="unknown", error_code="fetch_failed")],
    ):
        result = build_status_decision(records)
        assert result.decision.kind is DecisionKind.HARD_FAIL
        assert result.evidence.status["failed_feed_count"] == 1
        assert result.evidence.canonical_bytes == result.evidence.canonical_bytes


def test_accepted_and_quarantined_returns_incomplete_quarantine_decision() -> None:
    result = build_status_decision(
        [outcome("good", "accepted"), outcome("empty", "quarantined", error_code="zero_entries")]
    )
    assert result.decision.kind is DecisionKind.QUARANTINE
    assert result.evidence.status["accepted_row_count"] == 1
    assert result.evidence.status["publication_complete"] is False


def test_all_accepted_returns_success() -> None:
    result = build_status_decision([outcome("a", "accepted"), outcome("b", "accepted")])
    assert result.decision.kind is DecisionKind.SUCCESS
    assert result.evidence.status["publication_complete"] is True
    assert result.evidence.status["eligible_for_live_publication"] is True


def test_empty_or_malformed_input_is_sanitized_contract_error() -> None:
    with pytest.raises(DecisionContractError, match="feed_config_empty"):
        build_status_decision([])
    with pytest.raises(DecisionContractError, match="feed_kind_invalid"):
        build_status_decision([outcome("bad", "accepted", kind="unknown")])


def test_base_exception_propagates() -> None:
    def outcomes():
        raise KeyboardInterrupt
        yield outcome("never", "accepted")

    with pytest.raises(KeyboardInterrupt):
        build_status_decision(outcomes())


def test_wire_is_canonical_and_deterministic() -> None:
    first = build_status_decision([outcome("b", "accepted"), outcome("a", "accepted")])
    second = build_status_decision([outcome("a", "accepted"), outcome("b", "accepted")])
    assert first.evidence.canonical_bytes == second.evidence.canonical_bytes
    assert json.loads(first.evidence.canonical_bytes)["feeds"][0]["feed_id"] == "a"


def test_status_evidence_is_deeply_immutable_and_bound_to_bytes() -> None:
    result = build_status_decision([outcome("a", "accepted")])
    with pytest.raises(TypeError):
        result.evidence.status["feed_count"] = 99
    with pytest.raises(TypeError):
        result.evidence.status["feeds"][0]["feed_id"] = "tampered"
    assert json.loads(result.evidence.canonical_bytes)["feed_count"] == result.evidence.status["feed_count"]


def test_digest_sort_is_total_for_equal_published_at_and_item_id() -> None:
    first = {**ROW, "text": "first"}
    second = {**ROW, "text": "second"}
    left = build_status_decision([outcome("a", "accepted", rows=[first, second])])
    right = build_status_decision([outcome("a", "accepted", rows=[second, first])])
    assert left.evidence.canonical_bytes == right.evidence.canonical_bytes
