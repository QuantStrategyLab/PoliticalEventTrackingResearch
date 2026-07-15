"""Pure RSS/Atom content acceptance and canonical fetch-status contract."""
from __future__ import annotations

import email.utils
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

_STATUS_KEYS = frozenset(
    {
        "status_version",
        "configured_feed_count",
        "feed_count",
        "successful_feed_count",
        "failed_feed_count",
        "stale_feed_count",
        "missing_feed_count",
        "quarantined_feed_count",
        "accepted_row_count",
        "rejected_row_count",
        "publication_complete",
        "eligible_for_live_publication",
        "zero_entry_policy",
        "feeds",
    }
)
_FEED_KEYS = frozenset({"feed_id", "feed_url", "kind", "accepted_row_count", "rejected_row_count", "state", "error_code"})
_STATES = frozenset({"accepted", "failed", "stale", "missing", "quarantined"})
_KINDS = frozenset({"rss", "atom", "unknown"})
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]*$")
_ATOM = "http://www.w3.org/2005/Atom"
MAX_XML_BYTES = 1024 * 1024
MAX_XML_DEPTH = 32
MAX_XML_NODES = 10000
MAX_XML_TEXT_BYTES = 256 * 1024
MAX_XML_ATTRIBUTES = 128
_FORBIDDEN_DECLARATION = re.compile(rb"<!\s*(?:doctype|entity|element|attlist|notation)\b|\b(?:system|public)\b", re.IGNORECASE)


class FetchAcceptanceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> FetchAcceptanceError:
    return FetchAcceptanceError(code)


def _text(element: ET.Element | None, names: tuple[str, ...]) -> str:
    if element is None:
        return ""
    for name in names:
        child = element.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _atom_link(entry: ET.Element) -> str:
    for child in entry:
        if child.tag == f"{{{_ATOM}}}link" and child.attrib.get("href"):
            return child.attrib["href"]
    return _text(entry, (f"{{{_ATOM}}}id", "id"))


def _valid_timestamp(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(normalized)
        except (TypeError, ValueError):
            return False
    return parsed.tzinfo is not None and parsed.astimezone(timezone.utc) is not None


def _feed_result(feed_id: str, feed_url: str, kind: str, accepted: int, rejected: int, state: str, error_code: str | None) -> dict[str, object]:
    if type(feed_id) is not str or not feed_id or type(feed_url) is not str or not feed_url or kind not in _KINDS or state not in _STATES or type(accepted) is not int or accepted < 0 or type(rejected) is not int or rejected < 0 or type(error_code) not in {str, type(None)} or (error_code is not None and not _SAFE_ERROR.fullmatch(error_code)):
        raise _fail("feed_result_invalid")
    return {"feed_id": feed_id, "feed_url": feed_url, "kind": kind, "accepted_row_count": accepted, "rejected_row_count": rejected, "state": state, "error_code": error_code}


def _parse_bounded_xml(payload: bytes) -> ET.Element:
    if type(payload) is not bytes:
        raise _fail("feed_payload_invalid")
    if len(payload) > MAX_XML_BYTES:
        raise _fail("xml_oversize")
    if _FORBIDDEN_DECLARATION.search(payload):
        raise _fail("xml_forbidden_declaration")
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, UnicodeError, ValueError, RecursionError):
        raise _fail("xml_invalid") from None
    nodes = 0
    text_bytes = 0
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        nodes += 1
        if nodes > MAX_XML_NODES or depth > MAX_XML_DEPTH or len(element.attrib) > MAX_XML_ATTRIBUTES:
            raise _fail("xml_structure_over_limit")
        for text in (element.text, element.tail):
            if text is not None:
                text_bytes += len(text.encode("utf-8", errors="strict"))
                if text_bytes > MAX_XML_TEXT_BYTES:
                    raise _fail("xml_structure_over_limit")
        stack.extend((child, depth + 1) for child in reversed(list(element)))
    return root


def classify_feed_payload(feed_id: str, feed_url: str, payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes:
        raise _fail("feed_payload_invalid")
    try:
        root = _parse_bounded_xml(payload)
    except FetchAcceptanceError as error:
        return _feed_result(feed_id, feed_url, "unknown", 0, 0, "failed", error.code)
    if root.tag == "rss":
        if root.attrib.get("version") not in {"2.0"}:
            return _feed_result(feed_id, feed_url, "unknown", 0, 0, "failed", "rss_schema_unsupported")
        channel = root.find("./channel")
        if channel is None:
            return _feed_result(feed_id, feed_url, "rss", 0, 0, "failed", "rss_schema_invalid")
        entries = channel.findall("./item")
        kind = "rss"
        def row_valid(entry: ET.Element) -> bool:
            return bool(_text(entry, ("title",)) and (_text(entry, ("link",)) or _text(entry, ("guid",))) and _valid_timestamp(_text(entry, ("pubDate", "{http://purl.org/dc/elements/1.1/}date"))))
    elif root.tag == f"{{{_ATOM}}}feed":
        entries = root.findall(f"{{{_ATOM}}}entry")
        kind = "atom"
        def row_valid(entry: ET.Element) -> bool:
            published = _text(entry, (f"{{{_ATOM}}}published", f"{{{_ATOM}}}updated"))
            return bool(_text(entry, (f"{{{_ATOM}}}title",)) and _atom_link(entry) and _valid_timestamp(published))
    else:
        return _feed_result(feed_id, feed_url, "unknown", 0, 0, "failed", "payload_not_rss_atom")
    accepted = sum(row_valid(entry) for entry in entries)
    rejected = len(entries) - accepted
    if not entries:
        return _feed_result(feed_id, feed_url, kind, 0, 0, "quarantined", "zero_entries")
    if rejected:
        return _feed_result(feed_id, feed_url, kind, accepted, rejected, "quarantined", "entry_invalid")
    return _feed_result(feed_id, feed_url, kind, accepted, 0, "accepted", None)


def _validate_feed_result(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _FEED_KEYS:
        raise _fail("feed_result_shape_invalid")
    result = _feed_result(value["feed_id"], value["feed_url"], value["kind"], value["accepted_row_count"], value["rejected_row_count"], value["state"], value["error_code"])
    if result != dict(value):
        raise _fail("feed_result_noncanonical")
    state = result["state"]
    accepted_rows = result["accepted_row_count"]
    rejected_rows = result["rejected_row_count"]
    error_code = result["error_code"]
    if state == "accepted" and (accepted_rows <= 0 or rejected_rows != 0 or error_code is not None):
        raise _fail("feed_result_invalid")
    if state in {"failed", "stale", "missing"} and (accepted_rows != 0 or rejected_rows != 0 or not error_code):
        raise _fail("feed_result_invalid")
    if state == "quarantined" and not error_code:
        raise _fail("feed_result_invalid")
    return result


def build_acceptance_status(feed_results: Iterable[Mapping[str, object]]) -> dict[str, object]:
    if not isinstance(feed_results, list) or not feed_results:
        raise _fail("configured_feed_empty")
    feeds = [_validate_feed_result(item) for item in feed_results]
    if len({item["feed_id"] for item in feeds}) != len(feeds):
        raise _fail("feed_duplicate")
    feeds.sort(key=lambda item: (item["feed_id"], item["feed_url"]))
    accepted = sum(item["state"] == "accepted" for item in feeds)
    failed = sum(item["state"] == "failed" for item in feeds)
    stale = sum(item["state"] == "stale" for item in feeds)
    missing = sum(item["state"] == "missing" for item in feeds)
    quarantined = sum(item["state"] == "quarantined" for item in feeds)
    accepted_rows = sum(item["accepted_row_count"] for item in feeds)
    rejected_rows = sum(item["rejected_row_count"] for item in feeds)
    complete = len(feeds) > 0 and accepted == len(feeds) and not any((failed, stale, missing, quarantined)) and accepted_rows > 0
    return {
        "status_version": "pert.fetch_acceptance.v1",
        "configured_feed_count": len(feeds),
        "feed_count": len(feeds),
        "successful_feed_count": accepted,
        "failed_feed_count": failed,
        "stale_feed_count": stale,
        "missing_feed_count": missing,
        "quarantined_feed_count": quarantined,
        "accepted_row_count": accepted_rows,
        "rejected_row_count": rejected_rows,
        "publication_complete": complete,
        "eligible_for_live_publication": complete,
        "zero_entry_policy": "quarantine",
        "feeds": feeds,
    }


def _validate_status(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _STATUS_KEYS or value.get("status_version") != "pert.fetch_acceptance.v1" or value.get("zero_entry_policy") != "quarantine":
        raise _fail("status_shape_invalid")
    integer_keys = ("configured_feed_count", "feed_count", "successful_feed_count", "failed_feed_count", "stale_feed_count", "missing_feed_count", "quarantined_feed_count", "accepted_row_count", "rejected_row_count")
    if any(type(value[key]) is not int or value[key] < 0 for key in integer_keys) or type(value["publication_complete"]) is not bool or type(value["eligible_for_live_publication"]) is not bool or value["publication_complete"] != value["eligible_for_live_publication"] or not isinstance(value["feeds"], list):
        raise _fail("status_counter_invalid")
    expected = build_acceptance_status(value["feeds"])
    if dict(value) != expected:
        raise _fail("status_counter_mismatch")
    return expected


def serialize_status(value: Mapping[str, object]) -> bytes:
    try:
        payload = _validate_status(value)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except FetchAcceptanceError:
        raise
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _fail("status_serialization_invalid") from None


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
    except FetchAcceptanceError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _fail("status_wire_invalid") from None
    parsed = _validate_status(value)
    if serialize_status(parsed) != wire:
        raise _fail("status_noncanonical")
    return parsed
