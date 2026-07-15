#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.feed_status_canonical_h2c import read_status  # noqa: E402
from political_event_tracking_research.publish_input_policy import (  # noqa: E402
    build_publication_evidence,
    read_input_policy_evidence,
    read_publication_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source-items", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args()
    try:
        policy = read_input_policy_evidence(args.policy.read_bytes())
        evidence = read_publication_evidence(args.evidence.read_bytes())
        source_bytes = args.source_items.read_bytes()
        status_bytes = args.status.read_bytes()
        status = read_status(status_bytes)
        with args.source_items.open(newline="", encoding="utf-8") as handle:
            actual_row_count = sum(1 for _ in csv.DictReader(handle))
        if actual_row_count != evidence["source_items_row_count"]:
            raise ValueError("source_items_row_count_mismatch")
        actual = build_publication_evidence(
            policy,
            root=args.root,
            source_items_bytes=source_bytes,
            status_bytes=status_bytes,
            status_eligible=status["eligible_for_live_publication"],
            source_items_row_count=actual_row_count,
            aggregate_row_digest=status["aggregate_row_digest"],
        )
        if actual != evidence:
            raise ValueError("publication_evidence_mismatch")
        if args.require_publishable and (
            not evidence["eligible_for_live_publication"] or not evidence["status_eligible_for_live_publication"]
        ):
            raise SystemExit("publish_input_ineligible")
    except SystemExit:
        raise
    except (OSError, UnicodeError, ValueError):
        raise SystemExit("publication_evidence_invalid") from None


if __name__ == "__main__":
    main()
