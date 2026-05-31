from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.artifacts import build_live_manifest


def test_build_live_manifest_records_hash_and_row_count(tmp_path: Path) -> None:
    csv_path = tmp_path / "source_events.csv"
    csv_path.write_text("event_id,symbol\ne1,MU\ne2,INTC\n", encoding="utf-8")

    manifest = build_live_manifest([csv_path], base_dir=tmp_path)

    item = manifest["artifacts"]["source_events.csv"]
    assert manifest["manifest_type"] == "political_event_live_outputs"
    assert item["path"] == "source_events.csv"
    assert item["row_count"] == 2
    assert len(item["sha256"]) == 64
