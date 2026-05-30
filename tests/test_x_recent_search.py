from __future__ import annotations

from political_event_tracking_research.x_recent_search import XQueryConfig, build_recent_search_url, parse_x_response


def test_build_recent_search_url_uses_x_v2_endpoint() -> None:
    url = build_recent_search_url("from:example EVT1 -is:retweet", max_results=10)

    assert url.startswith("https://api.x.com/2/tweets/search/recent?")
    assert "tweet.fields=created_at" in url
    assert "from%3Aexample" in url


def test_parse_x_response_to_source_items() -> None:
    payload = {
        "data": [
            {
                "id": "123",
                "author_id": "u1",
                "created_at": "2026-04-05T10:00:00Z",
                "text": "EVT1 is a great partner.",
            }
        ],
        "includes": {"users": [{"id": "u1", "name": "Example User", "username": "example"}]},
    }
    config = XQueryConfig(
        query_id="example",
        query="from:example EVT1",
        source_type="verified_social_post",
        author_label="Example",
    )

    rows = parse_x_response(payload, config)

    assert rows == [
        {
            "item_id": "x-example-123",
            "published_at": "2026-04-05T10:00:00Z",
            "source_type": "verified_social_post",
            "source_url": "https://x.com/example/status/123",
            "author": "Example User",
            "text": "EVT1 is a great partner.",
        }
    ]

