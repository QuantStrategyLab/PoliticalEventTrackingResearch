from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.longbridge_profile_activity_fetch import (
    FollowedLongbridgeProfile,
    activity_to_source_row,
    fetch_longbridge_profile_activities,
    load_followed_profiles,
    profile_activity_auth_headers,
    resolve_cookie_header,
    write_profile_activity_source_items,
)


def test_load_followed_profiles_uses_member_ids(tmp_path: Path) -> None:
    allowlist = tmp_path / "authors.csv"
    allowlist.write_text(
        "member_id,name,label,notes,profile_url\n"
        "1450684,Hotspot,public,,https://longbridge.com/profiles/1450684\n"
        ",Only Name,screenshot,,\n"
        "1450684,Duplicate,public,,\n",
        encoding="utf-8",
    )

    profiles = load_followed_profiles(allowlist)

    assert profiles == [
        FollowedLongbridgeProfile(
            member_id="1450684",
            name="Hotspot",
            profile_url="https://longbridge.com/profiles/1450684",
        )
    ]


def test_activity_to_source_row_extracts_text_and_counter_ids() -> None:
    activity = {
        "id": "100000017629631",
        "action": "CreateTweet",
        "created_at": "1762756191",
        "actors": [{"member_id": "1450684", "name": "Hotspot"}],
        "targets": [
            {
                "id": "36186923",
                "description_html": "<p>特斯拉第三季度财报活动获奖者公告</p>",
                "counter_ids": ["ST/US/TSLA"],
                "detail_url": "https://m.lbctrl.com/social/36186923",
                "published_at": "1762756191",
            }
        ],
    }

    row = activity_to_source_row(activity, FollowedLongbridgeProfile(member_id="1450684"))

    assert row == {
        "item_id": "longbridge-activity-100000017629631",
        "published_at": "2025-11-10T06:29:51Z",
        "source_type": "community_research_lead",
        "source_url": "https://m.lbctrl.com/social/36186923",
        "author": "Longbridge:Hotspot",
        "text": "特斯拉第三季度财报活动获奖者公告 ST/US/TSLA TSLA TSLA.US",
    }


def test_profile_activity_auth_headers_accepts_copied_cookie_header() -> None:
    headers = profile_activity_auth_headers(
        "1450684",
        "https://longbridge.com/profiles/1450684",
        cookie_header="Cookie: a=b; c=d\n",
    )

    assert headers["Cookie"] == "a=b; c=d"
    assert headers["Referer"] == "https://longbridge.com/profiles/1450684"


def test_resolve_cookie_header_prefers_explicit_and_file(tmp_path: Path, monkeypatch) -> None:
    cookie_file = tmp_path / "longbridge.cookie"
    cookie_file.write_text("Cookie: file_cookie=1\n", encoding="utf-8")
    monkeypatch.setenv("LONGBRIDGE_COOKIE", "env_cookie=1")

    assert resolve_cookie_header(cookie_header="direct_cookie=1", cookie_file=cookie_file) == "direct_cookie=1"
    assert resolve_cookie_header(cookie_file=cookie_file) == "file_cookie=1"
    assert resolve_cookie_header() == "env_cookie=1"


def test_write_profile_activity_source_items_deduplicates(tmp_path: Path) -> None:
    raw_profiles = [
        {
            "member_id": "1450684",
            "name": "Hotspot",
            "profile_url": "https://longbridge.com/profiles/1450684",
            "pages": [
                {
                    "code": 0,
                    "data": {
                        "activities": [
                            {
                                "id": "act-1",
                                "created_at": "1770000000",
                                "actors": [{"name": "Hotspot"}],
                                "targets": [{"id": "topic-1", "description_html": "<p>Micron HBM</p>"}],
                            },
                            {
                                "id": "act-1",
                                "created_at": "1770000000",
                                "actors": [{"name": "Hotspot"}],
                                "targets": [{"id": "topic-1", "description_html": "<p>Micron HBM duplicate</p>"}],
                            },
                        ]
                    },
                }
            ],
        }
    ]
    output = tmp_path / "source_items.csv"

    rows = write_profile_activity_source_items(raw_profiles, output)

    assert len(rows) == 1
    assert rows[0]["text"] == "Micron HBM duplicate"
    assert output.read_text(encoding="utf-8").count("longbridge-activity-act-1") == 1


def test_fetch_longbridge_profile_activities_uses_pagination(tmp_path: Path) -> None:
    allowlist = tmp_path / "authors.csv"
    allowlist.write_text("member_id,name\n1450684,Hotspot\n", encoding="utf-8")
    source_items = tmp_path / "source_items.csv"
    raw_output = tmp_path / "raw.json"
    requested_urls: list[str] = []

    def fake_fetcher(url: str, headers: dict[str, str]) -> dict:
        requested_urls.append(url)
        assert headers["x-app-id"] == "longbridge"
        assert headers["Cookie"] == "session=abc"
        if "tail_mark=0" in url:
            return {
                "code": 0,
                "data": {
                    "activities": [{"id": "act-1", "created_at": "1770000000", "targets": [{"body": "Dell AI"}]}],
                    "next_params": {"tail_mark": "1770000000000000"},
                },
            }
        return {
            "code": 0,
            "data": {
                "activities": [{"id": "act-2", "created_at": "1770000100", "targets": [{"body": "Micron HBM"}]}],
                "next_params": None,
            },
        }

    rows = fetch_longbridge_profile_activities(
        author_allowlist_path=allowlist,
        raw_output_path=raw_output,
        source_items_output_path=source_items,
        pages=2,
        cookie_header="Cookie: session=abc",
        fetcher=fake_fetcher,
    )

    assert [row["item_id"] for row in rows] == ["longbridge-activity-act-1", "longbridge-activity-act-2"]
    assert len(requested_urls) == 2
    assert "tail_mark=1770000000000000" in requested_urls[1]
    assert raw_output.exists()
