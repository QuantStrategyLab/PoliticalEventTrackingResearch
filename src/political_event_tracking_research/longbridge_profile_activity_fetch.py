from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import time
import uuid
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from .csv_utils import read_csv_rows, write_csv_rows
from .longbridge_topic_import import LONGBRIDGE_SOURCE_TYPE, normalize_timestamp
from .rss_source_fetch import strip_html


DEFAULT_API_BASE = "https://m.lbkrs.com/api/forward"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
SOURCE_ITEM_FIELDS = ["item_id", "published_at", "source_type", "source_url", "author", "text"]


class LongbridgeProfileActivityError(RuntimeError):
    pass


@dataclass(frozen=True)
class FollowedLongbridgeProfile:
    member_id: str
    name: str = ""
    profile_url: str = ""


JsonFetcher = Callable[[str, dict[str, str]], Any]


def load_followed_profiles(path: str | Path) -> list[FollowedLongbridgeProfile]:
    profiles: list[FollowedLongbridgeProfile] = []
    seen: set[str] = set()
    for row in read_csv_rows(path):
        member_id = (row.get("member_id") or "").strip()
        if not member_id or member_id in seen:
            continue
        seen.add(member_id)
        profiles.append(
            FollowedLongbridgeProfile(
                member_id=member_id,
                name=(row.get("name") or "").strip(),
                profile_url=(row.get("profile_url") or "").strip() or canonical_profile_url(member_id),
            )
        )
    return profiles


def canonical_profile_url(member_id: str) -> str:
    return f"https://longbridge.com/profiles/{member_id}"


def profile_activity_url(
    member_id: str,
    *,
    api_base: str = DEFAULT_API_BASE,
    limit: int = 25,
    tail_mark: str = "0",
    action: str | None = "OriginalAll",
) -> str:
    params = {"limit": str(limit), "tail_mark": tail_mark}
    if action:
        params["action"] = action
    return f"{api_base.rstrip('/')}/v2/social/profiles/{member_id}/activities?{urlencode(params)}"


def profile_activity_headers(member_id: str, profile_url: str = "") -> dict[str, str]:
    referer = profile_url or f"https://longbridge.com/zh-CN/profiles/{member_id}/original"
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://longbridge.com",
        "Referer": referer,
        "x-refer-uri": referer,
        "x-platform": "web",
        "x-bridge-token": "none",
        "x-original-app-id": "longbridge",
        "x-app-id": "longbridge",
        "x-device-id": uuid.uuid4().hex,
        "x-client-request-instance": "x-request",
        "x-prefer-language": "zh-CN",
        "x-saas-host": "",
        "uber-trace-id": "0123456789abcdef:0123456789abcdef:0:1",
    }


def fetch_json_url(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read()
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    return json.loads(payload.decode("utf-8"))


def iter_activities(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            activities = data.get("activities")
            if isinstance(activities, list):
                for activity in activities:
                    if isinstance(activity, dict):
                        yield activity
                return
        activities = payload.get("activities")
        if isinstance(activities, list):
            for activity in activities:
                if isinstance(activity, dict):
                    yield activity
    elif isinstance(payload, list):
        for activity in payload:
            if isinstance(activity, dict):
                yield activity


def fetch_profile_activity_pages(
    profile: FollowedLongbridgeProfile,
    *,
    api_base: str = DEFAULT_API_BASE,
    limit: int = 25,
    pages: int = 1,
    action: str | None = "OriginalAll",
    fetcher: JsonFetcher = fetch_json_url,
    sleep_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    tail_mark = "0"
    for page_index in range(max(pages, 0)):
        url = profile_activity_url(
            profile.member_id,
            api_base=api_base,
            limit=limit,
            tail_mark=tail_mark,
            action=action,
        )
        payload = fetcher(url, profile_activity_headers(profile.member_id, profile.profile_url))
        if not isinstance(payload, dict):
            raise LongbridgeProfileActivityError(f"Longbridge activity response is not a JSON object: {url}")
        if payload.get("code") not in (None, 0):
            raise LongbridgeProfileActivityError(
                f"Longbridge activity response failed for {profile.member_id}: {payload.get('message') or payload}"
            )
        payloads.append(payload)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        activities = data.get("activities") if isinstance(data, dict) else []
        next_params = data.get("next_params") if isinstance(data, dict) else {}
        next_tail_mark = str((next_params or {}).get("tail_mark") or "")
        if not activities or not next_tail_mark:
            break
        tail_mark = next_tail_mark
        if sleep_seconds and page_index < pages - 1:
            time.sleep(sleep_seconds)
    return payloads


def normalize_longbridge_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if text.isdigit() and len(text) > 11:
        parsed = dt.datetime.fromtimestamp(int(text) / 1_000_000, tz=dt.UTC)
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        return normalize_timestamp(value)
    except (TypeError, ValueError, OSError, OverflowError):
        return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def activity_target(activity: dict[str, Any]) -> dict[str, Any]:
    target = first_dict(activity.get("targets"))
    if target:
        return target
    return first_dict(activity.get("target"))


def activity_author_name(activity: dict[str, Any], target: dict[str, Any], fallback: FollowedLongbridgeProfile) -> str:
    actor = first_dict(activity.get("actors"))
    author = first_dict(target.get("author"))
    name = str(actor.get("name") or author.get("name") or fallback.name or "").strip()
    return f"Longbridge:{name}" if name else "Longbridge"


def activity_url(target: dict[str, Any], fallback: FollowedLongbridgeProfile) -> str:
    for field in ("web_url", "detail_url", "url", "share_url"):
        value = str(target.get(field) or "").strip()
        if value:
            return value
    target_id = str(target.get("id") or target.get("topic_id") or "").strip()
    if target_id:
        return f"https://longbridge.cn/topics/{target_id}"
    return fallback.profile_url or canonical_profile_url(fallback.member_id)


def counter_tokens(target: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    counter_ids = target.get("counter_ids")
    if isinstance(counter_ids, list):
        for counter_id in counter_ids:
            text = str(counter_id or "").strip()
            if not text:
                continue
            tokens.append(text)
            parts = [part for part in text.split("/") if part]
            if len(parts) >= 3:
                tokens.append(parts[-1])
                tokens.append(f"{parts[-1]}.{parts[-2]}")
    return list(dict.fromkeys(tokens))


def activity_text(target: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("title", "name", "summary", "description", "description_html", "body", "content"):
        value = str(target.get(field) or "").strip()
        if value:
            parts.append(strip_html(value))
    parts.extend(counter_tokens(target))
    return " ".join(part for part in parts if part).strip()


def activity_to_source_row(
    activity: dict[str, Any],
    fallback: FollowedLongbridgeProfile,
    *,
    min_text_chars: int = 1,
) -> dict[str, str] | None:
    target = activity_target(activity)
    item_id_value = str(activity.get("id") or activity.get("activity_id") or target.get("id") or "").strip()
    if not item_id_value:
        return None
    text = activity_text(target)
    if len(text) < min_text_chars:
        return None
    published_at = normalize_longbridge_timestamp(
        target.get("published_at")
        or target.get("created_at")
        or activity.get("created_at")
        or activity.get("created_at_micro")
    )
    return {
        "item_id": f"longbridge-activity-{item_id_value}",
        "published_at": published_at,
        "source_type": LONGBRIDGE_SOURCE_TYPE,
        "source_url": activity_url(target, fallback),
        "author": activity_author_name(activity, target, fallback),
        "text": text,
    }


def iter_profile_activity_rows(raw_profiles: Iterable[dict[str, Any]], *, min_text_chars: int = 1) -> Iterable[dict[str, str]]:
    for raw_profile in raw_profiles:
        fallback = FollowedLongbridgeProfile(
            member_id=str(raw_profile.get("member_id") or "").strip(),
            name=str(raw_profile.get("name") or "").strip(),
            profile_url=str(raw_profile.get("profile_url") or "").strip(),
        )
        for page in raw_profile.get("pages") or []:
            for activity in iter_activities(page):
                row = activity_to_source_row(activity, fallback, min_text_chars=min_text_chars)
                if row:
                    yield row


def write_profile_activity_source_items(
    raw_profiles: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    min_text_chars: int = 1,
) -> list[dict[str, str]]:
    rows_by_id: dict[str, dict[str, str]] = {}
    for row in iter_profile_activity_rows(raw_profiles, min_text_chars=min_text_chars):
        rows_by_id[row["item_id"]] = row
    rows = sorted(rows_by_id.values(), key=lambda row: (row["published_at"], row["item_id"]))
    write_csv_rows(output_path, SOURCE_ITEM_FIELDS, rows)
    return rows


def fetch_longbridge_profile_activities(
    *,
    author_allowlist_path: str | Path | None = None,
    member_ids: list[str] | None = None,
    raw_output_path: str | Path | None = None,
    source_items_output_path: str | Path | None = None,
    api_base: str = DEFAULT_API_BASE,
    limit: int = 25,
    pages: int = 1,
    action: str | None = "OriginalAll",
    min_text_chars: int = 1,
    fetcher: JsonFetcher = fetch_json_url,
) -> list[dict[str, str]]:
    profiles: list[FollowedLongbridgeProfile] = []
    if author_allowlist_path:
        profiles.extend(load_followed_profiles(author_allowlist_path))
    if member_ids:
        existing = {profile.member_id for profile in profiles}
        for member_id in member_ids:
            clean_member_id = member_id.strip()
            if clean_member_id and clean_member_id not in existing:
                existing.add(clean_member_id)
                profiles.append(
                    FollowedLongbridgeProfile(
                        member_id=clean_member_id,
                        profile_url=canonical_profile_url(clean_member_id),
                    )
                )
    if not profiles:
        raise LongbridgeProfileActivityError("No Longbridge member_id values were provided.")

    raw_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        payloads = fetch_profile_activity_pages(
            profile,
            api_base=api_base,
            limit=limit,
            pages=pages,
            action=action,
            fetcher=fetcher,
        )
        raw_profiles.append(
            {
                "member_id": profile.member_id,
                "name": profile.name,
                "profile_url": profile.profile_url,
                "pages": payloads,
            }
        )

    if raw_output_path:
        raw_output = Path(raw_output_path)
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_text(
            json.dumps(
                {
                    "fetched_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "api_base": api_base,
                    "action": action or "",
                    "profiles": raw_profiles,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if source_items_output_path:
        return write_profile_activity_source_items(raw_profiles, source_items_output_path, min_text_chars=min_text_chars)
    return list(iter_profile_activity_rows(raw_profiles, min_text_chars=min_text_chars))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experimentally fetch public Longbridge profile activities into source_items CSV."
    )
    parser.add_argument("--author-allowlist", help="CSV with member_id/name columns for followed authors.")
    parser.add_argument("--member-id", nargs="*", default=[], help="Additional Longbridge member_id values to fetch.")
    parser.add_argument("--raw-output", help="Optional raw JSON output.")
    parser.add_argument("--source-items-output", help="Optional source_items CSV output.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--action", default="OriginalAll", help="Longbridge activity action filter. Empty string means all.")
    parser.add_argument("--min-text-chars", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    if not args.raw_output and not args.source_items_output:
        raise SystemExit("Provide at least one of --raw-output or --source-items-output.")
    try:
        fetch_longbridge_profile_activities(
            author_allowlist_path=args.author_allowlist,
            member_ids=args.member_id,
            raw_output_path=args.raw_output,
            source_items_output_path=args.source_items_output,
            api_base=args.api_base,
            limit=args.limit,
            pages=args.pages,
            action=args.action or None,
            min_text_chars=args.min_text_chars,
        )
    except LongbridgeProfileActivityError as exc:
        raise SystemExit(f"Longbridge profile activity fetch failed: {exc}") from exc


if __name__ == "__main__":
    main()
