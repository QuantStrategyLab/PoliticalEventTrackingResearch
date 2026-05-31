#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.artifacts import write_live_manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Write a JSON manifest for live CSV artifacts.")
    parser.add_argument("--output", required=True, help="Manifest JSON output path.")
    parser.add_argument("--base-dir", help="Optional base directory for display paths.")
    parser.add_argument("paths", nargs="+", help="Artifact files to record.")
    args = parser.parse_args()
    write_live_manifest(args.paths, args.output, base_dir=args.base_dir)


if __name__ == "__main__":
    main()
