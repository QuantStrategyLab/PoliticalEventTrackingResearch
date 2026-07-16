"""Producer-boundary freshness evidence for one bounded feed snapshot."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException


EVIDENCE_VERSION = "pert.source_freshness_evidence.v1"
POLICY_VERSION = "monday_weekly_8d_5m.v1"
MAX_BODY_BYTES = 1024 * 1024
MAX_HEADER_VALUE_BYTES = 4096
MAX_FRESHNESS_AGE = dt.timedelta(days=8)
FUTURE_TOLERANCE = dt.timedelta(minutes=5)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EVIDENCE_KEYS = frozenset(
    {
        "evidence_version",
        "policy_version",
        "feed_id",
        "source_identity_digest",
        "body_sha256",
        "reference_time",
        "selected_signal",
        "signals",
        "decision",
    }
)
_SIGNAL_KEYS = frozenset({"kind", "present", "valid", "value"})
_SIGNAL_KINDS = (
    "atom_feed_updated",
    "rss_channel_last_build_date",
    "http_last_modified",
    "http_date",
)
_SELECTABLE = frozenset(_SIGNAL_KINDS[:3])


class FreshnessError(ValueError):
    """Stable, sanitized producer freshness contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise FreshnessError(code)


def _string(value: object, code: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value) or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _timestamp(value: object, code: str = "freshness_time_invalid") -> dt.datetime:
    if type(value) is not str or not _TIMESTAMP_RE.fullmatch(value):
        _fail(code)
    try:
        return dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(code)


def _canonical_timestamp(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_date_signal(value: object) -> tuple[bool, str | None]:
    if type(value) is not str or not value or len(value) > MAX_HEADER_VALUE_BYTES:
        return False, None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed is None:
            raise ValueError
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return True, _canonical_timestamp(parsed)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.UTC)
            return True, _canonical_timestamp(parsed)
        except (TypeError, ValueError, OverflowError):
            return False, None


def _headers(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _fail("freshness_headers_invalid")
    result: dict[str, str] = {}
    try:
        items = list(value.items())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("freshness_headers_invalid")
    for key, item in items:
        if (
            type(key) is not str
            or any(ord(char) < 0x20 for char in key)
            or type(item) is not str
            or len(item.encode("utf-8")) > MAX_HEADER_VALUE_BYTES
        ):
            _fail("freshness_headers_invalid")
        normalized = key.lower()
        if normalized in result:
            _fail("freshness_headers_invalid")
        result[normalized] = item
    return result


def _source_identity(source_url: object) -> str:
    value = _string(source_url, "source_identity_invalid")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            _fail("source_identity_invalid")
    except ValueError:
        _fail("source_identity_invalid")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _xml_signal(body: bytes, kind: str) -> tuple[bool, str | None]:
    try:
        root = ET.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, LookupError, UnicodeError, ValueError, RecursionError):
        _fail("source_freshness_invalid")
    if root.tag == "rss":
        channels = [child for child in root if child.tag == "channel"]
        if len(channels) != 1:
            _fail("source_freshness_invalid")
        if kind == "rss_channel_last_build_date":
            values = [child.text.strip() for child in channels[0] if child.tag == "lastBuildDate" and child.text]
            if len(values) > 1:
                _fail("source_freshness_invalid")
            if not values:
                return False, None
            return True, _parse_date_signal(values[0])[1]
        return False, None
    if root.tag == "{http://www.w3.org/2005/Atom}feed":
        if kind == "atom_feed_updated":
            values = [child.text.strip() for child in root if child.tag == "{http://www.w3.org/2005/Atom}updated" and child.text]
            if len(values) > 1:
                _fail("source_freshness_invalid")
            if not values:
                return False, None
            return True, _parse_date_signal(values[0])[1]
        return False, None
    _fail("source_freshness_invalid")


def _signal(kind: str, present: bool, value: str | None, valid: bool) -> dict[str, object]:
    return {"kind": kind, "present": present, "valid": valid, "value": value}


def _validate_signal(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SIGNAL_KEYS:
        _fail("freshness_invalid")
    kind = _string(value["kind"], "freshness_invalid")
    if kind not in _SIGNAL_KINDS or type(value["present"]) is not bool or type(value["valid"]) is not bool:
        _fail("freshness_invalid")
    signal_value = value["value"]
    if signal_value is not None:
        _timestamp(signal_value, "freshness_invalid")
    if not value["present"] and (signal_value is not None or value["valid"]):
        _fail("freshness_invalid")
    if value["valid"] and signal_value is None:
        _fail("freshness_invalid")
    return {key: value[key] for key in ("kind", "present", "valid", "value")}


def _validate_evidence(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _EVIDENCE_KEYS:
        _fail("freshness_invalid")
    if value["evidence_version"] != EVIDENCE_VERSION or value["policy_version"] != POLICY_VERSION:
        _fail("freshness_invalid")
    _string(value["feed_id"], "freshness_invalid")
    for key in ("source_identity_digest", "body_sha256"):
        if type(value[key]) is not str or not _DIGEST_RE.fullmatch(value[key]):
            _fail("freshness_invalid")
    _timestamp(value["reference_time"], "freshness_invalid")
    signals = value["signals"]
    if not isinstance(signals, list) or len(signals) != len(_SIGNAL_KINDS):
        _fail("freshness_invalid")
    parsed = [_validate_signal(item) for item in signals]
    if [item["kind"] for item in parsed] != list(_SIGNAL_KINDS):
        _fail("freshness_invalid")
    for item in parsed[:3]:
        if item["present"] and not item["valid"]:
            _fail("freshness_invalid")
    first_present = next((item for item in parsed[:3] if item["present"]), None)
    selected = value["selected_signal"]
    if selected is not None:
        selected = _validate_signal(selected)
        if selected["kind"] not in _SELECTABLE or not selected["valid"]:
            _fail("freshness_invalid")
        matching = next(item for item in parsed if item["kind"] == selected["kind"])
        if selected != matching:
            _fail("freshness_invalid")
    if selected != first_present:
        _fail("freshness_invalid")
    if selected is not None:
        reference = _timestamp(value["reference_time"])
        selected_time = _timestamp(selected["value"])
        if selected_time > reference + FUTURE_TOLERANCE or reference - selected_time > MAX_FRESHNESS_AGE:
            _fail("freshness_invalid")
    if value["decision"] not in {"eligible", "source_freshness_unverified"}:
        _fail("freshness_invalid")
    if (value["decision"] == "eligible") != (selected is not None):
        _fail("freshness_invalid")
    return {
        "evidence_version": value["evidence_version"],
        "policy_version": value["policy_version"],
        "feed_id": value["feed_id"],
        "source_identity_digest": value["source_identity_digest"],
        "body_sha256": value["body_sha256"],
        "reference_time": value["reference_time"],
        "selected_signal": selected,
        "signals": parsed,
        "decision": value["decision"],
    }


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("freshness_serialization_invalid")


def build_freshness_evidence(
    *,
    feed_id: str,
    source_url: str,
    body: bytes,
    response_headers: Mapping[str, str],
    reference_time: str,
) -> bytes:
    if type(body) is not bytes or len(body) > MAX_BODY_BYTES:
        _fail("freshness_body_invalid")
    reference = _timestamp(reference_time)
    headers = _headers(response_headers)
    atom_present, atom_value = _xml_signal(body, "atom_feed_updated")
    rss_present, rss_value = _xml_signal(body, "rss_channel_last_build_date")
    last_modified = headers.get("last-modified")
    http_present = last_modified is not None
    http_valid, http_value = _parse_date_signal(last_modified) if http_present else (False, None)
    date_value = headers.get("date")
    date_present = date_value is not None
    date_valid, date_parsed = _parse_date_signal(date_value) if date_present else (False, None)
    signals = [
        _signal("atom_feed_updated", atom_present, atom_value, atom_present and atom_value is not None),
        _signal("rss_channel_last_build_date", rss_present, rss_value, rss_present and rss_value is not None),
        _signal("http_last_modified", http_present, http_value, http_present and http_valid),
        _signal("http_date", date_present, date_parsed, date_present and date_valid),
    ]
    selected: dict[str, object] | None = None
    for item in signals[:3]:
        if item["present"]:
            if not item["valid"]:
                _fail("source_freshness_invalid")
            selected = item
            break
    if selected is None:
        decision = "source_freshness_unverified"
    else:
        selected_time = _timestamp(selected["value"])
        if selected_time > reference + FUTURE_TOLERANCE:
            _fail("source_freshness_future")
        if reference - selected_time > MAX_FRESHNESS_AGE:
            _fail("source_freshness_stale")
        decision = "eligible"
    payload = {
        "evidence_version": EVIDENCE_VERSION,
        "policy_version": POLICY_VERSION,
        "feed_id": _string(feed_id, "freshness_invalid"),
        "source_identity_digest": _source_identity(source_url),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "reference_time": _canonical_timestamp(reference),
        "selected_signal": selected,
        "signals": signals,
        "decision": decision,
    }
    wire = _canonical(payload)
    read_freshness_evidence(wire)
    return wire


def read_freshness_evidence(wire: bytes) -> dict[str, object]:
    if type(wire) is not bytes:
        _fail("freshness_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("freshness_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except FreshnessError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("freshness_wire_invalid")
    parsed = _validate_evidence(value)
    if _canonical(parsed) != wire:
        _fail("freshness_noncanonical")
    return parsed
