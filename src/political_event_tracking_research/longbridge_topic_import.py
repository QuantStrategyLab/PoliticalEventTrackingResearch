from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .csv_utils import read_csv_rows, write_csv_rows
from .rss_source_fetch import strip_html


LONGBRIDGE_SOURCE_TYPE = "community_research_lead"


@dataclass(frozen=True)
class LongbridgeAuthor:
    member_id: str
    name: str


@dataclass(frozen=True)
class AuthorAllowlist:
    member_ids: frozenset[str]
    names: frozenset[str]

    def allows(self, author: LongbridgeAuthor) -> bool:
        if not self.member_ids and not self.names:
            return True
        if author.member_id and author.member_id in self.member_ids:
            return True
        return bool(author.name and author.name.casefold() in self.names)


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def iter_topic_items(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(payload, dict):
        return

    data = payload.get("data")
    if isinstance(data, dict):
        item = data.get("item")
        if isinstance(item, dict):
            yield item
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    yield item
    item = payload.get("item")
    if isinstance(item, dict):
        yield item
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                yield item


def load_author_allowlist(path: str | Path | None) -> AuthorAllowlist:
    if not path:
        return AuthorAllowlist(member_ids=frozenset(), names=frozenset())
    member_ids: set[str] = set()
    names: set[str] = set()
    for row in read_csv_rows(path):
        member_id = (row.get("member_id") or "").strip()
        name = (row.get("name") or "").strip()
        if member_id:
            member_ids.add(member_id)
        if name:
            names.add(name.casefold())
    return AuthorAllowlist(member_ids=frozenset(member_ids), names=frozenset(names))


def integer_field(item: dict[str, Any], name: str) -> int:
    value = item.get(name, 0)
    if value in ("", None):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if text.isdigit():
        parsed = dt.datetime.fromtimestamp(int(text), tz=dt.UTC)
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def topic_id(item: dict[str, Any]) -> str:
    value = str(item.get("id") or item.get("topic_id") or "").strip()
    if not value:
        raise ValueError("Longbridge topic item missing id")
    return value


def topic_author(item: dict[str, Any]) -> LongbridgeAuthor:
    author = item.get("author")
    if not isinstance(author, dict):
        author = {}
    member_id = str(author.get("member_id") or item.get("author_member_id") or "").strip()
    name = str(author.get("name") or item.get("author_name") or "").strip()
    return LongbridgeAuthor(member_id=member_id, name=name)


def topic_url(item: dict[str, Any], item_id: str) -> str:
    return str(item.get("detail_url") or item.get("url") or f"https://longbridge.cn/topics/{item_id}")


def topic_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("title", "description", "body"):
        value = str(item.get(field) or "").strip()
        if value:
            parts.append(strip_html(value))
    tickers = item.get("tickers") or []
    if isinstance(tickers, list) and tickers:
        parts.append(" ".join(str(ticker) for ticker in tickers if ticker))
    hashtags = item.get("hashtags") or []
    if isinstance(hashtags, list) and hashtags:
        parts.append(" ".join(f"#{tag}" for tag in hashtags if tag))
    return " ".join(part for part in parts if part)


def topic_passes_engagement_filter(
    item: dict[str, Any],
    *,
    min_likes: int,
    min_comments: int,
    min_shares: int,
    min_views: int,
) -> bool:
    return (
        integer_field(item, "likes_count") >= min_likes
        and integer_field(item, "comments_count") >= min_comments
        and integer_field(item, "shares_count") >= min_shares
        and integer_field(item, "views_count") >= min_views
    )


def import_longbridge_topics(
    input_paths: list[str | Path],
    output_path: str | Path,
    *,
    author_allowlist_path: str | Path | None = None,
    min_likes: int = 0,
    min_comments: int = 0,
    min_shares: int = 0,
    min_views: int = 0,
) -> list[dict[str, str]]:
    allowlist = load_author_allowlist(author_allowlist_path)
    rows_by_id: dict[str, dict[str, str]] = {}
    for input_path in input_paths:
        for item in iter_topic_items(load_json(input_path)):
            item_id = topic_id(item)
            author = topic_author(item)
            if not allowlist.allows(author):
                continue
            if not topic_passes_engagement_filter(
                item,
                min_likes=min_likes,
                min_comments=min_comments,
                min_shares=min_shares,
                min_views=min_views,
            ):
                continue
            published_at = normalize_timestamp(item.get("created_at") or item.get("published_at"))
            rows_by_id[f"longbridge-{item_id}"] = {
                "item_id": f"longbridge-{item_id}",
                "published_at": published_at,
                "source_type": LONGBRIDGE_SOURCE_TYPE,
                "source_url": topic_url(item, item_id),
                "author": f"Longbridge:{author.name}" if author.name else "Longbridge",
                "text": topic_text(item),
            }
    rows = sorted(rows_by_id.values(), key=lambda row: (row["published_at"], row["item_id"]))
    write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], rows)
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Longbridge community topic JSON into source_items CSV schema.")
    parser.add_argument("--input", nargs="+", required=True, help="Longbridge topic list/detail JSON file(s).")
    parser.add_argument("--output", required=True, help="Output source_items CSV.")
    parser.add_argument("--author-allowlist", help="Optional CSV with member_id,name columns for followed authors.")
    parser.add_argument("--min-likes", type=int, default=0)
    parser.add_argument("--min-comments", type=int, default=0)
    parser.add_argument("--min-shares", type=int, default=0)
    parser.add_argument("--min-views", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    import_longbridge_topics(
        args.input,
        args.output,
        author_allowlist_path=args.author_allowlist,
        min_likes=args.min_likes,
        min_comments=args.min_comments,
        min_shares=args.min_shares,
        min_views=args.min_views,
    )


if __name__ == "__main__":
    main()
