from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .csv_utils import write_csv_rows
from .truthsocial_export_import import normalize_posts


TRUTHSOCIAL_BASE_URL = "https://truthsocial.com"
USER_AGENT = "QuantStrategyLabSourceIngest/0.1 (https://github.com/QuantStrategyLab/PoliticalEventTrackingResearch)"


class TruthSocialFetchError(RuntimeError):
    pass


def fetch_json(url: str) -> dict[str, Any] | list[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise TruthSocialFetchError(f"HTTP {exc.code} from Truth Social public endpoint.") from exc
    except urllib.error.URLError as exc:
        raise TruthSocialFetchError(f"Network error from Truth Social public endpoint: {exc.reason}") from exc
    if "json" not in content_type.lower() and body.lstrip().startswith("<"):
        raise TruthSocialFetchError("Truth Social returned HTML instead of JSON; public API access may be blocked.")
    return json.loads(body)


def lookup_account(username: str, fetcher: Callable[[str], dict[str, Any] | list[dict[str, Any]]] = fetch_json) -> str:
    acct = username.lstrip("@")
    url = f"{TRUTHSOCIAL_BASE_URL}/api/v1/accounts/lookup?{urllib.parse.urlencode({'acct': acct})}"
    payload = fetcher(url)
    if not isinstance(payload, dict):
        raise TruthSocialFetchError("Truth Social account lookup returned an unexpected payload.")
    account_id = str(payload.get("id") or "").strip()
    if not account_id:
        raise TruthSocialFetchError(f"Truth Social account lookup did not return an id for {username!r}.")
    return account_id


def fetch_statuses(
    account_id: str,
    *,
    limit: int,
    fetcher: Callable[[str], dict[str, Any] | list[dict[str, Any]]] = fetch_json,
) -> list[dict[str, Any]]:
    params = {
        "exclude_replies": "true",
        "only_replies": "false",
        "with_muted": "true",
        "limit": str(limit),
    }
    url = f"{TRUTHSOCIAL_BASE_URL}/api/v1/accounts/{account_id}/statuses?{urllib.parse.urlencode(params)}"
    payload = fetcher(url)
    if isinstance(payload, list):
        return [post for post in payload if isinstance(post, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [post for post in payload["data"] if isinstance(post, dict)]
    raise TruthSocialFetchError("Truth Social statuses endpoint returned an unexpected payload.")


def fetch_truthsocial_public_posts(
    username: str,
    output_path: str | Path,
    *,
    limit: int = 20,
    fetcher: Callable[[str], dict[str, Any] | list[dict[str, Any]]] = fetch_json,
) -> list[dict[str, str]]:
    account_id = lookup_account(username, fetcher)
    posts = fetch_statuses(account_id, limit=limit, fetcher=fetcher)
    rows = normalize_posts(posts)
    write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], rows)
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Try to fetch public Truth Social account posts into source_items CSV schema."
    )
    parser.add_argument("--username", default="realDonaldTrump", help="Truth Social account username.")
    parser.add_argument("--output", required=True, help="Output source_items CSV.")
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        fetch_truthsocial_public_posts(args.username, args.output, limit=args.limit)
    except TruthSocialFetchError as exc:
        raise SystemExit(f"Truth Social public fetch failed: {exc}") from exc


if __name__ == "__main__":
    main()
