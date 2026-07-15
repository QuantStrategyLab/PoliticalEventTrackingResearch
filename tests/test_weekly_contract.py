from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from political_event_tracking_research.weekly_contract import (
    MAX_SAFE_JSON_INTEGER,
    WeeklyContractError,
    WeeklyFeedStatus,
    WeeklySourceArtifact,
    WeeklySourceContract,
    parse_weekly_contract,
    serialize_weekly_contract,
)


def payload(**overrides: object) -> dict[str, object]:
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


def test_parser_and_serializer_are_permutation_stable():
    items = [
        {"path": "z.csv", "sha256": "c" * 64, "row_count": 2},
        {"path": "a.csv", "sha256": "d" * 64, "row_count": 1},
    ]
    first = parse_weekly_contract(payload(source_artifacts=items))
    second = parse_weekly_contract(payload(source_artifacts=list(reversed(items))))
    assert first == second
    assert serialize_weekly_contract(first) == serialize_weekly_contract(second)


def test_direct_value_objects_canonicalize_and_round_trip():
    z = WeeklySourceArtifact("z.csv", "c" * 64, 2)
    a = WeeklySourceArtifact("a.csv", "d" * 64, 1)
    contract = WeeklySourceContract(
        date(2026, 7, 12), date(2026, 7, 6), date(2026, 7, 13), datetime(2026, 7, 13, tzinfo=timezone.utc),
        "manual", "a" * 40, "official_political_event_tracking_research_v1", (z, a), WeeklyFeedStatus(12, 12, 0, 0, 0, True),
    )
    assert [item.path for item in contract.source_artifacts] == ["a.csv", "z.csv"]
    assert parse_weekly_contract(json.loads(serialize_weekly_contract(contract))) == contract


@pytest.mark.parametrize("path", ["", "/absolute", "./a.csv", "a/../b.csv", "a//b.csv", "a/b.csv/", "a\\b.csv", "a\tb.csv", "a\nb.csv", "é.csv", "a\x00b.csv"])
def test_artifact_paths_use_ascii_safe_canonical_posix_allowlist(path):
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(source_artifacts=[{"path": path, "sha256": "c" * 64, "row_count": 1}]))
    with pytest.raises(WeeklyContractError):
        WeeklySourceArtifact(path, "c" * 64, 1)


@pytest.mark.parametrize("provenance", ["", "Official_PERT_v1", "official-pert-v1", "official_pert_é", "official.pert"])
def test_provenance_is_canonical_ascii_identifier(provenance):
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(source_provenance=provenance))


def test_safe_integer_boundaries_and_bool_rejection():
    assert WeeklySourceArtifact("a.csv", "a" * 64, MAX_SAFE_JSON_INTEGER).row_count == MAX_SAFE_JSON_INTEGER
    for value in (-1, MAX_SAFE_JSON_INTEGER + 1, True):
        with pytest.raises(WeeklyContractError):
            WeeklySourceArtifact("a.csv", "a" * 64, value)
        with pytest.raises(WeeklyContractError):
            parse_weekly_contract(payload(feed_status={"feed_count": value, "successful_feed_count": value, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True}))


def test_feed_status_is_typed_and_serializer_preserves_counters():
    status = WeeklyFeedStatus(12, 12, 0, 0, 0, True)
    assert parse_weekly_contract(json.loads(serialize_weekly_contract(parse_weekly_contract(payload(feed_status={"feed_count": 12, "successful_feed_count": 12, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True}))))) .feed_status == status


def test_unknown_fields_and_contract_or_period_mismatch_fail_closed():
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(extra=True))
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(as_of="2026-07-13"))
