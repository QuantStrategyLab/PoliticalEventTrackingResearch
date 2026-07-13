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
            research_status="triggered",
            thesis="seed",
            source_url="https://example.com",
        ),
        WatchlistItem(
            symbol="BBB",
            name="Beta",
            bucket="disclosed_holding",
            research_status="watchlist",
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


def test_tracker_does_not_score_industry_context_as_company_evidence() -> None:
    item = WatchlistItem("AAA", "Alpha", "watchlist", "watchlist", "seed", "https://example.com")
    events = [Event("e1", date(2026, 1, 1), "AAA", "public_mention", "bullish", "high", "https://example.com", "", "industry_context", "cybersecurity", "industry_context")]

    rows = build_tracker_rows([item], events)

    assert rows[0]["priority_score"] == 0


def test_tracker_uses_relationship_type_as_scoring_fact() -> None:
    item = WatchlistItem("AAA", "Alpha", "watchlist", "watchlist", "seed", "https://example.com")
    events = [Event("e1", date(2026, 1, 1), "AAA", "public_mention", "bullish", "high", "https://example.com", "", "industry_context", "cybersecurity", "issuer")]

    rows = build_tracker_rows([item], events)

    assert rows[0]["priority_score"] > 0
