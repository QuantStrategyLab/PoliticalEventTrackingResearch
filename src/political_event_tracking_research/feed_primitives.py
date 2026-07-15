"""Producer-owned validated rows and canonical feed status."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

STATUS_VERSION = "pert.feed_primitives.v1"
MAX_SAFE_JSON_INTEGER = 2**53 - 1
MAX_ROWS_PER_FEED = 10_000
_ROW_KEYS = frozenset({"item_id", "published_at", "source_type", "source_url", "author", "text"})
_FEED_KEYS = frozenset({"feed_id", "feed_url", "kind", "state", "rows", "error_code"})
_FEED_WIRE_KEYS = frozenset(
    {"feed_id", "feed_url", "kind", "state", "accepted_row_count", "rejected_row_count", "row_digest", "error_code"}
)
_STATUS_KEYS = frozenset(
    {
        "status_version",
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
        "feeds",
    }
)
_STATES = frozenset({"accepted", "failed", "quarantined"})
_KINDS = frozenset({"rss", "atom", "unknown"})
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]*$")


class PrimitiveStatusError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> PrimitiveStatusError:
    return PrimitiveStatusError(code)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _fail("status_serialization_invalid") from None


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _string(value: object, code: str, *, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        raise _fail(code)
    return value


def _safe_int(value: object, code: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_SAFE_JSON_INTEGER:
        raise _fail(code)
    return value


def _is_digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


@dataclass(frozen=True, slots=True)
class PrimitiveRow:
    item_id: str
    published_at: str
    source_type: str
    source_url: str
    author: str
    text: str

    @classmethod
    def from_mapping(cls, value: object) -> "PrimitiveRow":
        if isinstance(value, cls):
            value = value.to_mapping()
        if not isinstance(value, Mapping) or set(value) != _ROW_KEYS:
            raise _fail("row_shape_invalid")
        try:
            snapshot = dict(value)
        except (TypeError, ValueError, RuntimeError):
            raise _fail("row_shape_invalid") from None
        return cls(
            item_id=_string(snapshot["item_id"], "row_invalid", allow_empty=False),
            published_at=_string(snapshot["published_at"], "row_invalid", allow_empty=False),
            source_type=_string(snapshot["source_type"], "row_invalid", allow_empty=False),
            source_url=_string(snapshot["source_url"], "row_invalid", allow_empty=False),
            author=_string(snapshot["author"], "row_invalid"),
            text=_string(snapshot["text"], "row_invalid"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "item_id": self.item_id,
            "published_at": self.published_at,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "author": self.author,
            "text": self.text,
        }


def _snapshot_rows(value: object) -> tuple[PrimitiveRow, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise _fail("rows_shape_invalid")
    rows: list[PrimitiveRow] = []
    try:
        for item in value:
            if len(rows) >= MAX_ROWS_PER_FEED:
                raise _fail("rows_limit_exceeded")
            rows.append(PrimitiveRow.from_mapping(item))
    except PrimitiveStatusError:
        raise
    except (TypeError, ValueError, RuntimeError, RecursionError):
        raise _fail("rows_invalid") from None
    return tuple(rows)


def _snapshot_feed(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FEED_KEYS:
        raise _fail("feed_shape_invalid")
    try:
        snapshot = dict(value)
    except (TypeError, ValueError, RuntimeError):
        raise _fail("feed_shape_invalid") from None
    feed_id = _string(snapshot["feed_id"], "feed_invalid", allow_empty=False)
    feed_url = _string(snapshot["feed_url"], "feed_invalid", allow_empty=False)
    kind = _string(snapshot["kind"], "feed_invalid", allow_empty=False)
    state = _string(snapshot["state"], "feed_invalid", allow_empty=False)
    error_code = snapshot["error_code"]
    if kind not in _KINDS or state not in _STATES or (
        error_code is not None and (type(error_code) is not str or not _SAFE_ERROR.fullmatch(error_code))
    ):
        raise _fail("feed_invalid")
    rows = _snapshot_rows(snapshot["rows"])
    if state == "accepted" and (not rows or error_code is not None):
        raise _fail("feed_state_invalid")
    if state == "failed" and (rows or not error_code):
        raise _fail("feed_state_invalid")
    if state == "quarantined" and (rows or not error_code):
        raise _fail("feed_state_invalid")
    return {"feed_id": feed_id, "feed_url": feed_url, "kind": kind, "state": state, "rows": rows, "error_code": error_code}


def _feed_wire(feed: Mapping[str, Any]) -> dict[str, object]:
    rows = [row.to_mapping() for row in feed["rows"]]
    return {
        "feed_id": feed["feed_id"],
        "feed_url": feed["feed_url"],
        "kind": feed["kind"],
        "state": feed["state"],
        "accepted_row_count": len(rows),
        "rejected_row_count": 0,
        "row_digest": _digest(rows),
        "error_code": feed["error_code"],
    }


def build_status(feed_records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    if isinstance(feed_records, (str, bytes, Mapping)):
        raise _fail("feed_records_invalid")
    try:
        records = [_snapshot_feed(item) for item in feed_records]
    except PrimitiveStatusError:
        raise
    except (TypeError, ValueError, RuntimeError, RecursionError):
        raise _fail("feed_records_invalid") from None
    if not records:
        raise _fail("configured_feed_empty")
    if len(records) > MAX_SAFE_JSON_INTEGER:
        raise _fail("feed_count_overflow")
    if len({item["feed_id"] for item in records}) != len(records):
        raise _fail("feed_duplicate")
    records.sort(key=lambda item: (item["feed_id"], item["feed_url"]))
    feeds = [_feed_wire(item) for item in records]
    accepted = sum(item["state"] == "accepted" for item in records)
    failed = sum(item["state"] == "failed" for item in records)
    quarantined = sum(item["state"] == "quarantined" for item in records)
    rows = [row.to_mapping() for item in records if item["state"] == "accepted" for row in item["rows"]]
    complete = accepted == len(records) and failed == 0 and quarantined == 0 and bool(rows)
    return {
        "status_version": STATUS_VERSION,
        "configured_feed_count": len(records),
        "feed_count": len(records),
        "successful_feed_count": accepted,
        "failed_feed_count": failed,
        "quarantined_feed_count": quarantined,
        "accepted_row_count": len(rows),
        "rejected_row_count": 0,
        "publication_complete": complete,
        "eligible_for_live_publication": complete,
        "aggregate_row_digest": _digest(rows),
        "feeds": feeds,
    }


def _validate_wire(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _STATUS_KEYS:
        raise _fail("status_shape_invalid")
    try:
        snapshot = dict(value)
    except (TypeError, ValueError, RuntimeError):
        raise _fail("status_shape_invalid") from None
    if snapshot["status_version"] != STATUS_VERSION or type(snapshot["feeds"]) is not list:
        raise _fail("status_shape_invalid")
    integer_keys = (
        "configured_feed_count",
        "feed_count",
        "successful_feed_count",
        "failed_feed_count",
        "quarantined_feed_count",
        "accepted_row_count",
        "rejected_row_count",
    )
    for key in integer_keys:
        _safe_int(snapshot[key], "status_counter_invalid")
    if any(type(snapshot[key]) is not bool for key in ("publication_complete", "eligible_for_live_publication")):
        raise _fail("status_counter_invalid")
    if snapshot["publication_complete"] != snapshot["eligible_for_live_publication"] or not _is_digest(snapshot["aggregate_row_digest"]):
        raise _fail("status_integrity_invalid")
    if snapshot["configured_feed_count"] != snapshot["feed_count"] or snapshot["feed_count"] != len(snapshot["feeds"]):
        raise _fail("status_counter_mismatch")
    expected_counts = {
        "successful_feed_count": 0,
        "failed_feed_count": 0,
        "quarantined_feed_count": 0,
        "accepted_row_count": 0,
        "rejected_row_count": 0,
    }
    feed_ids: set[str] = set()
    feed_order: list[tuple[str, str]] = []
    for feed in snapshot["feeds"]:
        if not isinstance(feed, Mapping) or set(feed) != _FEED_WIRE_KEYS:
            raise _fail("feed_wire_shape_invalid")
        if any(type(feed[key]) is not str or not feed[key] for key in ("feed_id", "feed_url", "kind", "state")):
            raise _fail("feed_wire_shape_invalid")
        if feed["kind"] not in _KINDS or feed["state"] not in _STATES or feed["feed_id"] in feed_ids:
            raise _fail("feed_wire_shape_invalid")
        feed_ids.add(feed["feed_id"])
        feed_order.append((feed["feed_id"], feed["feed_url"]))
        _safe_int(feed["accepted_row_count"], "feed_counter_invalid")
        _safe_int(feed["rejected_row_count"], "feed_counter_invalid")
        if not _is_digest(feed["row_digest"]):
            raise _fail("feed_digest_invalid")
        state = feed["state"]
        error = feed["error_code"]
        if error is not None and (type(error) is not str or not _SAFE_ERROR.fullmatch(error)):
            raise _fail("feed_state_invalid")
        if state == "accepted" and (feed["accepted_row_count"] <= 0 or feed["rejected_row_count"] != 0 or error is not None):
            raise _fail("feed_state_invalid")
        if state in {"failed", "quarantined"} and (
            feed["accepted_row_count"] != 0 or feed["rejected_row_count"] != 0 or not error
        ):
            raise _fail("feed_state_invalid")
        expected_counts[f"{state if state != 'accepted' else 'successful'}_feed_count"] += 1
        expected_counts["accepted_row_count"] += feed["accepted_row_count"]
        expected_counts["rejected_row_count"] += feed["rejected_row_count"]
    if feed_order != sorted(feed_order):
        raise _fail("feed_order_invalid")
    if any(snapshot[key] != value for key, value in expected_counts.items()):
        raise _fail("status_counter_mismatch")
    complete = snapshot["successful_feed_count"] == snapshot["feed_count"] and snapshot["feed_count"] > 0 and snapshot["accepted_row_count"] > 0
    if snapshot["publication_complete"] != complete:
        raise _fail("status_counter_mismatch")
    return snapshot


def serialize_status(value: Mapping[str, object]) -> bytes:
    return _canonical_bytes(_validate_wire(value))


def parse_status_bytes(wire: bytes) -> dict[str, object]:
    if type(wire) is not bytes:
        raise _fail("status_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _fail("status_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _fail("status_wire_invalid") from None
    parsed = _validate_wire(value)
    if serialize_status(parsed) != wire:
        raise _fail("status_noncanonical")
    return parsed


def status_for_rows(wire: bytes, feed_records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    parse_status_bytes(wire)
    expected = build_status(feed_records)
    if serialize_status(expected) != wire:
        raise _fail("status_integrity_mismatch")
    return expected
