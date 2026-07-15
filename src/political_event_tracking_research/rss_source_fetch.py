from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .csv_utils import read_csv_rows, write_csv_rows
from .feed_primitives import PrimitiveRow, build_status, serialize_status


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


@dataclass(frozen=True)
class ParsedFeed:
    feed_kind: str
    entries: tuple[MappingProxyType, ...]


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


def parse_datetime(value: str) -> str:
    text = (value or "").strip()
    if not text:
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


def rss_item_link(item: ET.Element) -> str:
    guid = child_text(item, ("guid",))
    link = child_text(item, ("link",))
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


_RSS_FOREIGN_METADATA = frozenset(
    {
        "{http://www.w3.org/2005/Atom}link",
        "{http://purl.org/dc/elements/1.1/}date",
        "{http://purl.org/dc/elements/1.1/}creator",
        "{http://purl.org/dc/elements/1.1/}subject",
        "{http://purl.org/rss/1.0/modules/content/}encoded",
        "{http://purl.org/rss/1.0/modules/syndication/}updatePeriod",
        "{http://purl.org/rss/1.0/modules/syndication/}updateFrequency",
        "{http://purl.org/rss/1.0/modules/syndication/}updateBase",
    }
)


def parse_feed_snapshot(feed_bytes: bytes, feed: FeedConfig, *, max_items: int = 25) -> ParsedFeed:
    if type(feed_bytes) is not bytes:
        raise FeedXmlError("feed_xml_invalid")
    if len(feed_bytes) > MAX_XML_BYTES:
        raise FeedXmlError("feed_xml_oversize")
    try:
        root = ET.fromstring(feed_bytes, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, LookupError, UnicodeError, ValueError, RecursionError):
        raise FeedXmlError("feed_xml_invalid") from None
    def rows_for(items: list[ET.Element], kind: str) -> ParsedFeed:
        try:
            rows: list[dict[str, str]] = []
            for item in items[:max_items]:
                if kind == "rss2":
                    title = child_text(item, ("title",))
                    link = rss_item_link(item)
                    published = child_text(item, ("pubDate", "{http://purl.org/dc/elements/1.1/}date"))
                    description = child_text(item, ("description", "{http://purl.org/rss/1.0/modules/content/}encoded"))
                    text = " ".join(part for part in (title, strip_html(description)) if part)
                else:
                    title = child_text(item, ("{http://www.w3.org/2005/Atom}title", "title"))
                    link = atom_entry_link(item)
                    published = child_text(
                        item,
                        (
                            "{http://www.w3.org/2005/Atom}published",
                            "{http://www.w3.org/2005/Atom}updated",
                            "published",
                            "updated",
                        ),
                    )
                    summary = child_text(
                        item,
                        ("{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"),
                    )
                    text = " ".join(part for part in (title, strip_html(summary)) if part)
                rows.append(
                    {
                        "item_id": stable_item_id(feed.feed_id, link, title),
                        "published_at": parse_datetime(published),
                        "source_type": feed.source_type,
                        "source_url": link,
                        "author": feed.author,
                        "text": text,
                    }
                )
            return ParsedFeed(kind, tuple(MappingProxyType(row) for row in rows))
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise FeedXmlError("feed_xml_invalid") from None

    if root.tag == "rss":
        if root.attrib.get("version") != "2.0" or len(root) != 1 or root[0].tag != "channel":
            raise FeedXmlError("feed_schema_invalid")
        channel = root[0]
        allowed = {
            "title",
            "link",
            "description",
            "language",
            "copyright",
            "managingEditor",
            "webMaster",
            "pubDate",
            "lastBuildDate",
            "category",
            "generator",
            "docs",
            "cloud",
            "ttl",
            "image",
            "rating",
            "textInput",
            "skipHours",
            "skipDays",
            "item",
        }
        if any(child.tag not in allowed and child.tag not in _RSS_FOREIGN_METADATA for child in channel):
            raise FeedXmlError("feed_schema_invalid")
        items = [child for child in channel if child.tag == "item"]
        return rows_for(items, "rss2")

    atom_root = "{http://www.w3.org/2005/Atom}feed"
    atom_entry = "{http://www.w3.org/2005/Atom}entry"
    atom_metadata = {
        "{http://www.w3.org/2005/Atom}id",
        "{http://www.w3.org/2005/Atom}title",
        "{http://www.w3.org/2005/Atom}updated",
        "{http://www.w3.org/2005/Atom}subtitle",
        "{http://www.w3.org/2005/Atom}link",
        "{http://www.w3.org/2005/Atom}author",
        "{http://www.w3.org/2005/Atom}category",
        "{http://www.w3.org/2005/Atom}contributor",
        "{http://www.w3.org/2005/Atom}generator",
        "{http://www.w3.org/2005/Atom}icon",
        "{http://www.w3.org/2005/Atom}logo",
        "{http://www.w3.org/2005/Atom}rights",
    }
    if root.tag == atom_root and all(child.tag in atom_metadata or child.tag == atom_entry for child in root):
        return rows_for([child for child in root if child.tag == atom_entry], "atom")
    raise FeedXmlError("feed_schema_invalid")


def parse_feed_items(feed_bytes: bytes, feed: FeedConfig, *, max_items: int = 25) -> list[dict[str, str]]:
    return [dict(row) for row in parse_feed_snapshot(feed_bytes, feed, max_items=max_items).entries]


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_fetch_status(path: str | Path, feed_records: list[dict[str, object]]) -> None:
    payload = serialize_status(build_status(feed_records))
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)


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
    feed_records: list[dict[str, object]] = []
    for feed in load_feed_config(feeds_path):
        try:
            parsed = parse_feed_snapshot(fetcher(feed.feed_url), feed, max_items=max_items_per_feed)
            feed_rows = [PrimitiveRow.from_mapping(row).to_mapping() for row in parsed.entries]
            feed_records.append(
                {
                    "feed_id": feed.feed_id,
                    "feed_url": feed.feed_url,
                    "kind": parsed.feed_kind,
                    "state": "accepted" if feed_rows else "quarantined",
                    "rows": feed_rows,
                    "error_code": None if feed_rows else "zero_entries",
                }
            )
            rows.extend(feed_rows)
        except (
            DefusedXmlException,
            ET.ParseError,
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            UnicodeError,
        ) as exc:
            code = getattr(exc, "code", "fetch_failed")
            if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                code = "fetch_failed"
            feed_records.append(
                {
                    "feed_id": feed.feed_id,
                    "feed_url": feed.feed_url,
                    "kind": "unknown",
                    "state": "failed",
                    "rows": [],
                    "error_code": code,
                }
            )
            if not continue_on_feed_error:
                raise
    if feed_records and not any(record["state"] == "accepted" for record in feed_records):
        if status_output:
            write_fetch_status(status_output, feed_records)
        if any(record["state"] == "failed" for record in feed_records):
            raise RuntimeError("all configured RSS/Atom feeds failed")
        write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], [])
        return []
    rows.sort(key=lambda row: (row["published_at"], row["item_id"]))
    write_csv_rows(output_path, ["item_id", "published_at", "source_type", "source_url", "author", "text"], rows)
    if status_output:
        write_fetch_status(status_output, feed_records)
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
