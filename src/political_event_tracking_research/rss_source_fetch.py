from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .csv_utils import read_csv_rows, write_csv_rows


USER_AGENT = (
    "Mozilla/5.0 (compatible; QuantStrategyLabSourceIngest/0.1; "
    "+https://github.com/QuantStrategyLab/PoliticalEventTrackingResearch)"
)
MAX_XML_BYTES = 1024 * 1024


@dataclass(frozen=True)
class FeedConfig:
    feed_id: str
    feed_url: str
    source_type: str
    author: str


@dataclass(frozen=True)
class FeedFetchStatus:
    feed_id: str
    feed_url: str
    ok: bool
    item_count: int
    error: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "feed_id": self.feed_id,
            "feed_url": self.feed_url,
            "ok": self.ok,
            "item_count": self.item_count,
            "error": self.error,
        }


class FeedXmlError(ValueError):
    """Sanitized producer-boundary XML failure."""


def load_feed_config(path: str | Path) -> list[FeedConfig]:
    feeds: list[FeedConfig] = []
    for row in read_csv_rows(path):
        feeds.append(
            FeedConfig(
                feed_id=row["feed_id"],
                feed_url=row["feed_url"],
                source_type=row["source_type"],
                author=row.get("author", ""),
            )
        )
    return feeds


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(MAX_XML_BYTES + 1)
    if len(payload) > MAX_XML_BYTES:
        raise FeedXmlError("feed_xml_oversize")
    return payload


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return html.unescape(re.sub(r"\s+", " ", text).strip())


def parse_datetime(value: str, *, allow_missing: bool = True) -> str:
    text = (value or "").strip()
    if not text:
        if not allow_missing:
            raise FeedXmlError("feed_date_missing")
        return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rss_child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    wanted = set(names)
    for child in element:
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def rss_item_link(item: ET.Element) -> str:
    guid = _rss_child_text(item, ("guid",))
    link = _rss_child_text(item, ("link",))
    return link or guid


def atom_entry_link(entry: ET.Element) -> str:
    for child in entry:
        if child.tag.endswith("link"):
            href = child.attrib.get("href")
            if href:
                return href
    return child_text(entry, ("{http://www.w3.org/2005/Atom}id", "id"))


def stable_item_id(feed_id: str, link: str, title: str) -> str:
    digest = hashlib.sha1(f"{feed_id}|{link}|{title}".encode("utf-8")).hexdigest()[:12]
    return f"{feed_id}-{digest}"


def parse_feed_snapshot(
    feed_bytes: bytes,
    feed: FeedConfig,
    *,
    max_items: int = 25,
    allow_missing_dates: bool = True,
) -> tuple[str, list[dict[str, str]]]:
    if type(feed_bytes) is not bytes:
        raise FeedXmlError("feed_xml_invalid")
    if len(feed_bytes) > MAX_XML_BYTES:
        raise FeedXmlError("feed_xml_oversize")
    try:
        root = ET.fromstring(feed_bytes, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, LookupError, UnicodeError, ValueError, RecursionError):
        raise FeedXmlError("feed_xml_invalid") from None
    rows: list[dict[str, str]] = []

    is_rss = _local_name(root.tag) == "rss"
    channel = next((child for child in root if _local_name(child.tag) == "channel"), None) if is_rss else None
    if channel is not None:
        items = [child for child in channel if _local_name(child.tag) == "item"]
        for item in items[:max_items]:
            title = _rss_child_text(item, ("title",))
            link = rss_item_link(item)
            published = _rss_child_text(item, ("pubDate", "date"))
            description = _rss_child_text(item, ("description", "encoded"))
            text = " ".join(part for part in (title, strip_html(description)) if part)
            rows.append(
                {
                    "item_id": stable_item_id(feed.feed_id, link, title),
                    "published_at": parse_datetime(published, allow_missing=allow_missing_dates),
                    "source_type": feed.source_type,
                    "source_url": link,
                    "author": feed.author,
                    "text": text,
                }
            )
        return "rss2", rows

    atom_entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    for entry in atom_entries[:max_items]:
        title = child_text(entry, ("{http://www.w3.org/2005/Atom}title", "title"))
        link = atom_entry_link(entry)
        published = child_text(
            entry,
            ("{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated", "published", "updated"),
        )
        summary = child_text(entry, ("{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"))
        text = " ".join(part for part in (title, strip_html(summary)) if part)
        rows.append(
            {
                "item_id": stable_item_id(feed.feed_id, link, title),
                "published_at": parse_datetime(published, allow_missing=allow_missing_dates),
                "source_type": feed.source_type,
                "source_url": link,
                "author": feed.author,
                "text": text,
            }
        )
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise FeedXmlError("feed_xml_invalid")
    return "atom", rows


def parse_feed_items(feed_bytes: bytes, feed: FeedConfig, *, max_items: int = 25) -> list[dict[str, str]]:
    return parse_feed_snapshot(feed_bytes, feed, max_items=max_items)[1]


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_fetch_status(path: str | Path, statuses: list[FeedFetchStatus], *, item_count: int) -> None:
    payload = {
        "generated_at": utc_now_iso(),
        "feed_count": len(statuses),
        "successful_feed_count": sum(1 for item in statuses if item.ok),
        "failed_feed_count": sum(1 for item in statuses if not item.ok),
        "item_count": item_count,
        "feeds": [item.to_json() for item in statuses],
    }
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_rss_sources(
    feeds_path: str | Path,
    output_path: str | Path,
    *,
    max_items_per_feed: int = 25,
    continue_on_feed_error: bool = False,
    status_output: str | Path | None = None,
    fetcher: Callable[[str], bytes] = fetch_url,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    statuses: list[FeedFetchStatus] = []
    for feed in load_feed_config(feeds_path):
        try:
            feed_rows = parse_feed_items(fetcher(feed.feed_url), feed, max_items=max_items_per_feed)
        except Exception as exc:
            statuses.append(
                FeedFetchStatus(
                    feed_id=feed.feed_id,
                    feed_url=feed.feed_url,
                    ok=False,
                    item_count=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            if not continue_on_feed_error:
                raise
            continue
        rows.extend(feed_rows)
        statuses.append(
            FeedFetchStatus(
                feed_id=feed.feed_id,
                feed_url=feed.feed_url,
                ok=True,
                item_count=len(feed_rows),
            )
        )
    if statuses and not any(item.ok for item in statuses):
        if status_output:
            write_fetch_status(status_output, statuses, item_count=0)
        raise RuntimeError("all configured RSS/Atom feeds failed")
    rows.sort(key=lambda row: (row["published_at"], row["item_id"]))
    write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], rows)
    if status_output:
        write_fetch_status(status_output, statuses, item_count=len(rows))
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch RSS/Atom feeds into source_items CSV schema.")
    parser.add_argument("--feeds", required=True, help="Feed config CSV.")
    parser.add_argument("--output", required=True, help="Output source_items CSV.")
    parser.add_argument("--max-items-per-feed", type=int, default=25)
    parser.add_argument(
        "--continue-on-feed-error",
        action="store_true",
        help="Continue when one RSS/Atom feed fails and record the failure in --status-output.",
    )
    parser.add_argument("--status-output", help="Optional JSON feed-health status output path.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    fetch_rss_sources(
        args.feeds,
        args.output,
        max_items_per_feed=args.max_items_per_feed,
        continue_on_feed_error=args.continue_on_feed_error,
        status_output=args.status_output,
    )


if __name__ == "__main__":
    main()
