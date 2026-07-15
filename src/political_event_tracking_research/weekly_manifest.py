"""Pure deterministic manifest integration for ``political_event_weekly.v1``."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .weekly_contract import WeeklyContractError, WeeklySourceContract, parse_weekly_contract, serialize_weekly_contract

MANIFEST_TYPE = "political_event_weekly_manifest"
_MANIFEST_KEYS = frozenset({"manifest_type", "contract"})


def build_weekly_manifest(contract: WeeklySourceContract) -> dict[str, object]:
    if not isinstance(contract, WeeklySourceContract):
        raise WeeklyContractError("manifest_contract_invalid")
    try:
        contract_payload = json.loads(serialize_weekly_contract(contract))
    except (TypeError, ValueError, UnicodeError):
        raise WeeklyContractError("manifest_contract_invalid") from None
    return {"manifest_type": MANIFEST_TYPE, "contract": contract_payload}


def parse_weekly_manifest(value: Mapping[str, object]) -> WeeklySourceContract:
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_KEYS or value.get("manifest_type") != MANIFEST_TYPE:
        raise WeeklyContractError("manifest_shape_invalid")
    contract = value.get("contract")
    if not isinstance(contract, Mapping):
        raise WeeklyContractError("manifest_contract_invalid")
    return parse_weekly_contract(contract)


def validate_weekly_manifest(value: Mapping[str, object], expected: WeeklySourceContract) -> WeeklySourceContract:
    if not isinstance(expected, WeeklySourceContract):
        raise WeeklyContractError("manifest_expected_invalid")
    parsed = parse_weekly_manifest(value)
    if parsed != expected:
        raise WeeklyContractError("manifest_contract_mismatch")
    return parsed


def serialize_weekly_manifest(contract: WeeklySourceContract) -> bytes:
    payload = build_weekly_manifest(contract)
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WeeklyContractError("manifest_serialization_invalid") from None


def write_weekly_manifest(contract: WeeklySourceContract, output_path: str | Path) -> Path:
    content = serialize_weekly_manifest(contract)
    output = Path(output_path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    except (OSError, TypeError, ValueError):
        raise WeeklyContractError("manifest_write_invalid") from None
    return output
