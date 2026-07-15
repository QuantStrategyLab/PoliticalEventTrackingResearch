#!/usr/bin/env python3
"""Validate trusted run identity and the only permitted weekly period."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.workflow_boundary import (  # noqa: E402
    WorkflowBoundaryError,
    validate_manual_period,
    validate_manual_run,
    validate_scheduled_run,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", choices=("schedule", "workflow_dispatch"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--period-start", required=False)
    parser.add_argument("--as-of", required=False)
    parser.add_argument("--run-payload", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.run_payload.read_text(encoding="utf-8"))
        if args.event == "schedule":
            evidence = validate_scheduled_run(payload, run_id=args.run_id, workflow_ref=args.workflow_ref, run_attempt=args.run_attempt)
            start, end, as_of = evidence.period_start, evidence.period_end_exclusive, evidence.as_of
        else:
            evidence = validate_manual_run(payload, run_id=args.run_id, workflow_ref=args.workflow_ref, run_attempt=args.run_attempt)
            start, as_of = validate_manual_period(args.period_start, args.as_of, run_created_at=evidence.created_at)
            end = start.fromordinal(start.toordinal() + 7)
        args.output.write_text(json.dumps({"period_start": start.isoformat(), "period_end_exclusive": end.isoformat(), "as_of": as_of.isoformat(), "producer_ref": evidence.producer_ref, "source_attempt": evidence.run_attempt}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except WorkflowBoundaryError as error:
        raise SystemExit(error.code) from None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise SystemExit("workflow_boundary_invalid") from None


if __name__ == "__main__":
    main()
