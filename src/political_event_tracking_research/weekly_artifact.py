"""Concrete five-file weekly artifact with run-relative period provenance."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Final

from .weekly_contract import (
    WeeklyContractError,
    WeeklyFeedStatus,
    WeeklySourceArtifact,
    WeeklySourceContract,
    parse_weekly_contract,
    serialize_weekly_contract,
)
from .weekly_period_lock import (
    PeriodLockError,
    PoliticalEventWeeklyPeriodLockV1,
    SourceSnapshotArtifact,
    parse_period_lock_bytes,
    serialize_period_lock,
)
from .workflow_boundary import WORKFLOW_REF

ARTIFACT_NAME: Final = "political-event-weekly-v1"
RETENTION_DAYS: Final = 30
ARTIFACT_FILES: Final = ("period_lock.json", "political_events.csv", "political_watchlist.csv", "political_event_weekly.json", "weekly_manifest.json")
EVENTS = "political_events.csv"
WATCHLIST = "political_watchlist.csv"
WEEKLY = "political_event_weekly.json"
LOCK = "period_lock.json"
MANIFEST = "weekly_manifest.json"
EVENT_HEADER: Final = ("event_id", "event_date", "symbol", "event_type", "direction", "confidence", "source_url", "notes")
WATCHLIST_HEADER: Final = ("symbol", "name", "bucket", "research_status", "thesis", "source_url")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class WeeklyArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> WeeklyArtifactError:
    return WeeklyArtifactError(code)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _snapshot_digest(*values: bytes) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(len(value).to_bytes(8, "big"))
        h.update(value)
    return h.hexdigest()


def _json(value: object, code: str) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _fail(code) from None


def serialize_weekly_artifact_manifest(value: Mapping[str, object]) -> bytes:
    """Authoritative canonical serializer for the dedicated artifact manifest."""
    if not isinstance(value, Mapping):
        raise _fail("manifest_invalid")
    return _json(dict(value), "manifest_invalid")


def _parse_json(wire: bytes, code: str) -> object:
    if type(wire) is not bytes:
        raise _fail(code)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _fail(f"{code}_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except WeeklyArtifactError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _fail(code) from None
    if _json(value, code) != wire:
        raise _fail(f"{code}_noncanonical")
    return value


def _csv_rows(value: bytes, header: tuple[str, ...], code: str, *, allow_empty: bool = False) -> list[list[str]]:
    if type(value) is not bytes:
        raise _fail(code)
    try:
        rows = list(csv.reader(io.StringIO(value.decode("utf-8"), newline="")))
    except (UnicodeError, csv.Error, ValueError, RecursionError):
        raise _fail(code) from None
    if not rows or tuple(rows[0]) != header or (not allow_empty and len(rows) < 2):
        raise _fail(f"{code}_header")
    if any(len(row) != len(header) for row in rows[1:]):
        raise _fail(f"{code}_rows")
    return rows


def _filter_events(source: bytes, start: date, as_of: date) -> bytes:
    rows = _csv_rows(source, EVENT_HEADER, "events_csv_invalid", allow_empty=True)
    chosen: list[list[str]] = []
    for row in rows[1:]:
        try:
            observed = date.fromisoformat(row[1])
        except (TypeError, ValueError):
            raise _fail("events_date_invalid") from None
        if observed.isoformat() != row[1]:
            raise _fail("events_date_invalid")
        if start <= observed <= as_of:
            chosen.append(row)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(EVENT_HEADER)
    writer.writerows(chosen)
    return output.getvalue().encode("utf-8")


_FETCH_STATUS_KEYS = {"generated_at", "feed_count", "successful_feed_count", "failed_feed_count", "stale_feed_count", "missing_feed_count", "complete", "item_count", "feeds"}
_FEED_ENTRY_KEYS = {"feed_id", "feed_url", "ok", "item_count", "error"}


def _status(value: object) -> WeeklyFeedStatus:
    if not isinstance(value, Mapping) or set(value) != _FETCH_STATUS_KEYS or not isinstance(value["feeds"], list) or len(value["feeds"]) != value.get("feed_count"):
        raise _fail("feed_status_invalid")
    if type(value["generated_at"]) is not str or type(value["item_count"]) is not int or value["item_count"] < 0:
        raise _fail("feed_status_invalid")
    for feed in value["feeds"]:
        if not isinstance(feed, Mapping) or set(feed) != _FEED_ENTRY_KEYS or type(feed["feed_id"]) is not str or type(feed["feed_url"]) is not str or type(feed["ok"]) is not bool or type(feed["item_count"]) is not int or feed["item_count"] < 0 or type(feed["error"]) is not str:
            raise _fail("feed_status_invalid")
    counts = {key: value[key] for key in ("feed_count", "successful_feed_count", "failed_feed_count", "stale_feed_count", "missing_feed_count")}
    if any(type(counts[key]) is not int or counts[key] < 0 for key in counts):
        raise _fail("feed_status_invalid")
    complete = value["complete"]
    if type(complete) is not bool:
        raise _fail("feed_status_invalid")
    if counts["feed_count"] <= 0 or counts["successful_feed_count"] != counts["feed_count"] or any(counts[key] for key in ("failed_feed_count", "stale_feed_count", "missing_feed_count")) or not complete:
        raise _fail("feed_status_incomplete")
    return WeeklyFeedStatus(counts["feed_count"], counts["successful_feed_count"], counts["failed_feed_count"], counts["stale_feed_count"], counts["missing_feed_count"], complete)


def _date(value: object, code: str) -> date:
    if type(value) is not str:
        raise _fail(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _fail(code) from None
    if parsed.isoformat() != value:
        raise _fail(code)
    return parsed


def _manifest(lock: dict[str, object], weekly: dict[str, object], files: Mapping[str, bytes]) -> dict[str, object]:
    event_rows = _csv_rows(files[EVENTS], EVENT_HEADER, "events_csv_invalid", allow_empty=True)
    watch_rows = _csv_rows(files[WATCHLIST], WATCHLIST_HEADER, "watchlist_csv_invalid")
    return {
        "manifest_version": "political_event_weekly_artifact_manifest.v1",
        "artifact_name": ARTIFACT_NAME,
        "retention_days": RETENTION_DAYS,
        "schema_version": "1",
        "contract_version": "political_event_weekly.v1",
        "cadence": "weekly",
        "period_start": weekly["period_start"],
        "period_end_exclusive": weekly["period_end_exclusive"],
        "as_of": weekly["as_of"],
        "generated_at": weekly["generated_at"],
        "workflow_ref": lock["workflow_ref"],
        "source_run_id": lock["source_run_id"],
        "source_attempt": lock["source_attempt"],
        "producer_ref": lock["producer_ref"],
        "source_snapshot_digest": lock["source_snapshot_digest"],
        "source_provenance": "official_rss_source_pipeline_v1",
        "feed_status": weekly["feed_status"],
        "source_inputs": [
            {"name": EVENTS, "length": len(files[EVENTS]), "sha256": _sha(files[EVENTS]), "row_count": len(event_rows) - 1},
            {"name": WATCHLIST, "length": len(files[WATCHLIST]), "sha256": _sha(files[WATCHLIST]), "row_count": len(watch_rows) - 1},
        ],
        "files": [
            {"name": LOCK, "length": len(files[LOCK]), "sha256": _sha(files[LOCK]), "role": "period_lock"},
            {"name": EVENTS, "length": len(files[EVENTS]), "sha256": _sha(files[EVENTS]), "row_count": len(event_rows) - 1, "header": list(EVENT_HEADER), "role": "filtered_events"},
            {"name": WATCHLIST, "length": len(files[WATCHLIST]), "sha256": _sha(files[WATCHLIST]), "row_count": len(watch_rows) - 1, "header": list(WATCHLIST_HEADER), "role": "watchlist"},
            {"name": WEEKLY, "length": len(files[WEEKLY]), "sha256": _sha(files[WEEKLY]), "role": "weekly_contract"},
        ],
    }


def build_weekly_artifact(*, period_start: date, as_of: date, generated_at: datetime, workflow_ref: str, source_run_id: str, source_attempt: int = 1, producer_ref: str, source_events: bytes, watchlist: bytes, feed_status: Mapping[str, object], run_mode: str) -> dict[str, bytes]:
    if type(period_start) is not date or type(as_of) is not date or period_start.weekday() != 0 or workflow_ref != WORKFLOW_REF or run_mode not in {"scheduled", "manual"}:
        raise _fail("period_contract_invalid")
    try:
        end = period_start + timedelta(days=7)
    except OverflowError:
        raise _fail("period_contract_invalid") from None
    if as_of != end - timedelta(days=1):
        raise _fail("period_mismatch")
    if type(generated_at) is not datetime or generated_at.tzinfo != timezone.utc or generated_at < datetime.combine(end, datetime.min.time(), timezone.utc):
        raise _fail("generated_at_invalid")
    if type(source_run_id) is not str or not source_run_id.isdigit() or type(source_attempt) is not int or not 1 <= source_attempt <= 2**53 - 1 or type(producer_ref) is not str or not _SHA.fullmatch(producer_ref):
        raise _fail("source_identity_invalid")
    filtered = _filter_events(source_events, period_start, as_of)
    _csv_rows(watchlist, WATCHLIST_HEADER, "watchlist_csv_invalid")
    status = _status(feed_status)
    source_digest = _snapshot_digest(filtered, watchlist)
    artifacts = (WeeklySourceArtifact(EVENTS, _sha(filtered), len(_csv_rows(filtered, EVENT_HEADER, "events_csv_invalid", allow_empty=True)) - 1), WeeklySourceArtifact(WATCHLIST, _sha(watchlist), len(_csv_rows(watchlist, WATCHLIST_HEADER, "watchlist_csv_invalid")) - 1))
    contract = WeeklySourceContract(as_of, period_start, end, generated_at, run_mode, producer_ref, "official_rss_source_pipeline_v1", artifacts, status)
    weekly_wire = serialize_weekly_contract(contract)
    weekly = json.loads(weekly_wire)
    lock_object = PoliticalEventWeeklyPeriodLockV1(period_start, end, as_of, workflow_ref, source_run_id, source_attempt, producer_ref, f"rss_source_snapshot_{as_of:%Y%m%d}_{source_run_id}_{source_attempt}", source_digest, "official_rss_source_pipeline_v1", (SourceSnapshotArtifact(EVENTS, _sha(filtered), len(_csv_rows(filtered, EVENT_HEADER, "events_csv_invalid", allow_empty=True)) - 1), SourceSnapshotArtifact(WATCHLIST, _sha(watchlist), len(_csv_rows(watchlist, WATCHLIST_HEADER, "watchlist_csv_invalid")) - 1)))
    lock = json.loads(serialize_period_lock(lock_object))
    files: dict[str, bytes] = {LOCK: serialize_period_lock(lock_object), EVENTS: filtered, WATCHLIST: watchlist, WEEKLY: weekly_wire}
    files[MANIFEST] = serialize_weekly_artifact_manifest(_manifest(dict(lock), weekly, files))
    return parse_weekly_artifact(files)


def parse_weekly_artifact(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or tuple(files) != ARTIFACT_FILES or any(type(files[name]) is not bytes for name in ARTIFACT_FILES):
        raise _fail("artifact_file_set_invalid")
    try:
        lock_object = parse_period_lock_bytes(files[LOCK])
        lock = json.loads(files[LOCK])
    except (PeriodLockError, TypeError, ValueError):
        raise _fail("period_lock_invalid") from None
    weekly = _parse_json(files[WEEKLY], "weekly_contract_invalid")
    manifest = _parse_json(files[MANIFEST], "manifest_invalid")
    if not isinstance(lock, Mapping) or lock.get("lock_version") != "pert.weekly.period_lock.v1" or not isinstance(weekly, Mapping) or not isinstance(manifest, Mapping):
        raise _fail("artifact_contract_invalid")
    try:
        contract = parse_weekly_contract(weekly)
    except (WeeklyContractError, TypeError, ValueError):
        raise _fail("weekly_contract_invalid") from None
    start, as_of, end = contract.period_start, contract.as_of, contract.period_end_exclusive
    if lock_object.source_attempt < 1:
        raise _fail("period_mismatch")
    if lock_object.period_start != start or lock_object.as_of != as_of or lock_object.workflow_ref != WORKFLOW_REF or lock_object.producer_ref != contract.producer_ref:
        raise _fail("period_lock_mismatch")
    filtered = _filter_events(files[EVENTS], start, as_of)
    if filtered != files[EVENTS]:
        raise _fail("events_period_mismatch")
    _csv_rows(files[WATCHLIST], WATCHLIST_HEADER, "watchlist_csv_invalid")
    if lock_object.source_snapshot_digest != _snapshot_digest(files[EVENTS], files[WATCHLIST]):
        raise _fail("source_snapshot_mismatch")
    expected_manifest = _manifest(dict(lock), dict(weekly), files)
    if dict(manifest) != expected_manifest or serialize_weekly_artifact_manifest(dict(manifest)) != files[MANIFEST]:
        raise _fail("manifest_mismatch")
    return {name: files[name] for name in ARTIFACT_FILES}
