#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.publish_input_policy import (  # noqa: E402
    WORKFLOW_REF,
    build_input_policy_evidence,
    serialize_input_policy_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("PUBLISH", "DEBUG"), required=True)
    parser.add_argument("--max-items-per-feed", required=True)
    parser.add_argument("--commit-outputs", choices=("true", "false"), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-ref", default=WORKFLOW_REF)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = build_input_policy_evidence(
            mode=args.mode,
            raw_max_items_per_feed=args.max_items_per_feed,
            commit_outputs=args.commit_outputs == "true",
            source_sha=args.source_sha,
            workflow_ref=args.workflow_ref,
            root=args.root,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(serialize_input_policy_evidence(evidence))
    except (OSError, ValueError):
        raise SystemExit("publish_input_policy_invalid") from None


if __name__ == "__main__":
    main()
