from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .csv_utils import read_csv_rows, write_csv_rows


USER_AGENT = "QuantStrategyLabSourceIngest/0.1 (https://github.com/QuantStrategyLab/PoliticalEventTrackingResearch)"
AUTHOR_ALLOWLIST_FIELDS = [
    "member_id",
    "name",
    "label",
    "notes",
    "profile_url",
    "followers_count",
    "following_count",
    "activities_count",
    "liked_count",
    "bookmarked_count",
]


@dataclass(frozen=True)
class LongbridgeProfile:
    member_id: str
    name: str
    description: str
    profile_url: str
    followers_count: str
    following_count: str
    activities_count: str
    liked_count: str
    bookmarked_count: str


def fetch_profile_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def extract_member_id(url: str) -> str:
    profile_match = re.search(r"/profiles/(\d+)", url)
    if profile_match:
        return profile_match.group(1)
    channel_match = re.search(r"[?&]channel=m(\d+)", url)
    if channel_match:
        return channel_match.group(1)
    raise ValueError(f"Longbridge profile URL missing numeric profile id: {url}")


def canonical_profile_url(member_id: str) -> str:
    return f"https://longbridge.com/profiles/{member_id}"


def parse_next_data(html_text: str) -> dict:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html_text,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("Longbridge profile page missing __NEXT_DATA__ payload")
    return json.loads(html.unescape(match.group(1)))


def parse_profile_html(html_text: str, fallback_url: str) -> LongbridgeProfile:
    payload = parse_next_data(html_text)
    page_props = payload.get("props", {}).get("pageProps", {})
    profile = page_props.get("initProfile") or {}
    member_id = str(profile.get("member_id") or profile.get("id") or page_props.get("memberId") or "").strip()
    if not member_id:
        member_id = extract_member_id(fallback_url)
    return LongbridgeProfile(
        member_id=member_id,
        name=str(profile.get("nickname") or "").strip(),
        description=str(profile.get("description") or "").strip().replace("\r\n", "\n").replace("\r", "\n"),
        profile_url=canonical_profile_url(member_id),
        followers_count=str(profile.get("followers_count") or ""),
        following_count=str(profile.get("following_count") or ""),
        activities_count=str(profile.get("activities_count") or ""),
        liked_count=str(profile.get("liked_count") or ""),
        bookmarked_count=str(profile.get("bookmarked_count") or ""),
    )


def profile_to_allowlist_row(profile: LongbridgeProfile, label: str) -> dict[str, str]:
    metric_notes = []
    if profile.description:
        metric_notes.append(profile.description.replace("\n", " "))
    if profile.followers_count:
        metric_notes.append(f"followers={profile.followers_count}")
    if profile.activities_count:
        metric_notes.append(f"activities={profile.activities_count}")
    if profile.liked_count:
        metric_notes.append(f"liked={profile.liked_count}")
    if profile.bookmarked_count:
        metric_notes.append(f"bookmarked={profile.bookmarked_count}")
    return {
        "member_id": profile.member_id,
        "name": profile.name,
        "label": label,
        "notes": "; ".join(metric_notes),
        "profile_url": profile.profile_url,
        "followers_count": profile.followers_count,
        "following_count": profile.following_count,
        "activities_count": profile.activities_count,
        "liked_count": profile.liked_count,
        "bookmarked_count": profile.bookmarked_count,
    }


def merge_rows(existing_rows: list[dict[str, str]], incoming_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_key: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for row in existing_rows:
        key = (row.get("member_id") or "").strip() or f"name:{(row.get('name') or '').strip().casefold()}"
        if key not in rows_by_key:
            order.append(key)
        rows_by_key[key] = {field: row.get(field, "") for field in AUTHOR_ALLOWLIST_FIELDS}

    for row in incoming_rows:
        member_id = (row.get("member_id") or "").strip()
        name_key = f"name:{(row.get('name') or '').strip().casefold()}"
        key = member_id or name_key
        old_name_key = name_key if name_key in rows_by_key else ""
        if member_id and old_name_key and old_name_key != key:
            old_row = rows_by_key.pop(old_name_key)
            order = [key if item == old_name_key else item for item in order]
            rows_by_key[key] = old_row
        elif key not in rows_by_key:
            order.append(key)
        merged = dict(rows_by_key.get(key, {}))
        for field in AUTHOR_ALLOWLIST_FIELDS:
            value = row.get(field, "")
            if value:
                merged[field] = value
            else:
                merged.setdefault(field, "")
        rows_by_key[key] = merged
    return [rows_by_key[key] for key in order if key in rows_by_key]


def import_longbridge_profiles(
    profile_urls: list[str],
    allowlist_path: str | Path,
    *,
    output_path: str | Path | None = None,
    label: str = "profile_url",
    fetcher: Callable[[str], str] = fetch_profile_html,
) -> list[dict[str, str]]:
    existing_rows = read_csv_rows(allowlist_path) if Path(allowlist_path).exists() else []
    incoming_rows = [
        profile_to_allowlist_row(parse_profile_html(fetcher(url), url), label=label)
        for url in profile_urls
    ]
    rows = merge_rows(existing_rows, incoming_rows)
    write_csv_rows(output_path or allowlist_path, AUTHOR_ALLOWLIST_FIELDS, rows)
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Longbridge profile URLs into followed-author allowlist CSV.")
    parser.add_argument("--profile-url", nargs="+", required=True, help="Longbridge profile URL(s).")
    parser.add_argument("--allowlist", required=True, help="Existing allowlist CSV to update.")
    parser.add_argument("--output", help="Optional output CSV. Defaults to updating --allowlist in place.")
    parser.add_argument("--label", default="profile_url", help="Label to apply to imported profiles.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    import_longbridge_profiles(
        args.profile_url,
        args.allowlist,
        output_path=args.output,
        label=args.label,
    )


if __name__ == "__main__":
    main()
