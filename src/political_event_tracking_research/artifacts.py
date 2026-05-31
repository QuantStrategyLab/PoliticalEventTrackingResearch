from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_row_count(path: str | Path) -> int:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def summarize_source_events(path: str | Path) -> dict[str, Any]:
    symbols: set[str] = set()
    confidence_counts: dict[str, int] = {}
    event_type_counts: dict[str, int] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            symbol = row.get("symbol", "").strip().upper()
            if symbol:
                symbols.add(symbol)
            confidence = row.get("confidence", "").strip() or "unknown"
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
            event_type = row.get("event_type", "").strip() or "unknown"
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
    return {
        "symbol_count": len(symbols),
        "symbols": sorted(symbols),
        "confidence_counts": dict(sorted(confidence_counts.items())),
        "event_type_counts": dict(sorted(event_type_counts.items())),
    }


def summarize_feed_status(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    feed_count = int(payload.get("feed_count") or 0)
    successful_feed_count = int(payload.get("successful_feed_count") or 0)
    failed_feed_count = int(payload.get("failed_feed_count") or 0)
    return {
        "feed_count": feed_count,
        "successful_feed_count": successful_feed_count,
        "failed_feed_count": failed_feed_count,
        "feed_success_ratio": round(successful_feed_count / feed_count, 4) if feed_count else None,
    }


def build_data_quality_summary(paths: list[Path]) -> dict[str, Any]:
    by_name = {path.name: path for path in paths}
    summary: dict[str, Any] = {}
    source_events_path = by_name.get("source_events.csv") or by_name.get("political_events.csv")
    if source_events_path and source_events_path.exists():
        summary["source_events"] = summarize_source_events(source_events_path)
    feed_status_path = by_name.get("source_fetch_status.json")
    if feed_status_path and feed_status_path.exists():
        summary["feed_status"] = summarize_feed_status(feed_status_path)
    return summary


def build_live_manifest(paths: list[str | Path], *, base_dir: str | Path | None = None) -> dict[str, Any]:
    base = Path(base_dir).resolve() if base_dir else None
    artifacts: dict[str, Any] = {}
    resolved_paths = [Path(raw_path) for raw_path in paths]
    for path in resolved_paths:
        key = path.name
        display_path = str(path)
        if base:
            try:
                display_path = str(path.resolve().relative_to(base))
            except ValueError:
                display_path = str(path)
        artifacts[key] = {
            "path": display_path,
            "sha256": sha256_file(path),
            "row_count": csv_row_count(path) if path.suffix.lower() == ".csv" else None,
        }
    return {
        "manifest_type": "political_event_live_outputs",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "data_quality": build_data_quality_summary(resolved_paths),
    }


def write_live_manifest(paths: list[str | Path], output_path: str | Path, *, base_dir: str | Path | None = None) -> Path:
    payload = build_live_manifest(paths, base_dir=base_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
