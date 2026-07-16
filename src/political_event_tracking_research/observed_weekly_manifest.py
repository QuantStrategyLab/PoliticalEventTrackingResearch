"""Canonical manifest addendum for a configured-source observed snapshot."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping

from .weekly_contract import WeeklyContractError, WeeklySourceContract, parse_weekly_contract, serialize_weekly_contract


MANIFEST_TYPE = "political_event_weekly_observed_snapshot"
OBSERVED_VERSION = "configured_source_observed.v1"
WORKFLOW_REF = "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/pert_weekly_observed_snapshot.yml@refs/heads/main"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_RE = re.compile(r"^[1-9][0-9]*$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TOP_KEYS = frozenset({"manifest_type", "contract", "observed_snapshot"})
_OBSERVED_KEYS = frozenset(
    {
        "observed_snapshot_version",
        "coverage_semantics",
        "retrieved_at",
        "provider_freshness",
        "private_research_only",
        "fetch_parse_outcome",
        "source_run_id",
        "source_attempt",
        "workflow_ref",
        "source_snapshot_digest",
        "feed_snapshots",
        "selected_period_count",
        "selected_period_row_digest",
    }
)
_FEED_KEYS = frozenset({"feed_id", "kind", "body_sha256", "accepted_row_count"})


class ObservedManifestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ObservedManifestError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("observed_manifest_serialization_invalid")


def _string(value: object, code: str) -> str:
    if type(value) is not str or not value or any(ord(char) < 0x20 for char in value):
        _fail(code)
    return value


def _digest(value: object, code: str) -> str:
    if type(value) is not str or not _DIGEST_RE.fullmatch(value):
        _fail(code)
    return value


def _validate_observed(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _OBSERVED_KEYS:
        _fail("observed_manifest_shape_invalid")
    if value["observed_snapshot_version"] != OBSERVED_VERSION or value["coverage_semantics"] != "configured_source_observed":
        _fail("observed_manifest_version_invalid")
    if type(value["retrieved_at"]) is not str or not _TIME_RE.fullmatch(value["retrieved_at"]):
        _fail("observed_manifest_time_invalid")
    try:
        dt.datetime.strptime(value["retrieved_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        _fail("observed_manifest_time_invalid")
    if value["provider_freshness"] not in {"verified", "unverified", "stale"} or value["fetch_parse_outcome"] not in {"success", "failed", "quarantined", "incomplete"}:
        _fail("observed_manifest_state_invalid")
    if type(value["private_research_only"]) is not bool or not value["private_research_only"]:
        _fail("observed_manifest_scope_invalid")
    if type(value["source_attempt"]) is not int or value["source_attempt"] != 1:
        _fail("observed_manifest_attempt_invalid")
    if type(value["source_run_id"]) is not str or not _RUN_RE.fullmatch(value["source_run_id"]):
        _fail("observed_manifest_run_invalid")
    if value["workflow_ref"] != WORKFLOW_REF:
        _fail("observed_manifest_workflow_invalid")
    _digest(value["source_snapshot_digest"], "observed_manifest_digest_invalid")
    _digest(value["selected_period_row_digest"], "observed_manifest_digest_invalid")
    if type(value["selected_period_count"]) is not int or value["selected_period_count"] < 0:
        _fail("observed_manifest_count_invalid")
    feeds = value["feed_snapshots"]
    if not isinstance(feeds, list) or not feeds:
        _fail("observed_manifest_feed_invalid")
    previous = ""
    for item in feeds:
        if not isinstance(item, Mapping) or set(item) != _FEED_KEYS:
            _fail("observed_manifest_feed_invalid")
        feed_id = _string(item["feed_id"], "observed_manifest_feed_invalid")
        if feed_id <= previous or item["kind"] not in {"rss2", "atom"}:
            _fail("observed_manifest_feed_invalid")
        previous = feed_id
        _digest(item["body_sha256"], "observed_manifest_feed_invalid")
        if type(item["accepted_row_count"]) is not int or item["accepted_row_count"] <= 0:
            _fail("observed_manifest_feed_invalid")
    return {key: value[key] for key in _OBSERVED_KEYS}


def _payload(contract: WeeklySourceContract, observed: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(contract, WeeklySourceContract):
        _fail("observed_manifest_contract_invalid")
    parsed_observed = _validate_observed(observed)
    try:
        contract_payload = json.loads(serialize_weekly_contract(contract))
    except (TypeError, ValueError, UnicodeError, WeeklyContractError):
        _fail("observed_manifest_contract_invalid")
    return {"manifest_type": MANIFEST_TYPE, "contract": contract_payload, "observed_snapshot": parsed_observed}


def serialize_observed_manifest(contract: WeeklySourceContract, observed: Mapping[str, object]) -> bytes:
    wire = _canonical(_payload(contract, observed))
    read_observed_manifest(wire)
    return wire


def read_observed_manifest(wire: bytes) -> dict[str, object]:
    if type(wire) is not bytes:
        _fail("observed_manifest_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("observed_manifest_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(wire.decode("utf-8"), object_pairs_hook=pairs)
    except ObservedManifestError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("observed_manifest_wire_invalid")
    if not isinstance(value, Mapping) or set(value) != _TOP_KEYS or value["manifest_type"] != MANIFEST_TYPE:
        _fail("observed_manifest_shape_invalid")
    try:
        contract = parse_weekly_contract(value["contract"])
    except (TypeError, ValueError, WeeklyContractError):
        _fail("observed_manifest_contract_invalid")
    observed = _validate_observed(value["observed_snapshot"])
    parsed = {"manifest_type": MANIFEST_TYPE, "contract": json.loads(serialize_weekly_contract(contract)), "observed_snapshot": observed}
    if _canonical(parsed) != wire:
        _fail("observed_manifest_noncanonical")
    return parsed
