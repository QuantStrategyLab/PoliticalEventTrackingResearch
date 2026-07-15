"""Concrete producer-owned weekly artifact contract for the PERT RSS pipeline."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Final

from .weekly_contract import (
    WeeklyFeedStatus,
    WeeklySourceArtifact,
    WeeklySourceContract,
    WeeklyContractError,
    parse_weekly_contract,
    serialize_weekly_contract,
)
from .weekly_period_lock import (
    PoliticalEventWeeklyPeriodLockV1,
    PeriodLockError,
    SourceSnapshotArtifact,
    parse_period_lock_bytes,
    serialize_period_lock,
)

ARTIFACT_NAME: Final = "political-event-weekly-v1"
RETENTION_DAYS: Final = 30
MANIFEST_VERSION: Final = "political_event_weekly_artifact_manifest.v1"
EVENTS_NAME: Final = "political_events.csv"
WATCHLIST_NAME: Final = "political_watchlist.csv"
PERIOD_LOCK_NAME: Final = "period_lock.json"
WEEKLY_NAME: Final = "political_event_weekly.json"
MANIFEST_NAME: Final = "weekly_manifest.json"
ARTIFACT_FILES: Final = (PERIOD_LOCK_NAME, EVENTS_NAME, WATCHLIST_NAME, WEEKLY_NAME, MANIFEST_NAME)
EVENT_HEADER: Final = ("event_id", "event_date", "symbol", "event_type", "direction", "confidence", "source_url", "notes")
WATCHLIST_HEADER: Final = ("symbol", "name", "bucket", "research_status", "thesis", "source_url")


class WeeklyArtifactError(ValueError):
    """Stable, sanitized producer artifact contract error."""

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


def _canonical_json(value: object, code: str) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _invalid(code) from None


def _parse_canonical_json(wire: bytes, code: str) -> object:
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
    if _canonical_json(value, code) != wire:
        raise _invalid(f"{code}_noncanonical")
    return value


def _csv_snapshot(value: object, expected_header: tuple[str, ...], code: str) -> tuple[int, tuple[str, ...]]:
    if type(value) is not bytes:
        raise _invalid(code)
    try:
        text = value.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except (UnicodeError, csv.Error, ValueError, RecursionError):
        raise _invalid(code) from None
    if not rows or tuple(rows[0]) != expected_header:
        raise _invalid(f"{code}_header")
    if len(rows) < 2 or any(len(row) != len(expected_header) for row in rows[1:]):
        raise _invalid(f"{code}_rows")
    return len(rows) - 1, expected_header


def _feed_status(value: object) -> WeeklyFeedStatus:
    if not isinstance(value, Mapping):
        raise _invalid("feed_status_invalid")
    required = ("feed_count", "successful_feed_count", "failed_feed_count")
    if any(key not in value for key in required):
        raise _invalid("feed_status_invalid")
    try:
        status = WeeklyFeedStatus(
            value["feed_count"],
            value["successful_feed_count"],
            value["failed_feed_count"],
            value.get("stale_feed_count", 0),
            value.get("missing_feed_count", 0),
            True,
        )
    except (WeeklyContractError, TypeError, ValueError):
        raise _invalid("feed_status_incomplete") from None
    return status


def _period_dates(period_start: object, as_of: object) -> tuple[date, date]:
    if type(period_start) is not date or type(as_of) is not date:
        raise _invalid("period_invalid")
    try:
        period_end = period_start + timedelta(days=7)
    except OverflowError:
        raise _invalid("period_invalid") from None
    if period_start.weekday() != 0 or as_of != period_end - timedelta(days=1):
        raise _invalid("period_mismatch")
    return period_start, period_end


def completed_week_period(today: date) -> tuple[date, date]:
    """Return the completed ISO week immediately before a scheduled Monday run."""
    if type(today) is not date or today.weekday() != 0:
        raise _invalid("scheduled_period_invalid")
    try:
        period_start = today - timedelta(days=7)
    except OverflowError:
        raise _invalid("scheduled_period_invalid") from None
    return period_start, period_start + timedelta(days=7)


def _timestamp(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo != timezone.utc:
        raise _invalid("generated_at_invalid")
    return value


def _contract_payload(contract: WeeklySourceContract) -> dict[str, object]:
    return json.loads(serialize_weekly_contract(contract))


def _file_metadata(name: str, value: bytes, *, role: str, row_count: int | None = None, header: tuple[str, ...] | None = None) -> dict[str, object]:
    return {
        "name": name,
        "role": role,
        "length": len(value),
        "sha256": _sha256(value),
        "row_count": row_count,
        "header": list(header) if header is not None else None,
    }


def _manifest_payload(lock: PoliticalEventWeeklyPeriodLockV1, contract: WeeklySourceContract, files: Mapping[str, bytes]) -> dict[str, object]:
    event_rows, event_header = _csv_snapshot(files[EVENTS_NAME], EVENT_HEADER, "events_csv_invalid")
    watch_rows, watch_header = _csv_snapshot(files[WATCHLIST_NAME], WATCHLIST_HEADER, "watchlist_csv_invalid")
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
        "feed_status": _contract_payload(contract)["feed_status"],
        "files": [
            _file_metadata(PERIOD_LOCK_NAME, files[PERIOD_LOCK_NAME], role="period_lock"),
            _file_metadata(EVENTS_NAME, files[EVENTS_NAME], role="source_events", row_count=event_rows, header=event_header),
            _file_metadata(WATCHLIST_NAME, files[WATCHLIST_NAME], role="source_watchlist", row_count=watch_rows, header=watch_header),
            _file_metadata(WEEKLY_NAME, files[WEEKLY_NAME], role="weekly_contract"),
        ],
    }


def build_weekly_artifact(
    *,
    period_start: date,
    as_of: date,
    generated_at: datetime,
    workflow_ref: str,
    source_run_id: str,
    producer_ref: str,
    source_events: bytes,
    watchlist: bytes,
    feed_status: Mapping[str, object],
    source_provenance: str,
    run_mode: str,
) -> dict[str, bytes]:
    period_start, period_end = _period_dates(period_start, as_of)
    generated_at = _timestamp(generated_at)
    if generated_at < datetime.combine(period_end, datetime.min.time(), timezone.utc):
        raise _invalid("generated_at_invalid")
    event_rows, _ = _csv_snapshot(source_events, EVENT_HEADER, "events_csv_invalid")
    watch_rows, _ = _csv_snapshot(watchlist, WATCHLIST_HEADER, "watchlist_csv_invalid")
    status = _feed_status(feed_status)
    if type(source_provenance) is not str or source_provenance != "official_rss_source_pipeline_v1":
        raise _invalid("source_provenance_invalid")
    if type(run_mode) is not str or run_mode not in {"scheduled", "manual"}:
        raise _invalid("run_mode_invalid")
    source_snapshot_digest = _snapshot_digest(source_events, watchlist)
    source_snapshot_id = f"rss_source_snapshot_{as_of:%Y%m%d}_{source_run_id}"
    try:
        lock = PoliticalEventWeeklyPeriodLockV1(
            period_start,
            period_end,
            as_of,
            workflow_ref,
            source_run_id,
            1,
            producer_ref,
            source_snapshot_id,
            source_snapshot_digest,
            source_provenance,
            (
                SourceSnapshotArtifact(EVENTS_NAME, _sha256(source_events), event_rows),
                SourceSnapshotArtifact(WATCHLIST_NAME, _sha256(watchlist), watch_rows),
            ),
        )
        contract = WeeklySourceContract(
            as_of,
            period_start,
            period_end,
            generated_at,
            run_mode,
            producer_ref,
            source_provenance,
            (
                WeeklySourceArtifact(EVENTS_NAME, _sha256(source_events), event_rows),
                WeeklySourceArtifact(WATCHLIST_NAME, _sha256(watchlist), watch_rows),
            ),
            status,
        )
        period_lock = serialize_period_lock(lock)
        weekly = serialize_weekly_contract(contract)
    except (PeriodLockError, WeeklyContractError, TypeError, ValueError, OverflowError):
        raise _invalid("weekly_artifact_invalid") from None
    files: dict[str, bytes] = {
        PERIOD_LOCK_NAME: period_lock,
        EVENTS_NAME: source_events,
        WATCHLIST_NAME: watchlist,
        WEEKLY_NAME: weekly,
    }
    files[MANIFEST_NAME] = _canonical_json(_manifest_payload(lock, contract, files), "manifest_serialization_invalid")
    return parse_weekly_artifact(files)


def parse_weekly_artifact(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or set(files) != set(ARTIFACT_FILES):
        raise _invalid("artifact_file_set_invalid")
    if any(type(files[name]) is not bytes for name in ARTIFACT_FILES):
        raise _invalid("artifact_member_invalid")
    try:
        lock = parse_period_lock_bytes(files[PERIOD_LOCK_NAME])
    except (PeriodLockError, TypeError, ValueError):
        raise _invalid("period_lock_invalid") from None
    weekly_payload = _parse_canonical_json(files[WEEKLY_NAME], "weekly_wire_invalid")
    if not isinstance(weekly_payload, Mapping):
        raise _invalid("weekly_shape_invalid")
    try:
        contract = parse_weekly_contract(weekly_payload)
    except (WeeklyContractError, TypeError, ValueError):
        raise _invalid("weekly_contract_invalid") from None
    if serialize_weekly_contract(contract) != files[WEEKLY_NAME]:
        raise _invalid("weekly_noncanonical")
    event_rows, _ = _csv_snapshot(files[EVENTS_NAME], EVENT_HEADER, "events_csv_invalid")
    watch_rows, _ = _csv_snapshot(files[WATCHLIST_NAME], WATCHLIST_HEADER, "watchlist_csv_invalid")
    if _snapshot_digest(files[EVENTS_NAME], files[WATCHLIST_NAME]) != lock.source_snapshot_digest:
        raise _invalid("source_snapshot_digest_mismatch")
    expected_artifacts = (
        (EVENTS_NAME, _sha256(files[EVENTS_NAME]), event_rows),
        (WATCHLIST_NAME, _sha256(files[WATCHLIST_NAME]), watch_rows),
    )
    actual_lock_artifacts = tuple((item.path, item.sha256, item.row_count) for item in lock.source_artifacts)
    actual_contract_artifacts = tuple((item.path, item.sha256, item.row_count) for item in contract.source_artifacts)
    if actual_lock_artifacts != expected_artifacts or actual_contract_artifacts != expected_artifacts:
        raise _invalid("source_artifact_mismatch")
    expected_snapshot_id = f"rss_source_snapshot_{contract.as_of:%Y%m%d}_{lock.source_run_id}"
    if (
        lock.period_start != contract.period_start
        or lock.period_end_exclusive != contract.period_end_exclusive
        or lock.as_of != contract.as_of
        or lock.producer_ref != contract.producer_ref
        or lock.source_provenance != contract.source_provenance
        or lock.source_snapshot_id != expected_snapshot_id
        or lock.source_snapshot_digest != _snapshot_digest(files[EVENTS_NAME], files[WATCHLIST_NAME])
        or lock.source_attempt != 1
    ):
        raise _invalid("period_contract_mismatch")
    manifest_payload = _parse_canonical_json(files[MANIFEST_NAME], "manifest_wire_invalid")
    if not isinstance(manifest_payload, Mapping):
        raise _invalid("manifest_shape_invalid")
    expected_manifest = _manifest_payload(lock, contract, files)
    if manifest_payload != expected_manifest or _canonical_json(manifest_payload, "manifest_wire_invalid") != files[MANIFEST_NAME]:
        raise _invalid("manifest_mismatch")
    return {name: files[name] for name in ARTIFACT_FILES}


def serialize_weekly_artifact(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Validate and return the exact fixed file set in canonical order."""
    return parse_weekly_artifact(files)
