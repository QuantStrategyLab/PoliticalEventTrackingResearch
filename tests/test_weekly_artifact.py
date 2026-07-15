from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from political_event_tracking_research.weekly_artifact import (
    WeeklyArtifactError,
    build_weekly_artifact,
    parse_weekly_artifact,
)

EVENTS = b"event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\ne1,2026-07-08,AAPL,public_mention,neutral,high,https://example.test/e1,note\n"
WATCHLIST = b"symbol,name,bucket,research_status,thesis,source_url\nAAPL,Apple,named_mentioned,watchlist,thesis,https://example.test/aapl\n"


def status(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {"feed_count": 2, "successful_feed_count": 2, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True}
    result.update(overrides)
    return result


def build(**overrides: object) -> dict[str, bytes]:
    values: dict[str, object] = {
        "period_start": date(2026, 7, 6),
        "as_of": date(2026, 7, 12),
        "generated_at": datetime(2026, 7, 13, 12, 15, tzinfo=timezone.utc),
        "workflow_ref": "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main",
        "source_run_id": "12345",
        "producer_ref": "a" * 40,
        "source_events": EVENTS,
        "watchlist": WATCHLIST,
        "feed_status": status(),
        "source_provenance": "official_rss_source_pipeline_v1",
        "run_mode": "manual",
    }
    values.update(overrides)
    return build_weekly_artifact(**values)


def test_exact_five_files_deterministic_and_readback() -> None:
    first = build()
    second = build()
    assert tuple(first) == ("period_lock.json", "political_events.csv", "political_watchlist.csv", "political_event_weekly.json", "weekly_manifest.json")
    assert first == second == parse_weekly_artifact(first)
    manifest = json.loads(first["weekly_manifest.json"])
    assert manifest["artifact_name"] == "political-event-weekly-v1"
    assert manifest["retention_days"] == 30


def test_event_filtering_and_zero_event_are_deterministic() -> None:
    source = EVENTS + b"old,2026-07-05,MSFT,public_mention,neutral,high,https://example.test/old,note\n" + b"next,2026-07-13,MSFT,public_mention,neutral,high,https://example.test/next,note\n"
    filtered = build(source_events=source)
    assert filtered["political_events.csv"] == EVENTS
    empty = build(source_events=b"event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n")
    assert empty["political_events.csv"].endswith(b"\n")
    assert next(item for item in json.loads(empty["weekly_manifest.json"])["files"] if item["name"] == "political_events.csv")["row_count"] == 0


def test_malformed_event_date_and_tamper_fail_closed() -> None:
    with pytest.raises(WeeklyArtifactError) as error:
        build(source_events=EVENTS + b"bad,not-a-date,MSFT,public_mention,neutral,high,https://example.test/bad,note\n")
    assert error.value.code == "events_date_invalid"
    tampered = build()
    tampered["political_events.csv"] += b"x"
    with pytest.raises(WeeklyArtifactError):
        parse_weekly_artifact(tampered)


def test_source_snapshot_digest_is_recomputed_from_artifact_bytes() -> None:
    files = build()
    lock = json.loads(files["period_lock.json"])
    lock["source_snapshot_digest"] = "b" * 64
    files["period_lock.json"] = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(WeeklyArtifactError) as error:
        parse_weekly_artifact(files)
    assert error.value.code == "source_snapshot_digest_mismatch"


@pytest.mark.parametrize("feed", [status(complete=False), status(failed_feed_count=1, successful_feed_count=1), status(stale_feed_count=1), status(missing_feed_count=1)])
def test_incomplete_feed_never_builds(feed: dict[str, object]) -> None:
    with pytest.raises(WeeklyArtifactError):
        build(feed_status=feed)
