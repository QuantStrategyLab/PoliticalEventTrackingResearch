from __future__ import annotations

import json
from pathlib import Path

import pytest

from political_event_tracking_research.rss_source_fetch import FeedConfig, fetch_rss_sources, parse_feed_items


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

    rows = fetch_rss_sources(
        feeds_path,
        output,
        continue_on_feed_error=True,
        status_output=status,
        fetcher=fake_fetch,
    )

    assert len(rows) == 1
    payload = json.loads(status.read_text(encoding="utf-8"))
    assert payload["successful_feed_count"] == 1
    assert payload["failed_feed_count"] == 1
    assert payload["feeds"][1]["feed_id"] == "bad"
    assert "RuntimeError" in payload["feeds"][1]["error"]


def test_fetch_rss_sources_fails_when_all_feeds_fail(tmp_path: Path) -> None:
    feeds_path = tmp_path / "feeds.csv"
    feeds_path.write_text(
        "feed_id,feed_url,source_type,author\n"
        "bad,https://example.invalid/bad.xml,official_remarks,Example\n",
        encoding="utf-8",
    )

    def fake_fetch(_url: str) -> bytes:
        raise RuntimeError("blocked")

    with pytest.raises(RuntimeError, match="all configured"):
        fetch_rss_sources(
            feeds_path,
            tmp_path / "source_items.csv",
            continue_on_feed_error=True,
            status_output=tmp_path / "status.json",
            fetcher=fake_fetch,
        )
