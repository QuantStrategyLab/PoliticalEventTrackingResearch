"""Concrete five-file weekly artifact for the RSS producer."""

from __future__ import annotations

import csv
import hashlib
import io
import json
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

ARTIFACT_NAME: Final = "political-event-weekly-v1"
RETENTION_DAYS: Final = 30
MANIFEST_VERSION: Final = "political_event_weekly_artifact_manifest.v1"
PERIOD_LOCK_NAME: Final = "period_lock.json"
EVENTS_NAME: Final = "political_events.csv"
WATCHLIST_NAME: Final = "political_watchlist.csv"
WEEKLY_NAME: Final = "political_event_weekly.json"
MANIFEST_NAME: Final = "weekly_manifest.json"
ARTIFACT_FILES: Final = (PERIOD_LOCK_NAME, EVENTS_NAME, WATCHLIST_NAME, WEEKLY_NAME, MANIFEST_NAME)
EVENT_HEADER: Final = ("event_id", "event_date", "symbol", "event_type", "direction", "confidence", "source_url", "notes")
WATCHLIST_HEADER: Final = ("symbol", "name", "bucket", "research_status", "thesis", "source_url")


class WeeklyArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _invalid(code: str) -> WeeklyArtifactError:
    return WeeklyArtifactError(code)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _snapshot_digest(events: bytes, watchlist: bytes) -> str:
    digest = hashlib.sha256()
    for value in (events, watchlist):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _json_bytes(value: object, code: str) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _invalid(code) from None


def _parse_json(wire: bytes, code: str) -> object:
    if type(wire) is not bytes:
        raise _invalid(code)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _invalid(f"{code}_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except WeeklyArtifactError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _invalid(code) from None
    if _json_bytes(value, code) != wire:
        raise _invalid(f"{code}_noncanonical")
    return value


def _csv_snapshot(value: bytes, header: tuple[str, ...], code: str, *, allow_empty: bool = False) -> tuple[int, tuple[str, ...]]:
    if type(value) is not bytes:
        raise _invalid(code)
    try:
        rows = list(csv.reader(io.StringIO(value.decode("utf-8"), newline="")))
    except (UnicodeError, csv.Error, ValueError, RecursionError):
        raise _invalid(code) from None
    if not rows or tuple(rows[0]) != header:
        raise _invalid(f"{code}_header")
    if (not allow_empty and len(rows) < 2) or any(len(row) != len(header) for row in rows[1:]):
        raise _invalid(f"{code}_rows")
    return len(rows) - 1, header


def _filter_events(value: bytes, period_start: date, as_of: date) -> bytes:
    try:
        rows = list(csv.reader(io.StringIO(value.decode("utf-8"), newline="")))
    except (UnicodeError, csv.Error, ValueError, RecursionError):
        raise _invalid("events_csv_invalid") from None
    if not rows or tuple(rows[0]) != EVENT_HEADER:
        raise _invalid("events_csv_header")
    selected: list[list[str]] = []
    for row in rows[1:]:
        if len(row) != len(EVENT_HEADER):
            raise _invalid("events_csv_rows")
        try:
            event_date = date.fromisoformat(row[1])
        except (TypeError, ValueError):
            raise _invalid("events_date_invalid") from None
        if event_date.isoformat() != row[1]:
            raise _invalid("events_date_invalid")
        if period_start <= event_date <= as_of:
            selected.append(row)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(EVENT_HEADER)
    writer.writerows(selected)
    return output.getvalue().encode("utf-8")


def _status(value: object) -> WeeklyFeedStatus:
    if not isinstance(value, Mapping) or any(key not in value for key in ("feed_count", "successful_feed_count", "failed_feed_count", "complete")):
        raise _invalid("feed_status_invalid")
    try:
        return WeeklyFeedStatus(
            value["feed_count"], value["successful_feed_count"], value["failed_feed_count"],
            value.get("stale_feed_count", 0), value.get("missing_feed_count", 0), value["complete"],
        )
    except (WeeklyContractError, TypeError, ValueError):
        raise _invalid("feed_status_incomplete") from None


def _manifest(lock: PoliticalEventWeeklyPeriodLockV1, contract: WeeklySourceContract, files: Mapping[str, bytes]) -> dict[str, object]:
    event_count, event_header = _csv_snapshot(files[EVENTS_NAME], EVENT_HEADER, "events_csv_invalid", allow_empty=True)
    watch_count, watch_header = _csv_snapshot(files[WATCHLIST_NAME], WATCHLIST_HEADER, "watchlist_csv_invalid")
    return {
        "manifest_version": MANIFEST_VERSION,
        "artifact_name": ARTIFACT_NAME,
        "retention_days": RETENTION_DAYS,
        "schema_version": "1",
        "contract_version": "political_event_weekly.v1",
        "cadence": "weekly",
        "period_start": contract.period_start.isoformat(),
        "period_end_exclusive": contract.period_end_exclusive.isoformat(),
        "as_of": contract.as_of.isoformat(),
        "generated_at": contract.generated_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "workflow_ref": lock.workflow_ref,
        "producer_ref": lock.producer_ref,
        "source_run_id": lock.source_run_id,
        "source_attempt": lock.source_attempt,
        "source_snapshot_id": lock.source_snapshot_id,
        "source_snapshot_digest": lock.source_snapshot_digest,
        "source_provenance": lock.source_provenance,
        "feed_status": json.loads(serialize_weekly_contract(contract))["feed_status"],
        "files": [
            {"name": PERIOD_LOCK_NAME, "role": "period_lock", "length": len(files[PERIOD_LOCK_NAME]), "sha256": _sha256(files[PERIOD_LOCK_NAME]), "row_count": None, "header": None},
            {"name": EVENTS_NAME, "role": "source_events", "length": len(files[EVENTS_NAME]), "sha256": _sha256(files[EVENTS_NAME]), "row_count": event_count, "header": list(event_header)},
            {"name": WATCHLIST_NAME, "role": "source_watchlist", "length": len(files[WATCHLIST_NAME]), "sha256": _sha256(files[WATCHLIST_NAME]), "row_count": watch_count, "header": list(watch_header)},
            {"name": WEEKLY_NAME, "role": "weekly_contract", "length": len(files[WEEKLY_NAME]), "sha256": _sha256(files[WEEKLY_NAME]), "row_count": None, "header": None},
        ],
    }


def build_weekly_artifact(*, period_start: date, as_of: date, generated_at: datetime, workflow_ref: str, source_run_id: str, producer_ref: str, source_events: bytes, watchlist: bytes, feed_status: Mapping[str, object], source_provenance: str, run_mode: str) -> dict[str, bytes]:
    if type(period_start) is not date or type(as_of) is not date or period_start.weekday() != 0:
        raise _invalid("period_invalid")
    try:
        period_end = period_start + timedelta(days=7)
    except OverflowError:
        raise _invalid("period_invalid") from None
    if as_of != period_end - timedelta(days=1):
        raise _invalid("period_mismatch")
    if type(generated_at) is not datetime or generated_at.tzinfo != timezone.utc or generated_at < datetime.combine(period_end, datetime.min.time(), timezone.utc):
        raise _invalid("generated_at_invalid")
    if source_provenance != "official_rss_source_pipeline_v1" or run_mode not in {"scheduled", "manual"}:
        raise _invalid("producer_contract_invalid")
    raw_digest = _snapshot_digest(source_events, watchlist)
    period_events = _filter_events(source_events, period_start, as_of)
    event_count, _ = _csv_snapshot(period_events, EVENT_HEADER, "events_csv_invalid", allow_empty=True)
    watch_count, _ = _csv_snapshot(watchlist, WATCHLIST_HEADER, "watchlist_csv_invalid")
    status = _status(feed_status)
    snapshot_id = f"rss_source_snapshot_{as_of:%Y%m%d}_{source_run_id}"
    try:
        lock = PoliticalEventWeeklyPeriodLockV1(period_start, period_end, as_of, workflow_ref, source_run_id, 1, producer_ref, snapshot_id, raw_digest, source_provenance, (SourceSnapshotArtifact(EVENTS_NAME, _sha256(period_events), event_count), SourceSnapshotArtifact(WATCHLIST_NAME, _sha256(watchlist), watch_count)))
        contract = WeeklySourceContract(as_of, period_start, period_end, generated_at, run_mode, producer_ref, source_provenance, (WeeklySourceArtifact(EVENTS_NAME, _sha256(period_events), event_count), WeeklySourceArtifact(WATCHLIST_NAME, _sha256(watchlist), watch_count)), status)
        files: dict[str, bytes] = {PERIOD_LOCK_NAME: serialize_period_lock(lock), EVENTS_NAME: period_events, WATCHLIST_NAME: watchlist, WEEKLY_NAME: serialize_weekly_contract(contract)}
    except (PeriodLockError, WeeklyContractError, TypeError, ValueError, OverflowError):
        raise _invalid("weekly_artifact_invalid") from None
    files[MANIFEST_NAME] = _json_bytes(_manifest(lock, contract, files), "manifest_serialization_invalid")
    return parse_weekly_artifact(files)


def parse_weekly_artifact(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or set(files) != set(ARTIFACT_FILES) or any(type(files[name]) is not bytes for name in ARTIFACT_FILES):
        raise _invalid("artifact_file_set_invalid")
    try:
        lock = parse_period_lock_bytes(files[PERIOD_LOCK_NAME])
    except (PeriodLockError, TypeError, ValueError):
        raise _invalid("period_lock_invalid") from None
    weekly_value = _parse_json(files[WEEKLY_NAME], "weekly_wire_invalid")
    if not isinstance(weekly_value, Mapping):
        raise _invalid("weekly_shape_invalid")
    try:
        contract = parse_weekly_contract(weekly_value)
    except (WeeklyContractError, TypeError, ValueError):
        raise _invalid("weekly_contract_invalid") from None
    if serialize_weekly_contract(contract) != files[WEEKLY_NAME]:
        raise _invalid("weekly_noncanonical")
    expected_events = _filter_events(files[EVENTS_NAME], contract.period_start, contract.as_of)
    if expected_events != files[EVENTS_NAME]:
        raise _invalid("events_period_mismatch")
    event_count, _ = _csv_snapshot(files[EVENTS_NAME], EVENT_HEADER, "events_csv_invalid", allow_empty=True)
    watch_count, _ = _csv_snapshot(files[WATCHLIST_NAME], WATCHLIST_HEADER, "watchlist_csv_invalid")
    expected = ((EVENTS_NAME, _sha256(files[EVENTS_NAME]), event_count), (WATCHLIST_NAME, _sha256(files[WATCHLIST_NAME]), watch_count))
    if tuple((item.path, item.sha256, item.row_count) for item in lock.source_artifacts) != expected or tuple((item.path, item.sha256, item.row_count) for item in contract.source_artifacts) != expected:
        raise _invalid("source_artifact_mismatch")
    expected_id = f"rss_source_snapshot_{contract.as_of:%Y%m%d}_{lock.source_run_id}"
    if lock.source_snapshot_id != expected_id or lock.source_attempt != 1 or lock.period_start != contract.period_start or lock.period_end_exclusive != contract.period_end_exclusive or lock.as_of != contract.as_of or lock.producer_ref != contract.producer_ref or lock.source_provenance != contract.source_provenance:
        raise _invalid("period_contract_mismatch")
    manifest_value = _parse_json(files[MANIFEST_NAME], "manifest_wire_invalid")
    if not isinstance(manifest_value, Mapping) or manifest_value != _manifest(lock, contract, files):
        raise _invalid("manifest_mismatch")
    return {name: files[name] for name in ARTIFACT_FILES}
