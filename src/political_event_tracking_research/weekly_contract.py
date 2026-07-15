"""Pure producer-owned contract for complete official PERT weekly inputs."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath

SCHEMA_VERSION = "1"
CONTRACT_VERSION = "political_event_weekly.v1"
CADENCE = "weekly"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_KEYS = frozenset({
    "schema_version", "contract_version", "cadence", "as_of", "period_start", "period_end_exclusive",
    "generated_at", "run_mode", "producer_ref", "source_provenance", "source_artifacts", "feed_status",
})
_FEED_KEYS = frozenset({"feed_count", "successful_feed_count", "failed_feed_count", "stale_feed_count", "missing_feed_count", "complete"})
_ARTIFACT_KEYS = frozenset({"path", "sha256", "row_count"})


class WeeklyContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class WeeklySourceArtifact:
    path: str
    sha256: str
    row_count: int


@dataclass(frozen=True, slots=True)
class WeeklyFeedStatus:
    feed_count: int
    successful_feed_count: int
    failed_feed_count: int
    stale_feed_count: int
    missing_feed_count: int


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


def _invalid(code: str) -> WeeklyContractError:
    return WeeklyContractError(code)


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
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise _invalid("generated_at_invalid") from None
    if parsed.tzinfo != timezone.utc:
        raise _invalid("generated_at_invalid")
    return parsed


def _artifact(value: object) -> WeeklySourceArtifact:
    if not isinstance(value, Mapping) or set(value) != _ARTIFACT_KEYS:
        raise _invalid("source_artifact_invalid")
    path = value["path"]
    if type(path) is not str or not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
        raise _invalid("source_artifact_invalid")
    digest = value["sha256"]
    row_count = value["row_count"]
    if type(digest) is not str or not _SHA256_RE.fullmatch(digest) or type(row_count) is not int or row_count < 0:
        raise _invalid("source_artifact_invalid")
    return WeeklySourceArtifact(path, digest, row_count)


def _feed_status(value: object) -> WeeklyFeedStatus:
    if not isinstance(value, Mapping) or set(value) != _FEED_KEYS or value.get("complete") is not True:
        raise _invalid("feed_status_invalid")
    values = [value[key] for key in _FEED_KEYS if key != "complete"]
    if any(type(item) is not int or item < 0 for item in values):
        raise _invalid("feed_status_invalid")
    status = WeeklyFeedStatus(*(value[key] for key in ("feed_count", "successful_feed_count", "failed_feed_count", "stale_feed_count", "missing_feed_count")))
    if status.feed_count <= 0 or status.successful_feed_count != status.feed_count or any((status.failed_feed_count, status.stale_feed_count, status.missing_feed_count)):
        raise _invalid("feed_status_incomplete")
    return status


def parse_weekly_contract(value: Mapping[str, object]) -> WeeklySourceContract:
    if not isinstance(value, Mapping) or set(value) != _KEYS:
        raise _invalid("contract_shape_invalid")
    if value["schema_version"] != SCHEMA_VERSION or value["contract_version"] != CONTRACT_VERSION or value["cadence"] != CADENCE:
        raise _invalid("contract_version_invalid")
    if type(value["run_mode"]) is not str or value["run_mode"] not in {"scheduled", "manual"}:
        raise _invalid("run_mode_invalid")
    producer_ref = value["producer_ref"]
    provenance = value["source_provenance"]
    if type(producer_ref) is not str or not _SHA1_RE.fullmatch(producer_ref) or type(provenance) is not str or not provenance:
        raise _invalid("provenance_invalid")
    as_of = _date(value["as_of"])
    start = _date(value["period_start"])
    end = _date(value["period_end_exclusive"])
    if start.weekday() != 0 or end != start + timedelta(days=7) or as_of != end - timedelta(days=1):
        raise _invalid("period_invalid")
    generated_at = _generated_at(value["generated_at"])
    if generated_at < datetime.combine(end, datetime.min.time(), timezone.utc):
        raise _invalid("generated_at_before_period_end")
    artifacts_value = value["source_artifacts"]
    if not isinstance(artifacts_value, list) or not artifacts_value:
        raise _invalid("source_artifact_invalid")
    artifacts = tuple(sorted((_artifact(item) for item in artifacts_value), key=lambda item: item.path))
    if len({item.path for item in artifacts}) != len(artifacts):
        raise _invalid("source_artifact_duplicate")
    return WeeklySourceContract(as_of, start, end, generated_at, value["run_mode"], producer_ref, provenance, artifacts, _feed_status(value["feed_status"]))


def serialize_weekly_contract(contract: WeeklySourceContract) -> bytes:
    if not isinstance(contract, WeeklySourceContract):
        raise _invalid("contract_type_invalid")
    try:
        payload = {
            "schema_version": SCHEMA_VERSION, "contract_version": CONTRACT_VERSION, "cadence": CADENCE,
            "as_of": contract.as_of.isoformat(), "period_start": contract.period_start.isoformat(),
            "period_end_exclusive": contract.period_end_exclusive.isoformat(),
            "generated_at": contract.generated_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "run_mode": contract.run_mode, "producer_ref": contract.producer_ref, "source_provenance": contract.source_provenance,
            "source_artifacts": [{"path": item.path, "sha256": item.sha256, "row_count": item.row_count} for item in contract.source_artifacts],
            "feed_status": {"feed_count": contract.feed_status.feed_count, "successful_feed_count": contract.feed_status.successful_feed_count, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True},
        }
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise _invalid("contract_invalid") from None
    parse_weekly_contract(payload)
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, UnicodeError, ValueError):
        raise _invalid("serialization_invalid") from None
