from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

import political_event_tracking_research.trusted_workflow_identity_raw as module
from political_event_tracking_research.trusted_workflow_identity_raw import (
    IDENTITY_VERSION,
    MAX_IDENTITY_BYTES,
    TRUSTED_REPOSITORY,
    TRUSTED_WORKFLOW_PATH,
    TRUSTED_WORKFLOW_REF,
    TrustedWorkflowIdentityError,
    build_trusted_workflow_identity_bytes,
    serialize_trusted_workflow_identity,
    validate_trusted_workflow_identity_bytes,
    validate_trusted_workflow_ref,
)


SHA = "a" * 40


def wire() -> dict[str, str]:
    return {
        "identity_version": IDENTITY_VERSION,
        "repository": TRUSTED_REPOSITORY,
        "workflow_path": TRUSTED_WORKFLOW_PATH,
        "workflow_ref": TRUSTED_WORKFLOW_REF,
        "reviewed_workflow_sha": SHA,
    }


def test_fixed_identity_bytes_are_deterministic_and_revalidated() -> None:
    raw = build_trusted_workflow_identity_bytes(SHA)
    assert validate_trusted_workflow_identity_bytes(raw) == SHA
    assert serialize_trusted_workflow_identity(dict(reversed(list(wire().items())))) == raw
    assert validate_trusted_workflow_ref(TRUSTED_WORKFLOW_REF) == TRUSTED_WORKFLOW_REF


def test_returned_plain_values_are_not_trust_objects() -> None:
    value = module.parse_trusted_workflow_identity_bytes(build_trusted_workflow_identity_bytes(SHA))
    value["repository"] = "QuantStrategyLab/Other"
    with pytest.raises(TrustedWorkflowIdentityError, match="identity_mismatch"):
        serialize_trusted_workflow_identity(value)


@pytest.mark.parametrize("field", ["repository", "workflow_path", "workflow_ref"])
def test_each_identity_field_is_rechecked(field: str) -> None:
    value = wire()
    value[field] = "wrong"
    with pytest.raises(TrustedWorkflowIdentityError, match="identity_mismatch"):
        serialize_trusted_workflow_identity(value)


def test_reviewed_sha_is_explicit_runtime_evidence() -> None:
    value = wire()
    value["reviewed_workflow_sha"] = "b" * 40
    assert serialize_trusted_workflow_identity(value) != serialize_trusted_workflow_identity(wire())


@pytest.mark.parametrize("mutation", ["unknown", "missing", "duplicate", "noncanonical", "wrong_version"])
def test_wire_shape_and_canonical_bytes_fail_closed(mutation: str) -> None:
    value = wire()
    if mutation == "unknown":
        value["debug"] = "unexpected"  # type: ignore[typeddict-unknown-key]
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "missing":
        del value["workflow_path"]
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "duplicate":
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).replace(
            '"workflow_path":"' + TRUSTED_WORKFLOW_PATH + '"',
            '"workflow_path":"' + TRUSTED_WORKFLOW_PATH + '","workflow_path":"' + TRUSTED_WORKFLOW_PATH + '"',
        ).encode()
    elif mutation == "noncanonical":
        raw = json.dumps(value).encode()
    else:
        value["identity_version"] = "future"
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(TrustedWorkflowIdentityError):
        validate_trusted_workflow_identity_bytes(raw)


@pytest.mark.parametrize(
    "workflow_ref",
    [
        "QuantStrategyLab/Other/.github/workflows/pert_weekly_period_lock_harness.yml@refs/heads/main",
        TRUSTED_WORKFLOW_REF.replace(".github/workflows/", ".github//workflows/"),
        TRUSTED_WORKFLOW_REF.replace("refs/heads/main", "refs/tags/main"),
        TRUSTED_WORKFLOW_REF + "\n",
        "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/other.yml@refs/heads/main",
    ],
)
def test_wrong_workflow_refs_are_sanitized(workflow_ref: str) -> None:
    with pytest.raises(TrustedWorkflowIdentityError, match="identity_mismatch"):
        validate_trusted_workflow_ref(workflow_ref)


@pytest.mark.parametrize("sha", ["a" * 39, "A" * 40, "g" * 40, True, 1, "refs/heads/main"])
def test_reviewed_sha_requires_lowercase_full_hex(sha: object) -> None:
    with pytest.raises(TrustedWorkflowIdentityError, match="reviewed_workflow_sha_invalid"):
        build_trusted_workflow_identity_bytes(sha)


def test_oversized_and_non_ascii_wire_fail_closed() -> None:
    with pytest.raises(TrustedWorkflowIdentityError, match="identity_wire_oversized"):
        validate_trusted_workflow_identity_bytes(b"{" + b"a" * MAX_IDENTITY_BYTES)
    value = wire()
    value["repository"] = "QuantStrategyLab/PoliticalEventTrackingResearch\N{SNOWMAN}"
    with pytest.raises(TrustedWorkflowIdentityError, match="identity_mismatch"):
        serialize_trusted_workflow_identity(value)


@dataclass
class ForgedObject:
    repository: str = TRUSTED_REPOSITORY
    workflow_path: str = TRUSTED_WORKFLOW_PATH
    workflow_ref: str = TRUSTED_WORKFLOW_REF
    reviewed_workflow_sha: str = SHA


def test_forged_objects_and_attribute_failures_are_sanitized() -> None:
    with pytest.raises(TrustedWorkflowIdentityError, match="identity_wire_invalid"):
        serialize_trusted_workflow_identity(ForgedObject())

    class BrokenMapping(dict[str, str]):
        def items(self):  # type: ignore[no-untyped-def]
            raise AttributeError("untrusted attribute")

    with pytest.raises(TrustedWorkflowIdentityError, match="identity_wire_invalid"):
        serialize_trusted_workflow_identity(BrokenMapping())


def test_unexpected_runtime_error_is_not_broad_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenMapping(dict[str, str]):
        def items(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("programming failure")

    with pytest.raises(RuntimeError, match="programming failure"):
        serialize_trusted_workflow_identity(BrokenMapping())
    def fail_dumps(*_: object, **__: object) -> str:
        raise RuntimeError("programming failure")

    monkeypatch.setattr(module.json, "dumps", fail_dumps)
    with pytest.raises(RuntimeError, match="programming failure"):
        serialize_trusted_workflow_identity(wire())
