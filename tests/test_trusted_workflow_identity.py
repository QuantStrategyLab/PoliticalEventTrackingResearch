from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

import political_event_tracking_research.trusted_workflow_identity as module
from political_event_tracking_research.trusted_workflow_identity import (
    IDENTITY_VERSION,
    TRUSTED_REPOSITORY,
    TRUSTED_WORKFLOW_PATH,
    TRUSTED_WORKFLOW_REF,
    TrustedWorkflowIdentityError,
    TrustedWorkflowEvidence,
    parse_trusted_workflow_evidence,
    serialize_trusted_workflow_evidence,
    trusted_workflow_identity,
    validate_trusted_workflow_identity,
)


SHA = "a" * 40


def valid_wire() -> dict[str, str]:
    return {
        "identity_version": IDENTITY_VERSION,
        "repository": TRUSTED_REPOSITORY,
        "workflow_path": TRUSTED_WORKFLOW_PATH,
        "workflow_ref": TRUSTED_WORKFLOW_REF,
        "reviewed_workflow_sha": SHA,
    }


def test_fixed_identity_has_no_runtime_override() -> None:
    identity = trusted_workflow_identity()
    assert identity.repository == TRUSTED_REPOSITORY
    assert identity.workflow_path == TRUSTED_WORKFLOW_PATH
    assert identity.workflow_ref == TRUSTED_WORKFLOW_REF
    with pytest.raises(TypeError):
        module.TrustedWorkflowIdentity(TRUSTED_REPOSITORY, "other.yml", TRUSTED_WORKFLOW_REF)  # type: ignore[call-arg]
    with pytest.raises(FrozenInstanceError):
        identity.repository = "QuantStrategyLab/Other"  # type: ignore[misc]
    assert trusted_workflow_identity().repository == TRUSTED_REPOSITORY


def test_evidence_constructor_and_replace_revalidate_invariants() -> None:
    evidence = validate_trusted_workflow_identity(TRUSTED_WORKFLOW_REF, SHA)
    assert replace(evidence, reviewed_workflow_sha="b" * 40).reviewed_workflow_sha == "b" * 40
    with pytest.raises(TrustedWorkflowIdentityError, match="reviewed_workflow_sha_invalid"):
        replace(evidence, reviewed_workflow_sha="not-a-sha")

    forged_identity = object.__new__(module.TrustedWorkflowIdentity)
    object.__setattr__(forged_identity, "repository", "QuantStrategyLab/Other")
    object.__setattr__(forged_identity, "workflow_path", TRUSTED_WORKFLOW_PATH)
    object.__setattr__(forged_identity, "workflow_ref", TRUSTED_WORKFLOW_REF)
    with pytest.raises(TrustedWorkflowIdentityError, match="trusted_workflow_identity_mismatch"):
        TrustedWorkflowEvidence(forged_identity, SHA)


def test_runtime_sha_and_fixed_workflow_identity_round_trip() -> None:
    evidence = validate_trusted_workflow_identity(TRUSTED_WORKFLOW_REF, SHA)
    wire = serialize_trusted_workflow_evidence(evidence)
    assert parse_trusted_workflow_evidence(wire) == evidence
    assert wire == serialize_trusted_workflow_evidence(parse_trusted_workflow_evidence(wire))


@pytest.mark.parametrize(
    "workflow_ref",
    [
        "QuantStrategyLab/Other/.github/workflows/pert_weekly_period_lock_harness.yml@refs/heads/main",
        "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/other.yml@refs/heads/main",
        TRUSTED_WORKFLOW_REF.replace("refs/heads/main", "refs/tags/main"),
        TRUSTED_WORKFLOW_REF.replace("PoliticalEventTrackingResearch", "politicaleventtrackingresearch"),
        TRUSTED_WORKFLOW_REF.replace(".github/workflows/", ".github//workflows/"),
        TRUSTED_WORKFLOW_REF + "\n",
        SHA,
    ],
)
def test_wrong_workflow_identity_is_rejected(workflow_ref: str) -> None:
    with pytest.raises(TrustedWorkflowIdentityError, match="trusted_workflow_identity_mismatch"):
        validate_trusted_workflow_identity(workflow_ref, SHA)


@pytest.mark.parametrize("sha", ["a" * 39, "A" * 40, "g" * 40, "refs/heads/main", True, 1])
def test_reviewed_sha_is_strict_full_hex(sha: object) -> None:
    with pytest.raises(TrustedWorkflowIdentityError, match="reviewed_workflow_sha_invalid"):
        validate_trusted_workflow_identity(TRUSTED_WORKFLOW_REF, sha)


@pytest.mark.parametrize("mutation", ["unknown", "missing", "wrong_repo", "wrong_path", "wrong_ref", "wrong_sha"])
def test_wire_is_exact_and_sanitized(mutation: str) -> None:
    wire = valid_wire()
    if mutation == "unknown":
        wire["debug"] = "secret"
    elif mutation == "missing":
        del wire["workflow_path"]
    elif mutation == "wrong_repo":
        wire["repository"] = "QuantStrategyLab/Other"
    elif mutation == "wrong_path":
        wire["workflow_path"] = "other.yml"
    elif mutation == "wrong_ref":
        wire["workflow_ref"] = TRUSTED_WORKFLOW_REF.replace("main", "feature")
    else:
        wire["reviewed_workflow_sha"] = "b" * 40
    with pytest.raises(TrustedWorkflowIdentityError):
        parse_trusted_workflow_evidence(json.dumps(wire).encode())


def test_duplicate_and_noncanonical_wire_fail_closed() -> None:
    wire = json.dumps(valid_wire(), sort_keys=True, separators=(",", ":"))
    duplicate = wire.replace(
        '"workflow_path":"' + TRUSTED_WORKFLOW_PATH + '"',
        '"workflow_path":"' + TRUSTED_WORKFLOW_PATH + '","workflow_path":"' + TRUSTED_WORKFLOW_PATH + '"',
    )
    with pytest.raises(TrustedWorkflowIdentityError, match="trusted_workflow_duplicate_key"):
        parse_trusted_workflow_evidence(duplicate.encode())
    with pytest.raises(TrustedWorkflowIdentityError, match="trusted_workflow_noncanonical"):
        parse_trusted_workflow_evidence(json.dumps(valid_wire()).encode())


def test_unexpected_runtime_error_is_not_broad_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: object, **__: object) -> bytes:
        raise RuntimeError("programming failure")

    monkeypatch.setattr(module.json, "dumps", fail)
    with pytest.raises(RuntimeError, match="programming failure"):
        serialize_trusted_workflow_evidence(validate_trusted_workflow_identity(TRUSTED_WORKFLOW_REF, SHA))
