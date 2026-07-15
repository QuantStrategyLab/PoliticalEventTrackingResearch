from __future__ import annotations

import json
from datetime import date

import pytest

from political_event_tracking_research.weekly_period_lock import (
    LOCK_VERSION,
    PeriodLockError,
    SourceSnapshotArtifact,
    PoliticalEventWeeklyPeriodLockV1,
    assert_expected_period_lock,
    parse_period_lock,
    parse_period_lock_bytes,
    serialize_period_lock,
)


def artifact_payload(path: str = "data/live/source_events.csv") -> dict[str, object]:
    return {"path": path, "sha256": "b" * 64, "row_count": 11}


def payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "lock_version": LOCK_VERSION,
        "calendar": "utc_iso_week_monday_sunday",
        "period_start": "2026-07-06",
        "period_end_exclusive": "2026-07-13",
        "as_of": "2026-07-12",
        "workflow_ref": "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main",
        "source_run_id": "29396791050",
        "source_attempt": 1,
        "producer_ref": "a" * 40,
        "source_snapshot_id": "rss_source_snapshot_20260712",
        "source_snapshot_digest": "c" * 64,
        "source_provenance": "official_political_event_tracking_research_v1",
        "source_artifacts": [artifact_payload()],
    }
    value.update(overrides)
    return value


def test_valid_lock_is_canonical_and_round_trips() -> None:
    lock = parse_period_lock(payload())
    wire = serialize_period_lock(lock)
    assert parse_period_lock_bytes(wire) == lock
    assert json.loads(wire) == payload()


def test_source_artifacts_are_sorted_and_permutation_stable() -> None:
    items = [artifact_payload("z.csv"), artifact_payload("a.csv")]
    first = parse_period_lock(payload(source_artifacts=items))
    second = parse_period_lock(payload(source_artifacts=list(reversed(items))))
    assert first == second
    assert serialize_period_lock(first) == serialize_period_lock(second)
    assert [item.path for item in first.source_artifacts] == ["a.csv", "z.csv"]


def test_direct_value_object_canonicalizes_artifacts() -> None:
    first = SourceSnapshotArtifact("z.csv", "a" * 64, 2)
    second = SourceSnapshotArtifact("a.csv", "b" * 64, 1)
    lock = PoliticalEventWeeklyPeriodLockV1(
        date(2026, 7, 6),
        date(2026, 7, 13),
        date(2026, 7, 12),
        "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main",
        "29396791050",
        1,
        "a" * 40,
        "rss_source_snapshot_20260712",
        "c" * 64,
        "official_political_event_tracking_research_v1",
        (first, second),
    )
    assert [item.path for item in lock.source_artifacts] == ["a.csv", "z.csv"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("period_end_exclusive", "2026-07-14"),
        ("as_of", "2026-07-11"),
        ("calendar", "utc_calendar_day"),
        ("source_snapshot_digest", "not-a-digest"),
        ("producer_ref", "A" * 40),
    ],
)
def test_period_identity_and_original_attempt_are_strict(field: str, value: object) -> None:
    with pytest.raises(PeriodLockError):
        parse_period_lock(payload(**{field: value}))


@pytest.mark.parametrize("value", [-1, 2**53, True, "1"])
def test_source_attempt_rejects_unsafe_integer_shapes(value: object) -> None:
    with pytest.raises(PeriodLockError):
        parse_period_lock(payload(source_attempt=value))


@pytest.mark.parametrize("value", [1, 2, 3, 2**53 - 1])
def test_source_attempt_accepts_safe_positive_integer(value: int) -> None:
    assert parse_period_lock(payload(source_attempt=value)).source_attempt == value


@pytest.mark.parametrize("path", ["", "/data/a.csv", "./a.csv", "a/../b.csv", "a//b.csv", "a\\b.csv", "é.csv", "a\n.csv"])
def test_source_artifact_paths_are_canonical_safe_posix(path: str) -> None:
    with pytest.raises(PeriodLockError):
        parse_period_lock(payload(source_artifacts=[artifact_payload(path)]))


def test_unknown_missing_and_duplicate_keys_fail_closed() -> None:
    unknown = payload(extra=True)
    with pytest.raises(PeriodLockError):
        parse_period_lock(unknown)
    missing = payload()
    del missing["source_snapshot_digest"]
    with pytest.raises(PeriodLockError):
        parse_period_lock(missing)
    duplicate = b'{"calendar":"utc_iso_week_monday_sunday","calendar":"utc_iso_week_monday_sunday"}'
    with pytest.raises(PeriodLockError):
        parse_period_lock_bytes(duplicate)


def test_noncanonical_wire_and_generated_at_are_rejected() -> None:
    lock = parse_period_lock(payload())
    canonical = serialize_period_lock(lock)
    with pytest.raises(PeriodLockError):
        parse_period_lock_bytes(b" " + canonical)
    with pytest.raises(PeriodLockError):
        parse_period_lock(payload(generated_at="2026-07-13T00:00:00Z"))


def test_expected_lock_requires_exact_original_evidence() -> None:
    actual = parse_period_lock(payload())
    assert_expected_period_lock(actual, actual)
    with pytest.raises(PeriodLockError):
        assert_expected_period_lock(actual, parse_period_lock(payload(source_run_id="29396791051")))
    with pytest.raises(PeriodLockError):
        assert_expected_period_lock(actual, parse_period_lock(payload(source_snapshot_digest="d" * 64)))
