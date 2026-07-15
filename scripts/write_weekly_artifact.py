#!/usr/bin/env python3
"""Write a producer-owned ``political_event_weekly.v1`` manifest artifact."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.weekly_contract import WeeklyContractError
from political_event_tracking_research.weekly_producer import write_weekly_artifact_from_files


def _generated_at(value: str) -> datetime:
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("generated_at_invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise argparse.ArgumentTypeError("generated_at_invalid") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a validated weekly producer artifact.")
    parser.add_argument("paths", nargs="+", help="Explicit input files, relative to --base-dir.")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--feed-status", required=True)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--generated-at", required=True, type=_generated_at)
    parser.add_argument("--run-mode", required=True, choices=("scheduled", "manual"))
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--source-provenance", required=True)
    args = parser.parse_args()
    try:
        write_weekly_artifact_from_files(
            args.paths,
            base_dir=args.base_dir,
            output_dir=args.output_dir,
            feed_status_path=args.feed_status,
            period_start=args.period_start,
            as_of=args.as_of,
            generated_at=args.generated_at,
            run_mode=args.run_mode,
            producer_ref=args.producer_ref,
            source_provenance=args.source_provenance,
        )
    except WeeklyContractError as error:
        raise SystemExit(error.code) from None


if __name__ == "__main__":
    main()
