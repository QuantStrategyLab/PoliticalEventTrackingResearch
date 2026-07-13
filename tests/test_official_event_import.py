from __future__ import annotations

import csv
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
    assert by_id["official-financial-media-demo-media-evt5"]["confidence"] == "low"
    assert rows[-2]["event_id"] == "official-issuer-release-demo-issuer-evt3"
    assert rows[-1]["event_id"] == "official-financial-media-demo-media-evt5"
    assert rows[-1]["confidence"] == "low"


def test_legacy_input_defaults_entity_schema_fields_and_serializes_stably(tmp_path: Path) -> None:
    output = tmp_path / "events.csv"

    rows = import_official_events(ROOT / "examples/official_records.example.csv", output)

    assert all(row["entity_match_type"] == "unverified" for row in rows)
    assert all(row["match_evidence"] == "" for row in rows)
    assert all(row["relationship_type"] == "" for row in rows)
    with output.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == [
            "event_id",
            "event_date",
            "symbol",
            "event_type",
            "direction",
            "confidence",
            "source_url",
            "notes",
            "entity_match_type",
            "match_evidence",
            "relationship_type",
        ]


def test_entity_schema_fields_are_imported_and_normalized() -> None:
    record = OfficialRecord(
        record_id="entity-record",
        record_date="2026-01-10",
        symbol="EVT",
        source_type="government_filing",
        event_type="disclosure_buy",
        direction="bullish",
        source_url="https://www.sec.gov/example/entity-record",
        summary="Entity evidence.",
        entity_match_type="direct_beneficiary",
        match_evidence="Named beneficiary in filing.",
        relationship_type="supplier",
    )

    assert normalize_records([record])[0] == {
        "event_id": "official-government-filing-entity-record",
        "event_date": "2026-01-10",
        "symbol": "EVT",
        "event_type": "disclosure_buy",
        "direction": "bullish",
        "confidence": "high",
        "source_url": "https://www.sec.gov/example/entity-record",
        "notes": "Entity evidence.",
        "entity_match_type": "direct_beneficiary",
        "match_evidence": "Named beneficiary in filing.",
        "relationship_type": "supplier",
    }


@pytest.mark.parametrize("entity_match_type", ["issuer", "direct_beneficiary", "industry_context", "unverified"])
def test_entity_match_type_accepts_only_contract_values(entity_match_type: str) -> None:
    record = OfficialRecord(
        record_id="entity-record",
        record_date="2026-01-10",
        symbol="EVT",
        source_type="government_filing",
        event_type="disclosure_buy",
        direction="bullish",
        source_url="https://www.sec.gov/example/entity-record",
        summary="Entity evidence.",
        entity_match_type=entity_match_type,
    )

    normalize_records([record])


def test_entity_match_type_rejects_unknown_values() -> None:
    record = OfficialRecord(
        record_id="entity-record",
        record_date="2026-01-10",
        symbol="EVT",
        source_type="government_filing",
        event_type="disclosure_buy",
        direction="bullish",
        source_url="https://www.sec.gov/example/entity-record",
        summary="Entity evidence.",
        entity_match_type="inferred",
    )

    with pytest.raises(ValueError, match="unsupported entity_match_type"):
        normalize_records([record])


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


def test_verified_social_records_are_not_in_stable_source_set() -> None:
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

    with pytest.raises(ValueError, match="unsupported source_type"):
        normalize_records([record])


def test_community_lead_records_are_not_in_stable_source_set() -> None:
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

    with pytest.raises(ValueError, match="unsupported source_type"):
        normalize_records([record])
