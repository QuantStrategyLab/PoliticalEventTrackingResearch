from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from .feed_status_canonical_h2c import EMPTY_DIGEST, digest_rows, read_status


PUBLISH_MAX_ITEMS_PER_FEED = 50
MAX_DEBUG_ITEMS_PER_FEED = 10_000
CANONICAL_INPUT_PATHS = (
    "config/free_rss_feeds.csv",
    "config/core_us_equity_aliases.csv",
    "data/live/political_watchlist.csv",
)
REPOSITORY = "QuantStrategyLab/PoliticalEventTrackingResearch"
WORKFLOW_PATH = ".github/workflows/rss_source_pipeline.yml"
WORKFLOW_REF = f"{REPOSITORY}/{WORKFLOW_PATH}@refs/heads/main"
POLICY_VERSION = "pert.rss_publish_input.v1"
SOURCE_ITEM_FIELDS = ("item_id", "published_at", "source_type", "source_url", "author", "text")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_POLICY_KEYS = frozenset(
    {
        "evidence_version",
        "mode",
        "raw_max_items_per_feed",
        "effective_max_items_per_feed",
        "commit_outputs",
        "eligible_for_live_publication",
        "repository",
        "workflow_path",
        "workflow_ref",
        "source_sha",
        "input_paths",
        "input_sha256",
    }
)
_PUBLICATION_KEYS = _POLICY_KEYS | frozenset(
    {
        "source_items_sha256",
        "source_items_row_count",
        "status_sha256",
        "status_eligible_for_live_publication",
        "aggregate_row_digest",
    }
)


class PublishInputPolicyError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise PublishInputPolicyError(code)


def recompute_source_items_binding(source_items_bytes: bytes, status_bytes: bytes) -> tuple[int, str, bool]:
    if type(source_items_bytes) is not bytes or type(status_bytes) is not bytes:
        _fail("publication_evidence_invalid")
    try:
        reader = csv.DictReader(io.StringIO(source_items_bytes.decode("utf-8"), newline=""))
        if tuple(reader.fieldnames or ()) != SOURCE_ITEM_FIELDS:
            _fail("source_items_schema_invalid")
        rows: list[dict[str, str]] = []
        for row in reader:
            if set(row) != set(SOURCE_ITEM_FIELDS) or any(type(value) is not str for value in row.values()):
                _fail("source_items_schema_invalid")
            rows.append({key: row[key] for key in SOURCE_ITEM_FIELDS})
        canonical = io.StringIO(newline="")
        writer = csv.DictWriter(canonical, fieldnames=SOURCE_ITEM_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        if canonical.getvalue().encode("utf-8") != source_items_bytes:
            _fail("source_items_noncanonical")
        status = read_status(status_bytes)
    except (csv.Error, UnicodeError, ValueError):
        _fail("source_items_invalid")
    row_count = len(rows)
    aggregate_digest = digest_rows(rows) if rows else EMPTY_DIGEST
    derived_eligible = status["failed_feed_count"] == 0 and status["quarantined_feed_count"] == 0
    if (
        row_count != status["accepted_row_count"]
        or aggregate_digest != status["aggregate_row_digest"]
        or status["publication_complete"] is not derived_eligible
        or status["eligible_for_live_publication"] is not derived_eligible
    ):
        _fail("source_items_status_mismatch")
    return row_count, aggregate_digest, derived_eligible


def _mapping(value: object, keys: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        _fail(code)
    try:
        result = dict(value)
    except (AttributeError, KeyError, RuntimeError, TypeError, UnicodeError, ValueError):
        _fail(code)
    if set(result) != keys or any(type(key) is not str for key in result):
        _fail(code)
    return result


def _string(value: object, code: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or any(ord(char) < 0x20 for char in value):
        _fail(code)
    if pattern is not None and pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _sha256(value: object, code: str) -> str:
    return _string(value, code, pattern=_SHA256_RE)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail("evidence_serialization_invalid")


def serialize_input_policy_evidence(value: object) -> bytes:
    return _canonical_bytes(_validate_policy(value))


def serialize_publication_evidence(value: object) -> bytes:
    return _canonical_bytes(read_publication_evidence(value))


def _input_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in CANONICAL_INPUT_PATHS:
        path = root / relative
        try:
            info = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(info.st_mode):
                _fail("input_file_invalid")
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, UnicodeError):
            _fail("input_file_invalid")
    return result


def _validate_policy(value: object) -> dict[str, object]:
    data = _mapping(value, _POLICY_KEYS, "policy_evidence_invalid")
    if data["evidence_version"] != POLICY_VERSION:
        _fail("policy_version_invalid")
    mode = _string(data["mode"], "mode_invalid")
    if mode not in {"PUBLISH", "DEBUG"}:
        _fail("mode_invalid")
    raw = _string(data["raw_max_items_per_feed"], "max_items_per_feed_invalid")
    if (
        type(data["effective_max_items_per_feed"]) is not int
        or not 1 <= data["effective_max_items_per_feed"] <= MAX_DEBUG_ITEMS_PER_FEED
    ):
        _fail("max_items_per_feed_invalid")
    if mode == "PUBLISH" and (
        raw != "50" or data["effective_max_items_per_feed"] != PUBLISH_MAX_ITEMS_PER_FEED
    ):
        _fail("max_items_per_feed_invalid")
    if mode == "DEBUG" and (
        not raw.isdecimal() or str(int(raw)) != raw or int(raw) != data["effective_max_items_per_feed"]
    ):
        _fail("max_items_per_feed_invalid")
    if (
        type(data["commit_outputs"]) is not bool
        or type(data["eligible_for_live_publication"]) is not bool
    ):
        _fail("policy_flag_invalid")
    if data["commit_outputs"] != (mode == "PUBLISH") or (
        mode == "DEBUG" and data["eligible_for_live_publication"]
    ):
        _fail("publish_mode_invalid")
    if (
        data["repository"] != REPOSITORY
        or data["workflow_path"] != WORKFLOW_PATH
        or data["workflow_ref"] != WORKFLOW_REF
    ):
        _fail("workflow_identity_invalid")
    _string(data["source_sha"], "source_sha_invalid", pattern=_SHA1_RE)
    paths = data["input_paths"]
    if paths != list(CANONICAL_INPUT_PATHS):
        _fail("input_paths_invalid")
    hashes = data["input_sha256"]
    if not isinstance(hashes, Mapping) or set(hashes) != set(CANONICAL_INPUT_PATHS):
        _fail("input_digest_invalid")
    for path in CANONICAL_INPUT_PATHS:
        _sha256(hashes[path], "input_digest_invalid")
    return data


def read_input_policy_evidence(value: object) -> dict[str, object]:
    raw_bytes: bytes | None = None
    if type(value) is bytes:
        raw_bytes = value
        try:
            value = json.loads(value.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            _fail("policy_evidence_invalid")
    data = _validate_policy(value)
    canonical = _canonical_bytes(data)
    if raw_bytes is not None and canonical != raw_bytes:
        _fail("policy_evidence_noncanonical")
    return json.loads(canonical)


def build_input_policy_evidence(
    *,
    mode: str,
    raw_max_items_per_feed: object,
    commit_outputs: object,
    source_sha: str,
    workflow_ref: str,
    root: Path,
) -> dict[str, object]:
    if type(mode) is not str or mode not in {"PUBLISH", "DEBUG"} or type(commit_outputs) is not bool:
        _fail("publish_mode_invalid")
    if workflow_ref != WORKFLOW_REF:
        _fail("workflow_identity_invalid")
    if type(raw_max_items_per_feed) is not str:
        _fail("max_items_per_feed_invalid")
    try:
        effective = int(raw_max_items_per_feed)
    except (TypeError, ValueError, OverflowError):
        _fail("max_items_per_feed_invalid")
    evidence = {
        "evidence_version": POLICY_VERSION,
        "mode": mode,
        "raw_max_items_per_feed": raw_max_items_per_feed,
        "effective_max_items_per_feed": effective,
        "commit_outputs": commit_outputs,
        "eligible_for_live_publication": mode == "PUBLISH",
        "repository": REPOSITORY,
        "workflow_path": WORKFLOW_PATH,
        "workflow_ref": workflow_ref,
        "source_sha": source_sha,
        "input_paths": list(CANONICAL_INPUT_PATHS),
        "input_sha256": _input_hashes(root),
    }
    return read_input_policy_evidence(evidence)


def build_publication_evidence(
    policy: object,
    *,
    root: Path,
    source_items_bytes: bytes,
    status_bytes: bytes,
    status_eligible: bool,
    source_items_row_count: int,
    aggregate_row_digest: str,
) -> dict[str, object]:
    data = read_input_policy_evidence(policy)
    if _input_hashes(root) != data["input_sha256"]:
        _fail("input_digest_mismatch")
    if type(source_items_bytes) is not bytes or type(status_bytes) is not bytes:
        _fail("publication_evidence_invalid")
    if (
        type(status_eligible) is not bool
        or type(source_items_row_count) is not int
        or source_items_row_count < 0
    ):
        _fail("publication_evidence_invalid")
    _sha256(aggregate_row_digest, "aggregate_digest_invalid")
    evidence = {
        **data,
        "source_items_sha256": hashlib.sha256(source_items_bytes).hexdigest(),
        "source_items_row_count": source_items_row_count,
        "status_sha256": hashlib.sha256(status_bytes).hexdigest(),
        "status_eligible_for_live_publication": status_eligible,
        "aggregate_row_digest": aggregate_row_digest,
    }
    return read_publication_evidence(evidence)


def read_publication_evidence(value: object) -> dict[str, object]:
    raw_bytes: bytes | None = None
    if type(value) is bytes:
        raw_bytes = value
        try:
            value = json.loads(value.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            _fail("publication_evidence_invalid")
    data = _mapping(value, _PUBLICATION_KEYS, "publication_evidence_invalid")
    policy = _validate_policy({key: data[key] for key in _POLICY_KEYS})
    if type(data["status_eligible_for_live_publication"]) is not bool:
        _fail("publication_evidence_invalid")
    _sha256(data["source_items_sha256"], "publication_evidence_invalid")
    _sha256(data["status_sha256"], "publication_evidence_invalid")
    _sha256(data["aggregate_row_digest"], "aggregate_digest_invalid")
    if type(data["source_items_row_count"]) is not int or data["source_items_row_count"] < 0:
        _fail("publication_evidence_invalid")
    canonical = _canonical_bytes(data)
    if raw_bytes is not None and canonical != raw_bytes:
        _fail("publication_evidence_noncanonical")
    return json.loads(canonical)
