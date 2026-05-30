from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.source_mention_extract import extract_source_records, infer_direction, match_symbols
from political_event_tracking_research.source_mention_extract import MentionAlias


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
