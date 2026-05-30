from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.truthsocial_export_import import import_truthsocial_export


ROOT = Path(__file__).resolve().parents[1]


def test_import_truthsocial_export_to_source_items(tmp_path: Path) -> None:
    output = tmp_path / "truthsocial_source_items.csv"

    rows = import_truthsocial_export(ROOT / "examples/truthsocial_export.example.json", output)

    assert output.exists()
    assert rows[0]["item_id"] == "truthsocial-truth-demo-evt1"
    assert rows[0]["source_type"] == "verified_social_post"
    assert rows[0]["source_url"].startswith("https://truthsocial.com/")
    assert rows[0]["text"] == "EVT1 is a great American manufacturing partner."
    assert rows[1]["text"] == "New funding support for EVT2 suppliers."

