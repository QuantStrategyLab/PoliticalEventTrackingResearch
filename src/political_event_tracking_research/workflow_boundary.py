"""Pure workflow boundary and immediate-prior-week contract."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

REPOSITORY = "QuantStrategyLab/PoliticalEventTrackingResearch"
WORKFLOW_PATH = ".github/workflows/rss_source_pipeline.yml"
WORKFLOW_REF = f"{REPOSITORY}/{WORKFLOW_PATH}@refs/heads/main"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[1-9][0-9]*$")


class WorkflowBoundaryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class WorkflowRunEvidence:
    period_start: date
    period_end_exclusive: date
    as_of: date
    created_at: datetime
    producer_ref: str


def _fail(code: str) -> WorkflowBoundaryError:
    return WorkflowBoundaryError(code)


def _date(value: object) -> date:
    if type(value) is not str or not _DATE.fullmatch(value):
        raise _fail("manual_period_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _fail("manual_period_invalid") from None
    if parsed.isoformat() != value:
        raise _fail("manual_period_invalid")
    return parsed


def _created_at(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise _fail("workflow_created_at_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise _fail("workflow_created_at_invalid") from None
    if parsed.tzinfo != timezone.utc:
        raise _fail("workflow_created_at_invalid")
    return parsed


def _previous_week(created_at: datetime) -> tuple[date, date, date]:
    if type(created_at) is not datetime or created_at.tzinfo != timezone.utc:
        raise _fail("workflow_created_at_invalid")
    try:
        current_monday = created_at.date() - timedelta(days=created_at.date().weekday())
        end = current_monday
        start = end - timedelta(days=7)
    except (OverflowError, ValueError):
        raise _fail("period_boundary_invalid") from None
    return start, end, end - timedelta(days=1)


def validate_manual_period(period_start: object, as_of: object, *, run_created_at: datetime) -> tuple[date, date]:
    if run_created_at is None:
        raise _fail("workflow_created_at_missing")
    start = _date(period_start)
    observed_as_of = _date(as_of)
    expected_start, expected_end, expected_as_of = _previous_week(run_created_at)
    if (start, observed_as_of) != (expected_start, expected_as_of):
        raise _fail("manual_period_not_immediate_prior")
    return start, expected_as_of


def _validate_run(payload: Mapping[str, object], *, run_id: object, workflow_ref: object, event: str) -> WorkflowRunEvidence:
    if not isinstance(payload, Mapping) or type(run_id) is not str or not _RUN_ID.fullmatch(run_id) or workflow_ref != WORKFLOW_REF:
        raise _fail("workflow_identity_invalid")
    if type(payload.get("id")) is not int or payload["id"] != int(run_id):
        raise _fail("workflow_identity_invalid")
    if type(payload.get("run_attempt")) is not int or payload["run_attempt"] != 1 or payload.get("event") != event:
        raise _fail("workflow_identity_invalid")
    if payload.get("path") != WORKFLOW_PATH or payload.get("head_branch") != "main":
        raise _fail("workflow_identity_invalid")
    repo = payload.get("head_repository")
    if not isinstance(repo, Mapping) or repo.get("full_name") != REPOSITORY:
        raise _fail("workflow_identity_invalid")
    producer_ref = payload.get("head_sha")
    if type(producer_ref) is not str or not _SHA.fullmatch(producer_ref):
        raise _fail("workflow_identity_invalid")
    created_at = _created_at(payload.get("created_at"))
    start, end, as_of = _previous_week(created_at)
    return WorkflowRunEvidence(start, end, as_of, created_at, producer_ref)


def validate_scheduled_run(payload: Mapping[str, object], *, run_id: object, workflow_ref: object) -> WorkflowRunEvidence:
    return _validate_run(payload, run_id=run_id, workflow_ref=workflow_ref, event="schedule")


def validate_manual_run(payload: Mapping[str, object], *, run_id: object, workflow_ref: object) -> WorkflowRunEvidence:
    return _validate_run(payload, run_id=run_id, workflow_ref=workflow_ref, event="workflow_dispatch")
