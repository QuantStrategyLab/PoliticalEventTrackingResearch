"""Pure immutable period/input lock for retry-safe weekly production."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath

LOCK_VERSION = "pert.weekly.period_lock.v1"
CALENDAR = "utc_iso_week_monday_sunday"
MAX_SAFE_JSON_INTEGER = 2**53 - 1

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_WORKFLOW_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@-]*$")
_LOCK_KEYS = frozenset(
    {
        "lock_version",
        "calendar",
        "period_start",
        "period_end_exclusive",
        "as_of",
        "workflow_ref",
        "source_run_id",
        "source_attempt",
        "producer_ref",
        "source_snapshot_id",
        "source_snapshot_digest",
        "source_provenance",
        "source_artifacts",
    }
)
_ARTIFACT_KEYS = frozenset({"path", "sha256", "row_count"})


class PeriodLockError(ValueError):
    """Stable, sanitized period-lock contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _invalid(code: str) -> PeriodLockError:
    return PeriodLockError(code)


def _date(value: object) -> date:
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        raise _invalid("period_date_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid("period_date_invalid") from None


def _safe_int(value: object, code: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_JSON_INTEGER:
        raise _invalid(code)
    return value


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or not value.isascii() or unicodedata.normalize("NFC", value) != value or not _IDENTIFIER_RE.fullmatch(value):
        raise _invalid(code)
    return value


def _path(value: object) -> str:
    if type(value) is not str or not value.isascii() or unicodedata.normalize("NFC", value) != value or not _PATH_RE.fullmatch(value):
        raise _invalid("source_snapshot_path_invalid")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or value != str(parsed) or value.endswith("/") or "//" in value or any(part in {"", ".", ".."} for part in parsed.parts):
        raise _invalid("source_snapshot_path_invalid")
    return value


def _workflow_ref(value: object) -> str:
    if type(value) is not str or not value.isascii() or unicodedata.normalize("NFC", value) != value or not _WORKFLOW_REF_RE.fullmatch(value):
        raise _invalid("workflow_ref_invalid")
    return value


@dataclass(frozen=True, slots=True)
class SourceSnapshotArtifact:
    path: str
    sha256: str
    row_count: int

    def __post_init__(self) -> None:
        _path(self.path)
        if type(self.sha256) is not str or not _SHA256_RE.fullmatch(self.sha256):
            raise _invalid("source_snapshot_artifact_invalid")
        _safe_int(self.row_count, "source_snapshot_artifact_invalid")


@dataclass(frozen=True, slots=True)
class PoliticalEventWeeklyPeriodLockV1:
    period_start: date
    period_end_exclusive: date
    as_of: date
    workflow_ref: str
    source_run_id: str
    source_attempt: int
    producer_ref: str
    source_snapshot_id: str
    source_snapshot_digest: str
    source_provenance: str
    source_artifacts: tuple[SourceSnapshotArtifact, ...]

    def __post_init__(self) -> None:
        if type(self.period_start) is not date or type(self.period_end_exclusive) is not date or type(self.as_of) is not date:
            raise _invalid("period_date_invalid")
        try:
            expected_end = self.period_start + timedelta(days=7)
        except OverflowError:
            raise _invalid("period_boundary_invalid") from None
        if self.period_start.weekday() != 0 or self.period_end_exclusive != expected_end or self.as_of != expected_end - timedelta(days=1):
            raise _invalid("period_mismatch")
        _workflow_ref(self.workflow_ref)
        if type(self.source_run_id) is not str or not _RUN_ID_RE.fullmatch(self.source_run_id):
            raise _invalid("source_run_id_invalid")
        if type(self.source_attempt) is not int or not 1 <= self.source_attempt <= MAX_SAFE_JSON_INTEGER:
            raise _invalid("source_attempt_invalid")
        if type(self.producer_ref) is not str or not _SHA1_RE.fullmatch(self.producer_ref):
            raise _invalid("producer_ref_invalid")
        _identifier(self.source_snapshot_id, "source_snapshot_id_invalid")
        if type(self.source_snapshot_digest) is not str or not _SHA256_RE.fullmatch(self.source_snapshot_digest):
            raise _invalid("source_snapshot_digest_invalid")
        _identifier(self.source_provenance, "source_provenance_invalid")
        if not isinstance(self.source_artifacts, tuple) or not self.source_artifacts or any(
            not isinstance(item, SourceSnapshotArtifact) for item in self.source_artifacts
        ):
            raise _invalid("source_snapshot_artifact_invalid")
        ordered = tuple(sorted(self.source_artifacts, key=lambda item: item.path))
        if len({item.path for item in ordered}) != len(ordered):
            raise _invalid("source_snapshot_duplicate")
        object.__setattr__(self, "source_artifacts", ordered)


def parse_period_lock(value: Mapping[str, object]) -> PoliticalEventWeeklyPeriodLockV1:
    if not isinstance(value, Mapping) or set(value) != _LOCK_KEYS:
        raise _invalid("period_lock_shape_invalid")
    if value["lock_version"] != LOCK_VERSION or value["calendar"] != CALENDAR:
        raise _invalid("period_lock_version_invalid")
    artifacts_value = value["source_artifacts"]
    if not isinstance(artifacts_value, list) or not artifacts_value:
        raise _invalid("source_snapshot_artifact_invalid")
    artifacts: list[SourceSnapshotArtifact] = []
    for item in artifacts_value:
        if not isinstance(item, Mapping) or set(item) != _ARTIFACT_KEYS:
            raise _invalid("source_snapshot_artifact_invalid")
        artifacts.append(SourceSnapshotArtifact(item["path"], item["sha256"], item["row_count"]))
    return PoliticalEventWeeklyPeriodLockV1(
        _date(value["period_start"]),
        _date(value["period_end_exclusive"]),
        _date(value["as_of"]),
        _workflow_ref(value["workflow_ref"]),
        value["source_run_id"],
        _safe_int(value["source_attempt"], "source_attempt_invalid"),
        value["producer_ref"],
        value["source_snapshot_id"],
        value["source_snapshot_digest"],
        value["source_provenance"],
        tuple(artifacts),
    )


def _payload(lock: PoliticalEventWeeklyPeriodLockV1) -> dict[str, object]:
    if not isinstance(lock, PoliticalEventWeeklyPeriodLockV1):
        raise _invalid("period_lock_type_invalid")
    payload: dict[str, object] = {
        "lock_version": LOCK_VERSION,
        "calendar": CALENDAR,
        "period_start": lock.period_start.isoformat(),
        "period_end_exclusive": lock.period_end_exclusive.isoformat(),
        "as_of": lock.as_of.isoformat(),
        "workflow_ref": lock.workflow_ref,
        "source_run_id": lock.source_run_id,
        "source_attempt": lock.source_attempt,
        "producer_ref": lock.producer_ref,
        "source_snapshot_id": lock.source_snapshot_id,
        "source_snapshot_digest": lock.source_snapshot_digest,
        "source_provenance": lock.source_provenance,
        "source_artifacts": [
            {"path": item.path, "sha256": item.sha256, "row_count": item.row_count} for item in lock.source_artifacts
        ],
    }
    parse_period_lock(payload)
    return payload


def serialize_period_lock(lock: PoliticalEventWeeklyPeriodLockV1) -> bytes:
    try:
        return json.dumps(_payload(lock), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _invalid("period_lock_serialization_invalid") from None


def parse_period_lock_bytes(wire: bytes) -> PoliticalEventWeeklyPeriodLockV1:
    if type(wire) is not bytes:
        raise _invalid("period_lock_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _invalid("period_lock_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except PeriodLockError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _invalid("period_lock_wire_invalid") from None
    lock = parse_period_lock(value)
    if serialize_period_lock(lock) != wire:
        raise _invalid("period_lock_noncanonical")
    return lock


def assert_expected_period_lock(actual: PoliticalEventWeeklyPeriodLockV1, expected: PoliticalEventWeeklyPeriodLockV1) -> None:
    if not isinstance(actual, PoliticalEventWeeklyPeriodLockV1) or not isinstance(expected, PoliticalEventWeeklyPeriodLockV1):
        raise _invalid("period_lock_expected_invalid")
    if actual != expected:
        raise _invalid("period_lock_mismatch")
