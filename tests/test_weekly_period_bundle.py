from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from political_event_tracking_research.weekly_period_bundle import (
    BUNDLE_VERSION,
    ArtifactEvidence,
    BundleContext,
    BundleWire,
    RerunContext,
    WeeklyBundleError,
    build_period_bundle,
    verify_bundle_collection,
    verify_period_bundle,
    verify_rerun_context,
)
from political_event_tracking_research.weekly_period_lock import (
    PoliticalEventWeeklyPeriodLockV1,
    SourceSnapshotArtifact,
    serialize_period_lock,
)


RUN_ID = "29420000001"
WORKFLOW_SHA = "a" * 40
PRODUCER_SHA = "b" * 40
ARTIFACT_DIGEST = "sha256:" + "c" * 64


def lock() -> PoliticalEventWeeklyPeriodLockV1:
    return PoliticalEventWeeklyPeriodLockV1(
        period_start=date(2026, 7, 6),
        period_end_exclusive=date(2026, 7, 13),
        as_of=date(2026, 7, 12),
        workflow_ref=(
            "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/"
            "source_event_pipeline.yml@refs/heads/main"
        ),
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


def snapshot() -> dict[str, object]:
    current = lock()
    return {
        "snapshot_version": "pert.weekly.input_snapshot.v1",
        "source_run_id": RUN_ID,
        "source_attempt": 1,
        "workflow_sha": WORKFLOW_SHA,
        "producer_sha": PRODUCER_SHA,
        "source_snapshot_id": current.source_snapshot_id,
        "source_snapshot_digest": current.source_snapshot_digest,
        "source_provenance": current.source_provenance,
        "source_artifacts": [
            {"path": item.path, "sha256": item.sha256, "row_count": item.row_count}
            for item in current.source_artifacts
        ],
    }


def context(**overrides: object) -> BundleContext:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "workflow_sha": WORKFLOW_SHA,
        "producer_sha": PRODUCER_SHA,
        "artifact": ArtifactEvidence(
            name=f"pert-weekly-period-lock-{RUN_ID}",
            artifact_id=8342569267,
            digest=ARTIFACT_DIGEST,
            retention_days=30,
        ),
        "period_lock": lock(),
    }
    values.update(overrides)
    return BundleContext(**values)


def test_bundle_round_trip_and_full_binding() -> None:
    bundle = build_period_bundle(context(), lock(), snapshot())
    assert bundle.bundle_version == BUNDLE_VERSION
    assert verify_period_bundle(bundle, context()) == bundle
    assert bundle.lock_sha256 == hashlib.sha256(bundle.lock_bytes).hexdigest()
    assert bundle.snapshot_sha256 == hashlib.sha256(bundle.snapshot_bytes).hexdigest()
    assert bundle.manifest_sha256 == hashlib.sha256(bundle.manifest_bytes).hexdigest()


@pytest.mark.parametrize("member", ["lock", "snapshot", "manifest"])
def test_tampered_member_bytes_fail_closed(member: str) -> None:
    bundle = build_period_bundle(context(), lock(), snapshot())
    values = {
        "lock_bytes": bundle.lock_bytes,
        "snapshot_bytes": bundle.snapshot_bytes,
        "manifest_bytes": bundle.manifest_bytes,
    }
    key = f"{member}_bytes"
    values[key] = values[key] + b" "
    tampered = BundleWire(**values)
    with pytest.raises(WeeklyBundleError, match="bundle_.*invalid|bundle_.*mismatch"):
        verify_period_bundle(tampered, context())


def test_replaced_canonical_lock_fails_even_if_manifest_is_rebuilt() -> None:
    original = build_period_bundle(context(), lock(), snapshot())
    changed_lock = PoliticalEventWeeklyPeriodLockV1(
        date(2026, 6, 29),
        date(2026, 7, 6),
        date(2026, 7, 5),
        lock().workflow_ref,
        RUN_ID,
        1,
        PRODUCER_SHA,
        lock().source_snapshot_id,
        lock().source_snapshot_digest,
        lock().source_provenance,
        lock().source_artifacts,
    )
    changed = build_period_bundle(context(period_lock=changed_lock), changed_lock, snapshot())
    forged = BundleWire(changed.lock_bytes, changed.snapshot_bytes, changed.manifest_bytes, changed.artifact)
    with pytest.raises(WeeklyBundleError, match="bundle_lock_mismatch"):
        verify_period_bundle(forged, context())
    assert original.lock_bytes != changed.lock_bytes


@pytest.mark.parametrize("field", ["run_id", "workflow_sha", "producer_sha", "artifact"])
def test_context_mismatch_fails_closed(field: str) -> None:
    bundle = build_period_bundle(context(), lock(), snapshot())
    values: dict[str, object] = {
        "run_id": "29420000002",
        "workflow_sha": "1" * 40,
        "producer_sha": "2" * 40,
        "artifact": ArtifactEvidence("pert-weekly-period-lock-29420000001", 8342569268, "sha256:" + "1" * 64, 30),
    }
    with pytest.raises(WeeklyBundleError, match="bundle_.*mismatch"):
        verify_period_bundle(bundle, context(**{field: values[field]}))


def test_same_run_attempt_two_context_is_explicit() -> None:
    bundle = build_period_bundle(context(), lock(), snapshot())
    assert verify_rerun_context(bundle, RerunContext(context(), current_run_attempt=2)) == bundle
    for attempt in (1, 3):
        with pytest.raises(WeeklyBundleError, match="bundle_rerun_attempt_invalid"):
            verify_rerun_context(bundle, RerunContext(context(), current_run_attempt=attempt))


def test_missing_or_multiple_bundle_collection_fails_closed() -> None:
    bundle = build_period_bundle(context(), lock(), snapshot())
    assert verify_bundle_collection((bundle,), context()) == bundle
    for values in ((), (bundle, bundle)):
        with pytest.raises(WeeklyBundleError, match="bundle_collection_shape_invalid"):
            verify_bundle_collection(values, context())


@pytest.mark.parametrize(
    "values",
    [
        ("wrong", 1, ARTIFACT_DIGEST, 30),
        (f"pert-weekly-period-lock-{RUN_ID}", True, ARTIFACT_DIGEST, 30),
        (f"pert-weekly-period-lock-{RUN_ID}", 1, "sha256:bad", 30),
        (f"pert-weekly-period-lock-{RUN_ID}", 1, ARTIFACT_DIGEST, 0),
    ],
)
def test_artifact_metadata_is_strict(values: tuple[object, ...]) -> None:
    with pytest.raises(WeeklyBundleError):
        BundleContext(RUN_ID, WORKFLOW_SHA, PRODUCER_SHA, ArtifactEvidence(*values), lock())


@pytest.mark.parametrize("mutation", ["unknown", "missing", "duplicate", "unsafe_int"])
def test_snapshot_wire_shape_is_strict(mutation: str) -> None:
    base = snapshot()
    if mutation == "unknown":
        base["debug"] = "leak"
    elif mutation == "missing":
        del base["workflow_sha"]
    elif mutation == "duplicate":
        wire = json.dumps(base, sort_keys=True, separators=(",", ":")).replace(
            '"workflow_sha":"' + WORKFLOW_SHA + '"',
            '"workflow_sha":"' + WORKFLOW_SHA + '","workflow_sha":"' + WORKFLOW_SHA + '"',
        ).encode()
        with pytest.raises(WeeklyBundleError, match="bundle_snapshot_invalid"):
            build_period_bundle(context(), lock(), wire)
        return
    else:
        base["source_snapshot_id"] = 2**53
    with pytest.raises(WeeklyBundleError, match="bundle_snapshot_invalid"):
        build_period_bundle(context(), lock(), base)


def test_unexpected_runtime_error_is_not_broad_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    import political_event_tracking_research.weekly_period_bundle as module

    def fail(*_: object, **__: object) -> bytes:
        raise RuntimeError("programming failure")

    monkeypatch.setattr(module.json, "dumps", fail)
    with pytest.raises(RuntimeError, match="programming failure"):
        build_period_bundle(context(), lock(), snapshot())
