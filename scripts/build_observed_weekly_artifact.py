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

from political_event_tracking_research.csv_utils import write_csv_rows
from political_event_tracking_research.feed_status_canonical_h2c import build_decision, read_status
from political_event_tracking_research.observed_weekly_manifest import (
    WORKFLOW_REF,
    read_observed_manifest,
    serialize_observed_manifest,
)
from political_event_tracking_research.rss_source_fetch import FeedConfig, FeedXmlError, fetch_url, load_feed_config, parse_feed_snapshot
from political_event_tracking_research.source_mention_extract import extract_source_records
from political_event_tracking_research.weekly_contract import WeeklyFeedStatus, WeeklySourceArtifact, WeeklySourceContract, parse_weekly_contract
from political_event_tracking_research.weekly_period_lock import PoliticalEventWeeklyPeriodLockV1, SourceSnapshotArtifact, parse_period_lock_bytes, serialize_period_lock


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


class ObservedArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ObservedArtifactError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("artifact_serialization_invalid")


def _retrieved_at(value: str) -> dt.datetime:
    if type(value) is not str or not value.endswith("Z"):
        _fail("retrieved_at_invalid")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError:
        _fail("retrieved_at_invalid")


def expected_period(retrieved_at: str) -> tuple[dt.date, dt.date, dt.date]:
    reference = _retrieved_at(retrieved_at).date()
    monday = reference - dt.timedelta(days=reference.weekday())
    start = monday - dt.timedelta(days=7)
    end = monday
    return start, end, end - dt.timedelta(days=1)


def validate_period(retrieved_at: str, period_start: str | None, as_of: str | None) -> tuple[dt.date, dt.date, dt.date]:
    expected = expected_period(retrieved_at)
    if (period_start is None) != (as_of is None):
        _fail("manual_period_incomplete")
    if period_start is not None and as_of is not None:
        try:
            requested_start = dt.date.fromisoformat(period_start)
            requested_as_of = dt.date.fromisoformat(as_of)
        except ValueError:
            _fail("manual_period_invalid")
        if (requested_start, requested_start + dt.timedelta(days=6)) != (requested_start, requested_as_of):
            _fail("manual_period_invalid")
        if (requested_start, requested_as_of) != (expected[0], expected[2]):
            _fail("manual_period_mismatch")
    return expected


def _row_count(path: Path) -> int:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        _fail("artifact_input_invalid")


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        _fail("artifact_input_invalid")


def _filter_rows(rows: list[dict[str, str]], start: dt.date, as_of: dt.date) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        try:
            event_date = dt.date.fromisoformat(row["published_at"][:10])
        except (KeyError, TypeError, ValueError):
            _fail("event_date_invalid")
        if start <= event_date <= as_of:
            selected.append(row)
    return selected


def _fetch_once(feeds: list[FeedConfig]) -> tuple[list[dict[str, str]], list[dict[str, object]], list[dict[str, object]]]:
    if not feeds:
        _fail("feed_config_empty")
    rows: list[dict[str, str]] = []
    outcomes: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    for feed in feeds:
        try:
            body = fetch_url(feed.feed_url)
            kind, feed_rows = parse_feed_snapshot(body, feed, max_items=MAX_ITEMS_PER_FEED, allow_missing_dates=False)
        except (FeedXmlError, OSError, TimeoutError, ValueError, RuntimeError):
            outcomes.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": "unknown", "state": "failed", "rows": [], "error_code": "fetch_failed"})
            continue
        rows.extend(feed_rows)
        if not feed_rows:
            outcomes.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": kind, "state": "quarantined", "rows": [], "error_code": "zero_entries"})
            continue
        outcomes.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": kind, "state": "accepted", "rows": feed_rows, "error_code": None})
        snapshots.append({"feed_id": feed.feed_id, "kind": kind, "body_sha256": hashlib.sha256(body).hexdigest(), "accepted_row_count": len(feed_rows)})
    return rows, outcomes, snapshots


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv_rows(path, SOURCE_ITEM_FIELDS, rows)


def _readback(output: Path, lock_bytes: bytes, manifest_bytes: bytes, status_bytes: bytes, expected_contract: WeeklySourceContract, selected_count: int, selected_digest: str) -> None:
    try:
        if {item.name for item in output.iterdir()} != set(ARTIFACT_FILES):
            _fail("artifact_file_set_invalid")
        for name in ARTIFACT_FILES:
            path = output / name
            if path.is_symlink() or not path.is_file():
                _fail("artifact_member_invalid")
        if (output / "period_lock.json").read_bytes() != lock_bytes or (output / "weekly_manifest.json").read_bytes() != manifest_bytes or (output / "political_event_weekly.json").read_bytes() != status_bytes:
            _fail("artifact_readback_invalid")
        parse_period_lock_bytes(lock_bytes)
        read_status(status_bytes)
        parsed = read_observed_manifest(manifest_bytes)
        if parse_weekly_contract(parsed["contract"]) != expected_contract:
            _fail("manifest_contract_mismatch")
        observed = parsed["observed_snapshot"]
        if observed["selected_period_count"] != selected_count or observed["selected_period_row_digest"] != selected_digest:
            _fail("manifest_projection_mismatch")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        _fail("artifact_readback_invalid")


def build_observed_weekly_artifact(*, feeds_path: Path, aliases_path: Path, watchlist_path: Path, output_dir: Path, retrieved_at: str, source_run_id: str, source_attempt: int, producer_ref: str, run_mode: str, period_start: str | None = None, as_of: str | None = None) -> Path:
    start, end, sunday = validate_period(retrieved_at, period_start, as_of)
    if type(source_attempt) is not int or source_attempt != 1:
        _fail("source_attempt_invalid")
    if type(run_mode) is not str or run_mode not in {"scheduled", "manual"}:
        _fail("run_mode_invalid")
    rows, outcomes, snapshots = _fetch_once(load_feed_config(feeds_path))
    decision = build_decision(outcomes)
    status = read_status(decision.status_bytes)
    if decision.decision.kind.value != "success":
        _fail("source_incomplete")
    output_dir.mkdir(parents=True, exist_ok=False)
    internal = output_dir / ".source_items.csv"
    try:
        selected_rows = _filter_rows(rows, start, sunday)
        _write_rows(internal, selected_rows)
        events = output_dir / "political_events.csv"
        extract_source_records(internal, aliases_path, events)
        watchlist = output_dir / "political_watchlist.csv"
        shutil.copyfile(watchlist_path, watchlist)
        status_path = output_dir / "political_event_weekly.json"
        status_path.write_bytes(decision.status_bytes)
        selected_count = _row_count(events)
        selected_digest = _sha(events)
        artifacts = [
            {"path": "political_events.csv", "sha256": selected_digest, "row_count": selected_count},
            {"path": "political_watchlist.csv", "sha256": _sha(watchlist), "row_count": _row_count(watchlist)},
            {"path": "political_event_weekly.json", "sha256": _sha(status_path), "row_count": 0},
        ]
        lock = PoliticalEventWeeklyPeriodLockV1(start, end, sunday, WORKFLOW_REF, source_run_id, source_attempt, producer_ref, f"run_{source_run_id}_attempt_{source_attempt}", hashlib.sha256(_canonical(artifacts)).hexdigest(), SOURCE_PROVENANCE, tuple(SourceSnapshotArtifact(item["path"], item["sha256"], item["row_count"]) for item in artifacts))
        lock_bytes = serialize_period_lock(lock)
        (output_dir / "period_lock.json").write_bytes(lock_bytes)
        manifest_artifacts = [{"path": "period_lock.json", "sha256": hashlib.sha256(lock_bytes).hexdigest(), "row_count": 0}, *artifacts]
        contract = WeeklySourceContract(dt.date.fromisoformat(sunday.isoformat()), start, end, _retrieved_at(retrieved_at), run_mode, producer_ref, SOURCE_PROVENANCE, tuple(WeeklySourceArtifact(item["path"], item["sha256"], item["row_count"]) for item in manifest_artifacts), WeeklyFeedStatus(status["feed_count"], status["successful_feed_count"], status["failed_feed_count"], 0, 0, True))
        observed = {"observed_snapshot_version": "configured_source_observed.v1", "coverage_semantics": "configured_source_observed", "retrieved_at": retrieved_at, "provider_freshness": "unverified", "private_research_only": True, "fetch_parse_outcome": "success", "source_run_id": source_run_id, "source_attempt": source_attempt, "workflow_ref": WORKFLOW_REF, "source_snapshot_digest": hashlib.sha256(_canonical({"feeds": snapshots, "status_sha256": _sha(status_path), "selected_csv_sha256": selected_digest, "watchlist_sha256": _sha(watchlist)})).hexdigest(), "feed_snapshots": sorted(snapshots, key=lambda item: str(item["feed_id"])), "selected_period_count": selected_count, "selected_period_row_digest": selected_digest}
        manifest_bytes = serialize_observed_manifest(contract, observed)
        (output_dir / "weekly_manifest.json").write_bytes(manifest_bytes)
        internal.unlink()
        _readback(output_dir, lock_bytes, manifest_bytes, decision.status_bytes, contract, selected_count, selected_digest)
        return output_dir
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def _retrieved_at(value: str) -> dt.datetime:
    return _retrieved_at_strict(value)


def _retrieved_at_strict(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feeds", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--watchlist", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-attempt", type=int, required=True)
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--run-mode", choices=("scheduled", "manual"), required=True)
    parser.add_argument("--period-start")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    try:
        build_observed_weekly_artifact(feeds_path=args.feeds, aliases_path=args.aliases, watchlist_path=args.watchlist, output_dir=args.output_dir, retrieved_at=args.retrieved_at, source_run_id=args.source_run_id, source_attempt=args.source_attempt, producer_ref=args.producer_ref, run_mode=args.run_mode, period_start=args.period_start, as_of=args.as_of)
    except (OSError, UnicodeError, ValueError):
        raise SystemExit("observed_weekly_artifact_invalid") from None


if __name__ == "__main__":
    main()
