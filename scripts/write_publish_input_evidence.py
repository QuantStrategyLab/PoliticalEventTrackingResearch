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
    serialize_publication_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-items", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        policy = read_input_policy_evidence(args.policy.read_bytes())
        source_bytes = args.source_items.read_bytes()
        status_bytes = args.status.read_bytes()
        status = read_status(status_bytes)
        with args.source_items.open(newline="", encoding="utf-8") as handle:
            row_count = sum(1 for _ in csv.DictReader(handle))
        evidence = build_publication_evidence(
            policy,
            root=args.root,
            source_items_bytes=source_bytes,
            status_bytes=status_bytes,
            status_eligible=status["eligible_for_live_publication"],
            source_items_row_count=row_count,
            aggregate_row_digest=status["aggregate_row_digest"],
        )
        if read_publication_evidence(evidence) != evidence:
            raise ValueError("publication_evidence_readback_invalid")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(serialize_publication_evidence(evidence))
    except (OSError, UnicodeError, ValueError, csv.Error):
        raise SystemExit("publication_evidence_invalid") from None


if __name__ == "__main__":
    main()
