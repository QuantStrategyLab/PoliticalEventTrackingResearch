from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .csv_utils import read_csv_rows, write_csv_rows
from .event_study import parse_date


GOVERNMENT_SOURCE_TYPES = frozenset(
    {
        "government_filing",
        "official_remarks",
        "government_policy",
        "government_procurement",
        "regulatory_action",
    }
)

ISSUER_SOURCE_TYPES = frozenset({"issuer_release"})

ALLOWED_EVENT_TYPES = frozenset(
    {
        "disclosure_buy",
        "public_mention",
        "policy_capital",
        "procurement",
        "regulatory_action",
        "market_reaction",
    }
)


@dataclass(frozen=True)
class OfficialRecord:
    record_id: str
    record_date: str
    symbol: str
    source_type: str
    event_type: str
    direction: str
    source_url: str
    summary: str


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "record"


def is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_government_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return is_https_url(url) and (host.endswith(".gov") or host == "govinfo.gov")


def load_official_records(path: str | Path) -> list[OfficialRecord]:
    records: list[OfficialRecord] = []
    for row in read_csv_rows(path):
        records.append(
            OfficialRecord(
                record_id=row["record_id"],
                record_date=row["record_date"],
                symbol=row["symbol"].upper(),
                source_type=row["source_type"],
                event_type=row["event_type"],
                direction=row.get("direction", ""),
                source_url=row["source_url"],
                summary=row.get("summary", ""),
            )
        )
    return records


def validate_record(record: OfficialRecord) -> None:
    parse_date(record.record_date)
    if not record.record_id.strip():
        raise ValueError("record_id is required")
    if not record.symbol.strip():
        raise ValueError(f"{record.record_id}: symbol is required")
    if record.event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"{record.record_id}: unsupported event_type {record.event_type!r}")
    if record.source_type in GOVERNMENT_SOURCE_TYPES:
        if not is_government_url(record.source_url):
            raise ValueError(f"{record.record_id}: government source URLs must be https .gov URLs")
    elif record.source_type in ISSUER_SOURCE_TYPES:
        if not is_https_url(record.source_url):
            raise ValueError(f"{record.record_id}: issuer source URLs must be https URLs")
    else:
        raise ValueError(f"{record.record_id}: unsupported source_type {record.source_type!r}")


def confidence_for_source(record: OfficialRecord) -> str:
    if record.source_type in GOVERNMENT_SOURCE_TYPES:
        return "high"
    return "medium"


def normalize_records(records: list[OfficialRecord]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        validate_record(record)
        event_id = f"official-{slug(record.source_type)}-{slug(record.record_id)}"
        rows.append(
            {
                "event_id": event_id,
                "event_date": record.record_date,
                "symbol": record.symbol,
                "event_type": record.event_type,
                "direction": record.direction or "neutral",
                "confidence": confidence_for_source(record),
                "source_url": record.source_url,
                "notes": record.summary,
            }
        )
    rows.sort(key=lambda row: (row["event_date"], row["symbol"], row["event_id"]))
    return rows


def import_official_events(input_path: str | Path, output_path: str | Path) -> list[dict[str, str]]:
    records = load_official_records(input_path)
    rows = normalize_records(records)
    write_csv_rows(
        output_path,
        ["event_id", "event_date", "symbol", "event_type", "direction", "confidence", "source_url", "notes"],
        rows,
    )
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize official-source event records into the research event schema.")
    parser.add_argument("--input", required=True, help="Official-source record CSV.")
    parser.add_argument("--output", required=True, help="Output normalized event CSV.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    import_official_events(args.input, args.output)


if __name__ == "__main__":
    main()

