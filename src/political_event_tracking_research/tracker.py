from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .csv_utils import read_csv_rows, write_csv_rows
from .event_study import Event, load_events


BUCKET_WEIGHTS = {
    "named_mentioned": 4,
    "policy_capital": 4,
    "disclosed_holding": 2,
    "drone_policy_watchlist": 2,
}

EVENT_WEIGHTS = {
    "public_mention": 4,
    "policy_capital": 4,
    "procurement": 4,
    "disclosure_buy": 3,
    "regulatory_action": 3,
    "market_reaction": 1,
}

CONFIDENCE_WEIGHTS = {
    "high": 3,
    "medium": 2,
    "low": 1,
}


@dataclass(frozen=True)
class WatchlistItem:
    symbol: str
    name: str
    bucket: str
    research_status: str
    thesis: str
    source_url: str


def load_watchlist(path: str | Path) -> list[WatchlistItem]:
    items: list[WatchlistItem] = []
    for row in read_csv_rows(path):
        items.append(
            WatchlistItem(
                symbol=row["symbol"].upper(),
                name=row.get("name", ""),
                bucket=row.get("bucket", ""),
                research_status=row.get("research_status") or row.get("article_status", ""),
                thesis=row.get("thesis", ""),
                source_url=row.get("source_url", ""),
            )
        )
    return items


def latest_event(events: list[Event]) -> Event | None:
    if not events:
        return None
    return max(events, key=lambda event: (event.event_date, event.event_type, event.event_id))


def event_score(events: list[Event]) -> int:
    score = 0
    for event in events:
        if event.entity_match_type not in {"issuer", "direct_beneficiary"}:
            continue
        score += EVENT_WEIGHTS.get(event.event_type, 0)
        score += CONFIDENCE_WEIGHTS.get(event.confidence, 0)
    return score


def trigger_status(item: WatchlistItem, events: list[Event]) -> str:
    event_types = {event.event_type for event in events}
    if "public_mention" in event_types and "disclosure_buy" in event_types:
        return "disclosure_plus_mention"
    if "policy_capital" in event_types:
        return "policy_triggered"
    if "public_mention" in event_types:
        return "mentioned"
    if "disclosure_buy" in event_types:
        return "disclosed"
    return item.research_status or "watchlist"


def build_tracker_rows(items: list[WatchlistItem], events: list[Event]) -> list[dict[str, object]]:
    events_by_symbol: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        events_by_symbol[event.symbol].append(event)

    rows: list[dict[str, object]] = []
    for item in items:
        symbol_events = sorted(events_by_symbol.get(item.symbol, []), key=lambda event: (event.event_date, event.event_id))
        latest = latest_event(symbol_events)
        base_score = BUCKET_WEIGHTS.get(item.bucket, 0)
        score = base_score + event_score(symbol_events)
        rows.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "bucket": item.bucket,
                "trigger_status": trigger_status(item, symbol_events),
                "priority_score": score,
                "event_count": len(symbol_events),
                "latest_event_date": latest.event_date.isoformat() if latest else "",
                "latest_event_type": latest.event_type if latest else "",
                "source_url": item.source_url,
                "thesis": item.thesis,
            }
        )

    rows.sort(key=lambda row: (-int(row["priority_score"]), row["symbol"]))
    return rows


def build_tracker(watchlist_path: str | Path, events_path: str | Path, output_path: str | Path) -> list[dict[str, object]]:
    items = load_watchlist(watchlist_path)
    events = load_events(events_path)
    rows = build_tracker_rows(items, events)
    write_csv_rows(
        output_path,
        [
            "symbol",
            "name",
            "bucket",
            "trigger_status",
            "priority_score",
            "event_count",
            "latest_event_date",
            "latest_event_type",
            "source_url",
            "thesis",
        ],
        rows,
    )
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a candidate tracker from watchlist and event CSVs.")
    parser.add_argument("--watchlist", required=True, help="CSV watchlist file.")
    parser.add_argument("--events", required=True, help="CSV event file.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    build_tracker(args.watchlist, args.events, args.output)


if __name__ == "__main__":
    main()
