from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.source_mention_extract import (
    extract_source_records,
    infer_direction,
    match_symbols,
)
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


def test_generic_aliases_are_context_only_and_keep_evidence(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "nist-1,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/example,NIST,"
        'NIST guidance discusses nuclear reactor safety and tokenization.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "symbol,name,aliases\n"
        "OKLO,Oklo,Oklo|OKLO|nuclear reactor\n"
        "COIN,Coinbase,Coinbase|COIN|tokenization\n",
        encoding="utf-8",
    )

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["OKLO"]["entity_match_type"] == "industry_context"
    assert by_symbol["COIN"]["entity_match_type"] == "industry_context"
    assert by_symbol["OKLO"]["match_evidence"] == "nuclear reactor"
    assert by_symbol["COIN"]["relationship_type"] == "industry_context"


def test_explicit_issuer_match_is_company_level(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer-1,2026-04-01T00:00:00Z,issuer_release,https://example.com/release,Issuer,"
        'Coinbase announced a new product.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nCOIN,Coinbase,COIN|tokenization\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows[0]["entity_match_type"] == "issuer"
    assert rows[0]["relationship_type"] == "issuer"
    assert rows[0]["match_evidence"] == "Coinbase"


def test_canonical_name_on_trusted_issuer_release_beats_generic_denylist(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer-strategy,2026-04-01T00:00:00Z,issuer_release,https://example.com/strategy,Strategy,"
        'Strategy announced a new product.\n'
        "policy-strategy,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/strategy,NIST,"
        'Strategy guidance was published.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nMSTR,Strategy,Strategy|MSTR\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")
    by_id = {row["event_id"]: row for row in rows}

    assert by_id["official-issuer-release-issuer-strategy-mstr"]["entity_match_type"] == "issuer"
    assert by_id["official-government-policy-policy-strategy-mstr"]["entity_match_type"] == "industry_context"


def test_proper_noun_alternate_alias_remains_company_level(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer-2,2026-04-01T00:00:00Z,issuer_release,https://example.com/release,Issuer,"
        'Former Brand announced a new product.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nTEST,Current Company,Current Company|Former Brand\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows[0]["entity_match_type"] == "issuer"
    assert rows[0]["match_evidence"] == "Former Brand"


def test_strongest_match_wins_regardless_of_alias_order(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "mixed-1,2026-04-01T00:00:00Z,government_procurement,https://www.govinfo.gov/example,Agency,"
        'Funding for Current Company supports cybersecurity.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "symbol,name,aliases\nTEST,Current Company,cybersecurity|Current Company\n",
        encoding="utf-8",
    )

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows[0]["entity_match_type"] == "direct_beneficiary"
    assert rows[0]["match_evidence"] == "Current Company"


def test_explicit_beneficiary_relation_is_preserved(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "award-1,2026-04-01T00:00:00Z,government_procurement,https://www.govinfo.gov/example,Agency,"
        'Funding for Coinbase was announced.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nCOIN,Coinbase,COIN\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows[0]["entity_match_type"] == "direct_beneficiary"
    assert rows[0]["relationship_type"] == "direct_beneficiary"


def test_known_ticker_and_industry_collisions_never_become_issuer_events(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "mstr,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/mstr,NIST,Strategy guidance\n"
        "oklo,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/oklo,NIST,nuclear reactor safety\n"
        "panw,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/panw,NIST,generic cybersecurity guidance\n"
        "coin,2026-04-01T00:00:00Z,government_policy,https://www.federalreserve.gov/coin,Fed,tokenization policy\n"
        "intc,2026-04-01T00:00:00Z,government_policy,https://www.commerce.gov/intc,Commerce,CHIPS Act funding\n",
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "symbol,name,aliases\n"
        "MSTR,Strategy,Strategy|MSTR\n"
        "OKLO,Oklo,Oklo|OKLO|nuclear reactor\n"
        "PANW,Palo Alto Networks,Palo Alto Networks|PANW|cybersecurity\n"
        "COIN,Coinbase,Coinbase|COIN|tokenization\n"
        "INTC,Intel,Intel|INTC|CHIPS Act\n",
        encoding="utf-8",
    )

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert {row["symbol"] for row in rows} == {"MSTR", "OKLO", "PANW", "COIN", "INTC"}
    assert {row["entity_match_type"] for row in rows} == {"industry_context"}
