from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .csv_utils import read_csv_rows, write_csv_rows


X_RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
USER_AGENT = "QuantStrategyLabSourceIngest/0.1 (https://github.com/QuantStrategyLab/PoliticalEventTrackingResearch)"


@dataclass(frozen=True)
class XQueryConfig:
    query_id: str
    query: str
    source_type: str
    author_label: str


def load_query_config(path: str | Path) -> list[XQueryConfig]:
    configs: list[XQueryConfig] = []
    for row in read_csv_rows(path):
        configs.append(
            XQueryConfig(
                query_id=row["query_id"],
                query=row["query"],
                source_type=row.get("source_type") or "verified_social_post",
                author_label=row.get("author_label") or "X",
            )
        )
    return configs


def build_recent_search_url(query: str, *, max_results: int, next_token: str | None = None) -> str:
    params = {
        "query": query,
        "max_results": str(max_results),
        "tweet.fields": "created_at,author_id,text",
        "expansions": "author_id",
        "user.fields": "name,username,verified",
    }
    if next_token:
        params["next_token"] = next_token
    return f"{X_RECENT_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def fetch_recent_search_page(url: str, bearer_token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_x_response(payload: dict[str, Any], config: XQueryConfig) -> list[dict[str, str]]:
    users = {
        user.get("id"): user
        for user in payload.get("includes", {}).get("users", [])
        if isinstance(user, dict) and user.get("id")
    }
    rows: list[dict[str, str]] = []
    for tweet in payload.get("data", []) or []:
        tweet_id = str(tweet["id"])
        user = users.get(tweet.get("author_id"), {})
        username = user.get("username")
        author = user.get("name") or username or config.author_label
        source_url = f"https://x.com/{username}/status/{tweet_id}" if username else f"https://x.com/i/web/status/{tweet_id}"
        rows.append(
            {
                "item_id": f"x-{config.query_id}-{tweet_id}",
                "published_at": tweet["created_at"],
                "source_type": config.source_type,
                "source_url": source_url,
                "author": author,
                "text": tweet.get("text", ""),
            }
        )
    return rows


def fetch_x_recent_search(
    queries_path: str | Path,
    output_path: str | Path,
    *,
    bearer_token: str,
    max_results: int = 10,
    max_pages: int = 1,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for config in load_query_config(queries_path):
        next_token: str | None = None
        for _ in range(max_pages):
            url = build_recent_search_url(config.query, max_results=max_results, next_token=next_token)
            payload = fetch_recent_search_page(url, bearer_token)
            rows.extend(parse_x_response(payload, config))
            next_token = payload.get("meta", {}).get("next_token")
            if not next_token:
                break
    rows.sort(key=lambda row: (row["published_at"], row["item_id"]))
    write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], rows)
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch X API v2 recent search results into source_items CSV schema.")
    parser.add_argument("--queries", required=True, help="X recent-search query config CSV.")
    parser.add_argument("--output", required=True, help="Output source_items CSV.")
    parser.add_argument("--max-results", type=int, default=10, help="X max_results per request; X allows 10-100.")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum pages per query.")
    parser.add_argument("--bearer-token-env", default="X_BEARER_TOKEN", help="Environment variable containing X bearer token.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    token = os.environ.get(args.bearer_token_env)
    if not token:
        raise SystemExit(f"Missing X bearer token env var: {args.bearer_token_env}")
    fetch_x_recent_search(
        args.queries,
        args.output,
        bearer_token=token,
        max_results=args.max_results,
        max_pages=args.max_pages,
    )


if __name__ == "__main__":
    main()

