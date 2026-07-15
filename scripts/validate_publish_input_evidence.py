#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.publish_input_policy import (  # noqa: E402
    build_publication_evidence,
    recompute_source_items_binding,
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
        actual_row_count, aggregate_digest, status_eligible = recompute_source_items_binding(source_bytes, status_bytes)
        if actual_row_count != evidence["source_items_row_count"]:
            raise ValueError("source_items_row_count_mismatch")
        actual = build_publication_evidence(
            policy,
            root=args.root,
            source_items_bytes=source_bytes,
            status_bytes=status_bytes,
            status_eligible=status_eligible,
            source_items_row_count=actual_row_count,
            aggregate_row_digest=aggregate_digest,
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
