from __future__ import annotations

from datetime import date

import pytest

from political_event_tracking_research.event_study import Event, compute_event_returns, load_events


def test_compute_event_returns_uses_next_available_trading_date_and_benchmark() -> None:
    events = [
        Event(
            event_id="e1",
            event_date=date(2026, 1, 2),
            symbol="ABC",
            event_type="public_mention",
            direction="bullish",
            confidence="high",
            source_url="https://example.com",
            notes="seed",
            relationship_type="issuer",
        )
    ]
    prices = {
        "ABC": {
            date(2026, 1, 5): 100.0,
            date(2026, 1, 6): 110.0,
            date(2026, 1, 12): 121.0,
        },
        "SPY": {
            date(2026, 1, 5): 200.0,
            date(2026, 1, 6): 202.0,
            date(2026, 1, 12): 206.0,
        },
    }

    results = compute_event_returns(events, prices, windows=(1, 2), benchmark_symbol="SPY")

    assert len(results) == 2
    assert results[0].base_date == date(2026, 1, 5)
    assert results[0].exit_date == date(2026, 1, 6)
    assert results[0].return_pct == pytest.approx(10.0)
    assert results[0].benchmark_return_pct == pytest.approx(1.0)
    assert results[0].abnormal_return_pct == pytest.approx(9.0)
    assert results[1].return_pct == pytest.approx(21.0)


def test_compute_event_returns_skips_events_without_prices() -> None:
    events = [
        Event(
            event_id="missing",
            event_date=date(2026, 1, 2),
            symbol="MISSING",
            event_type="public_mention",
            direction="bullish",
            confidence="low",
            source_url="https://example.com",
            notes="seed",
        )
    ]

    assert compute_event_returns(events, prices={}, windows=(1,)) == []


def test_compute_event_returns_excludes_non_company_relationships() -> None:
    events = [
        Event("context", date(2026, 1, 2), "ABC", "public_mention", "bullish", "high", "https://example.com", "", relationship_type="industry_context"),
        Event("unknown", date(2026, 1, 2), "ABC", "public_mention", "bullish", "high", "https://example.com", ""),
    ]
    prices = {"ABC": {date(2026, 1, 5): 100.0, date(2026, 1, 6): 110.0}}

    assert compute_event_returns(events, prices, windows=(1,)) == []


def test_legacy_event_csv_requires_explicit_compatibility_and_provenance(tmp_path) -> None:
    path = tmp_path / "legacy_events.csv"
    path.write_text(
        "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n"
        "legacy-1,2026-01-02,ABC,public_mention,bullish,high,https://example.com,legacy\n",
        encoding="utf-8",
    )
    prices = {"ABC": {date(2026, 1, 5): 100.0, date(2026, 1, 6): 110.0}}

    legacy = load_events(path, historical_compatibility=True, compatibility_reason="reproduce 2026 baseline")
    assert legacy[0].relationship_type == "unverified"
    assert compute_event_returns(legacy, prices, windows=(1,)) == []
    results = compute_event_returns(legacy, prices, windows=(1,), historical_compatibility=True)

    assert results[0].compatibility_used is True
    assert results[0].compatibility_reason == "reproduce 2026 baseline"
    assert results[0].legacy_provenance == str(path)
