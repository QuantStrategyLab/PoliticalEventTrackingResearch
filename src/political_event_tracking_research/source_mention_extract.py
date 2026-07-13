from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from .csv_utils import read_csv_rows, write_csv_rows
from .event_study import parse_date
from .official_event_import import OfficialRecord, normalize_records


GENERIC_ALIAS_DENYLIST = frozenset(
    {
        "advanced nuclear",
        "bitcoin treasury",
        "chips act",
        "crypto assets",
        "cybersecurity",
        "digital assets",
        "energy-related infrastructure",
        "foundry",
        "nuclear energy",
        "nuclear reactor",
        "semiconductor manufacturing",
        "strategy",
        "tokenization",
    }
)

RELATIONSHIP_PRIORITY = {
    "unverified": 0,
    "industry_context": 1,
    "issuer": 2,
    "direct_beneficiary": 3,
}


@dataclass(frozen=True)
class RawSourceItem:
    item_id: str
    published_at: str
    source_type: str
    source_url: str
    author: str
    text: str


@dataclass(frozen=True)
class MentionAlias:
    symbol: str
    aliases: tuple[str, ...]
    name: str = ""


def load_raw_items(path: str | Path) -> list[RawSourceItem]:
    items: list[RawSourceItem] = []
    for row in read_csv_rows(path):
        items.append(
            RawSourceItem(
                item_id=row["item_id"],
                published_at=row["published_at"],
                source_type=row["source_type"],
                source_url=row["source_url"],
                author=row.get("author", ""),
                text=row.get("text", ""),
            )
        )
    return items


def split_aliases(value: str) -> tuple[str, ...]:
    aliases = [part.strip() for part in re.split(r"[|,]", value) if part.strip()]
    return tuple(dict.fromkeys(aliases))


def load_aliases(path: str | Path) -> list[MentionAlias]:
    records: list[MentionAlias] = []
    for row in read_csv_rows(path):
        symbol = row["symbol"].upper()
        name = row.get("name", "").strip()
        aliases = split_aliases(row.get("aliases", ""))
        if name and name.casefold() not in {alias.casefold() for alias in aliases}:
            aliases = (name, *aliases)
        if symbol not in aliases:
            aliases = (symbol, *aliases)
        records.append(MentionAlias(symbol=symbol, aliases=aliases, name=name))
    return records


def normalize_match_text(value: str) -> str:
    return (
        value.replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
    )


def alias_pattern(alias: str) -> re.Pattern[str]:
    normalized = normalize_match_text(alias)
    escaped = re.escape(normalized)
    if re.fullmatch(r"[A-Za-z]", normalized):
        return re.compile(rf"(?<![A-Za-z0-9])\${escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", normalized):
        return re.compile(rf"(?<![A-Za-z0-9$])\$?{escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def match_symbols(text: str, aliases: list[MentionAlias]) -> list[str]:
    normalized_text = normalize_match_text(text)
    matches: list[str] = []
    for alias_record in aliases:
        if any(alias_pattern(alias).search(normalized_text) for alias in alias_record.aliases):
            matches.append(alias_record.symbol)
    return sorted(dict.fromkeys(matches))


def _is_generic_alias(alias_record: MentionAlias, alias: str) -> bool:
    normalized = normalize_match_text(alias).strip()
    if normalized.upper() == alias_record.symbol.upper():
        return False
    return normalized.casefold() in GENERIC_ALIAS_DENYLIST


def match_evidence(text: str, alias_record: MentionAlias, source_type: str = "") -> tuple[str, str] | None:
    normalized_text = normalize_match_text(text)
    matches: list[tuple[str, str]] = []
    for alias in alias_record.aliases:
        normalized_alias = normalize_match_text(alias)
        if not alias_pattern(alias).search(normalized_text):
            continue
        direct_pattern = re.compile(
            rf"(?:awarded to|contract with|funding for|benefit(?:s|ed)? from)\s+"
            rf"(?:the\s+)?{re.escape(normalized_alias)}",
            re.IGNORECASE,
        )
        is_canonical_name = bool(alias_record.name) and alias.casefold() == alias_record.name.casefold()
        if direct_pattern.search(normalized_text):
            relationship = "direct_beneficiary"
        elif source_type == "issuer_release" and is_canonical_name:
            relationship = "issuer"
        elif _is_generic_alias(alias_record, alias):
            relationship = "industry_context"
        else:
            relationship = "issuer"
        matches.append((relationship, normalized_alias))
    if not matches:
        return None
    return max(matches, key=lambda match: (RELATIONSHIP_PRIORITY[match[0]], match[1].casefold()))


def infer_event_type(item: RawSourceItem) -> str:
    source_type = item.source_type
    text = item.text.lower()
    if source_type == "financial_media":
        return "public_mention"
    if "contract" in text or "procurement" in text or "award" in text:
        return "procurement"
    if "policy" in text or "funding" in text or "capital" in text or "stake" in text:
        return "policy_capital"
    return "public_mention"


def infer_direction(text: str) -> str:
    lowered = text.lower()
    negative_terms = ("avoid", "ban", "sanction", "investigation", "risk", "delay", "block", "bearish", "sell")
    positive_terms = (
        "buy",
        "bullish",
        "great",
        "partner",
        "award",
        "funding",
        "capital",
        "support",
        "contract",
        "upside",
    )
    if any(term in lowered for term in negative_terms):
        return "bearish"
    if any(term in lowered for term in positive_terms):
        return "bullish"
    return "neutral"


def item_date(item: RawSourceItem) -> str:
    date_text = item.published_at.split("T", 1)[0]
    parse_date(date_text)
    return date_text


def extract_source_records(raw_items_path: str | Path, aliases_path: str | Path, output_path: str | Path) -> list[dict[str, str]]:
    raw_items = load_raw_items(raw_items_path)
    aliases = load_aliases(aliases_path)
    records: list[OfficialRecord] = []
    for item in raw_items:
        for alias_record in aliases:
            evidence = match_evidence(item.text, alias_record, item.source_type)
            if evidence is None:
                continue
            entity_match_type, matched_text = evidence
            records.append(
                OfficialRecord(
                    record_id=f"{item.item_id}-{alias_record.symbol.lower()}",
                    record_date=item_date(item),
                    symbol=alias_record.symbol,
                    source_type=item.source_type,
                    event_type=infer_event_type(item),
                    direction=infer_direction(item.text),
                    source_url=item.source_url,
                    summary=f"{item.author}: {item.text}".strip(": "),
                    entity_match_type=entity_match_type,
                    match_evidence=matched_text,
                    relationship_type=entity_match_type,
                )
            )
    rows = normalize_records(records)
    write_csv_rows(
        output_path,
        [
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
        ],
        rows,
    )
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract source event records from raw post/news CSV input.")
    parser.add_argument("--raw-items", required=True, help="Raw post/news CSV.")
    parser.add_argument("--aliases", required=True, help="Symbol alias CSV.")
    parser.add_argument("--output", required=True, help="Output normalized event CSV.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    extract_source_records(args.raw_items, args.aliases, args.output)


if __name__ == "__main__":
    main()
