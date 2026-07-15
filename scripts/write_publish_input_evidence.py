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
        row_count, aggregate_digest, status_eligible = recompute_source_items_binding(source_bytes, status_bytes)
        evidence = build_publication_evidence(
            policy,
            root=args.root,
            source_items_bytes=source_bytes,
            status_bytes=status_bytes,
            status_eligible=status_eligible,
            source_items_row_count=row_count,
            aggregate_row_digest=aggregate_digest,
        )
        if read_publication_evidence(evidence) != evidence:
            raise ValueError("publication_evidence_readback_invalid")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(serialize_publication_evidence(evidence))
    except (OSError, UnicodeError, ValueError, csv.Error):
        raise SystemExit("publication_evidence_invalid") from None


if __name__ == "__main__":
    main()
