#!/usr/bin/env python3
"""Build the dedicated weekly artifact after dispatch validation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.weekly_artifact import WeeklyArtifactError, build_weekly_artifact  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--source-events", required=True, type=Path)
    parser.add_argument("--watchlist", required=True, type=Path)
    parser.add_argument("--feed-status", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-mode", choices=("scheduled", "manual"), required=True)
    args = parser.parse_args()
    try:
        period_start = date.fromisoformat(args.period_start)
        as_of = date.fromisoformat(args.as_of)
        generated_at = datetime.fromisoformat(args.generated_at.replace("Z", "+00:00"))
        feed_status = json.loads(args.feed_status.read_text(encoding="utf-8"))
        files = build_weekly_artifact(
            period_start=period_start,
            as_of=as_of,
            generated_at=generated_at,
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
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError):
        raise SystemExit("weekly_artifact_input_invalid") from None


if __name__ == "__main__":
    main()
