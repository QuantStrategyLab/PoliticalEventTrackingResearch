"""Side-effect-free validation of the PERT weekly workflow boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

REPOSITORY = "QuantStrategyLab/PoliticalEventTrackingResearch"
WORKFLOW_PATH = ".github/workflows/rss_source_pipeline.yml"
WORKFLOW_REF = f"{REPOSITORY}/{WORKFLOW_PATH}@refs/heads/main"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")


class WorkflowBoundaryError(ValueError):
    """Stable, sanitized dispatch-boundary error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ScheduledRunEvidence:
    period_start: date
    period_end_exclusive: date
    as_of: date
    created_at: datetime
    producer_ref: str


def _invalid(code: str) -> WorkflowBoundaryError:
    return WorkflowBoundaryError(code)


def _parse_date(value: object, code: str) -> date:
    if type(value) is not str or not _DATE_RE.fullmatch(value):
        raise _invalid(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _invalid(code) from None
    if parsed.isoformat() != value:
        raise _invalid(code)
    return parsed


def validate_manual_period(period_start: object, as_of: object) -> tuple[date, date]:
    start = _parse_date(period_start, "manual_period_invalid")
    end = _parse_date(as_of, "manual_period_invalid")
    try:
        expected_end = start + timedelta(days=7)
    except OverflowError:
        raise _invalid("manual_period_invalid") from None
    if start.weekday() != 0 or end != expected_end - timedelta(days=1):
        raise _invalid("manual_period_mismatch")
    return start, end


def _parse_created_at(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise _invalid("scheduled_run_created_at_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise _invalid("scheduled_run_created_at_invalid") from None
    if parsed.tzinfo != timezone.utc:
        raise _invalid("scheduled_run_created_at_invalid")
    return parsed


def validate_scheduled_run(payload: Mapping[str, object], *, run_id: object, workflow_ref: object) -> ScheduledRunEvidence:
    if not isinstance(payload, Mapping) or type(run_id) is not str or not _RUN_ID_RE.fullmatch(run_id) or workflow_ref != WORKFLOW_REF:
        raise _invalid("scheduled_run_identity_invalid")
    if type(payload.get("id")) is not int or payload["id"] != int(run_id):
        raise _invalid("scheduled_run_identity_invalid")
    if type(payload.get("run_attempt")) is not int or payload["run_attempt"] != 1 or payload.get("event") != "schedule":
        raise _invalid("scheduled_run_identity_invalid")
    if payload.get("path") != WORKFLOW_PATH or payload.get("head_branch") != "main":
        raise _invalid("scheduled_run_identity_invalid")
    repository = payload.get("head_repository")
    if not isinstance(repository, Mapping) or repository.get("full_name") != REPOSITORY:
        raise _invalid("scheduled_run_identity_invalid")
    producer_ref = payload.get("head_sha")
    if type(producer_ref) is not str or not _SHA_RE.fullmatch(producer_ref):
        raise _invalid("scheduled_run_identity_invalid")
    created_at = _parse_created_at(payload.get("created_at"))
    current_monday = created_at.date() - timedelta(days=created_at.date().weekday())
    period_start = current_monday - timedelta(days=7)
    return ScheduledRunEvidence(period_start, current_monday, current_monday - timedelta(days=1), created_at, producer_ref)
