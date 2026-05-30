from __future__ import annotations

from pathlib import Path

from political_event_tracking_research.longbridge_profile_import import (
    extract_member_id,
    import_longbridge_profiles,
    parse_profile_html,
)


PROFILE_HTML = """
<html>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "memberId": "15228814",
      "initProfile": {
        "id": "15228814",
        "member_id": "15228814",
        "nickname": "知行合一再投资",
        "description": "amazon/baba退休老人\\n价值投资",
        "following_count": 21,
        "followers_count": 2291,
        "activities_count": 228,
        "liked_count": 1690,
        "bookmarked_count": 533
      }
    }
  }
}
</script>
</html>
"""


def test_extract_member_id_from_profile_url() -> None:
    assert extract_member_id("https://longbridge.com/profiles/15228814?channel=m15228814") == "15228814"


def test_parse_profile_html_from_next_data() -> None:
    profile = parse_profile_html(PROFILE_HTML, "https://longbridge.com/profiles/15228814")

    assert profile.member_id == "15228814"
    assert profile.name == "知行合一再投资"
    assert profile.followers_count == "2291"
    assert profile.profile_url == "https://longbridge.com/profiles/15228814"


def test_import_longbridge_profiles_upserts_existing_name_row(tmp_path: Path) -> None:
    allowlist = tmp_path / "authors.csv"
    allowlist.write_text(
        "member_id,name,label,notes\n"
        ",知行合一再投资,screenshot_following,old note\n"
        ",其他作者,screenshot_following,keep\n",
        encoding="utf-8",
    )

    rows = import_longbridge_profiles(
        ["https://longbridge.com/profiles/15228814?channel=m15228814"],
        allowlist,
        fetcher=lambda _: PROFILE_HTML,
    )

    by_name = {row["name"]: row for row in rows}
    assert by_name["知行合一再投资"]["member_id"] == "15228814"
    assert by_name["知行合一再投资"]["profile_url"] == "https://longbridge.com/profiles/15228814"
    assert by_name["知行合一再投资"]["followers_count"] == "2291"
    assert by_name["其他作者"]["notes"] == "keep"
