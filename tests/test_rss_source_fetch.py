from __future__ import annotations

from political_event_tracking_research.rss_source_fetch import FeedConfig, parse_feed_items


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

