#!/usr/bin/env python3
"""Fail closed unless the existing RSS fetch status is complete."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.rss_source_fetch import FetchStatusError, validate_fetch_status  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--fetch-exit", required=True, type=Path)
    args = parser.parse_args()
    try:
        fetch_exit = int(args.fetch_exit.read_text(encoding="utf-8").strip())
        complete = validate_fetch_status(json.loads(args.status.read_text(encoding="utf-8")), fetch_exit=fetch_exit)
    except (FetchStatusError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise SystemExit("fetch_status_invalid") from None
    if not complete:
        raise SystemExit("fetch_incomplete")


if __name__ == "__main__":
    main()
