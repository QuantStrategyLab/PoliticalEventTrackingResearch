"""Pure, exact-binding models for the trusted weekly bundle preflight.

This module has no filesystem, GitHub, or workflow access. Privileged
artifact acquisition is intentionally a later integration boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .weekly_period_lock import (
    LOCK_VERSION,
    MAX_SAFE_JSON_INTEGER,
    PeriodLockError,
    PoliticalEventWeeklyPeriodLockV1,
    SourceSnapshotArtifact,
    parse_period_lock_bytes,
    serialize_period_lock,
)

BUNDLE_VERSION = "pert.weekly.period_bundle.v1"
SNAPSHOT_VERSION = "pert.weekly.input_snapshot.v1"
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_NAME_RE = re.compile(r"^pert-weekly-period-lock-[1-9][0-9]*$")
_SNAPSHOT_KEYS = frozenset(
    {
        "snapshot_version",
        "source_run_id",
        "source_attempt",
        "workflow_sha",
        "producer_sha",
        "source_snapshot_id",
        "source_snapshot_digest",
        "source_provenance",
        "source_artifacts",
    }
)
_ARTIFACT_KEYS = frozenset({"path", "sha256", "row_count"})
_MANIFEST_KEYS = frozenset(
    {
        "bundle_version",
        "artifact_name",
        "source_run_id",
        "source_attempt",
        "workflow_sha",
        "producer_sha",
        "lock_version",
        "snapshot_version",
        "lock_sha256",
        "snapshot_sha256",
    }
)


class WeeklyBundleError(ValueError):
    """Stable, sanitized bundle contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> WeeklyBundleError:
    return WeeklyBundleError(code)


def _string(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise _error(code)
    return value


def _safe_int(value: object, code: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_JSON_INTEGER:
        raise _error(code)
    return value


def _snapshot_tree(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _error("bundle_snapshot_invalid")
            if key in result:
                raise _error("bundle_snapshot_duplicate_key")
            result[key] = _snapshot_tree(item)
        return result
    if type(value) is list:
        return [_snapshot_tree(item) for item in value]
    if value is None or type(value) is bool or type(value) is str:
        return value
    if type(value) is int:
        return _safe_int(value, "bundle_snapshot_invalid")
    if type(value) is float and math.isfinite(value):
        return value
    raise _error("bundle_snapshot_invalid")


def _canonical_json(value: object, code: str) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error(code) from None


def _validate_snapshot(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_KEYS:
        raise _error("bundle_snapshot_invalid")
    if value["snapshot_version"] != SNAPSHOT_VERSION:
        raise _error("bundle_snapshot_version_invalid")
    _string(value["source_run_id"], _RUN_ID_RE, "bundle_snapshot_run_invalid")
    if type(value["source_attempt"]) is not int or value["source_attempt"] != 1:
        raise _error("bundle_snapshot_attempt_invalid")
    _string(value["workflow_sha"], _SHA1_RE, "bundle_snapshot_workflow_invalid")
    _string(value["producer_sha"], _SHA1_RE, "bundle_snapshot_producer_invalid")
    _string(value["source_snapshot_id"], re.compile(r"^[a-z][a-z0-9_]*$"), "bundle_snapshot_id_invalid")
    _string(value["source_snapshot_digest"], re.compile(r"^[0-9a-f]{64}$"), "bundle_snapshot_digest_invalid")
    _string(value["source_provenance"], re.compile(r"^[a-z][a-z0-9_]*$"), "bundle_snapshot_provenance_invalid")
    artifacts = value["source_artifacts"]
    if type(artifacts) is not list or not artifacts:
        raise _error("bundle_snapshot_artifacts_invalid")
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != _ARTIFACT_KEYS:
            raise _error("bundle_snapshot_artifacts_invalid")
        try:
            SourceSnapshotArtifact(item["path"], item["sha256"], item["row_count"])
        except PeriodLockError:
            raise _error("bundle_snapshot_artifacts_invalid") from None
    return value


def _snapshot_bytes(value: Mapping[str, object]) -> bytes:
    try:
        tree = _snapshot_tree(value)
        return _canonical_json(_validate_snapshot(tree), "bundle_snapshot_invalid")
    except WeeklyBundleError:
        raise
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("bundle_snapshot_invalid") from None


def _parse_snapshot(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise _error("bundle_snapshot_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _error("bundle_snapshot_duplicate_key")
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise _error("bundle_snapshot_invalid")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
    except WeeklyBundleError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("bundle_snapshot_invalid") from None
    validated = _validate_snapshot(value)
    if _canonical_json(validated, "bundle_snapshot_invalid") != raw:
        raise _error("bundle_snapshot_noncanonical")
    return validated


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _expected_snapshot(lock: PoliticalEventWeeklyPeriodLockV1, workflow_sha: str) -> dict[str, object]:
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_run_id": lock.source_run_id,
        "source_attempt": lock.source_attempt,
        "workflow_sha": workflow_sha,
        "producer_sha": lock.producer_ref,
        "source_snapshot_id": lock.source_snapshot_id,
        "source_snapshot_digest": lock.source_snapshot_digest,
        "source_provenance": lock.source_provenance,
        "source_artifacts": [
            {"path": item.path, "sha256": item.sha256, "row_count": item.row_count} for item in lock.source_artifacts
        ],
    }


@dataclass(frozen=True, slots=True)
class ArtifactEvidence:
    name: str
    artifact_id: int
    digest: str
    retention_days: int

    def __post_init__(self) -> None:
        _string(self.name, _ARTIFACT_NAME_RE, "bundle_artifact_name_invalid")
        _safe_int(self.artifact_id, "bundle_artifact_id_invalid")
        if self.artifact_id == 0 or type(self.digest) is not str or not _ARTIFACT_DIGEST_RE.fullmatch(self.digest):
            raise _error("bundle_artifact_metadata_invalid")
        if type(self.retention_days) is not int or not 1 <= self.retention_days <= 90:
            raise _error("bundle_retention_invalid")


@dataclass(frozen=True, slots=True)
class BundleContext:
    run_id: str
    workflow_sha: str
    producer_sha: str
    artifact: ArtifactEvidence
    period_lock: PoliticalEventWeeklyPeriodLockV1

    def __post_init__(self) -> None:
        _string(self.run_id, _RUN_ID_RE, "bundle_run_invalid")
        _string(self.workflow_sha, _SHA1_RE, "bundle_workflow_invalid")
        _string(self.producer_sha, _SHA1_RE, "bundle_producer_invalid")
        if type(self.artifact) is not ArtifactEvidence:
            raise _error("bundle_artifact_invalid")
        if type(self.period_lock) is not PoliticalEventWeeklyPeriodLockV1:
            raise _error("bundle_lock_type_invalid")
        if self.period_lock.source_run_id != self.run_id or self.period_lock.source_attempt != 1:
            raise _error("bundle_lock_context_mismatch")
        if self.period_lock.producer_ref != self.producer_sha:
            raise _error("bundle_producer_mismatch")
        if self.artifact.name != f"pert-weekly-period-lock-{self.run_id}":
            raise _error("bundle_artifact_name_mismatch")


@dataclass(frozen=True, slots=True)
class RerunContext:
    original: BundleContext
    current_run_attempt: int

    def __post_init__(self) -> None:
        if type(self.current_run_attempt) is not int or self.current_run_attempt != 2:
            raise _error("bundle_rerun_attempt_invalid")


@dataclass(frozen=True, slots=True)
class BundleWire:
    lock_bytes: bytes
    snapshot_bytes: bytes
    manifest_bytes: bytes
    artifact: ArtifactEvidence | None = None

    @property
    def bundle_version(self) -> str:
        return BUNDLE_VERSION

    @property
    def lock_sha256(self) -> str:
        return _sha256(self.lock_bytes)

    @property
    def snapshot_sha256(self) -> str:
        return _sha256(self.snapshot_bytes)

    @property
    def manifest_sha256(self) -> str:
        return _sha256(self.manifest_bytes)


def _manifest_bytes(context: BundleContext, lock_bytes: bytes, snapshot_bytes: bytes) -> bytes:
    return _canonical_json(
        {
            "bundle_version": BUNDLE_VERSION,
            "artifact_name": context.artifact.name,
            "source_run_id": context.run_id,
            "source_attempt": 1,
            "workflow_sha": context.workflow_sha,
            "producer_sha": context.producer_sha,
            "lock_version": LOCK_VERSION,
            "snapshot_version": SNAPSHOT_VERSION,
            "lock_sha256": _sha256(lock_bytes),
            "snapshot_sha256": _sha256(snapshot_bytes),
        },
        "bundle_manifest_invalid",
    )


def build_period_bundle(
    context: BundleContext,
    period_lock: PoliticalEventWeeklyPeriodLockV1,
    snapshot: Mapping[str, object],
) -> BundleWire:
    if type(context) is not BundleContext or type(period_lock) is not PoliticalEventWeeklyPeriodLockV1:
        raise _error("bundle_input_invalid")
    if period_lock != context.period_lock:
        raise _error("bundle_lock_mismatch")
    try:
        lock_bytes = serialize_period_lock(period_lock)
    except PeriodLockError:
        raise _error("bundle_lock_invalid") from None
    snapshot_bytes = _snapshot_bytes(snapshot)
    expected_snapshot_bytes = _snapshot_bytes(_expected_snapshot(period_lock, context.workflow_sha))
    if snapshot_bytes != expected_snapshot_bytes:
        raise _error("bundle_snapshot_mismatch")
    return BundleWire(
        lock_bytes, snapshot_bytes, _manifest_bytes(context, lock_bytes, snapshot_bytes), context.artifact
    )


def verify_period_bundle(bundle: BundleWire, expected: BundleContext) -> BundleWire:
    if type(bundle) is not BundleWire or type(expected) is not BundleContext:
        raise _error("bundle_input_invalid")
    if bundle.artifact != expected.artifact:
        raise _error("bundle_artifact_mismatch")
    try:
        parsed_lock = parse_period_lock_bytes(bundle.lock_bytes)
    except PeriodLockError:
        raise _error("bundle_lock_invalid") from None
    if parsed_lock != expected.period_lock or serialize_period_lock(parsed_lock) != bundle.lock_bytes:
        raise _error("bundle_lock_mismatch")
    parsed_snapshot = _parse_snapshot(bundle.snapshot_bytes)
    expected_snapshot_bytes = _snapshot_bytes(_expected_snapshot(expected.period_lock, expected.workflow_sha))
    if (
        bundle.snapshot_bytes != expected_snapshot_bytes
        or _canonical_json(parsed_snapshot, "bundle_snapshot_invalid") != bundle.snapshot_bytes
    ):
        raise _error("bundle_snapshot_mismatch")
    expected_manifest = _manifest_bytes(expected, bundle.lock_bytes, bundle.snapshot_bytes)
    if bundle.manifest_bytes != expected_manifest:
        raise _error("bundle_manifest_mismatch")
    _parse_manifest(bundle.manifest_bytes)
    return bundle


def _parse_manifest(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise _error("bundle_manifest_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _error("bundle_manifest_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except WeeklyBundleError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("bundle_manifest_invalid") from None
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise _error("bundle_manifest_invalid")
    return value


def verify_rerun_context(bundle: BundleWire, rerun: RerunContext) -> BundleWire:
    if type(rerun) is not RerunContext:
        raise _error("bundle_rerun_context_invalid")
    return verify_period_bundle(bundle, rerun.original)


def verify_bundle_collection(bundles: tuple[BundleWire, ...], expected: BundleContext) -> BundleWire:
    if type(bundles) is not tuple or len(bundles) != 1:
        raise _error("bundle_collection_shape_invalid")
    return verify_period_bundle(bundles[0], expected)
