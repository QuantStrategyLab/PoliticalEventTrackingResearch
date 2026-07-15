"""Pure, code-reviewed identity for the future trusted weekly harness.

This module has no workflow, filesystem, GitHub, or artifact access. Runtime
workflow SHA evidence is validated separately from the fixed repository and
workflow path/ref; callers cannot supply an alternate trust root.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

IDENTITY_VERSION = "pert.trusted_workflow_identity.v1"
TRUSTED_REPOSITORY = "QuantStrategyLab/PoliticalEventTrackingResearch"
TRUSTED_WORKFLOW_PATH = ".github/workflows/pert_weekly_period_lock_harness.yml"
TRUSTED_WORKFLOW_REF = (
    f"{TRUSTED_REPOSITORY}/{TRUSTED_WORKFLOW_PATH}@refs/heads/main"
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_WIRE_KEYS = frozenset(
    {
        "identity_version",
        "repository",
        "workflow_path",
        "workflow_ref",
        "reviewed_workflow_sha",
    }
)


class TrustedWorkflowIdentityError(ValueError):
    """Stable, sanitized identity contract error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> TrustedWorkflowIdentityError:
    return TrustedWorkflowIdentityError(code)


@dataclass(frozen=True, slots=True, init=False)
class TrustedWorkflowIdentity:
    """Immutable fixed identity; construction has no override parameters."""

    repository: str
    workflow_path: str
    workflow_ref: str

    def __init__(self) -> None:
        object.__setattr__(self, "repository", TRUSTED_REPOSITORY)
        object.__setattr__(self, "workflow_path", TRUSTED_WORKFLOW_PATH)
        object.__setattr__(self, "workflow_ref", TRUSTED_WORKFLOW_REF)


def trusted_workflow_identity() -> TrustedWorkflowIdentity:
    """Return the only supported repository/workflow identity."""

    return TrustedWorkflowIdentity()


def _reviewed_sha(value: object) -> str:
    if type(value) is not str or not _SHA_RE.fullmatch(value):
        raise _error("reviewed_workflow_sha_invalid")
    return value


@dataclass(frozen=True, slots=True)
class TrustedWorkflowEvidence:
    """Fixed identity plus independently supplied reviewed workflow SHA."""

    identity: TrustedWorkflowIdentity
    reviewed_workflow_sha: str

    def __post_init__(self) -> None:
        if (
            type(self.identity) is not TrustedWorkflowIdentity
            or self.identity.repository != TRUSTED_REPOSITORY
            or self.identity.workflow_path != TRUSTED_WORKFLOW_PATH
            or self.identity.workflow_ref != TRUSTED_WORKFLOW_REF
        ):
            raise _error("trusted_workflow_identity_mismatch")
        _reviewed_sha(self.reviewed_workflow_sha)


def validate_trusted_workflow_identity(
    workflow_ref: object, reviewed_workflow_sha: object
) -> TrustedWorkflowEvidence:
    """Validate fixed workflow ref and independent runtime SHA evidence."""

    if type(workflow_ref) is not str or workflow_ref != TRUSTED_WORKFLOW_REF:
        raise _error("trusted_workflow_identity_mismatch")
    return TrustedWorkflowEvidence(TrustedWorkflowIdentity(), _reviewed_sha(reviewed_workflow_sha))


def _canonical_bytes(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "ascii"
        )
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise _error("trusted_workflow_serialization_invalid") from None


def serialize_trusted_workflow_evidence(evidence: TrustedWorkflowEvidence) -> bytes:
    if type(evidence) is not TrustedWorkflowEvidence:
        raise _error("trusted_workflow_evidence_invalid")
    if (
        evidence.identity.repository != TRUSTED_REPOSITORY
        or evidence.identity.workflow_path != TRUSTED_WORKFLOW_PATH
        or evidence.identity.workflow_ref != TRUSTED_WORKFLOW_REF
    ):
        raise _error("trusted_workflow_identity_mismatch")
    return _canonical_bytes(
        {
            "identity_version": IDENTITY_VERSION,
            "repository": TRUSTED_REPOSITORY,
            "workflow_path": TRUSTED_WORKFLOW_PATH,
            "workflow_ref": TRUSTED_WORKFLOW_REF,
            "reviewed_workflow_sha": _reviewed_sha(evidence.reviewed_workflow_sha),
        }
    )


def _parse_wire_value(value: object) -> TrustedWorkflowEvidence:
    if type(value) is not dict or set(value) != _WIRE_KEYS:
        raise _error("trusted_workflow_shape_invalid")
    if value["identity_version"] != IDENTITY_VERSION:
        raise _error("trusted_workflow_version_invalid")
    if type(value["identity_version"]) is not str:
        raise _error("trusted_workflow_version_invalid")
    if value["repository"] != TRUSTED_REPOSITORY or type(value["repository"]) is not str:
        raise _error("trusted_workflow_identity_mismatch")
    if value["workflow_path"] != TRUSTED_WORKFLOW_PATH or type(value["workflow_path"]) is not str:
        raise _error("trusted_workflow_identity_mismatch")
    if value["workflow_ref"] != TRUSTED_WORKFLOW_REF or type(value["workflow_ref"]) is not str:
        raise _error("trusted_workflow_identity_mismatch")
    return validate_trusted_workflow_identity(value["workflow_ref"], value["reviewed_workflow_sha"])


def parse_trusted_workflow_evidence(raw: bytes) -> TrustedWorkflowEvidence:
    if type(raw) is not bytes:
        raise _error("trusted_workflow_wire_invalid")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise _error("trusted_workflow_duplicate_key")
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise _error("trusted_workflow_wire_invalid")

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs, parse_constant=reject_constant)
    except TrustedWorkflowIdentityError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("trusted_workflow_wire_invalid") from None
    evidence = _parse_wire_value(value)
    if serialize_trusted_workflow_evidence(evidence) != raw:
        raise _error("trusted_workflow_noncanonical")
    return evidence
