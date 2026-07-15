from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from political_event_tracking_research.weekly_contract import WeeklyContractError
from political_event_tracking_research.weekly_manifest import parse_weekly_manifest_bytes
from political_event_tracking_research.weekly_producer import (
    WEEKLY_ARTIFACT_FILE,
    WEEKLY_ARTIFACT_NAME,
    WEEKLY_ARTIFACT_RETENTION_DAYS,
    build_weekly_manifest_from_files,
    write_weekly_artifact_from_files,
)


def _write_inputs(root: Path, *, failed: bool = False) -> tuple[Path, Path]:
    events = root / "data" / "live" / "source_events.csv"
    status = root / "data" / "live" / "source_fetch_status.json"
    events.parent.mkdir(parents=True)
    events.write_text("event_id,symbol\ne1,MU\ne2,INTC\n", encoding="utf-8")
    status.write_text(
        json.dumps(
            {
                "feed_count": 2,
                "successful_feed_count": 1 if failed else 2,
                "failed_feed_count": 1 if failed else 0,
                "feeds": [
                    {"feed_id": "a", "ok": not failed, "item_count": 1},
                    {"feed_id": "b", "ok": True, "item_count": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    return events, status


def _kwargs(root: Path, events: Path, status: Path) -> dict[str, object]:
    return {
        "artifact_paths": [events, status],
        "feed_status_path": status,
        "base_dir": root,
        "period_start": "2026-07-06",
        "as_of": "2026-07-12",
        "generated_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
        "run_mode": "manual",
        "producer_ref": "a" * 40,
        "source_provenance": "official_political_event_tracking_research_v1",
    }


def test_builds_manifest_from_real_input_files_and_is_deterministic(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    first = build_weekly_manifest_from_files(**_kwargs(tmp_path, events, status))
    second_kwargs = _kwargs(tmp_path, events, status)
    second_kwargs["artifact_paths"] = [status, events]
    second = build_weekly_manifest_from_files(**second_kwargs)

    assert first == second
    contract = parse_weekly_manifest_bytes(first)
    assert contract.feed_status.feed_count == 2
    assert {item.path for item in contract.source_artifacts} == {
        "data/live/source_events.csv",
        "data/live/source_fetch_status.json",
    }


def test_writes_the_declared_single_file_artifact(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    output = tmp_path / "artifact"
    target = write_weekly_artifact_from_files(**_kwargs(tmp_path, events, status), output_dir=output)

    assert WEEKLY_ARTIFACT_NAME == "political-event-weekly-v1"
    assert WEEKLY_ARTIFACT_RETENTION_DAYS > 0
    assert target == output / WEEKLY_ARTIFACT_FILE
    assert [path.name for path in output.iterdir()] == [WEEKLY_ARTIFACT_FILE]
    parse_weekly_manifest_bytes(target.read_bytes())


@pytest.mark.parametrize("field", ["period_start", "as_of", "generated_at", "producer_ref"])
def test_requires_explicit_valid_producer_inputs(tmp_path: Path, field: str) -> None:
    events, status = _write_inputs(tmp_path)
    kwargs = _kwargs(tmp_path, events, status)
    kwargs[field] = "" if field != "generated_at" else datetime(2026, 7, 12, tzinfo=timezone.utc)
    with pytest.raises(WeeklyContractError):
        build_weekly_manifest_from_files(**kwargs)


def test_partial_feed_fails_before_artifact_creation(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path, failed=True)
    output = tmp_path / "artifact"
    with pytest.raises(WeeklyContractError):
        write_weekly_artifact_from_files(**_kwargs(tmp_path, events, status), output_dir=output)
    assert not output.exists()


def test_mismatched_expected_manifest_fails_before_write(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    output = tmp_path / "artifact"
    expected = {"manifest_type": "political_event_weekly_manifest", "contract": {}}
    with pytest.raises(WeeklyContractError):
        write_weekly_artifact_from_files(**_kwargs(tmp_path, events, status), output_dir=output, expected_manifest=expected)
    assert not output.exists()


def test_existing_nonempty_artifact_directory_is_not_overwritten(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    output = tmp_path / "artifact"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(WeeklyContractError):
        write_weekly_artifact_from_files(**_kwargs(tmp_path, events, status), output_dir=output)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_relative_inputs_are_resolved_under_base_dir(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    kwargs = _kwargs(tmp_path, events, status)
    kwargs["artifact_paths"] = ["data/live/source_events.csv", "data/live/source_fetch_status.json"]
    kwargs["feed_status_path"] = "data/live/source_fetch_status.json"
    assert parse_weekly_manifest_bytes(build_weekly_manifest_from_files(**kwargs)).feed_status.complete


def test_symlink_input_fails_closed(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    link = tmp_path / "data" / "live" / "link.csv"
    link.symlink_to(events)
    kwargs = _kwargs(tmp_path, events, status)
    kwargs["artifact_paths"] = [link, status]
    with pytest.raises(WeeklyContractError):
        build_weekly_manifest_from_files(**kwargs)


def test_stale_or_missing_feed_status_fails_closed(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    payload = json.loads(status.read_text(encoding="utf-8"))
    payload["feeds"][0]["stale"] = True
    status.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WeeklyContractError):
        build_weekly_manifest_from_files(**_kwargs(tmp_path, events, status))


def test_generated_at_before_completed_week_fails_closed(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    kwargs = _kwargs(tmp_path, events, status)
    kwargs["generated_at"] = datetime(2026, 7, 12, 23, 59, 59, tzinfo=timezone.utc)
    with pytest.raises(WeeklyContractError):
        build_weekly_manifest_from_files(**kwargs)


def test_unrepresentable_period_boundary_fails_closed(tmp_path: Path) -> None:
    events, status = _write_inputs(tmp_path)
    kwargs = _kwargs(tmp_path, events, status)
    kwargs["period_start"] = date.max
    with pytest.raises(WeeklyContractError):
        build_weekly_manifest_from_files(**kwargs)
