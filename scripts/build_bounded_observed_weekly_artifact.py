#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.bounded_observed_weekly import BoundedObservedError, build_weekly_observed_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a bounded private observed weekly artifact.")
    parser.add_argument("--feeds", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--watchlist", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--generated-at")
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-attempt", type=int, required=True)
    parser.add_argument("--producer-ref", required=True)
    parser.add_argument("--run-mode", choices=("scheduled", "manual"), required=True)
    parser.add_argument("--period-start")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    try:
        build_weekly_observed_artifact(
            feeds_path=args.feeds,
            aliases_path=args.aliases,
            watchlist_path=args.watchlist,
            output_dir=args.output_dir,
            retrieved_at=args.retrieved_at,
            generated_at=args.generated_at,
            source_run_id=args.source_run_id,
            source_attempt=args.source_attempt,
            producer_ref=args.producer_ref,
            run_mode=args.run_mode,
            period_start=args.period_start,
            as_of=args.as_of,
        )
    except BoundedObservedError as exc:
        raise SystemExit(exc.code) from None


if __name__ == "__main__":
    main()
