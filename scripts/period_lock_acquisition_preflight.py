"""Isolated GitHub Actions preflight for same-run weekly lock acquisition.

This is test-only harness code. It uses a fixed representative snapshot and
never derives a period from the wall clock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from political_event_tracking_research.weekly_period_lock import (
    LOCK_VERSION,
    PeriodLockError,
    parse_period_lock,
    parse_period_lock_bytes,
    serialize_period_lock,
)

BUNDLE_VERSION = "pert.weekly.period_lock_acquisition.v1"
BUNDLE_FILES = ("bundle_manifest.json", "input_snapshot.json", "period_lock.json")
SNAPSHOT_VERSION = "pert.weekly.input_snapshot.v1"
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")


def expected_artifact_name(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"pert-weekly-period-lock-{run_id}"


def _validate_run_id(run_id: object) -> str:
    if type(run_id) is not str or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("period_lock_run_invalid")
    return run_id


def _canonical_json(value: object, error_code: str) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ValueError(error_code) from None


def _parse_canonical_json(raw: bytes, error_code: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise ValueError(error_code)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError(error_code)
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError(error_code)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
    except ValueError:
        raise ValueError(error_code) from None
    if not isinstance(value, dict) or _canonical_json(value, error_code) != raw:
        raise ValueError(error_code)
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture_lock_payload(run_id: str) -> dict[str, object]:
    return {
        "lock_version": LOCK_VERSION,
        "calendar": "utc_iso_week_monday_sunday",
        "period_start": "2026-07-06",
        "period_end_exclusive": "2026-07-13",
        "as_of": "2026-07-12",
        "workflow_ref": "QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/pert_weekly_period_lock_acquisition.yml@refs/heads/main",
        "source_run_id": run_id,
        "source_attempt": 1,
        "producer_ref": "a" * 40,
        "source_snapshot_id": "pert_weekly_input_snapshot_20260712",
        "source_snapshot_digest": "b" * 64,
        "source_provenance": "official_political_event_tracking_research_v1",
        "source_artifacts": [
            {"path": "data/live/source_events.csv", "sha256": "c" * 64, "row_count": 11},
            {"path": "data/live/source_manifest.json", "sha256": "d" * 64, "row_count": 1},
        ],
    }


def _fixture_snapshot(lock_payload: dict[str, object]) -> dict[str, object]:
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_run_id": lock_payload["source_run_id"],
        "source_snapshot_id": lock_payload["source_snapshot_id"],
        "source_snapshot_digest": lock_payload["source_snapshot_digest"],
        "source_artifacts": lock_payload["source_artifacts"],
    }


def _fixture_manifest(run_id: str, artifact_name: str, lock_bytes: bytes, snapshot_bytes: bytes) -> dict[str, object]:
    return {
        "bundle_version": BUNDLE_VERSION,
        "artifact_name": artifact_name,
        "source_run_id": run_id,
        "source_attempt": 1,
        "lock_version": LOCK_VERSION,
        "snapshot_version": SNAPSHOT_VERSION,
        "files": [
            {"name": "input_snapshot.json", "sha256": _sha256(snapshot_bytes)},
            {"name": "period_lock.json", "sha256": _sha256(lock_bytes)},
        ],
    }


def _assert_empty_output_dir(output_dir: Path) -> None:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("period_lock_output_dir_invalid")
    try:
        if any(output_dir.iterdir()):
            raise ValueError("period_lock_output_not_empty")
    except OSError:
        raise ValueError("period_lock_output_dir_invalid") from None


def build_bundle(output_dir: Path, run_id: str, artifact_name: str | None = None) -> dict[str, object]:
    run_id = _validate_run_id(run_id)
    expected_name = expected_artifact_name(run_id)
    if artifact_name is not None and artifact_name != expected_name:
        raise ValueError("period_lock_artifact_name_mismatch")
    _assert_empty_output_dir(output_dir)

    lock_payload = _fixture_lock_payload(run_id)
    lock = parse_period_lock(lock_payload)
    lock_bytes = serialize_period_lock(lock)
    snapshot = _fixture_snapshot(lock_payload)
    snapshot_bytes = _canonical_json(snapshot, "period_lock_snapshot_invalid")
    manifest = _fixture_manifest(run_id, expected_name, lock_bytes, snapshot_bytes)
    manifest_bytes = _canonical_json(manifest, "period_lock_manifest_invalid")
    payloads = {
        "period_lock.json": lock_bytes,
        "input_snapshot.json": snapshot_bytes,
        "bundle_manifest.json": manifest_bytes,
    }
    try:
        for name, raw in payloads.items():
            with (output_dir / name).open("xb") as handle:
                handle.write(raw)
    except (OSError, ValueError):
        raise ValueError("period_lock_bundle_write_invalid") from None
    return verify_bundle(output_dir, run_id, expected_name)


def _read_exact_bundle(output_dir: Path) -> dict[str, bytes]:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("period_lock_bundle_shape_invalid")
    try:
        names = {path.name for path in output_dir.iterdir()}
    except OSError:
        raise ValueError("period_lock_bundle_shape_invalid") from None
    if names != set(BUNDLE_FILES):
        raise ValueError("period_lock_bundle_shape_invalid")
    result: dict[str, bytes] = {}
    for name in BUNDLE_FILES:
        path = output_dir / name
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("period_lock_bundle_member_invalid")
            result[name] = path.read_bytes()
        except (OSError, ValueError):
            raise ValueError("period_lock_bundle_member_invalid") from None
    return result


def verify_bundle(output_dir: Path, expected_run_id: str, expected_artifact: str) -> dict[str, object]:
    expected_run_id = _validate_run_id(expected_run_id)
    if expected_artifact != expected_artifact_name(expected_run_id):
        raise ValueError("period_lock_artifact_name_mismatch")
    payloads = _read_exact_bundle(output_dir)
    try:
        lock = parse_period_lock_bytes(payloads["period_lock.json"])
    except PeriodLockError:
        raise ValueError("period_lock_invalid") from None
    if serialize_period_lock(lock) != payloads["period_lock.json"] or lock.source_run_id != expected_run_id or lock.source_attempt != 1:
        raise ValueError("period_lock_run_mismatch")
    snapshot = _parse_canonical_json(payloads["input_snapshot.json"], "period_lock_snapshot_invalid")
    expected_snapshot = _fixture_snapshot(_fixture_lock_payload(expected_run_id))
    if snapshot != expected_snapshot:
        raise ValueError("period_lock_snapshot_mismatch")
    expected_manifest_bytes = _canonical_json(
        _fixture_manifest(expected_run_id, expected_artifact, payloads["period_lock.json"], payloads["input_snapshot.json"]),
        "period_lock_manifest_invalid",
    )
    if payloads["bundle_manifest.json"] != expected_manifest_bytes:
        raise ValueError("period_lock_manifest_mismatch")
    manifest = _parse_canonical_json(payloads["bundle_manifest.json"], "period_lock_manifest_invalid")
    if set(manifest) != {"bundle_version", "artifact_name", "source_run_id", "source_attempt", "lock_version", "snapshot_version", "files"}:
        raise ValueError("period_lock_manifest_invalid")
    if (
        manifest["bundle_version"] != BUNDLE_VERSION
        or manifest["artifact_name"] != expected_artifact
        or manifest["source_run_id"] != expected_run_id
        or type(manifest["source_attempt"]) is not int
        or manifest["source_attempt"] != 1
        or manifest["lock_version"] != LOCK_VERSION
        or manifest["snapshot_version"] != SNAPSHOT_VERSION
    ):
        raise ValueError("period_lock_manifest_mismatch")
    files = manifest["files"]
    if not isinstance(files, list) or {item.get("name") for item in files if isinstance(item, dict)} != {"input_snapshot.json", "period_lock.json"}:
        raise ValueError("period_lock_manifest_files_invalid")
    for item in files:
        if not isinstance(item, dict) or set(item) != {"name", "sha256"} or item["name"] not in payloads:
            raise ValueError("period_lock_manifest_files_invalid")
        if item["sha256"] != _sha256(payloads[item["name"]]):
            raise ValueError("period_lock_artifact_digest_mismatch")
    return {
        "bundle_version": BUNDLE_VERSION,
        "artifact_name": expected_artifact,
        "source_run_id": expected_run_id,
        "source_attempt": 1,
        "files": {name: _sha256(raw) for name, raw in sorted(payloads.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--artifact-name")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle-dir", type=Path, required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--artifact-name", required=True)
    args = parser.parse_args()
    evidence = (
        build_bundle(args.output_dir, args.run_id, args.artifact_name)
        if args.command == "build"
        else verify_bundle(args.bundle_dir, args.run_id, args.artifact_name)
    )
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
