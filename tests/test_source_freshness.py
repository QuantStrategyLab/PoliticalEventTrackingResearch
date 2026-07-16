from __future__ import annotations

import json
from collections import OrderedDict

import pytest

from political_event_tracking_research import rss_source_fetch
from political_event_tracking_research.source_freshness import (
    FreshnessError,
    build_freshness_evidence,
    read_freshness_evidence,
)


REFERENCE = "2026-07-13T12:00:00Z"
RSS = b"""<?xml version='1.0'?><rss version='2.0'><channel>
<lastBuildDate>Sun, 12 Jul 2026 11:00:00 GMT</lastBuildDate>
</channel></rss>"""
ATOM = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>
<updated>2026-07-13T11:00:00Z</updated></feed>"""


def build(body: bytes, headers: dict[str, str] | None = None) -> bytes:
    return build_freshness_evidence(
        feed_id="feed-a",
        source_url="https://example.test/feed.xml",
        body=body,
        response_headers=headers or {},
        reference_time=REFERENCE,
    )


def test_atom_signal_has_priority_over_rss_and_http() -> None:
    wire = build(
        ATOM,
        {
            "Last-Modified": "Sat, 11 Jul 2026 11:00:00 GMT",
            "Date": "Mon, 13 Jul 2026 12:01:00 GMT",
        },
    )
    value = read_freshness_evidence(wire)
    assert value["decision"] == "eligible"
    assert value["selected_signal"]["kind"] == "atom_feed_updated"
    assert [item["kind"] for item in value["signals"]] == [
        "atom_feed_updated",
        "rss_channel_last_build_date",
        "http_last_modified",
        "http_date",
    ]


def test_rss_signal_is_used_when_atom_is_missing() -> None:
    value = read_freshness_evidence(build(RSS, {"Last-Modified": "Sat, 11 Jul 2026 11:00:00 GMT"}))
    assert value["selected_signal"]["kind"] == "rss_channel_last_build_date"


def test_http_last_modified_is_last_fallback() -> None:
    body = b"<rss version='2.0'><channel/></rss>"
    value = read_freshness_evidence(build(body, {"Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT"}))
    assert value["selected_signal"]["kind"] == "http_last_modified"
    assert value["signals"][0]["present"] is False


def test_http_date_alone_does_not_prove_content_freshness() -> None:
    wire = build(
        RSS.replace(b"<lastBuildDate>Sun, 12 Jul 2026 11:00:00 GMT</lastBuildDate>", b""),
        {"Date": "Mon, 13 Jul 2026 12:00:00 GMT"},
    )
    assert read_freshness_evidence(wire)["decision"] == "source_freshness_unverified"


def test_invalid_high_priority_signal_does_not_fallback() -> None:
    body = ATOM.replace(b"2026-07-13T11:00:00Z", b"not-a-time")
    with pytest.raises(FreshnessError, match="source_freshness_invalid"):
        build(body, {"Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT"})


@pytest.mark.parametrize(
    "body,headers,error",
    [
        (RSS.replace(b"12 Jul 2026", b"01 Jul 2026"), {}, "source_freshness_stale"),
        (ATOM.replace(b"2026-07-13T11:00:00Z", b"2026-07-13T12:06:00Z"), {}, "source_freshness_future"),
    ],
)
def test_stale_and_future_signals_fail_closed(body: bytes, headers: dict[str, str], error: str) -> None:
    with pytest.raises(FreshnessError, match=error):
        build(body, headers)


def test_zero_entry_body_can_be_fresh_and_is_not_inferred_stale() -> None:
    value = read_freshness_evidence(build(RSS))
    assert value["decision"] == "eligible"


def test_evidence_is_canonical_and_tamper_resistant() -> None:
    wire = build(RSS)
    assert json.dumps(json.loads(wire), sort_keys=True, separators=(",", ":")).encode() == wire
    assert read_freshness_evidence(wire)["body_sha256"]
    with pytest.raises(FreshnessError, match="freshness_noncanonical"):
        read_freshness_evidence(json.dumps(json.loads(wire), indent=2).encode())
    with pytest.raises(FreshnessError, match="freshness_invalid"):
        read_freshness_evidence(wire.replace(b"eligible", b"tampered", 1))


def test_duplicate_and_non_mapping_headers_fail_closed() -> None:
    with pytest.raises(FreshnessError, match="freshness_headers_invalid"):
        build(RSS, OrderedDict((("Date", "x"), ("date", "y"))))


def test_fetch_boundary_returns_body_and_only_freshness_headers() -> None:
    class Headers:
        def get(self, name: str) -> str | None:
            return {"Date": "Mon, 13 Jul 2026 12:00:00 GMT", "Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT"}.get(name)

    class Response:
        headers = Headers()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def read(self, _size: int) -> bytes:
            return RSS

    original = rss_source_fetch.urllib.request.urlopen
    rss_source_fetch.urllib.request.urlopen = lambda *_args, **_kwargs: Response()  # type: ignore[assignment]
    try:
        body, headers = rss_source_fetch.fetch_url_with_metadata("https://example.test/feed.xml")
    finally:
        rss_source_fetch.urllib.request.urlopen = original
    assert body == RSS
    assert headers == {"Date": "Mon, 13 Jul 2026 12:00:00 GMT", "Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT"}
