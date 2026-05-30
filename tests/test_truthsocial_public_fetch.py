from __future__ import annotations

from pathlib import Path
from typing import Any

from political_event_tracking_research.truthsocial_public_fetch import fetch_truthsocial_public_posts


def test_fetch_truthsocial_public_posts_with_injected_fetcher(tmp_path: Path) -> None:
    def fake_fetcher(url: str) -> dict[str, Any] | list[dict[str, Any]]:
        if "accounts/lookup" in url:
            return {"id": "107780257626128497", "username": "realDonaldTrump"}
        if "statuses" in url:
            return [
                {
                    "id": "truth-1",
                    "created_at": "2026-02-02T14:30:00Z",
                    "url": "https://truthsocial.com/@realDonaldTrump/posts/truth-1",
                    "account": {"display_name": "Donald J. Trump", "username": "realDonaldTrump"},
                    "content": "<p>Micron and Dell are important American technology companies.</p>",
                }
            ]
        raise AssertionError(url)

    output = tmp_path / "truthsocial_source_items.csv"

    rows = fetch_truthsocial_public_posts("realDonaldTrump", output, fetcher=fake_fetcher)

    assert output.exists()
    assert rows == [
        {
            "item_id": "truthsocial-truth-1",
            "published_at": "2026-02-02T14:30:00Z",
            "source_type": "verified_social_post",
            "source_url": "https://truthsocial.com/@realDonaldTrump/posts/truth-1",
            "author": "Donald J. Trump",
            "text": "Micron and Dell are important American technology companies.",
        }
    ]
