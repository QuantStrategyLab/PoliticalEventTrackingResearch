from __future__ import annotations

from pathlib import Path

import pytest

from political_event_tracking_research.official_event_import import (
    OfficialRecord,
    import_official_events,
    normalize_records,
)


ROOT = Path(__file__).resolve().parents[1]


def test_import_official_events_normalizes_to_event_schema(tmp_path: Path) -> None:
    output = tmp_path / "events.csv"

    rows = import_official_events(ROOT / "examples/official_records.example.csv", output)

    assert output.exists()
    assert rows[0]["event_id"] == "official-government-filing-demo-filing-evt1"
    assert rows[0]["confidence"] == "high"
    by_id = {row["event_id"]: row for row in rows}
    assert by_id["official-issuer-release-demo-issuer-evt3"]["confidence"] == "medium"
    assert by_id["official-verified-social-post-demo-social-evt4"]["confidence"] == "medium"
    assert by_id["official-financial-media-demo-media-evt5"]["confidence"] == "low"
    assert rows[-3]["event_id"] == "official-issuer-release-demo-issuer-evt3"
    assert rows[-1]["event_id"] == "official-financial-media-demo-media-evt5"
    assert rows[-1]["confidence"] == "low"


def test_government_records_reject_non_gov_urls() -> None:
    record = OfficialRecord(
        record_id="bad-media-record",
        record_date="2026-01-10",
        symbol="BAD",
        source_type="official_remarks",
        event_type="public_mention",
        direction="bullish",
        source_url="https://example.com/article",
        summary="Not an official source.",
    )

    with pytest.raises(ValueError, match="government source URLs"):
        normalize_records([record])


def test_verified_social_records_reject_untrusted_hosts() -> None:
    record = OfficialRecord(
        record_id="bad-social-record",
        record_date="2026-01-10",
        symbol="BAD",
        source_type="verified_social_post",
        event_type="public_mention",
        direction="bullish",
        source_url="https://example.com/post/123",
        summary="Not a primary social source.",
    )

    with pytest.raises(ValueError, match="verified social source URLs"):
        normalize_records([record])


def test_community_lead_records_are_low_confidence() -> None:
    record = OfficialRecord(
        record_id="longbridge-topic",
        record_date="2026-02-02",
        symbol="MU",
        source_type="community_research_lead",
        event_type="public_mention",
        direction="bullish",
        source_url="https://longbridge.cn/topics/lb-demo-mu",
        summary="Community research lead.",
    )

    rows = normalize_records([record])

    assert rows[0]["confidence"] == "low"
