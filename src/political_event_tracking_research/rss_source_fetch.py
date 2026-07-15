from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import html
import io
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .csv_utils import read_csv_rows
from .feed_status_canonical_h2c import (
    CanonicalDecision,
    DecisionContractError,
    DecisionKind,
    build_decision,
    read_status,
)


USER_AGENT = (
    "Mozilla/5.0 (compatible; QuantStrategyLabSourceIngest/0.1; "
    "+https://github.com/QuantStrategyLab/PoliticalEventTrackingResearch)"
)
MAX_XML_BYTES = 1024 * 1024
SOURCE_ITEM_FIELDS = ("item_id", "published_at", "source_type", "source_url", "author", "text")


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
    kind: str
    state: str
    rows: tuple[dict[str, str], ...] = ()
    error_code: str | None = None

    def to_outcome(self) -> dict[str, object]:
        return {
            "feed_id": self.feed_id,
            "feed_url": self.feed_url,
            "kind": self.kind,
            "state": self.state,
            "rows": list(self.rows),
            "error_code": self.error_code,
        }


class FeedXmlError(ValueError):
    """Sanitized producer-boundary XML failure."""


class FetchStatusError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_fetch_status(payload: object, *, fetch_exit: int = 0) -> bool:
    if type(fetch_exit) is not int or fetch_exit < 0:
        raise FetchStatusError("fetch_exit_invalid")
    if fetch_exit != 0:
        raise FetchStatusError("fetch_failed")
    try:
        status_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        parsed = read_status(status_bytes)
    except (DecisionContractError, TypeError, UnicodeError, ValueError):
        raise FetchStatusError("fetch_status_invalid") from None
    return parsed["eligible_for_live_publication"] is True


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


def parse_feed_snapshot(
    feed_bytes: bytes, feed: FeedConfig, *, max_items: int = 25
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

    if root.tag == "rss":
        channel = root.find("./channel")
        if channel is None:
            raise FeedXmlError("feed_xml_invalid")
        rss_items = channel.findall("./item")
        for item in rss_items[:max_items]:
            title = child_text(item, ("title",))
            link = rss_item_link(item)
            published = child_text(item, ("pubDate", "{http://purl.org/dc/elements/1.1/}date"))
            description = child_text(item, ("description", "{http://purl.org/rss/1.0/modules/content/}encoded"))
            text = " ".join(part for part in (title, strip_html(description)) if part)
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
        return "rss2", rows

    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise FeedXmlError("feed_xml_invalid")
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
                "published_at": parse_datetime(published),
                "source_type": feed.source_type,
                "source_url": link,
                "author": feed.author,
                "text": text,
            }
        )
    return "atom", rows


def parse_feed_items(feed_bytes: bytes, feed: FeedConfig, *, max_items: int = 25) -> list[dict[str, str]]:
    return parse_feed_snapshot(feed_bytes, feed, max_items=max_items)[1]


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_fetch_status(statuses: list[FeedFetchStatus]) -> CanonicalDecision:
    if not statuses:
        raise FetchStatusError("feed_config_empty")
    try:
        decision = build_decision(item.to_outcome() for item in statuses)
        read_status(decision.status_bytes)
    except DecisionContractError as exc:
        raise FetchStatusError(exc.code) from None
    return decision


def write_fetch_status(path: str | Path, statuses: list[FeedFetchStatus]) -> DecisionKind:
    decision = build_fetch_status(statuses)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(decision.status_bytes)
    return decision.decision.kind


def serialize_source_items(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=SOURCE_ITEM_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in SOURCE_ITEM_FIELDS})
    return buffer.getvalue().encode("utf-8")


def readback_source_items(
    path: str | Path, expected_bytes: bytes, expected_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    try:
        actual_bytes = Path(path).read_bytes()
        if actual_bytes != expected_bytes:
            raise FetchStatusError("source_items_bytes_mismatch")
        text = actual_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if tuple(reader.fieldnames or ()) != SOURCE_ITEM_FIELDS:
            raise FetchStatusError("source_items_schema_invalid")
        actual_rows = [dict(row) for row in reader]
    except (OSError, UnicodeError, csv.Error):
        raise FetchStatusError("source_items_readback_invalid") from None
    if actual_rows != expected_rows or serialize_source_items(actual_rows) != actual_bytes:
        raise FetchStatusError("source_items_rows_mismatch")
    return actual_rows


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
    feeds = load_feed_config(feeds_path)
    if not feeds:
        raise FetchStatusError("feed_config_empty")
    for index, feed in enumerate(feeds):
        try:
            kind, feed_rows = parse_feed_snapshot(fetcher(feed.feed_url), feed, max_items=max_items_per_feed)
        except Exception as exc:
            statuses.append(
                FeedFetchStatus(
                    feed_id=feed.feed_id,
                    feed_url=feed.feed_url,
                    kind="unknown",
                    state="failed",
                    error_code="fetch_failed",
                )
            )
            if not continue_on_feed_error:
                statuses.extend(
                    FeedFetchStatus(
                        feed_id=unattempted.feed_id,
                        feed_url=unattempted.feed_url,
                        kind="unknown",
                        state="failed",
                        error_code="not_attempted",
                    )
                    for unattempted in feeds[index + 1 :]
                )
                break
            continue
        rows.extend(feed_rows)
        statuses.append(
            FeedFetchStatus(
                feed_id=feed.feed_id,
                feed_url=feed.feed_url,
                kind=kind,
                state="accepted" if feed_rows else "quarantined",
                rows=tuple(feed_rows),
                error_code=None if feed_rows else "zero_entries",
            )
        )
    rows.sort(key=lambda row: (row["published_at"], row["item_id"]))
    source_bytes = serialize_source_items(rows)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(source_bytes)
    readback_rows = readback_source_items(output_file, source_bytes, rows)
    if readback_rows != rows:
        raise FetchStatusError("source_items_rows_mismatch")
    decision = build_fetch_status(statuses)
    if status_output:
        Path(status_output).parent.mkdir(parents=True, exist_ok=True)
        Path(status_output).write_bytes(decision.status_bytes)
        if read_status(Path(status_output).read_bytes()) != json.loads(decision.status_bytes):
            raise FetchStatusError("fetch_status_readback_mismatch")
    if decision.decision.kind is DecisionKind.HARD_FAIL:
        raise RuntimeError("feed_fetch_failed")
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
