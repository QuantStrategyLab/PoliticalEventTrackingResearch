from __future__ import annotations

from datetime import date

import pytest

from political_event_tracking_research.event_study import Event, compute_event_returns


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
