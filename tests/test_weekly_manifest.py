from __future__ import annotations

import json
from pathlib import Path

import pytest

from political_event_tracking_research.weekly_contract import WeeklyContractError, parse_weekly_contract
from political_event_tracking_research.weekly_manifest import (
    MANIFEST_TYPE,
    build_weekly_manifest,
    parse_weekly_manifest,
    parse_weekly_manifest_bytes,
    serialize_weekly_manifest,
    validate_weekly_manifest,
    write_weekly_manifest,
)


def contract_payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1", "contract_version": "political_event_weekly.v1", "cadence": "weekly",
        "as_of": "2026-07-12", "period_start": "2026-07-06", "period_end_exclusive": "2026-07-13",
        "generated_at": "2026-07-13T00:00:00.123456Z", "run_mode": "manual", "producer_ref": "a" * 40,
        "source_provenance": "official_political_event_tracking_research_v1",
        "source_artifacts": [{"path": "data/live/political_events.csv", "sha256": "b" * 64, "row_count": 11}],
        "feed_status": {"feed_count": 12, "successful_feed_count": 12, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True},
    }
    value.update(overrides)
    return value


def test_weekly_manifest_is_deterministic_and_round_trips():
    contract = parse_weekly_contract(contract_payload())
    manifest = build_weekly_manifest(contract)
    assert manifest["manifest_type"] == MANIFEST_TYPE
    encoded = serialize_weekly_manifest(contract)
    assert encoded == serialize_weekly_manifest(parse_weekly_manifest(json.loads(encoded)))
    assert parse_weekly_manifest(manifest) == contract
    assert parse_weekly_manifest_bytes(encoded) == contract


@pytest.mark.parametrize("wire", [
    lambda encoded: b" " + encoded,
    lambda encoded: encoded.replace(b'"contract":', b'"contract" :'),
    lambda encoded: encoded.replace(b'"manifest_type":', b'"manifest_type":"x","manifest_type":'),
])
def test_manifest_wire_must_be_exact_canonical_bytes(wire):
    contract = parse_weekly_contract(contract_payload())
    encoded = serialize_weekly_manifest(contract)
    with pytest.raises(WeeklyContractError):
        parse_weekly_manifest_bytes(wire(encoded))


@pytest.mark.parametrize("field,value", [
    ("as_of", "2026-07-13"),
    ("generated_at", "2026-07-12T23:59:59Z"),
    ("producer_ref", "c" * 40),
    ("source_provenance", "official_other_v1"),
    ("source_artifacts", [{"path": "data/live/political_events.csv", "sha256": "c" * 64, "row_count": 12}]),
])
def test_manifest_contract_tamper_is_rejected(field, value):
    contract = parse_weekly_contract(contract_payload())
    manifest = build_weekly_manifest(contract)
    manifest["contract"][field] = value
    with pytest.raises(WeeklyContractError):
        validate_weekly_manifest(manifest, contract)


def test_mapping_with_alias_or_unknown_shape_fails_closed():
    contract = parse_weekly_contract(contract_payload())
    manifest = build_weekly_manifest(contract)
    manifest["contract"]["generatedAt"] = manifest["contract"].pop("generated_at")
    with pytest.raises(WeeklyContractError):
        validate_weekly_manifest(manifest, contract)


def test_manifest_feed_partial_and_shape_tamper_fail_closed():
    contract = parse_weekly_contract(contract_payload())
    manifest = build_weekly_manifest(contract)
    manifest["contract"]["feed_status"]["failed_feed_count"] = 1
    with pytest.raises(WeeklyContractError):
        parse_weekly_manifest(manifest)
    manifest = build_weekly_manifest(contract)
    manifest["extra"] = True
    with pytest.raises(WeeklyContractError):
        parse_weekly_manifest(manifest)


def test_write_validates_before_creating_output(tmp_path: Path):
    contract = parse_weekly_contract(contract_payload())
    output = tmp_path / "manifest.json"
    write_weekly_manifest(contract, output)
    assert json.loads(output.read_text(encoding="utf-8"))["manifest_type"] == MANIFEST_TYPE

    invalid = tmp_path / "invalid.json"
    with pytest.raises(WeeklyContractError):
        write_weekly_manifest(object(), invalid)  # type: ignore[arg-type]
    assert not invalid.exists()
