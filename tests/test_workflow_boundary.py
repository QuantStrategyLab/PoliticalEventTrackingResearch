from __future__ import annotations

from datetime import date

import pytest

from political_event_tracking_research.workflow_boundary import (
    WorkflowBoundaryError,
    validate_manual_period,
    validate_scheduled_run,
)


RUN = {
    "id": 12345,
    "run_attempt": 1,
    "event": "schedule",
    "path": ".github/workflows/rss_source_pipeline.yml",
    "head_branch": "main",
    "head_sha": "a" * 40,
    "head_repository": {"full_name": "QuantStrategyLab/PoliticalEventTrackingResearch"},
    "created_at": "2026-07-20T12:15:00Z",
}


def test_manual_guard_is_pure_and_strict() -> None:
    assert validate_manual_period("2026-07-13", "2026-07-19") == (date(2026, 7, 13), date(2026, 7, 19))
    with pytest.raises(WorkflowBoundaryError):
        validate_manual_period("", "2026-07-19")
    with pytest.raises(WorkflowBoundaryError):
        validate_manual_period("2026-07-14", "2026-07-20")


def test_scheduled_run_uses_api_created_at_not_local_clock() -> None:
    result = validate_scheduled_run(RUN, run_id="12345", workflow_ref="QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main")
    assert result.period_start == date(2026, 7, 13)
    assert result.as_of == date(2026, 7, 19)
    assert result.producer_ref == "a" * 40


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 12346),
        ("run_attempt", 2),
        ("event", "workflow_dispatch"),
        ("path", ".github/workflows/other.yml"),
        ("head_branch", "feature"),
        ("head_sha", "not-sha"),
        ("created_at", "not-time"),
    ],
)
def test_scheduled_run_identity_tamper_fails_closed(field: str, value: object) -> None:
    payload = dict(RUN)
    payload[field] = value
    with pytest.raises(WorkflowBoundaryError):
        validate_scheduled_run(payload, run_id="12345", workflow_ref="QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main")


def test_scheduled_run_wrong_repository_fails_closed() -> None:
    payload = {**RUN, "head_repository": {"full_name": "other/repo"}}
    with pytest.raises(WorkflowBoundaryError):
        validate_scheduled_run(payload, run_id="12345", workflow_ref="QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/rss_source_pipeline.yml@refs/heads/main")
