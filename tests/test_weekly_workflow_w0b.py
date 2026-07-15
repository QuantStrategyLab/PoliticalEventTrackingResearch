from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from political_event_tracking_research.feed_status_canonical_h2c import build_decision
from political_event_tracking_research.rss_source_fetch import (
    FetchStatusError,
    fetch_rss_sources,
    validate_fetch_status,
)
from scripts.validate_fetch_status import validate_status_file


def accepted_status() -> dict[str, object]:
    return json.loads(
        build_decision(
            [
                {
                    "feed_id": "a",
                    "feed_url": "https://example.test/a",
                    "kind": "rss2",
                    "state": "accepted",
                    "rows": [
                        {
                            "item_id": "a-1",
                            "published_at": "2026-05-01T00:00:00Z",
                            "source_type": "official",
                            "source_url": "https://example.test/a/1",
                            "author": "",
                            "text": "event",
                        }
                    ],
                    "error_code": None,
                }
            ]
        ).status_bytes
    )


def test_status_readback_requires_canonical_status_and_success_exit(tmp_path: Path) -> None:
    status = tmp_path / "status.json"
    status.write_text(json.dumps(accepted_status(), sort_keys=True, separators=(",", ":")), encoding="utf-8")
    fetch_exit = tmp_path / "fetch_exit.txt"
    fetch_exit.write_text("0\n", encoding="utf-8")
    assert validate_status_file(status, 0) is True
    assert validate_fetch_status(json.loads(status.read_text()), fetch_exit=0) is True

    fetch_exit.write_text("7\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="fetch_status_invalid"):
        validate_status_file(status, 7)


def test_status_tamper_is_rejected_before_publication(tmp_path: Path) -> None:
    status = tmp_path / "status.json"
    payload = accepted_status()
    payload["accepted_row_count"] = 0
    status.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(SystemExit, match="fetch_status_invalid"):
        validate_status_file(status, 0)


def test_empty_feed_configuration_fails_closed(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.csv"
    feeds.write_text("feed_id,feed_url,source_type,author\n", encoding="utf-8")
    with pytest.raises(FetchStatusError, match="feed_config_empty"):
        fetch_rss_sources(feeds, tmp_path / "items.csv", status_output=tmp_path / "status.json")


def test_workflow_uploads_and_validates_before_live_publish() -> None:
    workflow = Path(__file__).parents[1].joinpath(".github/workflows/rss_source_pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.index("Validate canonical workflow inputs") < workflow.index("actions/checkout@")
    assert workflow.index("Upload RSS source artifact") < workflow.index("Validate canonical feed status readback")
    assert workflow.index("Validate canonical feed status readback") < workflow.index("Publish live CSV outputs")
    assert "git push origin HEAD:refs/heads/main" in workflow
    assert "ref: refs/heads/main" in workflow
    assert "needs: validate-workflow-boundary" in workflow
    assert "weekly" not in workflow.lower()
