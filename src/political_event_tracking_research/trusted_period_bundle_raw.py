"""Pure raw-byte period bundle binding for the future trusted harness.

Every operation reparses its bounded bytes and reconstructs plain mappings.
No Python object, dataclass, singleton, or registry carries authority here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping

from .trusted_workflow_identity_raw import (
    TRUSTED_REPOSITORY,
    TRUSTED_WORKFLOW_PATH,
    TRUSTED_WORKFLOW_REF,
    parse_trusted_workflow_identity_bytes,
)
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
MAX_BUNDLE_MEMBER_BYTES = 256 * 1024
MAX_SNAPSHOT_DEPTH = 16
MAX_SNAPSHOT_STRING_LENGTH = 4096
MAX_SOURCE_ARTIFACTS = 64
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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
_SNAPSHOT_ARTIFACT_KEYS = frozenset({"path", "sha256", "row_count"})
_ARTIFACT_KEYS = frozenset({"name", "artifact_id", "digest", "retention_days"})
_BUNDLE_KEYS = frozenset({"lock_bytes", "snapshot_bytes", "manifest_bytes", "artifact"})
_MANIFEST_KEYS = frozenset(
    {
        "bundle_version",
        "artifact_name",
        "artifact_id",
        "artifact_digest",
        "retention_days",
        "repository",
        "workflow_path",
        "workflow_ref",
        "reviewed_workflow_sha",
        "source_run_id",
        "source_attempt",
        "lock_version",
        "snapshot_version",
        "lock_sha256",
        "snapshot_sha256",
    }
)


class TrustedPeriodBundleError(ValueError):
    """Stable, sanitized bundle contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> TrustedPeriodBundleError:
    return TrustedPeriodBundleError(code)


def _safe_int(value: object, code: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_JSON_INTEGER:
        raise _error(code)
    return value


def _string(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise _error(code)
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Mapping[str, object], code: str) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error(code) from None
    if len(raw) > MAX_BUNDLE_MEMBER_BYTES:
        raise _error("bundle_snapshot_oversized")
    return raw


def _snapshot_tree(value: object, depth: int = 0) -> object:
    if depth > MAX_SNAPSHOT_DEPTH:
        raise _error("bundle_snapshot_depth_exceeded")
    if isinstance(value, Mapping):
        try:
            items = list(value.items())
        except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            raise _error("bundle_snapshot_invalid") from None
        if len(items) > 64:
            raise _error("bundle_snapshot_object_oversized")
        result: dict[str, object] = {}
        for key, item in items:
            if type(key) is not str or key in result:
                raise _error("bundle_snapshot_invalid")
            result[key] = _snapshot_tree(item, depth + 1)
        return result
    if type(value) is list:
        if len(value) > 256:
            raise _error("bundle_snapshot_list_oversized")
        return [_snapshot_tree(item, depth + 1) for item in value]
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        if len(value) > MAX_SNAPSHOT_STRING_LENGTH:
            raise _error("bundle_snapshot_string_oversized")
        return value
    if type(value) is int:
        return _safe_int(value, "bundle_snapshot_invalid")
    if type(value) is float and math.isfinite(value):
        return value
    raise _error("bundle_snapshot_invalid")


def _identity(raw: object) -> dict[str, str]:
    try:
        return parse_trusted_workflow_identity_bytes(raw)
    except ValueError as exc:
        if isinstance(exc, TrustedPeriodBundleError):
            raise
        raise _error("bundle_identity_invalid") from None


def _lock(raw: object) -> PoliticalEventWeeklyPeriodLockV1:
    if type(raw) is not bytes:
        raise _error("bundle_lock_invalid")
    if len(raw) > MAX_BUNDLE_MEMBER_BYTES:
        raise _error("bundle_lock_oversized")
    try:
        value = parse_period_lock_bytes(raw)
    except PeriodLockError:
        raise _error("bundle_lock_invalid") from None
    try:
        canonical = serialize_period_lock(value)
    except PeriodLockError:
        raise _error("bundle_lock_invalid") from None
    if canonical != raw:
        raise _error("bundle_lock_noncanonical")
    return value


def _snapshot(raw: object) -> dict[str, object]:
    if type(raw) is not bytes:
        raise _error("bundle_snapshot_invalid")
    if len(raw) > MAX_BUNDLE_MEMBER_BYTES:
        raise _error("bundle_snapshot_oversized")

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
    except TrustedPeriodBundleError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("bundle_snapshot_invalid") from None
    snapshot = _snapshot_tree(value)
    if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_KEYS:
        raise _error("bundle_snapshot_invalid")
    if snapshot["snapshot_version"] != SNAPSHOT_VERSION:
        raise _error("bundle_snapshot_version_invalid")
    _string(snapshot["source_run_id"], _RUN_ID_RE, "bundle_snapshot_run_invalid")
    if snapshot["source_attempt"] != 1:
        raise _error("bundle_snapshot_attempt_invalid")
    _string(snapshot["workflow_sha"], _SHA1_RE, "bundle_snapshot_workflow_invalid")
    _string(snapshot["producer_sha"], _SHA1_RE, "bundle_snapshot_producer_invalid")
    _string(snapshot["source_snapshot_id"], re.compile(r"^[a-z][a-z0-9_]*$"), "bundle_snapshot_id_invalid")
    _string(snapshot["source_snapshot_digest"], _SHA256_RE, "bundle_snapshot_digest_invalid")
    _string(snapshot["source_provenance"], re.compile(r"^[a-z][a-z0-9_]*$"), "bundle_snapshot_provenance_invalid")
    artifacts = snapshot["source_artifacts"]
    if type(artifacts) is not list or not artifacts or len(artifacts) > MAX_SOURCE_ARTIFACTS:
        raise _error("bundle_snapshot_artifacts_invalid")
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != _SNAPSHOT_ARTIFACT_KEYS:
            raise _error("bundle_snapshot_artifacts_invalid")
        try:
            SourceSnapshotArtifact(item["path"], item["sha256"], item["row_count"])
        except PeriodLockError:
            raise _error("bundle_snapshot_artifacts_invalid") from None
    if _canonical_json(snapshot, "bundle_snapshot_invalid") != raw:
        raise _error("bundle_snapshot_noncanonical")
    return snapshot


def _artifact(value: object, run_id: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _error("bundle_artifact_invalid")
    try:
        items = list(value.items())
    except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("bundle_artifact_invalid") from None
    if len(items) != len(_ARTIFACT_KEYS):
        raise _error("bundle_artifact_invalid")
    if any(type(key) is not str for key, _ in items):
        raise _error("bundle_artifact_invalid")
    try:
        result = dict(items)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("bundle_artifact_invalid") from None
    if set(result) != _ARTIFACT_KEYS:
        raise _error("bundle_artifact_invalid")
    _string(result["name"], re.compile(r"^pert-weekly-period-lock-[1-9][0-9]*$"), "bundle_artifact_invalid")
    if result["name"] != f"pert-weekly-period-lock-{run_id}":
        raise _error("bundle_artifact_name_mismatch")
    artifact_id = _safe_int(result["artifact_id"], "bundle_artifact_invalid")
    if artifact_id == 0:
        raise _error("bundle_artifact_invalid")
    _string(result["digest"], _ARTIFACT_DIGEST_RE, "bundle_artifact_invalid")
    if type(result["retention_days"]) is not int or not 1 <= result["retention_days"] <= 90:
        raise _error("bundle_retention_invalid")
    return result


def _expected_snapshot(lock: PoliticalEventWeeklyPeriodLockV1, workflow_sha: str) -> dict[str, object]:
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_run_id": lock.source_run_id,
        "source_attempt": 1,
        "workflow_sha": workflow_sha,
        "producer_sha": lock.producer_ref,
        "source_snapshot_id": lock.source_snapshot_id,
        "source_snapshot_digest": lock.source_snapshot_digest,
        "source_provenance": lock.source_provenance,
        "source_artifacts": [
            {"path": item.path, "sha256": item.sha256, "row_count": item.row_count}
            for item in lock.source_artifacts
        ],
    }


def _manifest(value: object) -> dict[str, object]:
    if type(value) is not bytes:
        raise _error("bundle_manifest_invalid")
    if len(value) > MAX_BUNDLE_MEMBER_BYTES:
        raise _error("bundle_manifest_oversized")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _error("bundle_manifest_duplicate_key")
            result[key] = item
        return result

    try:
        parsed = json.loads(value.decode("utf-8"), object_pairs_hook=pairs)
    except TrustedPeriodBundleError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("bundle_manifest_invalid") from None
    if not isinstance(parsed, dict) or set(parsed) != _MANIFEST_KEYS:
        raise _error("bundle_manifest_invalid")
    if parsed["bundle_version"] != BUNDLE_VERSION:
        raise _error("bundle_manifest_version_invalid")
    for field in (
        "artifact_name",
        "repository",
        "workflow_path",
        "workflow_ref",
        "reviewed_workflow_sha",
        "source_run_id",
        "lock_version",
        "snapshot_version",
        "lock_sha256",
        "snapshot_sha256",
        "artifact_digest",
    ):
        if type(parsed[field]) is not str:
            raise _error("bundle_manifest_invalid")
    _string(parsed["reviewed_workflow_sha"], _SHA1_RE, "bundle_manifest_invalid")
    _string(parsed["lock_sha256"], _SHA256_RE, "bundle_manifest_invalid")
    _string(parsed["snapshot_sha256"], _SHA256_RE, "bundle_manifest_invalid")
    _string(parsed["artifact_digest"], _ARTIFACT_DIGEST_RE, "bundle_manifest_invalid")
    if (
        parsed["repository"] != TRUSTED_REPOSITORY
        or parsed["workflow_path"] != TRUSTED_WORKFLOW_PATH
        or parsed["workflow_ref"] != TRUSTED_WORKFLOW_REF
    ):
        raise _error("bundle_workflow_identity_mismatch")
    _safe_int(parsed["artifact_id"], "bundle_manifest_invalid")
    if type(parsed["source_attempt"]) is not int or parsed["source_attempt"] != 1:
        raise _error("bundle_manifest_invalid")
    if type(parsed["retention_days"]) is not int or not 1 <= parsed["retention_days"] <= 90:
        raise _error("bundle_manifest_invalid")
    if _canonical_json(parsed, "bundle_manifest_invalid") != value:
        raise _error("bundle_manifest_noncanonical")
    return parsed


def _manifest_bytes(
    lock: PoliticalEventWeeklyPeriodLockV1,
    identity: dict[str, str],
    artifact: dict[str, object],
    lock_bytes: bytes,
    snapshot_bytes: bytes,
) -> bytes:
    return _canonical_json(
        {
            "bundle_version": BUNDLE_VERSION,
            "artifact_name": artifact["name"],
            "artifact_id": artifact["artifact_id"],
            "artifact_digest": artifact["digest"],
            "retention_days": artifact["retention_days"],
            "repository": identity["repository"],
            "workflow_path": identity["workflow_path"],
            "workflow_ref": identity["workflow_ref"],
            "reviewed_workflow_sha": identity["reviewed_workflow_sha"],
            "source_run_id": lock.source_run_id,
            "source_attempt": 1,
            "lock_version": LOCK_VERSION,
            "snapshot_version": SNAPSHOT_VERSION,
            "lock_sha256": _sha256(lock_bytes),
            "snapshot_sha256": _sha256(snapshot_bytes),
        },
        "bundle_manifest_invalid",
    )


def build_period_bundle(
    lock_bytes: object,
    snapshot_bytes: object,
    identity_bytes: object,
    artifact: object,
) -> dict[str, object]:
    """Validate raw inputs and build a plain bundle mapping."""

    lock = _lock(lock_bytes)
    identity = _identity(identity_bytes)
    if lock.workflow_ref != TRUSTED_WORKFLOW_REF:
        raise _error("bundle_workflow_identity_mismatch")
    expected_snapshot = _canonical_json(
        _expected_snapshot(lock, identity["reviewed_workflow_sha"]), "bundle_snapshot_invalid"
    )
    parsed_snapshot = _snapshot(snapshot_bytes)
    if snapshot_bytes != expected_snapshot or parsed_snapshot != json.loads(expected_snapshot):
        raise _error("bundle_snapshot_mismatch")
    evidence = _artifact(artifact, lock.source_run_id)
    manifest = _manifest_bytes(lock, identity, evidence, lock_bytes, snapshot_bytes)
    _manifest(manifest)
    return {
        "lock_bytes": lock_bytes,
        "snapshot_bytes": snapshot_bytes,
        "manifest_bytes": manifest,
        "artifact": dict(evidence),
    }


def verify_period_bundle(
    bundle: object,
    expected_lock_bytes: object,
    expected_snapshot_bytes: object,
    expected_identity_bytes: object,
    expected_artifact: object,
) -> dict[str, object]:
    """Revalidate all raw inputs and require complete expected equality."""

    if not isinstance(bundle, Mapping):
        raise _error("bundle_shape_invalid")
    try:
        items = list(bundle.items())
    except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("bundle_shape_invalid") from None
    if len(items) != len(_BUNDLE_KEYS) or any(type(key) is not str for key, _ in items):
        raise _error("bundle_shape_invalid")
    try:
        values = dict(items)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("bundle_shape_invalid") from None
    if set(values) != _BUNDLE_KEYS:
        raise _error("bundle_shape_invalid")
    # Parse the manifest first so structural errors are not masked by a later byte mismatch.
    manifest = _manifest(values["manifest_bytes"])
    expected_lock = _lock(expected_lock_bytes)
    expected_identity = _identity(expected_identity_bytes)
    expected_snapshot = _snapshot(expected_snapshot_bytes)
    expected_evidence = _artifact(expected_artifact, expected_lock.source_run_id)
    actual_lock = _lock(values["lock_bytes"])
    actual_snapshot = _snapshot(values["snapshot_bytes"])
    actual_evidence = _artifact(values["artifact"], actual_lock.source_run_id)
    if values["lock_bytes"] != expected_lock_bytes or actual_lock != expected_lock:
        raise _error("bundle_lock_mismatch")
    if values["snapshot_bytes"] != expected_snapshot_bytes or actual_snapshot != expected_snapshot:
        raise _error("bundle_snapshot_mismatch")
    if actual_evidence != expected_evidence:
        raise _error("bundle_artifact_mismatch")
    if actual_lock.workflow_ref != TRUSTED_WORKFLOW_REF:
        raise _error("bundle_workflow_identity_mismatch")
    expected_manifest = _manifest_bytes(
        expected_lock, expected_identity, expected_evidence, expected_lock_bytes, expected_snapshot_bytes
    )
    if values["manifest_bytes"] != expected_manifest:
        raise _error("bundle_manifest_mismatch")
    if manifest != json.loads(expected_manifest):
        raise _error("bundle_manifest_mismatch")
    return {
        "lock_bytes": values["lock_bytes"],
        "snapshot_bytes": values["snapshot_bytes"],
        "manifest_bytes": values["manifest_bytes"],
        "artifact": dict(actual_evidence),
    }
