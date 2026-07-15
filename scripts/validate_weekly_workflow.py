#!/usr/bin/env python3
"""Validate dispatch inputs before PERT fetch/live side effects."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.workflow_boundary import (  # noqa: E402
    WORKFLOW_REF,
    WorkflowBoundaryError,
    validate_manual_run,
    validate_manual_period,
    validate_scheduled_run,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", choices=("schedule", "workflow_dispatch"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--period-start")
    parser.add_argument("--as-of")
    parser.add_argument("--run-payload", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.run_attempt != 1:
            raise WorkflowBoundaryError("run_attempt_invalid")
        if args.event in {"schedule", "workflow_dispatch"}:
            if args.run_payload is None:
                raise WorkflowBoundaryError("workflow_run_payload_missing")
            payload = json.loads(args.run_payload.read_text(encoding="utf-8"))
            if args.event == "schedule":
                evidence = validate_scheduled_run(payload, run_id=args.run_id, workflow_ref=args.workflow_ref)
                result = {
                    "period_start": evidence.period_start.isoformat(),
                    "period_end_exclusive": evidence.period_end_exclusive.isoformat(),
                    "as_of": evidence.as_of.isoformat(),
                    "scheduled_created_at": evidence.created_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "producer_ref": evidence.producer_ref,
                }
            else:
                evidence = validate_manual_run(payload, run_id=args.run_id, workflow_ref=args.workflow_ref)
                start, as_of = validate_manual_period(args.period_start, args.as_of, run_created_at=evidence.created_at)
                result = {"period_start": start.isoformat(), "period_end_exclusive": (start + timedelta(days=7)).isoformat(), "as_of": as_of.isoformat(), "producer_ref": evidence.producer_ref}
        else:
            start, as_of = validate_manual_period(args.period_start, args.as_of)
            if args.workflow_ref != WORKFLOW_REF or type(args.producer_ref) is not str or not _SHA_RE.fullmatch(args.producer_ref):
                raise WorkflowBoundaryError("workflow_identity_invalid")
            result = {"period_start": start.isoformat(), "period_end_exclusive": (start + timedelta(days=7)).isoformat(), "as_of": as_of.isoformat(), "producer_ref": args.producer_ref}
        args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except WorkflowBoundaryError as exc:
        raise SystemExit(exc.code) from None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise SystemExit("workflow_boundary_invalid") from None


if __name__ == "__main__":
    main()
