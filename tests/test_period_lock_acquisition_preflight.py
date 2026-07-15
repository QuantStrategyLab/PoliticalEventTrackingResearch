from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.period_lock_acquisition_preflight import (  # noqa: E402
    BUNDLE_FILES,
    BUNDLE_VERSION,
    build_bundle,
    expected_artifact_name,
    verify_bundle,
)


def test_build_and_verify_test_only_bundle_is_deterministic(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    build_bundle(first_dir, "29399816773")
    build_bundle(second_dir, "29399816773")

    assert {path.name for path in first_dir.iterdir()} == set(BUNDLE_FILES)
    assert {path.name for path in second_dir.iterdir()} == set(BUNDLE_FILES)
    assert [path.read_bytes() for path in sorted(first_dir.iterdir())] == [
        path.read_bytes() for path in sorted(second_dir.iterdir())
    ]
    assert verify_bundle(first_dir, "29399816773", expected_artifact_name("29399816773"))


def test_verify_rejects_wrong_run_or_artifact_name(tmp_path: Path) -> None:
    build_bundle(tmp_path, "29399816773")
    with pytest.raises(ValueError, match="period_lock_run_mismatch"):
        verify_bundle(tmp_path, "29399816774", expected_artifact_name("29399816774"))
    with pytest.raises(ValueError, match="period_lock_artifact_name_mismatch"):
        verify_bundle(tmp_path, "29399816773", "wrong-artifact")


@pytest.mark.parametrize("mutation", ["lock", "snapshot", "manifest"])
def test_verify_rejects_tampered_bundle(tmp_path: Path, mutation: str) -> None:
    build_bundle(tmp_path, "29399816773")
    target = tmp_path / mutation_to_filename(mutation)
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError):
        verify_bundle(tmp_path, "29399816773", expected_artifact_name("29399816773"))


def test_verify_rejects_missing_multiple_or_wrong_attempt(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()
    build_bundle(missing_dir, "29399816773")
    (missing_dir / "input_snapshot.json").unlink()
    with pytest.raises(ValueError, match="period_lock_bundle_shape_invalid"):
        verify_bundle(missing_dir, "29399816773", expected_artifact_name("29399816773"))

    wrong_attempt_dir = tmp_path / "wrong-attempt"
    wrong_attempt_dir.mkdir()
    build_bundle(wrong_attempt_dir, "29399816773")
    manifest_path = wrong_attempt_dir / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["source_attempt"] = 2
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ValueError, match="period_lock_manifest_mismatch"):
        verify_bundle(wrong_attempt_dir, "29399816773", expected_artifact_name("29399816773"))

    (wrong_attempt_dir / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="period_lock_bundle_shape_invalid"):
        verify_bundle(wrong_attempt_dir, "29399816773", expected_artifact_name("29399816773"))


@pytest.mark.parametrize("mutation", ["reorder", "duplicate"])
def test_verify_rejects_manifest_record_mutation(tmp_path: Path, mutation: str) -> None:
    build_bundle(tmp_path, "29399816773")
    manifest_path = tmp_path / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == "reorder":
        manifest["files"] = list(reversed(manifest["files"]))
    else:
        manifest["files"].append(manifest["files"][0])
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ValueError, match="period_lock_manifest_mismatch"):
        verify_bundle(tmp_path, "29399816773", expected_artifact_name("29399816773"))


def test_workflow_isolated_and_minimally_permissioned() -> None:
    workflow = Path(".github/workflows/pert_weekly_period_lock_acquisition.yml").read_text(encoding="utf-8")
    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert "artifact-metadata: write" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "contents: write" not in workflow
    assert "id-token:" not in workflow
    assert "secrets." not in workflow
    assert "run_attempt" in workflow
    assert "run-id: ${{ github.run_id }}" in workflow
    assert "retention-days: 30" in workflow
    assert "upload-artifact@" in workflow and "github.run_attempt == 1" in workflow
    assert "download-artifact@" in workflow and "github.run_attempt == 2" in workflow
    for action in ("actions/checkout@", "actions/setup-python@", "actions/upload-artifact@", "actions/download-artifact@"):
        assert action in workflow
        ref = workflow.split(action, 1)[1].split()[0]
        assert len(ref) == 40 and all(char in "0123456789abcdef" for char in ref)


def mutation_to_filename(mutation: str) -> str:
    return {
        "lock": "period_lock.json",
        "snapshot": "input_snapshot.json",
        "manifest": "bundle_manifest.json",
    }[mutation]
