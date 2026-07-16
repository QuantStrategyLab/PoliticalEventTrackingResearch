#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.feed_status_canonical_h2c import build_decision, read_status
from political_event_tracking_research.rss_source_fetch import (
    FeedConfig,
    FeedXmlError,
    fetch_url,
    load_feed_config,
    parse_feed_snapshot,
)
from political_event_tracking_research.source_mention_extract import extract_source_records
from political_event_tracking_research.weekly_contract import (
    WeeklyFeedStatus,
    WeeklySourceArtifact,
    WeeklySourceContract,
    parse_weekly_contract,
)
from political_event_tracking_research.weekly_manifest import (
    parse_weekly_manifest_bytes,
    serialize_weekly_manifest,
)
from political_event_tracking_research.weekly_period_lock import (
    PoliticalEventWeeklyPeriodLockV1,
    SourceSnapshotArtifact,
    parse_period_lock_bytes,
    serialize_period_lock,
)
from political_event_tracking_research.csv_utils import write_csv_rows


WORKFLOW_REF = (
    "QuantStrategyLab/PoliticalEventTrackingResearch/"
    ".github/workflows/pert_weekly_producer.yml@refs/heads/main"
)
ARTIFACT_NAME = "political-event-weekly-v1"
ARTIFACT_FILES = (
    "period_lock.json",
    "political_events.csv",
    "political_watchlist.csv",
    "political_event_weekly.json",
    "weekly_manifest.json",
)
MAX_ITEMS_PER_FEED = 50
SOURCE_PROVENANCE = "configured_source_snapshot_v1"
SOURCE_ITEM_FIELDS = ("item_id", "published_at", "source_type", "source_url", "author", "text")


class WeeklyArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise WeeklyArtifactError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("weekly_artifact_serialization_invalid")


def _parse_reference(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _fail("reference_time_invalid")
    if parsed.tzinfo != dt.UTC:
        _fail("reference_time_invalid")
    return parsed


def expected_period(reference_time: str) -> tuple[dt.date, dt.date, dt.date]:
    reference = _parse_reference(reference_time).date()
    current_monday = reference - dt.timedelta(days=reference.weekday())
    period_start = current_monday - dt.timedelta(days=7)
    period_end = current_monday
    return period_start, period_end, period_end - dt.timedelta(days=1)


def validate_requested_period(
    reference_time: str, period_start: str | None, as_of: str | None
) -> tuple[dt.date, dt.date, dt.date]:
    expected = expected_period(reference_time)
    if (period_start is None) != (as_of is None):
        _fail("manual_period_incomplete")
    if period_start is not None and as_of is not None:
        try:
            requested = (dt.date.fromisoformat(period_start), dt.date.fromisoformat(as_of))
        except ValueError:
            _fail("manual_period_invalid")
        if (requested[0], requested[0] + dt.timedelta(days=6)) != (requested[0], requested[1]):
            _fail("manual_period_invalid")
        if requested != (expected[0], expected[2]):
            _fail("manual_period_mismatch")
    return expected


def _row_count(path: Path) -> int:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        _fail("weekly_artifact_input_invalid")


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        _fail("weekly_artifact_input_invalid")


def _artifact(path: Path, relative: str, row_count: int) -> dict[str, object]:
    return {"path": relative, "sha256": _sha256(path), "row_count": row_count}


def _filter_source_rows(rows: list[dict[str, str]], period_start: dt.date, as_of: dt.date) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        try:
            event_date = dt.date.fromisoformat(row["published_at"][:10])
        except (KeyError, TypeError, ValueError):
            _fail("source_snapshot_date_invalid")
        if period_start <= event_date <= as_of:
            result.append(row)
    return result


def _write_source_items(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv_rows(path, SOURCE_ITEM_FIELDS, rows)


def _fetch_snapshot(feeds: list[FeedConfig]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    if not feeds:
        _fail("feed_config_empty")
    all_rows: list[dict[str, str]] = []
    outcomes: list[dict[str, object]] = []
    for feed in feeds:
        try:
            kind, rows = parse_feed_snapshot(
                fetch_url(feed.feed_url), feed, max_items=MAX_ITEMS_PER_FEED, allow_missing_dates=False
            )
        except (FeedXmlError, OSError, TimeoutError, ValueError, RuntimeError):
            outcomes.append(
                {
                    "feed_id": feed.feed_id,
                    "feed_url": feed.feed_url,
                    "kind": "unknown",
                    "state": "failed",
                    "rows": [],
                    "error_code": "fetch_failed",
                }
            )
            continue
        all_rows.extend(rows)
        outcomes.append(
            {
                "feed_id": feed.feed_id,
                "feed_url": feed.feed_url,
                "kind": kind,
                "state": "accepted" if rows else "quarantined",
                "rows": rows,
                "error_code": None if rows else "zero_entries",
            }
        )
    return all_rows, outcomes


def _source_snapshot_digest(artifacts: list[dict[str, object]]) -> str:
    return hashlib.sha256(_canonical(sorted(artifacts, key=lambda item: str(item["path"])))).hexdigest()


def _write_and_readback(
    output_dir: Path,
    *,
    lock_bytes: bytes,
    manifest_bytes: bytes,
    status_bytes: bytes,
    expected_contract: WeeklySourceContract,
) -> None:
    expected = set(ARTIFACT_FILES)
    try:
        names = {path.name for path in output_dir.iterdir()}
    except OSError:
        _fail("weekly_artifact_readback_invalid")
    if names != expected:
        _fail("weekly_artifact_file_set_invalid")
    for name in ARTIFACT_FILES:
        path = output_dir / name
        if not path.is_file() or path.is_symlink():
            _fail("weekly_artifact_member_invalid")
    try:
        if (output_dir / "period_lock.json").read_bytes() != lock_bytes:
            _fail("period_lock_readback_invalid")
        if (output_dir / "weekly_manifest.json").read_bytes() != manifest_bytes:
            _fail("weekly_manifest_readback_invalid")
        if (output_dir / "political_event_weekly.json").read_bytes() != status_bytes:
            _fail("status_readback_invalid")
        parse_period_lock_bytes(lock_bytes)
        parse_weekly_manifest_bytes(manifest_bytes)
        read_status(status_bytes)
        parse_weekly_contract(json.loads(manifest_bytes)["contract"])
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError):
        _fail("weekly_artifact_readback_invalid")
    if parse_weekly_manifest_bytes(manifest_bytes) != expected_contract:
        _fail("weekly_manifest_contract_mismatch")


def build_weekly_artifact(
    *,
    feeds_path: Path,
    aliases_path: Path,
    watchlist_path: Path,
    output_dir: Path,
    reference_time: str,
    source_run_id: str,
    source_attempt: int,
    producer_ref: str,
    period_start: str | None = None,
    as_of: str | None = None,
) -> Path:
    period_start_date, period_end_date, as_of_date = validate_requested_period(reference_time, period_start, as_of)
    if type(source_attempt) is not int or source_attempt != 1:
        _fail("run_attempt_invalid")
    rows, outcomes = _fetch_snapshot(load_feed_config(feeds_path))
    decision = build_decision(outcomes)
    status = read_status(decision.status_bytes)
    if decision.decision.kind.value != "success":
        _fail("weekly_source_incomplete")
    output_dir.mkdir(parents=True, exist_ok=False)
    internal = output_dir / ".source_items.csv"
    try:
        _write_source_items(internal, rows)
        period_rows = _filter_source_rows(rows, period_start_date, as_of_date)
        _write_source_items(internal, period_rows)
        events_path = output_dir / "political_events.csv"
        extract_source_records(internal, aliases_path, events_path)
        watchlist_output = output_dir / "political_watchlist.csv"
        shutil.copyfile(watchlist_path, watchlist_output)
        output_dir.joinpath("political_event_weekly.json").write_bytes(decision.status_bytes)
        artifacts = [
            _artifact(output_dir / "political_events.csv", "political_events.csv", _row_count(events_path)),
            _artifact(watchlist_output, "political_watchlist.csv", _row_count(watchlist_output)),
            _artifact(output_dir / "political_event_weekly.json", "political_event_weekly.json", 0),
        ]
        source_artifacts = [
            SourceSnapshotArtifact(item["path"], item["sha256"], item["row_count"]) for item in artifacts
        ]
        lock = PoliticalEventWeeklyPeriodLockV1(
            period_start_date,
            period_end_date,
            as_of_date,
            WORKFLOW_REF,
            source_run_id,
            source_attempt,
            producer_ref,
            f"run_{source_run_id}_attempt_1",
            _source_snapshot_digest(artifacts),
            SOURCE_PROVENANCE,
            tuple(source_artifacts),
        )
        lock_bytes = serialize_period_lock(lock)
        output_dir.joinpath("period_lock.json").write_bytes(lock_bytes)
        manifest_artifacts = [
            {"path": "period_lock.json", "sha256": hashlib.sha256(lock_bytes).hexdigest(), "row_count": 0},
            *artifacts,
        ]
        manifest_contract = WeeklySourceContract(
            as_of_date,
            period_start_date,
            period_end_date,
            _parse_reference(reference_time),
            "manual" if period_start is not None else "scheduled",
            producer_ref,
            SOURCE_PROVENANCE,
            tuple(WeeklySourceArtifact(item["path"], item["sha256"], item["row_count"]) for item in manifest_artifacts),
            WeeklyFeedStatus(
                status["feed_count"],
                status["successful_feed_count"],
                status["failed_feed_count"],
                0,
                0,
                status["publication_complete"],
            ),
        )
        manifest_bytes = serialize_weekly_manifest(manifest_contract)
        output_dir.joinpath("weekly_manifest.json").write_bytes(manifest_bytes)
        internal.unlink()
        _write_and_readback(
            output_dir,
            lock_bytes=lock_bytes,
            manifest_bytes=manifest_bytes,
            status_bytes=decision.status_bytes,
            expected_contract=manifest_contract,
        )
        return output_dir
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feeds", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--watchlist", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-time", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-attempt", type=int, required=True)
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--period-start")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    try:
        build_weekly_artifact(
            feeds_path=args.feeds,
            aliases_path=args.aliases,
            watchlist_path=args.watchlist,
            output_dir=args.output_dir,
            reference_time=args.reference_time,
            source_run_id=args.source_run_id,
            source_attempt=args.source_attempt,
            producer_ref=args.producer_ref,
            period_start=args.period_start,
            as_of=args.as_of,
        )
    except (OSError, UnicodeError, ValueError):
        raise SystemExit("weekly_artifact_invalid") from None


if __name__ == "__main__":
    main()
