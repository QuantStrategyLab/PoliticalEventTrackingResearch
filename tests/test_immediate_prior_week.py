from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from political_event_tracking_research.weekly_artifact import (
    ARTIFACT_FILES,
    WeeklyArtifactError,
    build_weekly_artifact,
    parse_weekly_artifact,
)
from political_event_tracking_research.workflow_boundary import (
    WORKFLOW_REF,
    WorkflowBoundaryError,
    validate_manual_period,
    validate_manual_run,
    validate_scheduled_run,
)


EVENTS = (
    b"event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n"
    b"e1,2026-07-08,AAPL,mention,neutral,high,https://example.test/e1,note\n"
)
WATCHLIST = b"symbol,name,bucket,research_status,thesis,source_url\nAAPL,Apple,watch,active,thesis,https://example.test/aapl\n"
STATUS = {
    "generated_at": "2026-07-13T12:45:00Z",
    "feed_count": 2,
    "successful_feed_count": 2,
    "failed_feed_count": 0,
    "stale_feed_count": 0,
    "missing_feed_count": 0,
    "complete": True,
    "item_count": 1,
    "feeds": [
        {"feed_id": "one", "feed_url": "https://example.test/one", "ok": True, "item_count": 1, "error": ""},
        {"feed_id": "two", "feed_url": "https://example.test/two", "ok": True, "item_count": 0, "error": ""},
    ],
}


def run_payload(*, created_at: str = "2026-07-13T12:45:00Z", attempt: int = 1) -> dict[str, object]:
    return {
        "id": 123,
        "run_attempt": attempt,
        "event": "workflow_dispatch",
        "path": ".github/workflows/rss_source_pipeline.yml",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "created_at": created_at,
        "head_repository": {"full_name": "QuantStrategyLab/PoliticalEventTrackingResearch"},
    }


def test_schedule_and_manual_use_same_previous_complete_week() -> None:
    payload = {**run_payload(), "event": "schedule"}
    scheduled = validate_scheduled_run(payload, run_id="123", workflow_ref=WORKFLOW_REF)
    assert (scheduled.period_start, scheduled.as_of) == (date(2026, 7, 6), date(2026, 7, 12))
    manual = validate_manual_run({**payload, "event": "workflow_dispatch"}, run_id="123", workflow_ref=WORKFLOW_REF)
    assert validate_manual_period("2026-07-06", "2026-07-12", run_created_at=manual.created_at) == (
        date(2026, 7, 6),
        date(2026, 7, 12),
    )


@pytest.mark.parametrize(("period_start", "as_of"), [("2026-06-29", "2026-07-05"), ("2026-07-13", "2026-07-19"), ("2026-07-13", "2026-07-19")])
def test_manual_history_current_or_future_is_rejected(period_start: str, as_of: str) -> None:
    with pytest.raises(WorkflowBoundaryError) as error:
        validate_manual_period(period_start, as_of, run_created_at=datetime(2026, 7, 13, 12, 45, tzinfo=timezone.utc))
    assert error.value.code in {"manual_period_mismatch", "manual_period_not_immediate_prior"}


def test_delayed_runner_uses_created_at_not_wall_clock() -> None:
    payload = {**run_payload(created_at="2026-07-14T23:59:59Z"), "event": "schedule"}
    evidence = validate_scheduled_run(payload, run_id="123", workflow_ref=WORKFLOW_REF)
    assert evidence.period_start == date(2026, 7, 6)


def test_manual_identity_mismatch_fails_before_period_validation() -> None:
    payload = run_payload()
    with pytest.raises(WorkflowBoundaryError):
        validate_manual_run(payload, run_id="124", workflow_ref=WORKFLOW_REF)


def test_attempt_two_and_wrong_workflow_fail_closed() -> None:
    evidence = validate_scheduled_run({**run_payload(attempt=2), "event": "schedule"}, run_id="123", workflow_ref=WORKFLOW_REF, run_attempt=2)
    assert evidence.run_attempt == 2
    with pytest.raises(WorkflowBoundaryError):
        validate_scheduled_run({**run_payload(attempt=2), "event": "schedule"}, run_id="123", workflow_ref=WORKFLOW_REF, run_attempt=3)
    with pytest.raises(WorkflowBoundaryError):
        validate_scheduled_run({**run_payload(), "event": "schedule"}, run_id="123", workflow_ref="wrong")


def _build(**overrides: object) -> dict[str, bytes]:
    values: dict[str, object] = {
        "period_start": date(2026, 7, 6),
        "as_of": date(2026, 7, 12),
        "generated_at": datetime(2026, 7, 13, 12, 45, tzinfo=timezone.utc),
        "workflow_ref": WORKFLOW_REF,
        "source_run_id": "123",
        "producer_ref": "a" * 40,
        "source_events": EVENTS,
        "watchlist": WATCHLIST,
        "feed_status": STATUS,
        "run_mode": "manual",
    }
    values.update(overrides)
    return build_weekly_artifact(**values)


def test_artifact_is_exact_five_files_and_round_trips() -> None:
    files = _build()
    assert tuple(files) == ARTIFACT_FILES
    assert parse_weekly_artifact(files) == files
    manifest = json.loads(files["weekly_manifest.json"])
    assert manifest["period_start"] == "2026-07-06"
    assert manifest["as_of"] == "2026-07-12"


def test_attempt_is_bound_in_lock_and_manifest() -> None:
    files = _build(source_attempt=3)
    assert json.loads(files["period_lock.json"])["source_attempt"] == 3
    assert json.loads(files["weekly_manifest.json"])["source_attempt"] == 3


def test_out_of_period_rows_are_filtered_but_malformed_dates_fail() -> None:
    source = EVENTS + b"old,2026-07-05,MSFT,mention,neutral,high,https://example.test/old,note\n"
    assert b"old," not in _build(source_events=source)["political_events.csv"]
    with pytest.raises(WeeklyArtifactError):
        _build(source_events=EVENTS + b"bad,not-a-date,MSFT,mention,neutral,high,x,n\n")


def test_zero_event_week_and_incomplete_feed_are_distinct() -> None:
    empty = _build(source_events=b"event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n")
    assert empty["political_events.csv"].endswith(b"\n")
    with pytest.raises(WeeklyArtifactError):
        _build(feed_status={**STATUS, "complete": False})


def test_manifest_tamper_and_file_set_fail_closed() -> None:
    files = _build()
    tampered = dict(files)
    tampered["political_events.csv"] += b"e2,2026-07-09,MSFT,mention,neutral,high,x,n\n"
    with pytest.raises(WeeklyArtifactError):
        parse_weekly_artifact(tampered)
    with pytest.raises(WeeklyArtifactError):
        parse_weekly_artifact({**files, "extra": b"x"})


@pytest.mark.parametrize("change", [{"complete": None}, {"unexpected": 1}, {"failed_feed_count": 1}])
def test_fetch_status_shape_is_exact_and_complete(change: dict[str, object]) -> None:
    status = dict(STATUS)
    status.update(change)
    with pytest.raises(WeeklyArtifactError):
        _build(feed_status=status)


def test_workflow_guard_and_legacy_upload_precede_weekly_build() -> None:
    workflow = Path(__file__).parents[1].joinpath(".github/workflows/rss_source_pipeline.yml").read_text(encoding="utf-8")
    assert workflow.index("Validate run identity and period before checkout") < workflow.index("actions/checkout@")
    assert workflow.index("Upload RSS source artifact") < workflow.index("Build completed weekly producer artifact")
    assert 'git config --local http.https://github.com/.extraheader' in workflow
    assert 'git config --local --unset-all http.https://github.com/.extraheader' in workflow
    assert 'echo "${GITHUB_TOKEN}"' not in workflow
    assert "github.event.inputs.period_start || ''" in workflow
    assert "manual_period_not_immediate_prior" in workflow
