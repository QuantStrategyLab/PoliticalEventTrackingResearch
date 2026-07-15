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


def _status(value: object) -> dict[str, object]:
    required = {"feed_count", "successful_feed_count", "failed_feed_count"}
    optional = {"stale_feed_count", "missing_feed_count", "complete"}
    if not isinstance(value, Mapping) or not required.issubset(value) or set(value) - required - optional:
        raise _fail("feed_status_invalid")
    counts = {key: value.get(key, 0) for key in required | {"stale_feed_count", "missing_feed_count"}}
    if any(type(counts[key]) is not int or counts[key] < 0 for key in counts):
        raise _fail("feed_status_invalid")
    complete = value.get("complete", counts["failed_feed_count"] == 0 and counts["successful_feed_count"] == counts["feed_count"])
    if type(complete) is not bool:
        raise _fail("feed_status_invalid")
    if counts["feed_count"] <= 0 or counts["successful_feed_count"] != counts["feed_count"] or any(counts[key] for key in ("failed_feed_count", "stale_feed_count", "missing_feed_count")) or not complete:
        raise _fail("feed_status_incomplete")
    return {key: counts[key] for key in sorted(counts)} | {"complete": complete}


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
        "source_attempt": 1,
        "producer_ref": lock["producer_ref"],
        "source_snapshot_digest": lock["source_snapshot_digest"],
        "source_provenance": "official_rss_source_pipeline_v1",
        "feed_status": weekly["feed_status"],
        "source_inputs": [
            {"name": "source_events.csv", "length": lock["source_event_length"], "sha256": lock["source_event_sha256"]},
            {"name": WATCHLIST, "length": lock["source_watchlist_length"], "sha256": lock["source_watchlist_sha256"], "row_count": len(watch_rows) - 1},
        ],
        "files": [
            {"name": LOCK, "length": len(files[LOCK]), "sha256": _sha(files[LOCK]), "role": "period_lock"},
            {"name": EVENTS, "length": len(files[EVENTS]), "sha256": _sha(files[EVENTS]), "row_count": len(event_rows) - 1, "header": list(EVENT_HEADER), "role": "filtered_events"},
            {"name": WATCHLIST, "length": len(files[WATCHLIST]), "sha256": _sha(files[WATCHLIST]), "row_count": len(watch_rows) - 1, "header": list(WATCHLIST_HEADER), "role": "watchlist"},
            {"name": WEEKLY, "length": len(files[WEEKLY]), "sha256": _sha(files[WEEKLY]), "role": "weekly_contract"},
        ],
    }


def build_weekly_artifact(*, period_start: date, as_of: date, generated_at: datetime, workflow_ref: str, source_run_id: str, producer_ref: str, source_events: bytes, watchlist: bytes, feed_status: Mapping[str, object], run_mode: str) -> dict[str, bytes]:
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
    if type(source_run_id) is not str or not source_run_id.isdigit() or type(producer_ref) is not str or not _SHA.fullmatch(producer_ref):
        raise _fail("source_identity_invalid")
    filtered = _filter_events(source_events, period_start, as_of)
    _csv_rows(watchlist, WATCHLIST_HEADER, "watchlist_csv_invalid")
    status = _status(feed_status)
    source_digest = _snapshot_digest(source_events, watchlist)
    weekly: dict[str, object] = {
        "schema_version": "1", "contract_version": "political_event_weekly.v1", "cadence": "weekly",
        "period_start": period_start.isoformat(), "period_end_exclusive": end.isoformat(), "as_of": as_of.isoformat(),
        "generated_at": generated_at.isoformat(timespec="microseconds").replace("+00:00", "Z"), "run_mode": run_mode,
        "producer_ref": producer_ref, "source_provenance": "official_rss_source_pipeline_v1", "source_snapshot_digest": source_digest,
        "feed_status": status,
    }
    lock: dict[str, object] = {
        "lock_version": "pert.weekly.period_lock.v1", "calendar": "utc_iso_week_monday_sunday",
        "period_start": period_start.isoformat(), "period_end_exclusive": end.isoformat(), "as_of": as_of.isoformat(),
        "workflow_ref": workflow_ref, "source_run_id": source_run_id, "source_attempt": 1, "producer_ref": producer_ref,
        "source_snapshot_digest": source_digest, "source_provenance": "official_rss_source_pipeline_v1",
        "source_event_length": len(source_events), "source_event_sha256": _sha(source_events),
        "source_watchlist_length": len(watchlist), "source_watchlist_sha256": _sha(watchlist),
        "source_inputs": [{"name": "source_events.csv", "length": len(source_events), "sha256": _sha(source_events)}, {"name": WATCHLIST, "length": len(watchlist), "sha256": _sha(watchlist)}],
    }
    files: dict[str, bytes] = {LOCK: _json(lock, "period_lock_invalid"), EVENTS: filtered, WATCHLIST: watchlist, WEEKLY: _json(weekly, "weekly_contract_invalid")}
    files[MANIFEST] = _json(_manifest(lock, weekly, files), "manifest_invalid")
    return parse_weekly_artifact(files)


def parse_weekly_artifact(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or tuple(files) != ARTIFACT_FILES or any(type(files[name]) is not bytes for name in ARTIFACT_FILES):
        raise _fail("artifact_file_set_invalid")
    lock = _parse_json(files[LOCK], "period_lock_invalid")
    weekly = _parse_json(files[WEEKLY], "weekly_contract_invalid")
    manifest = _parse_json(files[MANIFEST], "manifest_invalid")
    if not isinstance(lock, Mapping) or lock.get("lock_version") != "pert.weekly.period_lock.v1" or not isinstance(weekly, Mapping) or weekly.get("contract_version") != "political_event_weekly.v1" or not isinstance(manifest, Mapping):
        raise _fail("artifact_contract_invalid")
    start = _date(weekly.get("period_start"), "period_invalid")
    as_of = _date(weekly.get("as_of"), "period_invalid")
    end = _date(weekly.get("period_end_exclusive"), "period_invalid")
    if start.weekday() != 0 or end != start + timedelta(days=7) or as_of != end - timedelta(days=1):
        raise _fail("period_mismatch")
    if lock.get("period_start") != weekly.get("period_start") or lock.get("as_of") != weekly.get("as_of") or lock.get("workflow_ref") != WORKFLOW_REF:
        raise _fail("period_lock_mismatch")
    filtered = _filter_events(files[EVENTS], start, as_of)
    if filtered != files[EVENTS]:
        raise _fail("events_period_mismatch")
    _csv_rows(files[WATCHLIST], WATCHLIST_HEADER, "watchlist_csv_invalid")
    if lock.get("source_snapshot_digest") != weekly.get("source_snapshot_digest"):
        raise _fail("source_snapshot_mismatch")
    expected_manifest = _manifest(dict(lock), dict(weekly), files)
    if dict(manifest) != expected_manifest:
        raise _fail("manifest_mismatch")
    return {name: files[name] for name in ARTIFACT_FILES}
