from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from political_event_tracking_research.weekly_artifact import (
    ARTIFACT_NAME,
    RETENTION_DAYS,
    WeeklyArtifactError,
    build_weekly_artifact,
    completed_week_period,
    parse_weekly_artifact,
    serialize_weekly_artifact,
)


EVENTS = b"event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\ne1,2026-07-08,AAPL,public_mention,neutral,high,https://example.test/e1,note\n"
WATCHLIST = b"symbol,name,bucket,research_status,thesis,source_url\nAAPL,Apple,named_mentioned,watchlist,thesis,https://example.test/aapl\n"


def feed_status(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "feed_count": 2,
        "successful_feed_count": 2,
        "failed_feed_count": 0,
        "stale_feed_count": 0,
        "missing_feed_count": 0,
        "complete": True,
    }
    value.update(overrides)
    return value


def build(**overrides: object) -> dict[str, bytes]:
    value: dict[str, object] = {
        "period_start": date(2026, 7, 6),
        "as_of": date(2026, 7, 12),
        "generated_at": datetime(2026, 7, 13, 12, 45, tzinfo=timezone.utc),
        "workflow_ref": "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main",
        "source_run_id": "12345",
        "producer_ref": "a" * 40,
        "source_events": EVENTS,
        "watchlist": WATCHLIST,
        "feed_status": feed_status(),
        "source_provenance": "official_rss_source_pipeline_v1",
        "run_mode": "scheduled",
    }
    value.update(overrides)
    return build_weekly_artifact(**value)


def test_build_is_exact_five_files_and_round_trips() -> None:
    files = build()
    assert tuple(files) == (
        "period_lock.json",
        "political_events.csv",
        "political_watchlist.csv",
        "political_event_weekly.json",
        "weekly_manifest.json",
    )
    assert parse_weekly_artifact(files) == files
    assert serialize_weekly_artifact(files) == files

    manifest = json.loads(files["weekly_manifest.json"])
    assert manifest["artifact_name"] == ARTIFACT_NAME
    assert manifest["retention_days"] == RETENTION_DAYS
    assert {item["name"] for item in manifest["files"]} == set(files) - {"weekly_manifest.json"}


def test_build_is_deterministic_for_same_inputs() -> None:
    assert build() == build()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("as_of", date(2026, 7, 11)),
        ("generated_at", datetime(2026, 7, 12, 23, 0, tzinfo=timezone.utc)),
    ],
)
def test_period_and_provenance_mismatch_fail_closed(field: str, value: object) -> None:
    with pytest.raises(WeeklyArtifactError):
        build(**{field: value})


@pytest.mark.parametrize(
    "status",
    [
        feed_status(failed_feed_count=1, successful_feed_count=1),
        feed_status(stale_feed_count=1),
        feed_status(missing_feed_count=1),
        {"feed_count": 0, "successful_feed_count": 0, "failed_feed_count": 0},
    ],
)
def test_incomplete_feed_status_does_not_build(status: dict[str, object]) -> None:
    with pytest.raises(WeeklyArtifactError):
        build(feed_status=status)


@pytest.mark.parametrize("field", ["source_events", "watchlist"])
def test_missing_or_malformed_csv_does_not_build(field: str) -> None:
    with pytest.raises(WeeklyArtifactError):
        build(**{field: b"not,the,approved,header\n"})


def test_events_are_filtered_to_locked_period_deterministically() -> None:
    source = EVENTS + b"old,2026-07-05,MSFT,public_mention,neutral,high,https://example.test/old,note\n"
    files = build(source_events=source)
    assert files["political_events.csv"] == EVENTS
    base_lock = json.loads(build()["period_lock.json"])
    filtered_lock = json.loads(files["period_lock.json"])
    assert filtered_lock["source_snapshot_digest"] != base_lock["source_snapshot_digest"]
    manifest = json.loads(files["weekly_manifest.json"])
    event_file = next(item for item in manifest["files"] if item["name"] == "political_events.csv")
    assert event_file["row_count"] == 1


def test_event_date_outside_period_is_filtered_including_next_monday() -> None:
    source = EVENTS + b"next,2026-07-13,MSFT,public_mention,neutral,high,https://example.test/next,note\n"
    files = build(source_events=source)
    assert files["political_events.csv"] == EVENTS


def test_malformed_event_date_fails_closed() -> None:
    source = EVENTS + b"bad,not-a-date,MSFT,public_mention,neutral,high,https://example.test/bad,note\n"
    with pytest.raises(WeeklyArtifactError) as error:
        build(source_events=source)
    assert error.value.code == "events_date_invalid"


def test_zero_event_week_is_allowed() -> None:
    files = build(source_events=b"event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n")
    manifest = json.loads(files["weekly_manifest.json"])
    event_file = next(item for item in manifest["files"] if item["name"] == "political_events.csv")
    assert event_file["row_count"] == 0
    assert files["political_events.csv"].endswith(b"\n")


def test_incoming_complete_false_is_not_overridden() -> None:
    with pytest.raises(WeeklyArtifactError):
        build(feed_status=feed_status(complete=False))


def test_manifest_file_tamper_is_rejected() -> None:
    files = build()
    tampered = dict(files)
    tampered["political_events.csv"] += b"e2,2026-07-09,MSFT,public_mention,neutral,high,https://example.test/e2,note\n"
    with pytest.raises(WeeklyArtifactError):
        parse_weekly_artifact(tampered)


def test_extra_or_missing_file_is_rejected() -> None:
    files = build()
    with pytest.raises(WeeklyArtifactError):
        parse_weekly_artifact({key: value for key, value in files.items() if key != "weekly_manifest.json"})
    with pytest.raises(WeeklyArtifactError):
        parse_weekly_artifact({**files, "extra.txt": b"x"})


def test_malformed_period_lock_is_sanitized() -> None:
    files = build()
    tampered = dict(files)
    tampered["period_lock.json"] = b"{}"
    with pytest.raises(WeeklyArtifactError) as error:
        parse_weekly_artifact(tampered)
    assert error.value.code == "period_lock_invalid"


def test_manifest_is_not_self_hash_bound() -> None:
    manifest = json.loads(build()["weekly_manifest.json"])
    assert "weekly_manifest.json" not in {item["name"] for item in manifest["files"]}


def test_scheduled_period_is_previous_complete_week() -> None:
    assert completed_week_period(date(2026, 7, 13)) == (date(2026, 7, 6), date(2026, 7, 13))
    with pytest.raises(WeeklyArtifactError):
        completed_week_period(date(2026, 7, 12))
