from __future__ import annotations

import json
import urllib.error

import pytest

from political_event_tracking_research import rss_source_fetch
from political_event_tracking_research.source_freshness import (
    FreshnessError,
    build_freshness_evidence,
    read_freshness_evidence,
)


REFERENCE = "2026-07-13T12:00:00Z"
RSS = b"<rss version='2.0'><channel><lastBuildDate>Sun, 12 Jul 2026 11:00:00 GMT</lastBuildDate></channel></rss>"
ATOM = b"<feed xmlns='http://www.w3.org/2005/Atom'><updated>2026-07-13T11:00:00Z</updated></feed>"


def build(body: bytes, headers: dict[str, str] | None = None) -> bytes:
    return build_freshness_evidence(
        feed_id="feed-a",
        source_url="https://example.test/feed.xml",
        body=body,
        response_headers=headers or {},
        reference_time=REFERENCE,
    )


def test_legacy_fetch_url_returns_body_without_inspecting_headers() -> None:
    class Headers:
        def get_all(self, _name: str) -> list[str]:
            raise AssertionError("legacy fetch must not inspect headers")

        def get(self, _name: str) -> str:
            raise AssertionError("legacy fetch must not inspect headers")

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
        assert rss_source_fetch.fetch_url("https://example.test/feed.xml") == RSS
    finally:
        rss_source_fetch.urllib.request.urlopen = original


def test_opt_in_metadata_fetch_rejects_duplicate_headers() -> None:
    class Headers:
        def get_all(self, name: str) -> list[str]:
            return ["Sun, 12 Jul 2026 11:00:00 GMT", "Sun, 12 Jul 2026 12:00:00 GMT"] if name == "Date" else []

        def get(self, _name: str) -> str | None:
            return None

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
        with pytest.raises(ValueError, match="feed_header_duplicate"):
            rss_source_fetch.fetch_url_with_metadata("https://example.test/feed.xml")
    finally:
        rss_source_fetch.urllib.request.urlopen = original


@pytest.mark.parametrize("failure", [TimeoutError("timeout"), OSError("network"), urllib.error.URLError("http")])
def test_metadata_fetch_translates_expected_transport_failures(failure: BaseException) -> None:
    original = rss_source_fetch.urllib.request.urlopen
    rss_source_fetch.urllib.request.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(failure)  # type: ignore[assignment]
    try:
        with pytest.raises(ValueError, match="feed_fetch_failed"):
            rss_source_fetch.fetch_url_with_metadata("https://example.test/feed.xml")
    finally:
        rss_source_fetch.urllib.request.urlopen = original


def test_metadata_fetch_translates_short_or_malformed_read() -> None:
    class Headers:
        def get_all(self, _name: str) -> list[str]:
            return []

        def get(self, name: str) -> str | None:
            return "10" if name == "Content-Length" else None

    class Response:
        headers = Headers()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def read(self, _size: int) -> str:
            return "short"

    original = rss_source_fetch.urllib.request.urlopen
    rss_source_fetch.urllib.request.urlopen = lambda *_args, **_kwargs: Response()  # type: ignore[assignment]
    try:
        with pytest.raises(ValueError, match="feed_fetch_failed"):
            rss_source_fetch.fetch_url_with_metadata("https://example.test/feed.xml")
    finally:
        rss_source_fetch.urllib.request.urlopen = original


def test_strict_signal_priority_and_canonical_readback() -> None:
    wire = build(ATOM, {"Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT", "Date": "Mon, 13 Jul 2026 12:00:00 GMT"})
    value = read_freshness_evidence(wire)
    assert value["selected_signal"]["kind"] == "atom_feed_updated"
    assert json.dumps(value, sort_keys=True, separators=(",", ":")).encode() == wire


def test_rss_and_http_fallbacks() -> None:
    assert read_freshness_evidence(build(RSS))["selected_signal"]["kind"] == "rss_channel_last_build_date"
    body = b"<rss version='2.0'><channel/></rss>"
    assert read_freshness_evidence(build(body, {"Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT"}))["selected_signal"]["kind"] == "http_last_modified"


def test_http_date_is_not_a_content_freshness_signal() -> None:
    body = b"<rss version='2.0'><channel/></rss>"
    value = read_freshness_evidence(build(body, {"Date": "Mon, 13 Jul 2026 12:00:00 GMT"}))
    assert value["decision"] == "source_freshness_unverified"


@pytest.mark.parametrize(
    "body,headers",
    [
        (b"<feed xmlns='http://www.w3.org/2005/Atom'><updated>2026-07-13T11:00:00</updated></feed>", {}),
        (b"<rss version='2.0'><channel><lastBuildDate>2026-07-12</lastBuildDate></channel></rss>", {}),
        (b"<rss version='2.0'><channel/></rss>", {"Last-Modified": "2026-07-13T11:00:00Z"}),
        (b"<rss version='2.0'><channel/></rss>", {"Last-Modified": "Sun, 12 Jul 2026 11:00:00"}),
    ],
)
def test_naive_date_only_and_iso_http_dates_are_rejected(body: bytes, headers: dict[str, str]) -> None:
    with pytest.raises(FreshnessError, match="source_freshness_invalid"):
        build(body, headers)


def test_present_empty_or_duplicate_high_priority_signal_cannot_fallback() -> None:
    empty = b"<feed xmlns='http://www.w3.org/2005/Atom'><updated/></feed>"
    duplicate = b"<feed xmlns='http://www.w3.org/2005/Atom'><updated>2026-07-13T11:00:00Z</updated><updated/></feed>"
    for body in (empty, duplicate):
        with pytest.raises(FreshnessError, match="source_freshness_invalid"):
            build(body, {"Last-Modified": "Sun, 12 Jul 2026 11:00:00 GMT"})


def test_stale_and_future_fail_closed() -> None:
    stale = b"<rss version='2.0'><channel><lastBuildDate>Sun, 01 Jul 2026 11:00:00 GMT</lastBuildDate></channel></rss>"
    future = b"<feed xmlns='http://www.w3.org/2005/Atom'><updated>2026-07-13T12:06:00Z</updated></feed>"
    with pytest.raises(FreshnessError, match="source_freshness_stale"):
        build(stale)
    with pytest.raises(FreshnessError, match="source_freshness_future"):
        build(future)


def test_zero_entry_feed_can_have_freshness_without_being_inferred_stale() -> None:
    assert read_freshness_evidence(build(RSS))["decision"] == "eligible"


def test_source_identity_rejects_fragment_and_unicode_encode_failure() -> None:
    with pytest.raises(FreshnessError, match="source_identity_invalid"):
        build_freshness_evidence(
            feed_id="feed-a",
            source_url="https://example.test/feed.xml#fragment",
            body=RSS,
            response_headers={},
            reference_time=REFERENCE,
        )
    with pytest.raises(FreshnessError, match="source_identity_invalid"):
        build_freshness_evidence(
            feed_id="feed-a",
            source_url="https://example.test/\ud800",
            body=RSS,
            response_headers={},
            reference_time=REFERENCE,
        )


def test_wire_size_and_tamper_fail_closed() -> None:
    wire = build(RSS)
    with pytest.raises(FreshnessError, match="freshness_wire_invalid"):
        read_freshness_evidence(b" " * (64 * 1024 + 1))
    with pytest.raises(FreshnessError, match="freshness_noncanonical"):
        read_freshness_evidence(json.dumps(json.loads(wire), indent=2).encode())
    with pytest.raises(FreshnessError, match="freshness_invalid"):
        read_freshness_evidence(wire.replace(b"eligible", b"tampered", 1))
