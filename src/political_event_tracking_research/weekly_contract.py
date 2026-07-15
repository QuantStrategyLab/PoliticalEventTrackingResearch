"""Pure producer-owned contract for complete official PERT weekly inputs."""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath

SCHEMA_VERSION = "1"
CONTRACT_VERSION = "political_event_weekly.v1"
CADENCE = "weekly"
MAX_SAFE_JSON_INTEGER = 2**53 - 1
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_PROVENANCE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_KEYS = frozenset({"schema_version", "contract_version", "cadence", "as_of", "period_start", "period_end_exclusive", "generated_at", "run_mode", "producer_ref", "source_provenance", "source_artifacts", "feed_status"})
_FEED_KEYS = frozenset({"feed_count", "successful_feed_count", "failed_feed_count", "stale_feed_count", "missing_feed_count", "complete"})
_ARTIFACT_KEYS = frozenset({"path", "sha256", "row_count"})


class WeeklyContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _invalid(code: str) -> WeeklyContractError:
    return WeeklyContractError(code)


def _safe_int(value: object, code: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_JSON_INTEGER:
        raise _invalid(code)
    return value


def _canonical_path(value: object) -> str:
    if type(value) is not str or not value or not value.isascii() or unicodedata.normalize("NFC", value) != value or not _PATH_RE.fullmatch(value):
        raise _invalid("source_artifact_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or value != str(path) or value.endswith("/") or "//" in value or any(part in {"", ".", ".."} for part in path.parts):
        raise _invalid("source_artifact_path_invalid")
    return value


@dataclass(frozen=True, slots=True)
class WeeklySourceArtifact:
    path: str
    sha256: str
    row_count: int

    def __post_init__(self) -> None:
        _canonical_path(self.path)
        if type(self.sha256) is not str or not _SHA256_RE.fullmatch(self.sha256):
            raise _invalid("source_artifact_invalid")
        _safe_int(self.row_count, "source_artifact_invalid")


@dataclass(frozen=True, slots=True)
class WeeklyFeedStatus:
    feed_count: int
    successful_feed_count: int
    failed_feed_count: int
    stale_feed_count: int
    missing_feed_count: int
    complete: bool

    def __post_init__(self) -> None:
        counts = (self.feed_count, self.successful_feed_count, self.failed_feed_count, self.stale_feed_count, self.missing_feed_count)
        for count in counts:
            _safe_int(count, "feed_status_invalid")
        if type(self.complete) is not bool:
            raise _invalid("feed_status_invalid")
        if self.feed_count <= 0 or self.successful_feed_count != self.feed_count or any((self.failed_feed_count, self.stale_feed_count, self.missing_feed_count)) or not self.complete:
            raise _invalid("feed_status_incomplete")


@dataclass(frozen=True, slots=True)
class WeeklySourceContract:
    as_of: date
    period_start: date
    period_end_exclusive: date
    generated_at: datetime
    run_mode: str
    producer_ref: str
    source_provenance: str
    source_artifacts: tuple[WeeklySourceArtifact, ...]
    feed_status: WeeklyFeedStatus

    def __post_init__(self) -> None:
        if type(self.as_of) is not date or type(self.period_start) is not date or type(self.period_end_exclusive) is not date or self.period_start.weekday() != 0 or self.period_end_exclusive != self.period_start + timedelta(days=7) or self.as_of != self.period_end_exclusive - timedelta(days=1):
            raise _invalid("period_invalid")
        if type(self.generated_at) is not datetime or self.generated_at.tzinfo != timezone.utc or self.generated_at < datetime.combine(self.period_end_exclusive, datetime.min.time(), timezone.utc):
            raise _invalid("generated_at_invalid")
        if self.run_mode not in {"scheduled", "manual"} or type(self.producer_ref) is not str or not _SHA1_RE.fullmatch(self.producer_ref) or type(self.source_provenance) is not str or not _PROVENANCE_RE.fullmatch(self.source_provenance):
            raise _invalid("provenance_invalid")
        if not isinstance(self.source_artifacts, tuple) or not self.source_artifacts or any(not isinstance(item, WeeklySourceArtifact) for item in self.source_artifacts):
            raise _invalid("source_artifact_invalid")
        ordered = tuple(sorted(self.source_artifacts, key=lambda item: item.path))
        if len({item.path for item in ordered}) != len(ordered):
            raise _invalid("source_artifact_duplicate")
        object.__setattr__(self, "source_artifacts", ordered)
        if not isinstance(self.feed_status, WeeklyFeedStatus):
            raise _invalid("feed_status_invalid")


def _date(value: object) -> date:
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        raise _invalid("date_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid("date_invalid") from None


def _generated_at(value: object) -> datetime:
    if type(value) is not str or not _TIMESTAMP_RE.fullmatch(value):
        raise _invalid("generated_at_invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise _invalid("generated_at_invalid") from None


def parse_weekly_contract(value: Mapping[str, object]) -> WeeklySourceContract:
    if not isinstance(value, Mapping) or set(value) != _KEYS:
        raise _invalid("contract_shape_invalid")
    if value["schema_version"] != SCHEMA_VERSION or value["contract_version"] != CONTRACT_VERSION or value["cadence"] != CADENCE:
        raise _invalid("contract_version_invalid")
    if type(value["run_mode"]) is not str or value["run_mode"] not in {"scheduled", "manual"}:
        raise _invalid("run_mode_invalid")
    source_artifacts = value["source_artifacts"]
    if not isinstance(source_artifacts, list) or not source_artifacts:
        raise _invalid("source_artifact_invalid")
    artifacts_list: list[WeeklySourceArtifact] = []
    for item in source_artifacts:
        if not isinstance(item, Mapping) or set(item) != _ARTIFACT_KEYS:
            raise _invalid("source_artifact_invalid")
        artifacts_list.append(WeeklySourceArtifact(item["path"], item["sha256"], item["row_count"]))
    artifacts = tuple(artifacts_list)
    status_value = value["feed_status"]
    if not isinstance(status_value, Mapping) or set(status_value) != _FEED_KEYS:
        raise _invalid("feed_status_invalid")
    status = WeeklyFeedStatus(status_value["feed_count"], status_value["successful_feed_count"], status_value["failed_feed_count"], status_value["stale_feed_count"], status_value["missing_feed_count"], status_value["complete"])
    return WeeklySourceContract(_date(value["as_of"]), _date(value["period_start"]), _date(value["period_end_exclusive"]), _generated_at(value["generated_at"]), value["run_mode"], value["producer_ref"], value["source_provenance"], artifacts, status)


def serialize_weekly_contract(contract: WeeklySourceContract) -> bytes:
    if not isinstance(contract, WeeklySourceContract):
        raise _invalid("contract_type_invalid")
    payload = {"schema_version": SCHEMA_VERSION, "contract_version": CONTRACT_VERSION, "cadence": CADENCE, "as_of": contract.as_of.isoformat(), "period_start": contract.period_start.isoformat(), "period_end_exclusive": contract.period_end_exclusive.isoformat(), "generated_at": contract.generated_at.isoformat(timespec="microseconds").replace("+00:00", "Z"), "run_mode": contract.run_mode, "producer_ref": contract.producer_ref, "source_provenance": contract.source_provenance, "source_artifacts": [{"path": item.path, "sha256": item.sha256, "row_count": item.row_count} for item in contract.source_artifacts], "feed_status": {"feed_count": contract.feed_status.feed_count, "successful_feed_count": contract.feed_status.successful_feed_count, "failed_feed_count": contract.feed_status.failed_feed_count, "stale_feed_count": contract.feed_status.stale_feed_count, "missing_feed_count": contract.feed_status.missing_feed_count, "complete": contract.feed_status.complete}}
    parse_weekly_contract(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
