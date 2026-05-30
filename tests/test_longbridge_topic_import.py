from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.longbridge_topic_import import import_longbridge_topics


ROOT = Path(__file__).resolve().parents[1]


def test_import_longbridge_topics_filters_followed_authors(tmp_path: Path) -> None:
    output = tmp_path / "longbridge_source_items.csv"

    rows = import_longbridge_topics(
        [ROOT / "examples/longbridge_topics.example.json"],
        output,
        author_allowlist_path=ROOT / "examples/longbridge_followed_authors.example.csv",
        min_likes=10,
    )

    assert output.exists()
    assert [row["item_id"] for row in rows] == ["longbridge-lb-demo-mu", "longbridge-lb-demo-dell"]
    assert rows[0]["source_type"] == "community_research_lead"
    assert rows[0]["source_url"] == "https://longbridge.cn/topics/lb-demo-mu"
    assert rows[0]["author"] == "Longbridge:Example Longbridge Expert"
    assert "Micron" in rows[0]["text"]
    assert "Unfollowed" not in "\n".join(row["text"] for row in rows)


def test_import_longbridge_topics_accepts_detail_payload(tmp_path: Path) -> None:
    detail = tmp_path / "detail.json"
    detail.write_text(
        """
        {
          "code": 0,
          "data": {
            "item": {
              "id": "detail-1",
              "title": "Dell detail",
              "body": "**Bullish** on DELL.US AI server demand.",
              "detail_url": "https://longbridge.com/topics/detail-1",
              "created_at": "1770000000",
              "likes_count": 1,
              "author": {"member_id": "expert-1001", "name": "Example Longbridge Expert"}
            }
          }
        }
        """,
        encoding="utf-8",
    )
    output = tmp_path / "longbridge_source_items.csv"

    rows = import_longbridge_topics([detail], output)

    assert rows == [
        {
            "item_id": "longbridge-detail-1",
            "published_at": "2026-02-02T02:40:00Z",
            "source_type": "community_research_lead",
            "source_url": "https://longbridge.com/topics/detail-1",
            "author": "Longbridge:Example Longbridge Expert",
            "text": "Dell detail **Bullish** on DELL.US AI server demand.",
        }
    ]
