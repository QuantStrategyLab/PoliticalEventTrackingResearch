from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from political_event_tracking_research.longbridge_cli_fetch import fetch_longbridge_cli_topics


def completed(payload: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["longbridge"], returncode=0, stdout=json.dumps(payload), stderr="")


def test_fetch_longbridge_cli_topics_writes_raw_and_source_items(tmp_path: Path) -> None:
    symbols = tmp_path / "symbols.csv"
    symbols.write_text("symbol,notes\nMU.US,memory\n", encoding="utf-8")
    allowlist = tmp_path / "authors.csv"
    allowlist.write_text("member_id,name,label,notes\nexpert-1001,Example Expert,top,\n", encoding="utf-8")
    raw_output = tmp_path / "topics.json"
    source_items = tmp_path / "source_items.csv"
    calls: list[list[str]] = []

    def fake_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["longbridge", "topic", "MU.US"]:
            return completed(
                {
                    "data": {
                        "items": [
                            {
                                "id": "lb-1",
                                "title": "Micron setup",
                                "description": "MU.US HBM lead",
                                "url": "https://longbridge.cn/topics/lb-1",
                                "published_at": "1770000000",
                                "likes_count": 5,
                                "author": {"member_id": "expert-1001", "name": "Example Expert"},
                            }
                        ]
                    }
                }
            )
        if command[:4] == ["longbridge", "topic", "detail", "lb-1"]:
            return completed(
                {
                    "data": {
                        "item": {
                            "id": "lb-1",
                            "title": "Micron setup",
                            "body": "Micron MU.US full detail.",
                            "detail_url": "https://longbridge.cn/topics/lb-1",
                            "created_at": "1770000000",
                            "likes_count": 5,
                            "author": {"member_id": "expert-1001", "name": "Example Expert"},
                        }
                    }
                }
            )
        raise AssertionError(command)

    rows = fetch_longbridge_cli_topics(
        symbols,
        raw_output,
        source_items_output_path=source_items,
        author_allowlist_path=allowlist,
        include_details=True,
        runner=fake_runner,
    )

    assert len(rows) == 1
    assert calls == [
        ["longbridge", "topic", "MU.US", "--format", "json"],
        ["longbridge", "topic", "detail", "lb-1", "--format", "json"],
    ]
    assert "Micron MU.US full detail" in raw_output.read_text(encoding="utf-8")
    assert "longbridge-lb-1" in source_items.read_text(encoding="utf-8")
