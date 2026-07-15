#!/usr/bin/env python3
"""Fail closed unless canonical fetch status permits live publication."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from political_event_tracking_research.feed_status_canonical_h2c import DecisionContractError, read_status  # noqa: E402
from political_event_tracking_research.rss_source_fetch import FetchStatusError  # noqa: E402


def validate_status_file(status_path: Path, fetch_exit: int) -> bool:
    try:
        status_bytes = status_path.read_bytes()
        payload = read_status(status_bytes)
        if type(fetch_exit) is not int or fetch_exit < 0:
            raise FetchStatusError("fetch_exit_invalid")
        if fetch_exit != 0:
            raise FetchStatusError("fetch_failed")
    except (DecisionContractError, FetchStatusError, OSError, UnicodeError):
        raise SystemExit("fetch_status_invalid") from None
    return payload["eligible_for_live_publication"] is True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--fetch-exit", required=True, type=Path)
    args = parser.parse_args()
    try:
        fetch_exit = int(args.fetch_exit.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError, ValueError):
        raise SystemExit("fetch_status_invalid") from None
    if not validate_status_file(args.status, fetch_exit):
        raise SystemExit("fetch_incomplete")


if __name__ == "__main__":
    main()
