from __future__ import annotations

from pathlib import Path

import pytest

from political_event_tracking_research.official_event_import import (
    OfficialRecord,
    import_official_events,
    load_official_records,
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
    assert set(rows[0]) == {
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
    }


def test_load_official_records_defaults_entity_fields_for_legacy_csv(tmp_path: Path) -> None:
    input_path = tmp_path / "legacy.csv"
    input_path.write_text(
        "record_id,record_date,symbol,source_type,event_type,direction,source_url,summary\n"
        "legacy-1,2026-01-10,EVT1,government_filing,disclosure_buy,bullish,"
        "https://www.sec.gov/example/legacy-1,Legacy record.\n",
        encoding="utf-8",
    )

    record = load_official_records(input_path)[0]

    assert record.entity_match_type == "unverified"
    assert record.match_evidence == ""
    assert record.relationship_type == "unverified"


@pytest.mark.parametrize("value", ["issuer", "direct_beneficiary", "industry_context", "unverified"])
def test_new_entity_fields_accept_allowed_values(tmp_path: Path, value: str) -> None:
    input_path = tmp_path / "entity-fields.csv"
    input_path.write_text(
        "record_id,record_date,symbol,source_type,event_type,direction,source_url,summary,"
        "entity_match_type,match_evidence,relationship_type\n"
        "entity-1,2026-01-10,EVT1,government_filing,disclosure_buy,bullish,"
        f"https://www.sec.gov/example/entity-1,Entity record.,{value},SEC filing,{value}\n",
        encoding="utf-8",
    )

    rows = normalize_records(load_official_records(input_path))

    assert rows[0]["event_id"] == "official-government-filing-entity-1"


@pytest.mark.parametrize("field", ["entity_match_type", "relationship_type"])
@pytest.mark.parametrize("value", ["", "   ", "not-allowed"])
def test_new_entity_fields_fail_closed_for_blank_or_invalid_values(tmp_path: Path, field: str, value: str) -> None:
    input_path = tmp_path / f"invalid-{field}.csv"
    entity_match_type = value if field == "entity_match_type" else "issuer"
    relationship_type = value if field == "relationship_type" else "issuer"
    input_path.write_text(
        "record_id,record_date,symbol,source_type,event_type,direction,source_url,summary,"
        "entity_match_type,match_evidence,relationship_type\n"
        f"entity-1,2026-01-10,EVT1,government_filing,disclosure_buy,bullish,"
        f"https://www.sec.gov/example/entity-1,Entity record.,{entity_match_type},SEC filing,{relationship_type}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        normalize_records(load_official_records(input_path))


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


def test_normalize_records_preserves_verified_entity_relationship_fields(tmp_path: Path) -> None:
    input_path = tmp_path / "entity-fields.csv"
    input_path.write_text(
        "record_id,record_date,symbol,source_type,event_type,direction,source_url,summary,"
        "entity_match_type,match_evidence,relationship_type\n"
        "entity-1,2026-01-10,EVT1,government_filing,disclosure_buy,bullish,"
        "https://www.sec.gov/example/entity-1,Entity record.,issuer,SEC filing names EVT1,issuer\n",
        encoding="utf-8",
    )

    rows = normalize_records(load_official_records(input_path))

    assert rows[0]["entity_match_type"] == "issuer"
    assert rows[0]["match_evidence"] == "SEC filing names EVT1"
    assert rows[0]["relationship_type"] == "issuer"
