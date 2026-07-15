from __future__ import annotations

import json

import pytest

from political_event_tracking_research.fetch_acceptance import (
    FetchAcceptanceError,
    build_acceptance_status,
    classify_feed_payload,
    parse_status_bytes,
    serialize_status,
)


RSS = b"""<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>Feed</title><item><title>Event</title><link>https://example.test/event</link><pubDate>Fri, 01 May 2026 12:30:00 GMT</pubDate><description>Text</description></item></channel></rss>"""
ATOM = b"""<?xml version=\"1.0\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"><title>Feed</title><entry><title>Event</title><link href=\"https://example.test/event\"/><updated>2026-05-01T12:30:00Z</updated><summary>Text</summary></entry></feed>"""
NON_FEED = b"<root><item><title>Not RSS</title></item></root>"


def test_rss_and_atom_are_recognized_with_exact_rows() -> None:
    rss = classify_feed_payload("rss", "https://example.test/rss", RSS)
    atom = classify_feed_payload("atom", "https://example.test/atom", ATOM)
    assert (rss["kind"], rss["accepted_row_count"], rss["rejected_row_count"]) == ("rss", 1, 0)
    assert (atom["kind"], atom["accepted_row_count"], atom["rejected_row_count"]) == ("atom", 1, 0)


@pytest.mark.parametrize("payload", [NON_FEED, b"<rss>", b"not xml"])
def test_non_rss_or_malformed_payload_fails_closed(payload: bytes) -> None:
    result = classify_feed_payload("feed", "https://example.test/feed", payload)
    assert result["state"] == "failed"
    assert result["accepted_row_count"] == 0


def test_unsupported_rss_schema_is_not_successful() -> None:
    result = classify_feed_payload("feed", "https://example.test/feed", RSS.replace(b'version="2.0"', b'version="1.0"'))
    assert result["state"] == "failed"
    assert result["error_code"] == "rss_schema_unsupported"


def test_zero_entry_is_quarantined_not_complete() -> None:
    result = classify_feed_payload("empty", "https://example.test/empty", b"<rss version='2.0'><channel><title>Empty</title></channel></rss>")
    status = build_acceptance_status([result])
    assert result["state"] == "quarantined"
    assert status["publication_complete"] is False
    assert status["eligible_for_live_publication"] is False
    assert status["zero_entry_policy"] == "quarantine"


def test_mixed_partial_counts_are_exact_and_incomplete() -> None:
    accepted = classify_feed_payload("ok", "https://example.test/ok", RSS)
    failed = classify_feed_payload("bad", "https://example.test/bad", NON_FEED)
    status = build_acceptance_status([accepted, failed])
    assert status["configured_feed_count"] == 2
    assert status["successful_feed_count"] == 1
    assert status["failed_feed_count"] == 1
    assert status["accepted_row_count"] == 1
    assert status["publication_complete"] is False


def test_empty_config_and_counter_mismatch_fail_closed() -> None:
    with pytest.raises(FetchAcceptanceError):
        build_acceptance_status([])
    status = build_acceptance_status([classify_feed_payload("ok", "https://example.test/ok", RSS)])
    tampered = dict(status)
    tampered["accepted_row_count"] = 999
    with pytest.raises(FetchAcceptanceError):
        serialize_status(tampered)


def test_status_canonical_roundtrip_and_tamper_rejection() -> None:
    status = build_acceptance_status([classify_feed_payload("ok", "https://example.test/ok", RSS)])
    wire = serialize_status(status)
    assert parse_status_bytes(wire) == status
    assert serialize_status(parse_status_bytes(wire)) == wire
    with pytest.raises(FetchAcceptanceError):
        parse_status_bytes(b" " + wire)
    payload = json.loads(wire)
    payload["unknown"] = True
    with pytest.raises(FetchAcceptanceError):
        serialize_status(payload)


def test_invalid_entry_is_counted_not_accepted() -> None:
    payload = RSS.replace(b"<link>https://example.test/event</link>", b"")
    result = classify_feed_payload("feed", "https://example.test/feed", payload)
    assert result["accepted_row_count"] == 0
    assert result["rejected_row_count"] == 1
    assert result["state"] == "quarantined"
