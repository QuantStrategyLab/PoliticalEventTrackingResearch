#!/usr/bin/env python3
"""Build the dedicated producer-owned political-event weekly artifact."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.weekly_artifact import (  # noqa: E402
    WeeklyArtifactError,
    build_weekly_artifact,
    completed_week_period,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("invalid ISO date") from None


def _generated_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError("invalid UTC timestamp") from None
    if parsed.tzinfo != timezone.utc:
        raise argparse.ArgumentTypeError("generated_at must be UTC")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period-start", type=_date)
    parser.add_argument("--as-of", type=_date)
    parser.add_argument("--scheduled-today", type=_date)
    parser.add_argument("--generated-at", required=True, type=_generated_at)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--source-events", required=True, type=Path)
    parser.add_argument("--watchlist", required=True, type=Path)
    parser.add_argument("--feed-status", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-mode", choices=("scheduled", "manual"), required=True)
    args = parser.parse_args()

    if args.scheduled_today is not None:
        if args.run_mode != "scheduled" or args.period_start is not None or args.as_of is not None:
            parser.error("scheduled mode requires only --scheduled-today")
        period_start, period_end = completed_week_period(args.scheduled_today)
        as_of = period_end - date.resolution
    elif args.run_mode == "manual" and args.period_start is not None and args.as_of is not None:
        period_start, as_of = args.period_start, args.as_of
    else:
        parser.error("manual mode requires --period-start and --as-of")

    try:
        feed_status = json.loads(args.feed_status.read_text(encoding="utf-8"))
        files = build_weekly_artifact(
            period_start=period_start,
            as_of=as_of,
            generated_at=args.generated_at,
            workflow_ref=args.workflow_ref,
            source_run_id=args.source_run_id,
            producer_ref=args.producer_ref,
            source_events=args.source_events.read_bytes(),
            watchlist=args.watchlist.read_bytes(),
            feed_status=feed_status,
            source_provenance="official_rss_source_pipeline_v1",
            run_mode=args.run_mode,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any(args.output_dir.iterdir()):
            raise WeeklyArtifactError("artifact_output_not_empty")
        for name, content in files.items():
            (args.output_dir / name).write_bytes(content)
    except WeeklyArtifactError as exc:
        raise SystemExit(exc.code) from None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise SystemExit("weekly_artifact_input_invalid") from None


if __name__ == "__main__":
    main()
