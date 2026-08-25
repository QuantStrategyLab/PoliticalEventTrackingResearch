from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum


STATUS_VERSION = "pert.feed_status_canonical.v1"
MAX_SAFE_JSON_INTEGER = 2**53 - 1
MAX_ROWS_PER_FEED = 10_000
EMPTY_DIGEST = hashlib.sha256(b"[]").hexdigest()
_ROW_KEYS = ("item_id", "published_at", "source_type", "source_url", "author", "text")
_OUTCOME_KEYS = frozenset({"feed_id", "feed_url", "kind", "state", "rows", "error_code"})
_FEED_KEYS = frozenset(
    {"feed_id", "feed_url", "kind", "state", "accepted_row_count", "rejected_row_count", "row_digest", "error_code"}
)
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
_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class DecisionContractError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DecisionKind(str, Enum):
    SUCCESS = "success"
    QUARANTINE = "quarantine"
    HARD_FAIL = "hard_fail"


@dataclass(frozen=True)
class ProducerDecision:
    kind: DecisionKind


@dataclass(frozen=True)
class CanonicalDecision:
    status_bytes: bytes
    decision: ProducerDecision


def _fail(code: str) -> None:
    raise DecisionContractError(code)


def _mapping(value: object, keys: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        _fail(code)
    try:
        data = dict(value)
    except (AttributeError, KeyError, OverflowError, RuntimeError, TypeError, UnicodeError, ValueError):
        _fail(code)
    if set(data) != keys or any(type(key) is not str for key in data):
        _fail(code)
    return data


def _string(value: object, code: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value) or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _integer(value: object, code: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_SAFE_JSON_INTEGER:
        _fail(code)
    return value


def _row(value: object) -> dict[str, str]:
    data = _mapping(value, frozenset(_ROW_KEYS), "row_invalid")
    return {key: _string(data[key], "row_invalid", allow_empty=key == "author") for key in _ROW_KEYS}


def _digest(rows: list[dict[str, str]]) -> str:
    ordered = sorted(rows, key=lambda row: tuple(row[key] for key in _ROW_KEYS))
    try:
        payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail("row_digest_invalid")
    return hashlib.sha256(payload).hexdigest()


def _parse_outcome(value: object) -> tuple[dict[str, object], list[dict[str, str]]]:
    data = _mapping(value, _OUTCOME_KEYS, "outcome_invalid")
    kind = data["kind"]
    state = data["state"]
    if type(kind) is not str or kind not in {"rss2", "atom", "unknown"}:
        _fail("feed_kind_invalid")
    if type(state) is not str or state not in {"accepted", "failed", "quarantined"}:
        _fail("feed_state_invalid")
    rows_value = data["rows"]
    if not isinstance(rows_value, (list, tuple)) or len(rows_value) > MAX_ROWS_PER_FEED:
        _fail("rows_invalid")
    rows = [_row(item) for item in rows_value]
    error = data["error_code"]
    if error is not None and (type(error) is not str or not _ERROR_RE.fullmatch(error)):
        _fail("error_code_invalid")
    if state in {"accepted", "quarantined"} and kind not in {"rss2", "atom"}:
        _fail("feed_kind_invalid")
    if state == "accepted" and (not rows or error is not None):
        _fail("outcome_invariant_invalid")
    if state == "quarantined" and (rows or error is None):
        _fail("outcome_invariant_invalid")
    if state == "failed" and (rows or error is None):
        _fail("outcome_invariant_invalid")
    return {
        "feed_id": _string(data["feed_id"], "feed_invalid"),
        "feed_url": _string(data["feed_url"], "feed_invalid"),
        "kind": kind,
        "state": state,
        "error_code": error,
    }, rows


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail("status_serialization_invalid")


def _build_wire(parsed: list[tuple[dict[str, object], list[dict[str, str]]]]) -> dict[str, object]:
    parsed.sort(key=lambda pair: (pair[0]["feed_id"], pair[0]["feed_url"]))
    accepted_rows = sorted(
        [row for data, rows in parsed if data["state"] == "accepted" for row in rows],
        key=lambda row: tuple(row[key] for key in _ROW_KEYS),
    )
    feeds = []
    for data, rows in parsed:
        accepted = data["state"] == "accepted"
        feeds.append(
            {
                "feed_id": data["feed_id"],
                "feed_url": data["feed_url"],
                "kind": data["kind"],
                "state": data["state"],
                "accepted_row_count": len(rows) if accepted else 0,
                "rejected_row_count": 0,
                "row_digest": _digest(rows) if accepted else EMPTY_DIGEST,
                "error_code": data["error_code"],
            }
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
        "aggregate_row_digest": _digest(accepted_rows) if accepted_rows else EMPTY_DIGEST,
        "feeds": feeds,
    }


def build_decision(validated_outcomes: Iterable[Mapping[str, object]]) -> CanonicalDecision:
    try:
        values = list(validated_outcomes)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("outcomes_invalid")
    if not values:
        _fail("feed_config_empty")
    parsed = [_parse_outcome(value) for value in values]
    if len({data["feed_id"] for data, _ in parsed}) != len(parsed):
        _fail("feed_duplicate")
    status = _build_wire(parsed)
    kind = (
        DecisionKind.HARD_FAIL
        if status["failed_feed_count"]
        else DecisionKind.QUARANTINE
        if status["quarantined_feed_count"]
        else DecisionKind.SUCCESS
    )
    return CanonicalDecision(_canonical(status), ProducerDecision(kind))


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("status_duplicate_key")
        result[key] = value
    return result


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
    if not isinstance(feeds, list) or not feeds:
        _fail("feed_invalid")
    previous: tuple[str, str] | None = None
    ids: set[str] = set()
    for value in feeds:
        item = _mapping(value, _FEED_KEYS, "feed_invalid")
        feed_id = _string(item["feed_id"], "feed_invalid")
        feed_url = _string(item["feed_url"], "feed_invalid")
        key = (feed_id, feed_url)
        if feed_id in ids:
            _fail("feed_duplicate")
        if previous is not None and key <= previous:
            _fail("feed_order_invalid")
        ids.add(feed_id)
        previous = key
        kind = item["kind"]
        state = item["state"]
        if type(kind) is not str or kind not in {"rss2", "atom", "unknown"}:
            _fail("feed_kind_invalid")
        if type(state) is not str or state not in {"accepted", "failed", "quarantined"}:
            _fail("feed_state_invalid")
        if state in {"accepted", "quarantined"} and kind not in {"rss2", "atom"}:
            _fail("feed_kind_invalid")
        accepted_count = _integer(item["accepted_row_count"], "feed_counter_invalid")
        rejected_count = _integer(item["rejected_row_count"], "feed_counter_invalid")
        if accepted_count > MAX_ROWS_PER_FEED:
            _fail("feed_counter_invalid")
        if rejected_count != 0:
            _fail("rejected_count_invalid")
        if state == "accepted" and accepted_count == 0:
            _fail("feed_state_invalid")
        if state != "accepted" and accepted_count != 0:
            _fail("feed_state_invalid")
        digest = _string(item["row_digest"], "status_digest_invalid")
        if not _DIGEST_RE.fullmatch(digest):
            _fail("status_digest_invalid")
        if state == "accepted" and digest == EMPTY_DIGEST:
            _fail("empty_digest_invalid")
        if state != "accepted" and digest != EMPTY_DIGEST:
            _fail("empty_digest_invalid")
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
    rejected_rows = sum(item["rejected_row_count"] for item in feeds)
    if data["successful_feed_count"] != accepted or data["failed_feed_count"] != failed:
        _fail("status_counter_invalid")
    if data["quarantined_feed_count"] != quarantined or data["accepted_row_count"] != accepted_rows:
        _fail("status_counter_invalid")
    if rejected_rows != 0 or data["rejected_row_count"] != 0:
        _fail("rejected_count_invalid")
    if accepted_rows == 0 and aggregate != EMPTY_DIGEST:
        _fail("empty_digest_invalid")
    if accepted_rows > 0 and aggregate == EMPTY_DIGEST:
        _fail("empty_digest_invalid")
    complete = failed == 0 and quarantined == 0
    if data["publication_complete"] != complete or data["eligible_for_live_publication"] != complete:
        _fail("status_flag_invalid")
    return data


def read_status(status_bytes: bytes) -> dict[str, object]:
    if type(status_bytes) is not bytes:
        _fail("status_bytes_invalid")
    try:
        value = json.loads(status_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("status_bytes_invalid")
    data = _validate_wire(value)
    if _canonical(data) != status_bytes:
        _fail("status_noncanonical")
    return json.loads(status_bytes.decode("utf-8"))
