from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


STATUS_VERSION = "pert.feed_primitives.v1"
MAX_SAFE_JSON_INTEGER = 2**53 - 1
MAX_ROWS_PER_FEED = 10_000
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ROW_KEYS = ("item_id", "published_at", "source_type", "source_url", "author", "text")
_RECORD_KEYS = frozenset({"feed_id", "feed_url", "kind", "state", "rows", "error_code"})
_WIRE_KEYS = frozenset(
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
_FEED_WIRE_KEYS = frozenset(
    {
        "feed_id",
        "feed_url",
        "kind",
        "state",
        "accepted_row_count",
        "rejected_row_count",
        "row_digest",
        "error_code",
    }
)


class PrimitiveStatusError(ValueError):
    """Sanitized status-contract error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise PrimitiveStatusError(code)


def _mapping(value: object, keys: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        _fail(code)
    try:
        result = dict(value)
    except (AttributeError, KeyError, OverflowError, RuntimeError, TypeError, UnicodeError, ValueError):
        _fail(code)
    if set(result) != keys or any(type(key) is not str for key in result):
        _fail(code)
    return result


def _string(value: object, code: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value) or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _integer(value: object, code: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_SAFE_JSON_INTEGER:
        _fail(code)
    return value


@dataclass(frozen=True)
class PrimitiveRow:
    item_id: str
    published_at: str
    source_type: str
    source_url: str
    author: str
    text: str

    @classmethod
    def from_mapping(cls, value: object) -> PrimitiveRow:
        data = _mapping(value, frozenset(_ROW_KEYS), "row_invalid")
        values = [_string(data[key], "row_invalid", allow_empty=key == "author") for key in _ROW_KEYS]
        return cls(*values)

    def to_mapping(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in _ROW_KEYS}


@dataclass(frozen=True)
class FetchResult:
    rows: tuple[PrimitiveRow, ...]
    status: dict[str, object]
    publication_eligible: bool
    hard_failure: bool


def _row_key(row: PrimitiveRow) -> tuple[str, str]:
    return row.published_at, row.item_id


def _canonical(value: object, code: str) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail(code)


def _rows_digest(rows: list[PrimitiveRow]) -> str:
    ordered = sorted(rows, key=_row_key)
    return hashlib.sha256(_canonical([row.to_mapping() for row in ordered], "row_digest_invalid")).hexdigest()


def _record(value: object) -> tuple[dict[str, object], list[PrimitiveRow]]:
    data = _mapping(value, _RECORD_KEYS, "feed_invalid")
    feed_id = _string(data["feed_id"], "feed_invalid")
    feed_url = _string(data["feed_url"], "feed_invalid")
    kind = data["kind"]
    state = data["state"]
    if type(kind) is not str or kind not in {"rss2", "atom", "unknown"}:
        _fail("feed_kind_invalid")
    if type(state) is not str or state not in {"accepted", "failed", "quarantined"}:
        _fail("feed_state_invalid")
    rows_value = data["rows"]
    if not isinstance(rows_value, (list, tuple)) or len(rows_value) > MAX_ROWS_PER_FEED:
        _fail("feed_rows_invalid")
    rows = [PrimitiveRow.from_mapping(row) for row in rows_value]
    error = data["error_code"]
    if error is not None and (type(error) is not str or not _ERROR_RE.fullmatch(error)):
        _fail("feed_error_invalid")
    if state == "accepted" and (kind not in {"rss2", "atom"} or not rows or error is not None):
        _fail("feed_state_invalid")
    if state == "quarantined" and (kind not in {"rss2", "atom"} or rows or error is None):
        _fail("feed_state_invalid")
    if state == "failed" and (rows or error is None):
        _fail("feed_state_invalid")
    return {"feed_id": feed_id, "feed_url": feed_url, "kind": kind, "state": state, "error_code": error}, rows


def _wire_feed(data: dict[str, object], rows: list[PrimitiveRow]) -> dict[str, object]:
    accepted = data["state"] == "accepted"
    return {
        "feed_id": data["feed_id"],
        "feed_url": data["feed_url"],
        "kind": data["kind"],
        "state": data["state"],
        "accepted_row_count": len(rows) if accepted else 0,
        "rejected_row_count": 0,
        "row_digest": _rows_digest(rows) if accepted else hashlib.sha256(b"[]").hexdigest(),
        "error_code": data["error_code"],
    }


def build_status(feed_records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    try:
        records = list(feed_records)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("status_invalid")
    parsed = [_record(record) for record in records]
    if not parsed:
        _fail("feed_config_empty")
    if len({data["feed_id"] for data, _ in parsed}) != len(parsed):
        _fail("feed_duplicate")
    parsed.sort(key=lambda item: (item[0]["feed_id"], item[0]["feed_url"]))
    feeds = [_wire_feed(data, rows) for data, rows in parsed]
    accepted_rows = sorted(
        [row for data, rows in parsed if data["state"] == "accepted" for row in rows], key=_row_key
    )
    failed = sum(data["state"] == "failed" for data, _ in parsed)
    quarantined = sum(data["state"] == "quarantined" for data, _ in parsed)
    complete = failed == 0 and quarantined == 0
    return {
        "status_version": STATUS_VERSION,
        "configured_feed_count": len(parsed),
        "feed_count": len(parsed),
        "successful_feed_count": len(parsed) - failed - quarantined,
        "failed_feed_count": failed,
        "quarantined_feed_count": quarantined,
        "accepted_row_count": len(accepted_rows),
        "rejected_row_count": 0,
        "publication_complete": complete,
        "eligible_for_live_publication": complete,
        "aggregate_row_digest": _rows_digest(accepted_rows),
        "feeds": feeds,
    }


def build_fetch_result(feed_records: Iterable[Mapping[str, object]]) -> FetchResult:
    try:
        records = list(feed_records)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("status_invalid")
    status = build_status(records)
    parsed = [_record(record) for record in records]
    rows = sorted(
        [row for data, feed_rows in parsed if data["state"] == "accepted" for row in feed_rows], key=_row_key
    )
    failed = status["failed_feed_count"] > 0
    return FetchResult(tuple(rows), status, bool(status["eligible_for_live_publication"]), failed)


def _validate_wire(value: object) -> dict[str, object]:
    data = _mapping(value, _WIRE_KEYS, "status_invalid")
    if data["status_version"] != STATUS_VERSION:
        _fail("status_version_invalid")
    counter_keys = _WIRE_KEYS - {
        "status_version",
        "publication_complete",
        "eligible_for_live_publication",
        "aggregate_row_digest",
        "feeds",
    }
    for key in counter_keys:
        _integer(data[key], "status_counter_invalid")
    for key in ("publication_complete", "eligible_for_live_publication"):
        if type(data[key]) is not bool:
            _fail("status_flag_invalid")
    aggregate = _string(data["aggregate_row_digest"], "status_digest_invalid")
    if not _DIGEST_RE.fullmatch(aggregate):
        _fail("status_digest_invalid")
    feeds = data["feeds"]
    if not isinstance(feeds, list):
        _fail("feed_invalid")
    previous: tuple[str, str] | None = None
    feed_ids: set[str] = set()
    for value in feeds:
        item = _mapping(value, _FEED_WIRE_KEYS, "feed_invalid")
        feed_id = _string(item["feed_id"], "feed_invalid")
        feed_url = _string(item["feed_url"], "feed_invalid")
        key = (feed_id, feed_url)
        if feed_id in feed_ids:
            _fail("feed_duplicate")
        if previous is not None and key <= previous:
            _fail("feed_order_invalid")
        previous = key
        feed_ids.add(feed_id)
        kind = item["kind"]
        state = item["state"]
        if type(kind) is not str or kind not in {"rss2", "atom", "unknown"}:
            _fail("feed_kind_invalid")
        if type(state) is not str or state not in {"accepted", "failed", "quarantined"}:
            _fail("feed_state_invalid")
        if state in {"accepted", "quarantined"} and kind not in {"rss2", "atom"}:
            _fail("feed_kind_invalid")
        accepted_count = _integer(item["accepted_row_count"], "feed_counter_invalid")
        _integer(item["rejected_row_count"], "feed_counter_invalid")
        if state == "accepted" and accepted_count == 0:
            _fail("feed_state_invalid")
        if state != "accepted" and accepted_count != 0:
            _fail("feed_state_invalid")
        digest = _string(item["row_digest"], "status_digest_invalid")
        if not _DIGEST_RE.fullmatch(digest):
            _fail("status_digest_invalid")
        error = item["error_code"]
        if state == "accepted" and error is not None:
            _fail("feed_state_invalid")
        if state != "accepted" and (type(error) is not str or not _ERROR_RE.fullmatch(error)):
            _fail("feed_error_invalid")
    if data["configured_feed_count"] != len(feeds) or data["feed_count"] != len(feeds):
        _fail("status_counter_invalid")
    accepted = sum(item["state"] == "accepted" for item in feeds)
    failed = sum(item["state"] == "failed" for item in feeds)
    quarantined = sum(item["state"] == "quarantined" for item in feeds)
    accepted_rows = sum(item["accepted_row_count"] for item in feeds)
    if data["successful_feed_count"] != accepted or data["failed_feed_count"] != failed:
        _fail("status_counter_invalid")
    if data["quarantined_feed_count"] != quarantined or data["accepted_row_count"] != accepted_rows:
        _fail("status_counter_invalid")
    complete = failed == 0 and quarantined == 0
    if data["publication_complete"] != complete or data["eligible_for_live_publication"] != complete:
        _fail("status_flag_invalid")
    return data


def serialize_status(status: Mapping[str, object]) -> bytes:
    return _canonical(_validate_wire(status), "status_invalid")


def parse_status_bytes(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes:
        _fail("status_bytes_invalid")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("status_bytes_invalid")
    data = _validate_wire(value)
    if serialize_status(data) != payload:
        _fail("status_noncanonical")
    return data


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("status_duplicate_key")
        result[key] = value
    return result
