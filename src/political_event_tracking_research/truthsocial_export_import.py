from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .csv_utils import write_csv_rows
from .rss_source_fetch import strip_html


def load_export(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        if isinstance(payload.get("posts"), list):
            return payload["posts"]
        if isinstance(payload.get("statuses"), list):
            return payload["statuses"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Truth Social export must be a list or an object with posts/statuses/data list")


def post_url(post: dict[str, Any]) -> str:
    url = post.get("url") or post.get("uri")
    if url:
        return str(url)
    account = post.get("account") or {}
    username = account.get("username") or account.get("acct") or "unknown"
    post_id = post.get("id") or post.get("post_id") or "unknown"
    return f"https://truthsocial.com/@{username}/posts/{post_id}"


def post_author(post: dict[str, Any]) -> str:
    account = post.get("account") or {}
    return str(account.get("display_name") or account.get("username") or account.get("acct") or "Truth Social")


def post_text(post: dict[str, Any]) -> str:
    text = post.get("text") or post.get("content") or post.get("body") or ""
    return strip_html(str(text))


def normalize_created_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Truth Social post missing created_at")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}$", text):
        return f"{text}T00:00:00Z"
    return text


def import_truthsocial_export(input_path: str | Path, output_path: str | Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for post in load_export(input_path):
        post_id = str(post.get("id") or post.get("post_id") or len(rows))
        rows.append(
            {
                "item_id": f"truthsocial-{post_id}",
                "published_at": normalize_created_at(post.get("created_at") or post.get("published_at")),
                "source_type": "verified_social_post",
                "source_url": post_url(post),
                "author": post_author(post),
                "text": post_text(post),
            }
        )
    rows.sort(key=lambda row: (row["published_at"], row["item_id"]))
    write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], rows)
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a Truth Social JSON export into source_items CSV schema.")
    parser.add_argument("--input", required=True, help="Truth Social JSON export.")
    parser.add_argument("--output", required=True, help="Output source_items CSV.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    import_truthsocial_export(args.input, args.output)


if __name__ == "__main__":
    main()

