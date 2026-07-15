from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum


STATUS_VERSION = "pert.feed_status_decision.v1"
MAX_SAFE_JSON_INTEGER = 2**53 - 1
MAX_ROWS_PER_FEED = 10_000
_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ROW_KEYS = ("item_id", "published_at", "source_type", "source_url", "author", "text")
_OUTCOME_KEYS = frozenset({"feed_id", "feed_url", "kind", "state", "rows", "error_code"})
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


class DecisionContractError(ValueError):
    """Sanitized error for malformed already-validated primitive outcomes."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DecisionKind(str, Enum):
    SUCCESS = "success"
    QUARANTINE = "quarantine"
    HARD_FAIL = "hard_fail"


@dataclass(frozen=True)
class _Row:
    item_id: str
    published_at: str
    source_type: str
    source_url: str
    author: str
    text: str

    def wire(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in _ROW_KEYS}


@dataclass(frozen=True)
class StatusEvidence:
    status: dict[str, object]
    canonical_bytes: bytes


@dataclass(frozen=True)
class ProducerDecision:
    kind: DecisionKind


@dataclass(frozen=True)
class StatusDecision:
    evidence: StatusEvidence
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


def _row(value: object) -> _Row:
    data = _mapping(value, frozenset(_ROW_KEYS), "row_invalid")
    values = [_string(data[key], "row_invalid", allow_empty=key == "author") for key in _ROW_KEYS]
    return _Row(*values)


def _parse_outcome(value: object) -> tuple[dict[str, object], list[_Row]]:
    data = _mapping(value, _OUTCOME_KEYS, "outcome_invalid")
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
    return {"feed_id": feed_id, "feed_url": feed_url, "kind": kind, "state": state, "error_code": error}, rows


def _row_key(row: _Row) -> tuple[str, str]:
    return row.published_at, row.item_id


def _digest(rows: list[_Row]) -> str:
    ordered = sorted(rows, key=_row_key)
    try:
        data = json.dumps(
            [row.wire() for row in ordered],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail("digest_invalid")
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail("status_serialization_invalid")


def _build_status(parsed: list[tuple[dict[str, object], list[_Row]]]) -> dict[str, object]:
    parsed.sort(key=lambda item: (item[0]["feed_id"], item[0]["feed_url"]))
    accepted_rows = sorted(
        [row for data, rows in parsed if data["state"] == "accepted" for row in rows], key=_row_key
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
                "row_digest": _digest(rows) if accepted else hashlib.sha256(b"[]").hexdigest(),
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
        "aggregate_row_digest": _digest(accepted_rows),
        "feeds": feeds,
    }


def build_status_decision(outcomes: Iterable[Mapping[str, object]]) -> StatusDecision:
    try:
        values = list(outcomes)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("outcomes_invalid")
    if not values:
        _fail("feed_config_empty")
    parsed = [_parse_outcome(value) for value in values]
    ids = [data["feed_id"] for data, _ in parsed]
    if len(set(ids)) != len(ids):
        _fail("feed_duplicate")
    status = _build_status(parsed)
    evidence = StatusEvidence(status, _canonical(status))
    if status["failed_feed_count"]:
        kind = DecisionKind.HARD_FAIL
    elif status["quarantined_feed_count"]:
        kind = DecisionKind.QUARANTINE
    else:
        kind = DecisionKind.SUCCESS
    return StatusDecision(evidence, ProducerDecision(kind))
