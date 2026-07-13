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


def test_entity_evidence_prefers_strongest_alias_match(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "mixed,2026-04-01T00:00:00Z,government_procurement,https://www.govinfo.gov/example,Agency,"
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
    assert rows[0]["relationship_type"] == "direct_beneficiary"


def test_generic_context_does_not_become_company_evidence(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "nist,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/example,NIST,"
        'NIST guidance discusses nuclear reactor safety and tokenization.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "symbol,name,aliases\nOKLO,Oklo,Oklo|OKLO|nuclear reactor\n"
        "COIN,Coinbase,Coinbase|COIN|tokenization\n",
        encoding="utf-8",
    )

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert {row["symbol"] for row in rows} == {"OKLO", "COIN"}
    assert {row["entity_match_type"] for row in rows} == {"industry_context"}


def test_canonical_name_is_trusted_only_in_issuer_release(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer,2026-04-01T00:00:00Z,issuer_release,https://example.com/release,Issuer,"
        'Strategy announced a new product.\n'
        "policy,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/example,NIST,"
        'Strategy guidance was published.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nMSTR,Strategy,Strategy|MSTR\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")
    by_id = {row["event_id"]: row for row in rows}

    assert by_id["official-issuer-release-issuer-mstr"]["entity_match_type"] == "issuer"
    assert by_id["official-government-policy-policy-mstr"]["entity_match_type"] == "industry_context"


def test_curation_omission_keeps_canonical_name_as_metadata_only(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer,2026-04-01T00:00:00Z,issuer_release,https://example.com/release,Issuer,"
        'Palo Alto Networks announced a new product.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nPANW,Palo Alto Networks,PANW\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows == []


def test_third_party_mentions_are_not_issuer_evidence(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "policy,2026-04-01T00:00:00Z,government_policy,https://www.nist.gov/example,NIST,"
        'Palo Alto Networks was mentioned in general guidance.\n'
        "remarks,2026-04-02T00:00:00Z,official_remarks,https://www.whitehouse.gov/example,White House,"
        'Palo Alto Networks was mentioned in remarks.\n'
        "media,2026-04-03T00:00:00Z,financial_media,https://example.com/article,Media,"
        'Palo Alto Networks was mentioned in market coverage.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nPANW,Palo Alto Networks,Palo Alto Networks|PANW\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert len(rows) == 3
    assert {row["entity_match_type"] for row in rows} == {"unverified"}


def test_direct_beneficiary_overrides_generic_alias(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "award,2026-04-01T00:00:00Z,government_procurement,https://www.govinfo.gov/example,Agency,"
        'Funding for Strategy was announced.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nMSTR,Strategy,Strategy|MSTR\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows[0]["entity_match_type"] == "direct_beneficiary"


def test_canonical_name_wins_same_strength_alias_tie(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer,2026-04-01T00:00:00Z,issuer_release,https://example.com/release,Issuer,"
        'Palo Alto Networks (PANW) announced a new product.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,name,aliases\nPANW,Palo Alto Networks,Palo Alto Networks|PANW\n", encoding="utf-8")

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert rows[0]["match_evidence"] == "Palo Alto Networks"


def test_duplicate_alias_rows_emit_one_record_per_symbol(tmp_path: Path) -> None:
    raw_items = tmp_path / "source_items.csv"
    raw_items.write_text(
        "item_id,published_at,source_type,source_url,author,text\n"
        "issuer,2026-04-01T00:00:00Z,issuer_release,https://example.com/release,Issuer,"
        'Coinbase (COIN) announced a new product.\n',
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "symbol,name,aliases\nCOIN,Coinbase,Coinbase|COIN\nCOIN,Coinbase,Coinbase|COIN|tokenization\n",
        encoding="utf-8",
    )

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "COIN"


def test_known_ticker_collisions_remain_context_only(tmp_path: Path) -> None:
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
        "symbol,name,aliases\nMSTR,Strategy,Strategy|MSTR\nOKLO,Oklo,Oklo|OKLO|nuclear reactor\n"
        "PANW,Palo Alto Networks,Palo Alto Networks|PANW|cybersecurity\n"
        "COIN,Coinbase,Coinbase|COIN|tokenization\nINTC,Intel,Intel|INTC|CHIPS Act\n",
        encoding="utf-8",
    )

    rows = extract_source_records(raw_items, aliases, tmp_path / "events.csv")

    assert {row["symbol"] for row in rows} == {"MSTR", "OKLO", "PANW", "COIN", "INTC"}
    assert {row["entity_match_type"] for row in rows} == {"industry_context"}
