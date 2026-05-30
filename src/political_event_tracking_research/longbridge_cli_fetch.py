from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from .csv_utils import read_csv_rows
from .longbridge_topic_import import import_longbridge_topics, iter_topic_items


class LongbridgeCliError(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]


def load_symbols(path: str | Path) -> list[str]:
    symbols: list[str] = []
    for row in read_csv_rows(path):
        symbol = (row.get("symbol") or "").strip()
        if symbol:
            symbols.append(symbol)
    return list(dict.fromkeys(symbols))


def run_longbridge_json(args: Sequence[str], *, runner: Runner = subprocess.run) -> Any:
    command = ["longbridge", *args, "--format", "json"]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise LongbridgeCliError(stderr or f"longbridge command failed: {' '.join(command)}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LongbridgeCliError("longbridge command did not return JSON. Check CLI version and --format support.") from exc


def fetch_longbridge_cli_topics(
    symbols_path: str | Path,
    raw_output_path: str | Path,
    *,
    source_items_output_path: str | Path | None = None,
    author_allowlist_path: str | Path | None = None,
    include_details: bool = False,
    min_likes: int = 0,
    runner: Runner = subprocess.run,
) -> list[dict[str, Any]]:
    topics_by_id: dict[str, dict[str, Any]] = {}
    for symbol in load_symbols(symbols_path):
        payload = run_longbridge_json(["topic", symbol], runner=runner)
        for item in iter_topic_items(payload):
            topic_id = str(item.get("id") or "").strip()
            if topic_id:
                topics_by_id[topic_id] = item

    if include_details:
        for topic_id in list(topics_by_id):
            detail_payload = run_longbridge_json(["topic", "detail", topic_id], runner=runner)
            detail_items = list(iter_topic_items(detail_payload))
            if detail_items:
                topics_by_id[topic_id] = detail_items[0]

    rows = sorted(topics_by_id.values(), key=lambda item: str(item.get("id") or ""))
    raw_output = Path(raw_output_path)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps({"data": {"items": rows}}, ensure_ascii=False, indent=2), encoding="utf-8")

    if source_items_output_path:
        import_longbridge_topics(
            [raw_output],
            source_items_output_path,
            author_allowlist_path=author_allowlist_path,
            min_likes=min_likes,
        )
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Longbridge community topics through the official Longbridge CLI."
    )
    parser.add_argument("--symbols", required=True, help="CSV with a symbol column, e.g. NVDA.US.")
    parser.add_argument("--raw-output", required=True, help="Output raw Longbridge topic JSON.")
    parser.add_argument("--source-items-output", help="Optional output source_items CSV.")
    parser.add_argument("--author-allowlist", help="Optional followed-author allowlist CSV path.")
    parser.add_argument("--include-details", action="store_true", help="Fetch full topic detail for each topic id.")
    parser.add_argument("--min-likes", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        fetch_longbridge_cli_topics(
            args.symbols,
            args.raw_output,
            source_items_output_path=args.source_items_output,
            author_allowlist_path=args.author_allowlist,
            include_details=args.include_details,
            min_likes=args.min_likes,
        )
    except LongbridgeCliError as exc:
        raise SystemExit(f"Longbridge CLI fetch failed: {exc}") from exc


if __name__ == "__main__":
    main()
