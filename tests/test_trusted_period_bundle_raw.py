from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import pytest

from political_event_tracking_research.trusted_workflow_identity_raw import (
    TRUSTED_WORKFLOW_REF,
    build_trusted_workflow_identity_bytes,
)
from political_event_tracking_research.trusted_period_bundle_raw import (
    BUNDLE_VERSION,
    MAX_BUNDLE_MEMBER_BYTES,
    TrustedPeriodBundleError,
    build_period_bundle,
    verify_period_bundle,
)
from political_event_tracking_research.weekly_period_lock import (
    PoliticalEventWeeklyPeriodLockV1,
    SourceSnapshotArtifact,
    serialize_period_lock,
)


RUN_ID = "29430000001"
WORKFLOW_SHA = "a" * 40
PRODUCER_SHA = "b" * 40
ARTIFACT_DIGEST = "sha256:" + "c" * 64
IDENTITY_BYTES = build_trusted_workflow_identity_bytes(WORKFLOW_SHA)


def lock_bytes() -> bytes:
    lock = PoliticalEventWeeklyPeriodLockV1(
        period_start=date(2026, 7, 6),
        period_end_exclusive=date(2026, 7, 13),
        as_of=date(2026, 7, 12),
        workflow_ref=TRUSTED_WORKFLOW_REF,
        source_run_id=RUN_ID,
        source_attempt=1,
        producer_ref=PRODUCER_SHA,
        source_snapshot_id="pert_weekly_input_snapshot_20260712",
        source_snapshot_digest="d" * 64,
        source_provenance="official_political_event_tracking_research_v1",
        source_artifacts=(
            SourceSnapshotArtifact("data/live/source_events.csv", "e" * 64, 11),
            SourceSnapshotArtifact("data/live/source_manifest.json", "f" * 64, 1),
        ),
    )
    return serialize_period_lock(lock)


def snapshot_value() -> dict[str, object]:
    return {
        "snapshot_version": "pert.weekly.input_snapshot.v1",
        "source_run_id": RUN_ID,
        "source_attempt": 1,
        "workflow_sha": WORKFLOW_SHA,
        "producer_sha": PRODUCER_SHA,
        "source_snapshot_id": "pert_weekly_input_snapshot_20260712",
        "source_snapshot_digest": "d" * 64,
        "source_provenance": "official_political_event_tracking_research_v1",
        "source_artifacts": [
            {"path": "data/live/source_events.csv", "sha256": "e" * 64, "row_count": 11},
            {"path": "data/live/source_manifest.json", "sha256": "f" * 64, "row_count": 1},
        ],
    }


def snapshot_bytes() -> bytes:
    return json.dumps(snapshot_value(), sort_keys=True, separators=(",", ":")).encode()


def artifact() -> dict[str, object]:
    return {
        "name": f"pert-weekly-period-lock-{RUN_ID}",
        "artifact_id": 8342569270,
        "digest": ARTIFACT_DIGEST,
        "retention_days": 30,
    }


def bundle() -> dict[str, object]:
    return build_period_bundle(lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())


def test_build_verify_full_raw_binding() -> None:
    value = bundle()
    assert value["manifest_bytes"]
    assert verify_period_bundle(value, lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact()) == value
    manifest = json.loads(value["manifest_bytes"])
    assert manifest["bundle_version"] == BUNDLE_VERSION
    assert manifest["repository"] == "QuantStrategyLab/PoliticalEventTrackingResearch"


@pytest.mark.parametrize("member", ["lock_bytes", "snapshot_bytes"])
def test_expected_member_replacement_fails_closed(member: str) -> None:
    value = bundle()
    replacement = dict(value)
    replacement[member] = replacement[member] + b" "
    with pytest.raises(TrustedPeriodBundleError, match="bundle_.*mismatch|bundle_.*invalid|bundle_.*noncanonical"):
        verify_period_bundle(replacement, lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())


@pytest.mark.parametrize("mutation", ["unknown", "missing", "duplicate", "noncanonical"])
def test_manifest_is_structurally_validated_before_byte_binding(mutation: str) -> None:
    value = bundle()
    manifest = json.loads(value["manifest_bytes"])
    if mutation == "unknown":
        manifest["debug"] = "unexpected"
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "missing":
        del manifest["repository"]
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "duplicate":
        raw = value["manifest_bytes"].replace(
            b'"repository":"QuantStrategyLab/PoliticalEventTrackingResearch"',
            b'"repository":"QuantStrategyLab/PoliticalEventTrackingResearch",'
            b'"repository":"QuantStrategyLab/PoliticalEventTrackingResearch"',
        )
    else:
        raw = json.dumps(manifest).encode()
    value["manifest_bytes"] = raw
    with pytest.raises(TrustedPeriodBundleError, match="bundle_manifest_"):
        verify_period_bundle(value, lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())


def test_manifest_identity_fields_are_validated_before_reconstructed_equality() -> None:
    value = bundle()
    manifest = json.loads(value["manifest_bytes"])
    manifest["workflow_ref"] = "QuantStrategyLab/Other/workflow.yml@refs/heads/main"
    value["manifest_bytes"] = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(TrustedPeriodBundleError, match="bundle_workflow_identity_mismatch"):
        verify_period_bundle(value, lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())


@pytest.mark.parametrize("field", ["artifact", "identity", "lock_expected", "snapshot_expected"])
def test_context_tamper_fails_closed(field: str) -> None:
    value = bundle()
    expected_artifact = artifact()
    expected_identity = IDENTITY_BYTES
    expected_lock = lock_bytes()
    expected_snapshot = snapshot_bytes()
    if field == "artifact":
        expected_artifact = {**expected_artifact, "artifact_id": 8342569271}
    elif field == "identity":
        expected_identity = build_trusted_workflow_identity_bytes("d" * 40)
    elif field == "lock_expected":
        expected_lock = expected_lock + b" "
    else:
        expected_snapshot = expected_snapshot + b" "
    with pytest.raises(TrustedPeriodBundleError):
        verify_period_bundle(value, expected_lock, expected_snapshot, expected_identity, expected_artifact)


@pytest.mark.parametrize("raw", [b"x" * (MAX_BUNDLE_MEMBER_BYTES + 1), None, "raw"])
def test_member_bounds_and_types_are_sanitized(raw: object) -> None:
    value = bundle()
    value["snapshot_bytes"] = raw
    with pytest.raises(TrustedPeriodBundleError, match="bundle_snapshot_"):
        verify_period_bundle(value, lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())


@dataclass
class ForgedBundle:
    lock_bytes: bytes
    snapshot_bytes: bytes
    manifest_bytes: bytes
    artifact: dict[str, object]


def test_forged_bundle_object_and_mapping_errors_are_sanitized() -> None:
    value = bundle()
    with pytest.raises(TrustedPeriodBundleError, match="bundle_shape_invalid"):
        verify_period_bundle(ForgedBundle(**value), lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())

    class BrokenMapping(dict[str, object]):
        def items(self):  # type: ignore[no-untyped-def]
            raise AttributeError("untrusted attribute")

    with pytest.raises(TrustedPeriodBundleError, match="bundle_shape_invalid"):
        verify_period_bundle(BrokenMapping(value), lock_bytes(), snapshot_bytes(), IDENTITY_BYTES, artifact())
