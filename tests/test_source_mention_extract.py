from __future__ import annotations

import csv
from pathlib import Path

import pytest

from political_event_tracking_research.source_mention_extract import (
    MentionAlias,
    extract_source_records,
    infer_direction,
    match_symbols,
)

ROOT = Path(__file__).resolve().parents[1]


def test_match_symbols_supports_ticker_and_name_aliases() -> None:
    aliases = [MentionAlias(symbol="EVT1", aliases=("EVT1", "Example Catalyst One"))]

    assert match_symbols("Example Catalyst One is mentioned.", aliases) == ["EVT1"]
    assert match_symbols("$EVT1 is mentioned.", aliases) == ["EVT1"]
    assert match_symbols("PREVT1 should not match.", aliases) == []


def test_single_letter_ticker_requires_cash_tag_or_name_alias() -> None:
    aliases = [MentionAlias(symbol="F", aliases=("F", "Ford", "F-150"))]

    assert match_symbols("5 C.F.R. mentions investment workforce.", aliases) == []
    assert match_symbols("$F is mentioned.", aliases) == ["F"]
    assert match_symbols("Ford is mentioned.", aliases) == ["F"]
    assert match_symbols("F-150 policy is mentioned.", aliases) == ["F"]


def test_match_symbols_normalizes_unicode_hyphen_aliases() -> None:
    aliases = [MentionAlias(symbol="VRT", aliases=("VRT", "energy-related infrastructure"))]

    assert match_symbols("Energy‑Related Infrastructure policy update", aliases) == ["VRT"]

def test_infer_direction_handles_common_investor_language() -> None:
    assert infer_direction("Bullish on DELL upside from AI servers.") == "bullish"
    assert infer_direction("Bearish risk and sell pressure.") == "bearish"


def test_extract_source_records_outputs_confidence_by_source_type(tmp_path: Path) -> None:
    output = tmp_path / "source_events.csv"

    rows = extract_source_records(
        ROOT / "examples/source_items.example.csv",
        ROOT / "examples/symbol_aliases.example.csv",
        output,
    )

    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["EVT1"]["confidence"] == "high"
    assert by_symbol["EVT2"]["event_type"] == "policy_capital"
    assert by_symbol["EVT3"]["confidence"] == "low"
    assert by_symbol["EVT4"]["event_type"] == "procurement"
    assert output.exists()


def test_extract_source_records_preserves_entity_fields_in_csv(tmp_path: Path) -> None:
    output = tmp_path / "source_events.csv"

    rows = extract_source_records(
        ROOT / "examples/source_items.example.csv",
        ROOT / "examples/symbol_aliases.example.csv",
        output,
    )

    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
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
        exported_rows = list(reader)

    assert exported_rows == rows
    for row in exported_rows:
        assert row["entity_match_type"] == "unverified"
        assert row["match_evidence"] == ""
        assert row["relationship_type"] == "unverified"


@pytest.mark.parametrize(
    ("text", "symbols"),
    [
        ("National standards strategy creates a shared framework.", {"MSTR"}),
        ("Cybersecurity policy supports workforce development.", {"PANW"}),
        ("New policy for crypto assets custody.", {"COIN", "MSTR"}),
        ("Fraudsters used WhatsApp to contact investors.", {"META"}),
    ],
)
def test_high_source_confidence_does_not_verify_company_mentions(
    tmp_path: Path, text: str, symbols: set[str]
) -> None:
    raw_items = tmp_path / "source_items.csv"
    with raw_items.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item_id", "published_at", "source_type", "source_url", "author", "text"])
        writer.writerow(
            ["synthetic-1", "2026-01-10", "government_policy", "https://www.sec.gov/example", "Example", text]
        )
    output = tmp_path / "source_events.csv"

    extract_source_records(raw_items, ROOT / "config/core_us_equity_aliases.csv", output)

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["symbol"] for row in rows} == symbols
    for row in rows:
        assert row["confidence"] == "high"
        assert row["entity_match_type"] == "unverified"
        assert row["match_evidence"] == ""
        assert row["relationship_type"] == "unverified"
