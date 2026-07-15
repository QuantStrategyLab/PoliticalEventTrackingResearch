from __future__ import annotations

from datetime import date

import pytest

from political_event_tracking_research.weekly_contract import (
    WeeklyContractError,
    parse_weekly_contract,
    serialize_weekly_contract,
)


def payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "contract_version": "political_event_weekly.v1",
        "cadence": "weekly",
        "as_of": "2026-07-12",
        "period_start": "2026-07-06",
        "period_end_exclusive": "2026-07-13",
        "generated_at": "2026-07-13T00:00:00.123456Z",
        "run_mode": "manual",
        "producer_ref": "a" * 40,
        "source_provenance": "official_political_event_tracking_research",
        "source_artifacts": [
            {"path": "data/live/political_events.csv", "sha256": "b" * 64, "row_count": 11},
        ],
        "feed_status": {
            "feed_count": 9,
            "successful_feed_count": 9,
            "failed_feed_count": 0,
            "stale_feed_count": 0,
            "missing_feed_count": 0,
            "complete": True,
        },
    }
    value.update(overrides)
    return value


def test_valid_weekly_contract_round_trips_deterministically():
    contract = parse_weekly_contract(payload())
    encoded = serialize_weekly_contract(contract)
    assert encoded == serialize_weekly_contract(parse_weekly_contract(__import__("json").loads(encoded)))
    assert contract.as_of == date(2026, 7, 12)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "2"),
    ("contract_version", "political_event_weekly.v2"),
    ("cadence", "daily"),
    ("as_of", "2026-07-13"),
    ("period_start", "2026-07-07"),
    ("period_end_exclusive", "2026-07-14"),
    ("generated_at", "2026-07-12T23:59:59Z"),
    ("generated_at", "2026-07-13T00:00:00+08:00"),
])
def test_period_and_time_contract_fail_closed(field, value):
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(**{field: value}))


def test_scheduled_and_manual_are_explicit():
    assert parse_weekly_contract(payload(run_mode="scheduled")).run_mode == "scheduled"
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(run_mode=""))
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract({key: value for key, value in payload().items() if key != "as_of"})


def test_real_feed_counters_round_trip_without_serializer_defaults():
    status = {"feed_count": 12, "successful_feed_count": 12, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True}
    contract = parse_weekly_contract(payload(feed_status=status))
    encoded = serialize_weekly_contract(contract)
    assert b'"feed_count":12' in encoded
    assert parse_weekly_contract(__import__("json").loads(encoded)).feed_status == contract.feed_status


@pytest.mark.parametrize("status", [
    {"feed_count": 9, "successful_feed_count": 8, "failed_feed_count": 1, "stale_feed_count": 0, "missing_feed_count": 0, "complete": True},
    {"feed_count": 9, "successful_feed_count": 9, "failed_feed_count": 0, "stale_feed_count": 1, "missing_feed_count": 0, "complete": True},
    {"feed_count": 9, "successful_feed_count": 9, "failed_feed_count": 0, "stale_feed_count": 0, "missing_feed_count": 0, "complete": False},
])
def test_partial_stale_or_incomplete_feed_status_fails_closed(status):
    with pytest.raises(WeeklyContractError, match="feed_status"):
        parse_weekly_contract(payload(feed_status=status))


def test_artifacts_are_sorted_and_duplicate_or_unsafe_inputs_fail_closed():
    items = [
        {"path": "z.csv", "sha256": "c" * 64, "row_count": 1},
        {"path": "a.csv", "sha256": "d" * 64, "row_count": 2},
    ]
    contract = parse_weekly_contract(payload(source_artifacts=items))
    assert [item.path for item in contract.source_artifacts] == ["a.csv", "z.csv"]
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(source_artifacts=[items[0], items[0]]))
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(source_artifacts=[{"path": "../secret", "sha256": "c" * 64, "row_count": 1}]))
    for alias in ("a//b.csv", "a/b.csv/", "./a.csv", "a/./b.csv", "a\\b.csv", "é.csv"):
        with pytest.raises(WeeklyContractError):
            parse_weekly_contract(payload(source_artifacts=[{"path": alias, "sha256": "c" * 64, "row_count": 1}]))


@pytest.mark.parametrize("field", ["row_count", "feed_count", "successful_feed_count"])
def test_wire_integers_use_safe_json_range_and_reject_bool(field):
    artifact = {"path": "data/live/political_events.csv", "sha256": "b" * 64, "row_count": 11}
    status = payload()["feed_status"]
    if field == "row_count":
        with pytest.raises(WeeklyContractError):
            parse_weekly_contract(payload(source_artifacts=[{**artifact, "row_count": 2**53}]))
        with pytest.raises(WeeklyContractError):
            parse_weekly_contract(payload(source_artifacts=[{**artifact, "row_count": True}]))
    else:
        with pytest.raises(WeeklyContractError):
            parse_weekly_contract(payload(feed_status={**status, field: 2**53}))
        with pytest.raises(WeeklyContractError):
            parse_weekly_contract(payload(feed_status={**status, field: True}))


def test_unknown_fields_and_wire_type_confusion_fail_closed():
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(extra=True))
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(schema_version=1))
    with pytest.raises(WeeklyContractError):
        parse_weekly_contract(payload(feed_status={**payload()["feed_status"], "feed_count": True}))
