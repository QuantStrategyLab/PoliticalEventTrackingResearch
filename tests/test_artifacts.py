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


def test_build_live_manifest_includes_source_quality_summary(tmp_path: Path) -> None:
    csv_path = tmp_path / "source_events.csv"
    csv_path.write_text(
        "\n".join(
            [
                "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes",
                "e1,2026-05-30,MU,public_mention,neutral,high,https://example.invalid/mu,MU mention",
                "e2,2026-05-30,VRT,policy_capital,bullish,medium,https://example.invalid/vrt,VRT policy",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    status_path = tmp_path / "source_fetch_status.json"
    status_path.write_text(
        '{"feed_count": 2, "successful_feed_count": 1, "failed_feed_count": 1, "feeds": []}\n',
        encoding="utf-8",
    )

    manifest = build_live_manifest([csv_path, status_path], base_dir=tmp_path)

    assert manifest["data_quality"]["source_events"]["symbols"] == ["MU", "VRT"]
    assert manifest["data_quality"]["source_events"]["confidence_counts"] == {"high": 1, "medium": 1}
    assert manifest["data_quality"]["feed_status"]["feed_success_ratio"] == 0.5
