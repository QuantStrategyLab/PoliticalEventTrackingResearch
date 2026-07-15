from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from political_event_tracking_research import rss_source_fetch
from political_event_tracking_research.feed_status_canonical_h2c import read_status
from political_event_tracking_research.rss_source_fetch import (
    FeedConfig,
    fetch_rss_sources,
    parse_feed_items,
    parse_feed_snapshot,
)


def test_parse_rss_feed_items_to_source_items() -> None:
    feed_xml = b"""<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Remarks on EVT1 manufacturing</title>
          <link>https://www.whitehouse.gov/example/evt1</link>
          <pubDate>Fri, 01 May 2026 12:30:00 GMT</pubDate>
          <description><![CDATA[The President mentioned EVT1 in remarks.]]></description>
        </item>
      </channel>
    </rss>
    """
    feed = FeedConfig(
        feed_id="whitehouse-test",
        feed_url="https://www.whitehouse.gov/presidential-actions/feed/",
        source_type="official_remarks",
        author="White House",
    )

    rows = parse_feed_items(feed_xml, feed)

    assert rows == [
        {
            "item_id": rows[0]["item_id"],
            "published_at": "2026-05-01T12:30:00Z",
            "source_type": "official_remarks",
            "source_url": "https://www.whitehouse.gov/example/evt1",
            "author": "White House",
            "text": "Remarks on EVT1 manufacturing The President mentioned EVT1 in remarks.",
        }
    ]
    assert rows[0]["item_id"].startswith("whitehouse-test-")


def test_parse_atom_feed_items_to_source_items() -> None:
    feed_xml = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>SEC action mentions EVT2</title>
        <link href="https://www.sec.gov/example/evt2"/>
        <updated>2026-05-02T10:00:00Z</updated>
        <summary>Regulatory action context.</summary>
      </entry>
    </feed>
    """
    feed = FeedConfig(
        feed_id="sec-test",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
        source_type="regulatory_action",
        author="SEC",
    )

    rows = parse_feed_items(feed_xml, feed)

    assert rows[0]["published_at"] == "2026-05-02T10:00:00Z"
    assert rows[0]["source_url"] == "https://www.sec.gov/example/evt2"
    assert "EVT2" in rows[0]["text"]


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (b"<rss version='2.0'><channel/></rss>", "rss2"),
        (b"<feed xmlns='http://www.w3.org/2005/Atom'/>", "atom"),
    ],
)
def test_empty_feed_keeps_parser_kind(payload: bytes, kind: str) -> None:
    parsed_kind, rows = parse_feed_snapshot(payload, FeedConfig("x", "https://example.test", "official", ""))
    assert parsed_kind == kind
    assert rows == []


@pytest.mark.parametrize(
    "payload",
    [
        b"<!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><rss version='2.0'><channel/></rss>",
        b"<?xml version='1.0'?><!DOCTYPE rss [<!ENTITY laugh 'x'>]><rss version='2.0'><channel/></rss>",
        b"<?xml version='1.0' encoding='UTF-16'?><!DOCTYPE rss><rss version='2.0'><channel/></rss>",
        b"<?xml version='1.0' encoding='x-unknown'?><rss version='2.0'><channel/></rss>",
    ],
)
def test_defused_parser_rejects_entities_and_dtd(payload: bytes) -> None:
    with pytest.raises(ValueError, match="feed_xml_"):
        parse_feed_items(payload, FeedConfig("x", "https://example.test", "official", ""))


def test_utf16_entity_is_rejected_before_row_conversion() -> None:
    payload = """<?xml version='1.0' encoding='UTF-16'?>
    <!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]>
    <rss version='2.0'><channel><item><title>&x;</title></item></channel></rss>""".encode("utf-16")
    with pytest.raises(ValueError, match="feed_xml_"):
        parse_feed_items(payload, FeedConfig("x", "https://example.test", "official", ""))


def test_utf16_valid_feed_is_supported_without_fallback() -> None:
    payload = """<?xml version='1.0' encoding='UTF-16'?>
    <rss version='2.0'><channel><item><title>UTF16</title>
    <link>https://example.test/utf16</link><pubDate>Fri, 01 May 2026 12:30:00 GMT</pubDate>
    </item></channel></rss>""".encode("utf-16")
    rows = parse_feed_items(payload, FeedConfig("x", "https://example.test", "official", ""))
    assert rows[0]["source_url"] == "https://example.test/utf16"


def test_xml_payload_size_is_bounded_before_parse() -> None:
    feed = FeedConfig("x", "https://example.test", "official", "")
    with pytest.raises(ValueError, match="feed_xml_oversize"):
        parse_feed_items(b"x" * (rss_source_fetch.MAX_XML_BYTES + 1), feed)


def test_network_read_is_bounded_and_oversize_is_sanitized() -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size: int) -> bytes:
            assert size == rss_source_fetch.MAX_XML_BYTES + 1
            return b"x" * size

    with patch.object(rss_source_fetch.urllib.request, "urlopen", return_value=Response()):
        with pytest.raises(ValueError, match="feed_xml_oversize"):
            rss_source_fetch.fetch_url("https://example.test/feed")


def test_network_timeout_is_not_retried_or_parsed() -> None:
    with patch.object(rss_source_fetch.urllib.request, "urlopen", side_effect=TimeoutError("timeout")):
        with pytest.raises(TimeoutError, match="timeout"):
            rss_source_fetch.fetch_url("https://example.test/feed")


def test_parser_has_no_stdlib_xml_fallback() -> None:
    assert rss_source_fetch.ET.__name__ == "defusedxml.ElementTree"



def test_fetch_rss_sources_can_continue_and_write_status(tmp_path: Path) -> None:
    feeds_path = tmp_path / "feeds.csv"
    feeds_path.write_text(
        "feed_id,feed_url,source_type,author\n"
        "ok,https://example.invalid/ok.xml,official_remarks,Example\n"
        "bad,https://example.invalid/bad.xml,official_remarks,Example\n",
        encoding="utf-8",
    )
    feed_xml = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>Policy mentions EVT1</title>
      <link>https://example.invalid/evt1</link>
      <pubDate>Fri, 01 May 2026 12:30:00 GMT</pubDate>
    </item></channel></rss>
    """

    def fake_fetch(url: str) -> bytes:
        if url.endswith("bad.xml"):
            raise RuntimeError("blocked")
        return feed_xml

    output = tmp_path / "source_items.csv"
    status = tmp_path / "status.json"

    with pytest.raises(RuntimeError, match="feed_fetch_failed"):
        fetch_rss_sources(
            feeds_path,
            output,
            continue_on_feed_error=True,
            status_output=status,
            fetcher=fake_fetch,
        )

    assert output.exists()
    payload = read_status(status.read_bytes())
    assert payload["successful_feed_count"] == 1
    assert payload["failed_feed_count"] == 1
    failed = next(item for item in payload["feeds"] if item["feed_id"] == "bad")
    assert failed["state"] == "failed"
    assert failed["error_code"] == "fetch_failed"


def test_fetch_rss_sources_fails_when_all_feeds_fail(tmp_path: Path) -> None:
    feeds_path = tmp_path / "feeds.csv"
    feeds_path.write_text(
        "feed_id,feed_url,source_type,author\n"
        "bad,https://example.invalid/bad.xml,official_remarks,Example\n",
        encoding="utf-8",
    )

    def fake_fetch(_url: str) -> bytes:
        raise RuntimeError("blocked")

    with pytest.raises(RuntimeError, match="feed_fetch_failed"):
        fetch_rss_sources(
            feeds_path,
            tmp_path / "source_items.csv",
            continue_on_feed_error=True,
            status_output=tmp_path / "status.json",
            fetcher=fake_fetch,
        )
    payload = read_status((tmp_path / "status.json").read_bytes())
    assert payload["failed_feed_count"] == 1
    assert payload["eligible_for_live_publication"] is False


def test_zero_entry_quarantine_writes_canonical_noneligible_status(tmp_path: Path) -> None:
    feeds_path = tmp_path / "feeds.csv"
    feeds_path.write_text(
        "feed_id,feed_url,source_type,author\nempty,https://example.invalid/empty,official,\n",
        encoding="utf-8",
    )
    output = tmp_path / "source_items.csv"
    status = tmp_path / "status.json"

    rows = fetch_rss_sources(
        feeds_path,
        output,
        continue_on_feed_error=True,
        status_output=status,
        fetcher=lambda _url: b"<rss version='2.0'><channel/></rss>",
    )

    assert rows == []
    payload = read_status(status.read_bytes())
    assert payload["quarantined_feed_count"] == 1
    assert payload["eligible_for_live_publication"] is False
    assert status.read_bytes() == json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
