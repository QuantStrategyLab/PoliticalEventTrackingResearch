"""Canonical raw-byte validation for the future trusted weekly harness.

No returned Python value is an authority token. Each caller must retain and
revalidate the canonical bytes at its operation boundary.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

IDENTITY_VERSION = "pert.trusted_workflow_identity.v1"
TRUSTED_REPOSITORY = "QuantStrategyLab/PoliticalEventTrackingResearch"
TRUSTED_WORKFLOW_PATH = ".github/workflows/pert_weekly_period_lock_harness.yml"
TRUSTED_WORKFLOW_REF = f"{TRUSTED_REPOSITORY}/{TRUSTED_WORKFLOW_PATH}@refs/heads/main"
MAX_IDENTITY_BYTES = 4096
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_KEYS = frozenset({"identity_version", "repository", "workflow_path", "workflow_ref", "reviewed_workflow_sha"})


class TrustedWorkflowIdentityError(ValueError):
    """Stable, sanitized raw identity contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> TrustedWorkflowIdentityError:
    return TrustedWorkflowIdentityError(code)


def _reviewed_sha(value: object) -> str:
    if type(value) is not str or not _SHA_RE.fullmatch(value):
        raise _error("reviewed_workflow_sha_invalid")
    return value


def validate_trusted_workflow_ref(value: object) -> str:
    if type(value) is not str or value != TRUSTED_WORKFLOW_REF:
        raise _error("trusted_workflow_identity_mismatch")
    return TRUSTED_WORKFLOW_REF


def _wire_snapshot(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _error("identity_wire_invalid")
    try:
        items = list(value.items())
    except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("identity_wire_invalid") from None
    if len(items) != len(_KEYS):
        raise _error("identity_shape_invalid")
    result: dict[str, str] = {}
    for key, item in items:
        if type(key) is not str or key in result or type(item) is not str:
            raise _error("identity_wire_invalid")
        result[key] = item
    if set(result) != _KEYS:
        raise _error("identity_shape_invalid")
    if result["identity_version"] != IDENTITY_VERSION:
        raise _error("identity_version_invalid")
    if result["repository"] != TRUSTED_REPOSITORY or any(
        char in result["repository"] for char in "\x00\n\r\t"
    ):
        raise _error("identity_mismatch")
    if result["workflow_path"] != TRUSTED_WORKFLOW_PATH:
        raise _error("identity_mismatch")
    validate_trusted_workflow_ref(result["workflow_ref"])
    _reviewed_sha(result["reviewed_workflow_sha"])
    return result


def _canonical_bytes(value: Mapping[str, str]) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "ascii"
        )
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("identity_serialization_invalid") from None
    if len(raw) > MAX_IDENTITY_BYTES:
        raise _error("identity_wire_oversized")
    return raw


def serialize_trusted_workflow_identity(value: object) -> bytes:
    """Validate a plain mapping completely, then emit canonical bytes."""

    return _canonical_bytes(_wire_snapshot(value))


def build_trusted_workflow_identity_bytes(reviewed_workflow_sha: object) -> bytes:
    """Build canonical bytes from fixed identity constants and explicit SHA."""

    sha = _reviewed_sha(reviewed_workflow_sha)
    return serialize_trusted_workflow_identity(
        {
            "identity_version": IDENTITY_VERSION,
            "repository": TRUSTED_REPOSITORY,
            "workflow_path": TRUSTED_WORKFLOW_PATH,
            "workflow_ref": TRUSTED_WORKFLOW_REF,
            "reviewed_workflow_sha": sha,
        }
    )


def parse_trusted_workflow_identity_bytes(raw: object) -> dict[str, str]:
    """Parse and reconstruct a plain value; never return an authority object."""

    if type(raw) is not bytes:
        raise _error("identity_wire_invalid")
    if len(raw) > MAX_IDENTITY_BYTES:
        raise _error("identity_wire_oversized")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _error("identity_duplicate_key")
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise _error("identity_wire_invalid")

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs, parse_constant=reject_constant)
    except TrustedWorkflowIdentityError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("identity_wire_invalid") from None
    snapshot = _wire_snapshot(value)
    canonical = _canonical_bytes(snapshot)
    if canonical != raw:
        raise _error("identity_noncanonical")
    return dict(snapshot)


def validate_trusted_workflow_identity_bytes(raw: object) -> str:
    """Reparse canonical bytes and return only the reviewed SHA value."""

    return parse_trusted_workflow_identity_bytes(raw)["reviewed_workflow_sha"]
