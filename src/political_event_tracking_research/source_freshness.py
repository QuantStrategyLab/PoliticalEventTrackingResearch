"""Strict, producer-boundary freshness evidence for one feed response."""

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
MAX_WIRE_BYTES = 64 * 1024
MAX_HEADER_VALUE_BYTES = 4096
MAX_AGE = dt.timedelta(days=8)
FUTURE_TOLERANCE = dt.timedelta(minutes=5)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_IMF_RE = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} \d{2}:\d{2}:\d{2} GMT$")
_RFC2822_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"\d{4} \d{2}:\d{2}:\d{2} (?:[+-]\d{4}|UT|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)$"
)
_SIGNAL_KINDS = ("atom_feed_updated", "rss_channel_last_build_date", "http_last_modified", "http_date")
_SELECTABLE = frozenset(_SIGNAL_KINDS[:3])
_EVIDENCE_KEYS = frozenset(
    {"evidence_version", "policy_version", "feed_id", "source_identity_digest", "body_sha256", "reference_time", "selected_signal", "signals", "decision"}
)
_SIGNAL_KEYS = frozenset({"kind", "present", "valid", "value"})


class FreshnessError(ValueError):
    """Stable, sanitized freshness contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise FreshnessError(code)


def _string(value: object, code: str) -> str:
    if type(value) is not str or not value or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _reference(value: object) -> dt.datetime:
    if type(value) is not str or not value.endswith("Z") or not _UTC_RE.fullmatch(value):
        _fail("freshness_time_invalid")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    except ValueError:
        _fail("freshness_time_invalid")


def _rfc3339(value: object) -> tuple[bool, str | None]:
    if type(value) is not str or len(value) > MAX_HEADER_VALUE_BYTES or not _UTC_RE.fullmatch(value):
        return False, None
    normalized = value[:-1] + "+0000" if value.endswith("Z") else value[:-3] + value[-3:].replace(":", "")
    try:
        parsed = dt.datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            parsed = dt.datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return False, None
    return True, parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_date(value: object) -> tuple[bool, str | None]:
    if type(value) is not str or not _IMF_RE.fullmatch(value):
        return False, None
    try:
        parsed = dt.datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=dt.UTC)
    except ValueError:
        return False, None
    return True, parsed.isoformat().replace("+00:00", "Z")


def _rfc2822(value: object) -> tuple[bool, str | None]:
    if type(value) is not str or len(value) > MAX_HEADER_VALUE_BYTES or not _RFC2822_RE.fullmatch(value):
        return False, None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return False, None
    if parsed is None or parsed.tzinfo is None:
        return False, None
    return True, parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _headers(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _fail("freshness_headers_invalid")
    try:
        items = list(value.items())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("freshness_headers_invalid")
    result: dict[str, str] = {}
    for key, item in items:
        if type(key) is not str or any(ord(char) < 0x20 for char in key) or type(item) is not str or len(item.encode()) > MAX_HEADER_VALUE_BYTES:
            _fail("freshness_headers_invalid")
        normalized = key.lower()
        if normalized in result:
            _fail("freshness_headers_invalid")
        result[normalized] = item
    return result


def _source_digest(source_url: object) -> str:
    value = _string(source_url, "source_identity_invalid")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            _fail("source_identity_invalid")
    except ValueError:
        _fail("source_identity_invalid")
    return hashlib.sha256(value.encode()).hexdigest()


def _xml_values(body: bytes) -> tuple[str | None, str | None]:
    try:
        root = ET.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, LookupError, UnicodeError, ValueError, RecursionError):
        _fail("source_freshness_invalid")
    if root.tag == "rss":
        channels = [child for child in root if child.tag == "channel"]
        if len(channels) != 1:
            _fail("source_freshness_invalid")
        values = [child.text.strip() if child.text is not None else "" for child in channels[0] if child.tag == "lastBuildDate"]
        if len(values) > 1:
            _fail("source_freshness_invalid")
        return None, values[0] if values else None
    if root.tag == "{http://www.w3.org/2005/Atom}feed":
        values = [child.text.strip() if child.text is not None else "" for child in root if child.tag == "{http://www.w3.org/2005/Atom}updated"]
        if len(values) > 1:
            _fail("source_freshness_invalid")
        return values[0] if values else None, None
    _fail("source_freshness_invalid")


def _signal(kind: str, present: bool, valid: bool, value: str | None) -> dict[str, object]:
    return {"kind": kind, "present": present, "valid": valid, "value": value}


def _validate_signal(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SIGNAL_KEYS:
        _fail("freshness_invalid")
    kind = value["kind"]
    if type(kind) is not str or kind not in _SIGNAL_KINDS or type(value["present"]) is not bool or type(value["valid"]) is not bool:
        _fail("freshness_invalid")
    signal_value = value["value"]
    if signal_value is not None:
        _reference(signal_value)
    if not value["present"] and (signal_value is not None or value["valid"]):
        _fail("freshness_invalid")
    if value["valid"] != (signal_value is not None):
        _fail("freshness_invalid")
    return {key: value[key] for key in ("kind", "present", "valid", "value")}


def _validate(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _EVIDENCE_KEYS:
        _fail("freshness_invalid")
    if value["evidence_version"] != EVIDENCE_VERSION or value["policy_version"] != POLICY_VERSION:
        _fail("freshness_invalid")
    _string(value["feed_id"], "freshness_invalid")
    for key in ("source_identity_digest", "body_sha256"):
        if type(value[key]) is not str or not _DIGEST_RE.fullmatch(value[key]):
            _fail("freshness_invalid")
    reference = _reference(value["reference_time"])
    signals = value["signals"]
    if not isinstance(signals, list) or len(signals) != len(_SIGNAL_KINDS):
        _fail("freshness_invalid")
    parsed = [_validate_signal(item) for item in signals]
    if [item["kind"] for item in parsed] != list(_SIGNAL_KINDS):
        _fail("freshness_invalid")
    for item in parsed[:3]:
        if item["present"] and not item["valid"]:
            _fail("freshness_invalid")
    selected = value["selected_signal"]
    first_present = next((item for item in parsed[:3] if item["present"]), None)
    if selected is not None:
        selected = _validate_signal(selected)
        if selected["kind"] not in _SELECTABLE or not selected["valid"]:
            _fail("freshness_invalid")
        if selected != next(item for item in parsed if item["kind"] == selected["kind"]):
            _fail("freshness_invalid")
        selected_time = _reference(selected["value"])
        if selected_time > reference + FUTURE_TOLERANCE or reference - selected_time > MAX_AGE:
            _fail("freshness_invalid")
    if selected != first_present or value["decision"] not in {"eligible", "source_freshness_unverified"}:
        _fail("freshness_invalid")
    if (value["decision"] == "eligible") != (selected is not None):
        _fail("freshness_invalid")
    return {key: value[key] for key in ("evidence_version", "policy_version", "feed_id", "source_identity_digest", "body_sha256", "reference_time", "selected_signal", "signals", "decision")}


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("freshness_serialization_invalid")


def build_freshness_evidence(*, feed_id: str, source_url: str, body: bytes, response_headers: Mapping[str, str], reference_time: str) -> bytes:
    if type(body) is not bytes or len(body) > MAX_BODY_BYTES:
        _fail("freshness_body_invalid")
    reference = _reference(reference_time)
    headers = _headers(response_headers)
    atom_raw, rss_raw = _xml_values(body)
    atom_valid, atom_value = _rfc3339(atom_raw) if atom_raw is not None else (False, None)
    rss_valid, rss_value = _rfc2822(rss_raw) if rss_raw is not None else (False, None)
    last_modified_raw = headers.get("last-modified")
    last_modified_present = last_modified_raw is not None
    last_modified_valid, last_modified_value = _http_date(last_modified_raw) if last_modified_present else (False, None)
    date_raw = headers.get("date")
    date_present = date_raw is not None
    date_valid, date_value = _http_date(date_raw) if date_present else (False, None)
    signals = [
        _signal("atom_feed_updated", atom_raw is not None, atom_valid, atom_value),
        _signal("rss_channel_last_build_date", rss_raw is not None, rss_valid, rss_value),
        _signal("http_last_modified", last_modified_present, last_modified_valid, last_modified_value),
        _signal("http_date", date_present, date_valid, date_value),
    ]
    selected = None
    for item in signals[:3]:
        if item["present"]:
            if not item["valid"]:
                _fail("source_freshness_invalid")
            selected = item
            break
    if selected is None:
        decision = "source_freshness_unverified"
    else:
        selected_time = _reference(selected["value"])
        if selected_time > reference + FUTURE_TOLERANCE:
            _fail("source_freshness_future")
        if reference - selected_time > MAX_AGE:
            _fail("source_freshness_stale")
        decision = "eligible"
    payload = {
        "evidence_version": EVIDENCE_VERSION,
        "policy_version": POLICY_VERSION,
        "feed_id": _string(feed_id, "freshness_invalid"),
        "source_identity_digest": _source_digest(source_url),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "reference_time": reference_time,
        "selected_signal": selected,
        "signals": signals,
        "decision": decision,
    }
    wire = _canonical(payload)
    read_freshness_evidence(wire)
    return wire


def read_freshness_evidence(wire: bytes) -> dict[str, object]:
    if type(wire) is not bytes or len(wire) > MAX_WIRE_BYTES:
        _fail("freshness_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("freshness_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except FreshnessError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("freshness_wire_invalid")
    parsed = _validate(value)
    if _canonical(parsed) != wire:
        _fail("freshness_noncanonical")
    return parsed
