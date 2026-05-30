from __future__ import annotations

from datetime import date

from political_event_tracking_research.event_study import Event
from political_event_tracking_research.tracker import WatchlistItem, build_tracker_rows


def test_tracker_prioritizes_disclosure_plus_mention() -> None:
    items = [
        WatchlistItem(
            symbol="AAA",
            name="Alpha",
            bucket="named_mentioned",
            article_status="triggered",
            thesis="seed",
            source_url="https://example.com",
        ),
        WatchlistItem(
            symbol="BBB",
            name="Beta",
            bucket="disclosed_holding",
            article_status="watchlist",
            thesis="seed",
            source_url="https://example.com",
        ),
    ]
    events = [
        Event("e1", date(2026, 1, 1), "AAA", "disclosure_buy", "bullish", "low", "https://example.com", ""),
        Event("e2", date(2026, 1, 2), "AAA", "public_mention", "bullish", "low", "https://example.com", ""),
    ]

    rows = build_tracker_rows(items, events)

    assert rows[0]["symbol"] == "AAA"
    assert rows[0]["trigger_status"] == "disclosure_plus_mention"
    assert rows[0]["event_count"] == 2
    assert rows[0]["latest_event_date"] == "2026-01-02"
    assert rows[1]["symbol"] == "BBB"
    assert rows[1]["trigger_status"] == "watchlist"
