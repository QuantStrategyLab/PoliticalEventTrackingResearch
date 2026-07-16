"""Concrete bounded observed weekly producer contract."""
from __future__ import annotations

import csv
import datetime as dt
import email.utils
import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from .csv_utils import read_csv_rows, write_csv_rows
from .feed_status_canonical_h2c import build_decision, read_status
from .rss_source_fetch import FeedConfig, fetch_url, load_feed_config
from .source_mention_extract import extract_source_records
from .weekly_period_lock import (
    PoliticalEventWeeklyPeriodLockV1,
    SourceSnapshotArtifact,
    parse_period_lock_bytes,
    serialize_period_lock,
)


ARTIFACT_NAME = "political-event-weekly-v1"
ARTIFACT_FILES = (
    "period_lock.json",
    "political_events.csv",
    "political_watchlist.csv",
    "political_event_weekly.json",
    "weekly_manifest.json",
)
MANIFEST_TYPE = "political_event_weekly_bounded_observed.v1"
OBSERVED_SNAPSHOT_VERSION = "configured_source_observed.v1"
COVERAGE_COMPLETENESS = "bounded_unverified"
MAX_ITEMS_PER_FEED = 50
RETENTION_DAYS = 30
SOURCE_PROVENANCE = "configured_source_observed_v1"
WORKFLOW_REF = (
    "QuantStrategyLab/PoliticalEventTrackingResearch/"
    ".github/workflows/pert_weekly_bounded_observed_artifact.yml@refs/heads/main"
)
ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/elements/1.1/"
MAX_XML_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ROW_FIELDS = ("item_id", "published_at", "source_type", "source_url", "author", "text")
_SOURCE_INPUT_PATHS = (
    "config/free_rss_feeds.csv",
    "config/core_us_equity_aliases.csv",
    "data/live/political_watchlist.csv",
)
_MANIFEST_KEYS = frozenset(
    {
        "manifest_type",
        "artifact_name",
        "retention_days",
        "observed_snapshot_version",
        "coverage_completeness",
        "max_items_per_feed",
        "truncation_possible",
        "private_research_only",
        "provider_freshness",
        "period_start",
        "period_end_exclusive",
        "as_of",
        "retrieved_at",
        "generated_at",
        "run_mode",
        "source_run_id",
        "source_attempt",
        "producer_ref",
        "workflow_ref",
        "source_provenance",
        "source_snapshot_digest",
        "source_inputs",
        "feed_snapshots",
        "h2c_status_sha256",
        "h2c",
        "selected_period_count",
        "selected_period_row_digest",
        "files",
    }
)
_FILE_KEYS = frozenset({"sha256", "size", "row_count", "role"})
_H2C_KEYS = frozenset(
    {
        "configured_feed_count",
        "feed_count",
        "successful_feed_count",
        "failed_feed_count",
        "quarantined_feed_count",
        "accepted_row_count",
        "rejected_row_count",
        "publication_complete",
        "eligible_for_live_publication",
        "aggregate_row_digest",
    }
)


class BoundedObservedError(ValueError):
    """Stable producer contract error without raw payload details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise BoundedObservedError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("manifest_serialization_invalid")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_timestamp(value: object, code: str = "timestamp_invalid") -> dt.datetime:
    if type(value) is not str or not _UTC_TIMESTAMP_RE.fullmatch(value):
        _fail(code)
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError:
        _fail(code)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strict_date(value: object, code: str = "period_invalid") -> dt.date:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail(code)
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        _fail(code)


def _safe_int(value: object, code: str) -> int:
    if type(value) is not int or value < 0 or value > 2**53 - 1:
        _fail(code)
    return value


def _string(value: object, code: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value) or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _digest(value: object, code: str = "digest_invalid") -> str:
    result = _string(value, code)
    if not _SHA256_RE.fullmatch(result):
        _fail(code)
    return result


def _local_name(tag: str) -> str:
    """Only structural RSS container compatibility uses local names."""
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, tag: str) -> ET.Element | None:
    for child in element:
        if child.tag == tag:
            return child
    return None


def _text(element: ET.Element, tag: str, *, allow_empty: bool = True) -> str:
    child = _child(element, tag)
    value = "" if child is None or child.text is None else child.text.strip()
    if not allow_empty and not value:
        _fail("feed_field_invalid")
    return value


def _parse_rss_date(value: str) -> str:
    if not value:
        _fail("event_date_invalid")
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        _fail("event_date_invalid")
    if parsed.tzinfo is None:
        _fail("event_date_invalid")
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_rfc3339(value: str) -> str:
    if not _RFC3339_RE.fullmatch(value):
        _fail("event_date_invalid")
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        _fail("event_date_invalid")
    if parsed.tzinfo is None:
        _fail("event_date_invalid")
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_item_id(feed_id: str, link: str, title: str) -> str:
    return f"{feed_id}-{hashlib.sha1(f'{feed_id}|{link}|{title}'.encode('utf-8')).hexdigest()[:12]}"


def _rss_items(root: ET.Element) -> list[ET.Element]:
    if _local_name(root.tag) != "rss":
        _fail("feed_kind_invalid")
    channels = [child for child in root if _local_name(child.tag) == "channel"]
    if len(channels) != 1:
        _fail("feed_grammar_invalid")
    return [child for child in channels[0] if _local_name(child.tag) == "item"]


def _parse_rss_item(item: ET.Element, feed: FeedConfig) -> dict[str, str]:
    title = _text(item, "title")
    link = _text(item, "link") or _text(item, "guid")
    pub_date = _text(item, "pubDate")
    dc_date = _text(item, f"{{{DC_NS}}}date")
    if pub_date and dc_date:
        _fail("event_date_ambiguous")
    published_at = _parse_rss_date(pub_date) if pub_date else _parse_rfc3339(dc_date)
    description = _text(item, "description") or _text(item, "{http://purl.org/rss/1.0/modules/content/}encoded")
    return {
        "item_id": _stable_item_id(feed.feed_id, link, title),
        "published_at": published_at,
        "source_type": feed.source_type,
        "source_url": link,
        "author": feed.author,
        "text": " ".join(part for part in (title, description) if part),
    }


def _parse_atom_item(item: ET.Element, feed: FeedConfig) -> dict[str, str]:
    title = _text(item, f"{{{ATOM_NS}}}title")
    link_node = _child(item, f"{{{ATOM_NS}}}link")
    link = link_node.attrib.get("href", "") if link_node is not None else _text(item, f"{{{ATOM_NS}}}id")
    published = _text(item, f"{{{ATOM_NS}}}published")
    updated = _text(item, f"{{{ATOM_NS}}}updated")
    published_at = _parse_rfc3339(published or updated)
    summary = _text(item, f"{{{ATOM_NS}}}summary") or _text(item, f"{{{ATOM_NS}}}content")
    return {
        "item_id": _stable_item_id(feed.feed_id, link, title),
        "published_at": published_at,
        "source_type": feed.source_type,
        "source_url": link,
        "author": feed.author,
        "text": " ".join(part for part in (title, summary) if part),
    }


class FeedSnapshot:
    __slots__ = ("kind", "rows", "observed_count", "truncation_possible")

    def __init__(self, kind: str, rows: list[dict[str, str]], observed_count: int, truncation_possible: bool) -> None:
        self.kind = kind
        self.rows = rows
        self.observed_count = observed_count
        self.truncation_possible = truncation_possible


def parse_bounded_feed_snapshot(feed_bytes: bytes, feed: FeedConfig) -> FeedSnapshot:
    if type(feed_bytes) is not bytes:
        _fail("feed_xml_invalid")
    if len(feed_bytes) > MAX_XML_BYTES:
        _fail("feed_xml_oversize")
    try:
        root = ET.fromstring(feed_bytes, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, LookupError, UnicodeError, ValueError, RecursionError):
        _fail("feed_xml_invalid")
    if _local_name(root.tag) == "rss":
        items = _rss_items(root)
        rows = [_parse_rss_item(item, feed) for item in items[:MAX_ITEMS_PER_FEED]]
        return FeedSnapshot("rss2", rows, len(rows), True)
    if root.tag != f"{{{ATOM_NS}}}feed":
        _fail("feed_grammar_invalid")
    entries = [child for child in root if child.tag == f"{{{ATOM_NS}}}entry"]
    rows = [_parse_atom_item(entry, feed) for entry in entries[:MAX_ITEMS_PER_FEED]]
    return FeedSnapshot("atom", rows, len(rows), True)


def _read_count(path: Path) -> int:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        _fail("input_invalid")


def _file_meta(path: Path, relative: str) -> dict[str, object]:
    try:
        content = path.read_bytes()
    except (OSError, UnicodeError):
        _fail("input_invalid")
    return {"path": relative, "sha256": _sha_bytes(content), "row_count": _read_count(path)}


def _expected_period(retrieved_at: str) -> tuple[dt.date, dt.date, dt.date]:
    reference = _strict_timestamp(retrieved_at, "retrieved_at_invalid").date()
    monday = reference - dt.timedelta(days=reference.weekday())
    start = monday - dt.timedelta(days=7)
    return start, monday, monday - dt.timedelta(days=1)


def _validate_period(retrieved_at: str, period_start: str | None, as_of: str | None) -> tuple[dt.date, dt.date, dt.date]:
    expected = _expected_period(retrieved_at)
    if (period_start is None) != (as_of is None):
        _fail("manual_period_incomplete")
    if period_start is not None and as_of is not None:
        requested_start = _strict_date(period_start, "manual_period_invalid")
        requested_as_of = _strict_date(as_of, "manual_period_invalid")
        if requested_start.weekday() != 0 or requested_as_of != requested_start + dt.timedelta(days=6):
            _fail("manual_period_invalid")
        if (requested_start, requested_as_of) != (expected[0], expected[2]):
            _fail("manual_period_mismatch")
    return expected


def _fetch_outcomes(feeds: list[FeedConfig], fetcher: Callable[[str], bytes]) -> tuple[list[dict[str, str]], list[dict[str, object]], list[dict[str, object]]]:
    if not feeds:
        _fail("feed_config_empty")
    all_rows: list[dict[str, str]] = []
    outcomes: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    for feed in feeds:
        try:
            body = fetcher(feed.feed_url)
            snapshot = parse_bounded_feed_snapshot(body, feed)
        except Exception:
            outcomes.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": "unknown", "state": "failed", "rows": [], "error_code": "fetch_failed"})
            continue
        all_rows.extend(snapshot.rows)
        if not snapshot.rows:
            outcomes.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": snapshot.kind, "state": "quarantined", "rows": [], "error_code": "zero_entries"})
            continue
        outcomes.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": snapshot.kind, "state": "accepted", "rows": snapshot.rows, "error_code": None})
        snapshots.append({"feed_id": feed.feed_id, "feed_url": feed.feed_url, "kind": snapshot.kind, "body_sha256": _sha_bytes(body), "observed_count": snapshot.observed_count, "truncation_possible": True})
    return all_rows, outcomes, snapshots


def _filter_rows(rows: list[dict[str, str]], start: dt.date, as_of: dt.date) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        try:
            event_date = dt.date.fromisoformat(row["published_at"][:10])
        except (KeyError, TypeError, ValueError):
            _fail("event_date_invalid")
        if start <= event_date <= as_of:
            selected.append(row)
    return selected


def _manifest_payload(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_KEYS:
        _fail("manifest_shape_invalid")
    if value["manifest_type"] != MANIFEST_TYPE or value["artifact_name"] != ARTIFACT_NAME or value["retention_days"] != RETENTION_DAYS:
        _fail("manifest_contract_invalid")
    if value["observed_snapshot_version"] != OBSERVED_SNAPSHOT_VERSION or value["coverage_completeness"] != COVERAGE_COMPLETENESS:
        _fail("coverage_invalid")
    if value["max_items_per_feed"] != MAX_ITEMS_PER_FEED or value["truncation_possible"] is not True or value["private_research_only"] is not True or value["provider_freshness"] != "unverified":
        _fail("coverage_invalid")
    period_start = _strict_date(value["period_start"])
    period_end = _strict_date(value["period_end_exclusive"])
    as_of = _strict_date(value["as_of"])
    if period_start.weekday() != 0 or period_end != period_start + dt.timedelta(days=7) or as_of != period_end - dt.timedelta(days=1):
        _fail("period_invalid")
    retrieved_at = _strict_timestamp(value["retrieved_at"], "retrieved_at_invalid")
    generated_at = _strict_timestamp(value["generated_at"], "generated_at_invalid")
    if generated_at < retrieved_at or retrieved_at.date() < as_of:
        _fail("timestamp_invalid")
    if value["run_mode"] not in {"scheduled", "manual"}:
        _fail("run_mode_invalid")
    _string(value["source_run_id"], "source_run_id_invalid")
    if not _RUN_ID_RE.fullmatch(value["source_run_id"]):
        _fail("source_run_id_invalid")
    if value["source_attempt"] != 1 or type(value["source_attempt"]) is not int:
        _fail("source_attempt_invalid")
    if type(value["producer_ref"]) is not str or not _SHA1_RE.fullmatch(value["producer_ref"]):
        _fail("producer_ref_invalid")
    if value["workflow_ref"] != WORKFLOW_REF or value["source_provenance"] != SOURCE_PROVENANCE:
        _fail("source_identity_invalid")
    _digest(value["source_snapshot_digest"])
    inputs = value["source_inputs"]
    if not isinstance(inputs, list) or not all(isinstance(item, Mapping) for item in inputs) or [item.get("path") for item in inputs] != list(_SOURCE_INPUT_PATHS):
        _fail("source_input_invalid")
    for item in inputs:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256", "row_count"}:
            _fail("source_input_invalid")
        _digest(item["sha256"])
        _safe_int(item["row_count"], "source_input_invalid")
    snapshots = value["feed_snapshots"]
    if not isinstance(snapshots, list) or not snapshots:
        _fail("feed_snapshot_invalid")
    previous = ""
    for item in snapshots:
        if not isinstance(item, Mapping) or set(item) != {"feed_id", "feed_url", "kind", "body_sha256", "observed_count", "truncation_possible"}:
            _fail("feed_snapshot_invalid")
        feed_id = _string(item["feed_id"], "feed_snapshot_invalid")
        if feed_id <= previous:
            _fail("feed_snapshot_order_invalid")
        previous = feed_id
        if item["kind"] not in {"rss2", "atom"}:
            _fail("feed_snapshot_invalid")
        _digest(item["body_sha256"])
        _safe_int(item["observed_count"], "feed_snapshot_invalid")
        if item["observed_count"] > MAX_ITEMS_PER_FEED:
            _fail("feed_snapshot_invalid")
        if item["truncation_possible"] is not True:
            _fail("coverage_invalid")
    _digest(value["h2c_status_sha256"])
    h2c = value["h2c"]
    if not isinstance(h2c, Mapping) or set(h2c) != _H2C_KEYS:
        _fail("status_binding_invalid")
    for key in _H2C_KEYS - {"aggregate_row_digest", "publication_complete", "eligible_for_live_publication"}:
        _safe_int(h2c[key], "status_binding_invalid")
    if h2c["publication_complete"] is not True or h2c["eligible_for_live_publication"] is not True or h2c["failed_feed_count"] != 0 or h2c["quarantined_feed_count"] != 0:
        _fail("status_binding_invalid")
    if h2c["configured_feed_count"] != len(snapshots) or h2c["successful_feed_count"] != len(snapshots) or h2c["accepted_row_count"] != sum(item["observed_count"] for item in snapshots):
        _fail("status_binding_invalid")
    _digest(h2c["aggregate_row_digest"])
    _safe_int(value["selected_period_count"], "selected_count_invalid")
    _digest(value["selected_period_row_digest"])
    files = value["files"]
    if not isinstance(files, Mapping) or set(files) != set(ARTIFACT_FILES[:-1]):
        _fail("artifact_file_set_invalid")
    for name in ARTIFACT_FILES[:-1]:
        item = files[name]
        if not isinstance(item, Mapping) or set(item) != _FILE_KEYS:
            _fail("artifact_member_invalid")
        _digest(item["sha256"])
        _safe_int(item["size"], "artifact_member_invalid")
        _safe_int(item["row_count"], "artifact_member_invalid")
        _string(item["role"], "artifact_member_invalid")
    return dict(value)


def serialize_observed_manifest(value: Mapping[str, object]) -> bytes:
    payload = _manifest_payload(value)
    return _canonical(payload)


def read_observed_manifest(wire: bytes) -> dict[str, object]:
    if type(wire) is not bytes or len(wire) > MAX_MANIFEST_BYTES:
        _fail("manifest_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("manifest_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except BoundedObservedError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        _fail("manifest_wire_invalid")
    payload = _manifest_payload(value)
    if serialize_observed_manifest(payload) != wire:
        _fail("manifest_noncanonical")
    return json.loads(wire.decode("utf-8"))


def _file_record(path: Path, role: str, row_count: int) -> dict[str, object]:
    try:
        content = path.read_bytes()
    except OSError:
        _fail("artifact_input_invalid")
    return {"sha256": _sha_bytes(content), "size": len(content), "row_count": row_count, "role": role}


def _readback(output: Path, lock_bytes: bytes, status_bytes: bytes, manifest_bytes: bytes) -> None:
    try:
        if {entry.name for entry in output.iterdir()} != set(ARTIFACT_FILES):
            _fail("artifact_file_set_invalid")
        for name in ARTIFACT_FILES:
            path = output / name
            if path.is_symlink() or not path.is_file():
                _fail("artifact_member_invalid")
        if (output / "period_lock.json").read_bytes() != lock_bytes or (output / "political_event_weekly.json").read_bytes() != status_bytes or (output / "weekly_manifest.json").read_bytes() != manifest_bytes:
            _fail("artifact_readback_invalid")
        lock = parse_period_lock_bytes(lock_bytes)
        read_status(status_bytes)
        manifest = read_observed_manifest(manifest_bytes)
        expected_records = {
            "period_lock.json": _file_record(output / "period_lock.json", "period_lock", 0),
            "political_events.csv": _file_record(output / "political_events.csv", "selected_period_events", _read_count(output / "political_events.csv")),
            "political_watchlist.csv": _file_record(output / "political_watchlist.csv", "watchlist_input", _read_count(output / "political_watchlist.csv")),
            "political_event_weekly.json": _file_record(output / "political_event_weekly.json", "h2c_status", 0),
        }
        if manifest["files"] != expected_records:
            _fail("artifact_readback_invalid")
        if manifest["h2c_status_sha256"] != _sha_bytes(status_bytes) or manifest["selected_period_row_digest"] != expected_records["political_events.csv"]["sha256"]:
            _fail("artifact_readback_invalid")
        if lock.source_snapshot_digest != manifest["source_snapshot_digest"] or lock.source_run_id != manifest["source_run_id"] or lock.source_attempt != manifest["source_attempt"]:
            _fail("artifact_readback_invalid")
    except BoundedObservedError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        _fail("artifact_readback_invalid")


def build_weekly_observed_artifact(
    *,
    feeds_path: Path,
    aliases_path: Path,
    watchlist_path: Path,
    output_dir: Path,
    retrieved_at: str,
    generated_at: str | None,
    source_run_id: str,
    source_attempt: int,
    producer_ref: str,
    run_mode: str,
    period_start: str | None = None,
    as_of: str | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> Path:
    start, end, sunday = _validate_period(retrieved_at, period_start, as_of)
    if type(source_attempt) is not int or source_attempt != 1:
        _fail("source_attempt_invalid")
    if type(source_run_id) is not str or not _RUN_ID_RE.fullmatch(source_run_id):
        _fail("source_run_id_invalid")
    if type(producer_ref) is not str or not _SHA1_RE.fullmatch(producer_ref):
        _fail("producer_ref_invalid")
    if run_mode not in {"scheduled", "manual"}:
        _fail("run_mode_invalid")
    if output_dir.exists():
        _fail("output_exists")
    try:
        with tempfile.TemporaryDirectory(prefix="pert-observed-input-") as input_directory:
            input_root = Path(input_directory)
            try:
                feed_bytes = feeds_path.read_bytes()
                alias_bytes = aliases_path.read_bytes()
                watchlist_bytes = watchlist_path.read_bytes()
            except OSError:
                _fail("input_invalid")
            feed_snapshot_path = input_root / "feeds.csv"
            alias_snapshot_path = input_root / "aliases.csv"
            watchlist_snapshot_path = input_root / "watchlist.csv"
            feed_snapshot_path.write_bytes(feed_bytes)
            alias_snapshot_path.write_bytes(alias_bytes)
            watchlist_snapshot_path.write_bytes(watchlist_bytes)
            try:
                feeds = load_feed_config(feed_snapshot_path)
            except (KeyError, OSError, UnicodeError, ValueError):
                _fail("input_invalid")
            rows, outcomes, snapshots = _fetch_outcomes(feeds, fetcher or fetch_url)
            try:
                decision = build_decision(outcomes)
                status = read_status(decision.status_bytes)
            except (TypeError, ValueError, UnicodeError, RecursionError):
                _fail("status_invalid")
            if decision.decision.kind.value != "success":
                _fail("source_incomplete")
            if generated_at is None:
                generated_at = utc_now_iso()
            _strict_timestamp(generated_at, "generated_at_invalid")
            source_inputs = [_file_meta(path, relative) for path, relative in ((feed_snapshot_path, _SOURCE_INPUT_PATHS[0]), (alias_snapshot_path, _SOURCE_INPUT_PATHS[1]), (watchlist_snapshot_path, _SOURCE_INPUT_PATHS[2]))]
            source_snapshot = {"inputs": source_inputs, "feeds": sorted(snapshots, key=lambda item: str(item["feed_id"])), "h2c_status_sha256": _sha_bytes(decision.status_bytes)}
            source_snapshot_digest = _sha_bytes(_canonical(source_snapshot))
            output_dir.mkdir(parents=True, exist_ok=False)
            with tempfile.TemporaryDirectory(prefix="pert-observed-raw-") as temporary:
                raw_items = Path(temporary) / "source_items.csv"
                selected_rows = _filter_rows(rows, start, sunday)
                write_csv_rows(raw_items, list(_ROW_FIELDS), selected_rows)
                events = output_dir / "political_events.csv"
                try:
                    extract_source_records(raw_items, alias_snapshot_path, events)
                except (KeyError, OSError, UnicodeError, ValueError):
                    _fail("event_projection_invalid")
            watchlist = output_dir / "political_watchlist.csv"
            watchlist.write_bytes(watchlist_bytes)
            status_path = output_dir / "political_event_weekly.json"
            status_path.write_bytes(decision.status_bytes)
            event_count = _read_count(events)
            event_digest = _sha_bytes(events.read_bytes())
            input_artifacts = tuple(SourceSnapshotArtifact(item["path"], item["sha256"], item["row_count"]) for item in source_inputs)
            feed_artifacts = tuple(SourceSnapshotArtifact(f"source/feeds/{item['feed_id']}.xml", item["body_sha256"], item["observed_count"]) for item in snapshots)
            lock = PoliticalEventWeeklyPeriodLockV1(start, end, sunday, WORKFLOW_REF, source_run_id, source_attempt, producer_ref, f"run_{source_run_id}_attempt_{source_attempt}", source_snapshot_digest, SOURCE_PROVENANCE, input_artifacts + feed_artifacts)
            lock_bytes = serialize_period_lock(lock)
            (output_dir / "period_lock.json").write_bytes(lock_bytes)
            file_records = {
                "period_lock.json": _file_record(output_dir / "period_lock.json", "period_lock", 0),
                "political_events.csv": _file_record(events, "selected_period_events", event_count),
                "political_watchlist.csv": _file_record(watchlist, "watchlist_input", _read_count(watchlist)),
                "political_event_weekly.json": _file_record(status_path, "h2c_status", 0),
            }
            manifest = {
            "manifest_type": MANIFEST_TYPE,
            "artifact_name": ARTIFACT_NAME,
            "retention_days": RETENTION_DAYS,
            "observed_snapshot_version": OBSERVED_SNAPSHOT_VERSION,
            "coverage_completeness": COVERAGE_COMPLETENESS,
            "max_items_per_feed": MAX_ITEMS_PER_FEED,
            "truncation_possible": True,
            "private_research_only": True,
            "provider_freshness": "unverified",
            "period_start": start.isoformat(),
            "period_end_exclusive": end.isoformat(),
            "as_of": sunday.isoformat(),
            "retrieved_at": retrieved_at,
            "generated_at": generated_at,
            "run_mode": run_mode,
            "source_run_id": source_run_id,
            "source_attempt": source_attempt,
            "producer_ref": producer_ref,
            "workflow_ref": WORKFLOW_REF,
            "source_provenance": SOURCE_PROVENANCE,
            "source_snapshot_digest": source_snapshot_digest,
            "source_inputs": source_inputs,
            "feed_snapshots": sorted(snapshots, key=lambda item: str(item["feed_id"])),
            "h2c_status_sha256": _sha_bytes(decision.status_bytes),
            "h2c": {key: status[key] for key in _H2C_KEYS},
            "selected_period_count": event_count,
            "selected_period_row_digest": event_digest,
            "files": file_records,
            }
            manifest_bytes = serialize_observed_manifest(manifest)
            (output_dir / "weekly_manifest.json").write_bytes(manifest_bytes)
            _readback(output_dir, lock_bytes, decision.status_bytes, manifest_bytes)
            return output_dir
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


__all__ = [
    "ARTIFACT_FILES",
    "ARTIFACT_NAME",
    "BoundedObservedError",
    "FeedConfig",
    "FeedSnapshot",
    "MAX_ITEMS_PER_FEED",
    "parse_bounded_feed_snapshot",
    "read_observed_manifest",
    "serialize_observed_manifest",
    "build_weekly_observed_artifact",
]
