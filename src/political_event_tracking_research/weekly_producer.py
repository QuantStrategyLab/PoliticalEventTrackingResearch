"""Producer-side integration for a validated ``political_event_weekly.v1`` artifact.

This module only materializes a manifest from explicitly supplied local inputs.  It
does not fetch feeds, infer a period, or publish/upload an artifact.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import stat
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .weekly_contract import (
    MAX_SAFE_JSON_INTEGER,
    WeeklyContractError,
    WeeklyFeedStatus,
    WeeklySourceArtifact,
    WeeklySourceContract,
    _date,
)
from .weekly_manifest import (
    parse_weekly_manifest,
    serialize_weekly_manifest,
)

WEEKLY_ARTIFACT_NAME = "political-event-weekly-v1"
WEEKLY_ARTIFACT_FILE = "weekly_manifest.json"
WEEKLY_ARTIFACT_FILES = (WEEKLY_ARTIFACT_FILE,)
WEEKLY_ARTIFACT_RETENTION_DAYS = 30


def _invalid(code: str) -> WeeklyContractError:
    return WeeklyContractError(code)


def _checked_base(path: str | Path) -> Path:
    try:
        base = Path(path)
    except (TypeError, ValueError):
        raise _invalid("producer_base_invalid") from None
    try:
        base_stat = base.lstat()
    except OSError:
        raise _invalid("producer_base_invalid") from None
    if stat.S_ISLNK(base_stat.st_mode) or not stat.S_ISDIR(base_stat.st_mode):
        raise _invalid("producer_base_invalid")
    return base


def _relative_input(path: str | Path, base: Path) -> tuple[str, Path]:
    try:
        candidate = Path(path)
    except (TypeError, ValueError):
        raise _invalid("producer_input_path_invalid") from None
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        relative = candidate.relative_to(base)
    except ValueError:
        raise _invalid("producer_input_path_invalid") from None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts) or "\\" in relative.as_posix():
        raise _invalid("producer_input_path_invalid")

    current = base
    try:
        for index, part in enumerate(relative.parts):
            current = current / part
            item_stat = current.lstat()
            is_final = index == len(relative.parts) - 1
            if stat.S_ISLNK(item_stat.st_mode) or (is_final and not stat.S_ISREG(item_stat.st_mode)) or (
                not is_final and not stat.S_ISDIR(item_stat.st_mode)
            ):
                raise _invalid("producer_input_file_invalid")
    except WeeklyContractError:
        raise
    except OSError:
        raise _invalid("producer_input_file_invalid") from None
    return relative.as_posix(), current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise _invalid("producer_input_file_invalid") from None
    return digest.hexdigest()


def _row_count(path: Path) -> int:
    if path.suffix.lower() != ".csv":
        return 0
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        raise _invalid("producer_input_file_invalid") from None


def _safe_counter(value: object, code: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_JSON_INTEGER:
        raise _invalid(code)
    return value


def _feed_status(path: Path) -> WeeklyFeedStatus:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _invalid("feed_status_invalid") from None
    if not isinstance(value, Mapping):
        raise _invalid("feed_status_invalid")
    required = {"feed_count", "successful_feed_count", "failed_feed_count", "feeds"}
    if not required.issubset(value) or not isinstance(value["feeds"], list) or not value["feeds"]:
        raise _invalid("feed_status_invalid")

    feed_count = _safe_counter(value["feed_count"], "feed_status_invalid")
    successful = _safe_counter(value["successful_feed_count"], "feed_status_invalid")
    failed = _safe_counter(value["failed_feed_count"], "feed_status_invalid")
    stale = _safe_counter(value.get("stale_feed_count", 0), "feed_status_invalid")
    missing = _safe_counter(value.get("missing_feed_count", 0), "feed_status_invalid")
    calculated_successful = 0
    calculated_failed = 0
    calculated_stale = 0
    calculated_missing = 0
    for item in value["feeds"]:
        if not isinstance(item, Mapping) or type(item.get("ok")) is not bool:
            raise _invalid("feed_status_invalid")
        if item["ok"]:
            calculated_successful += 1
        else:
            calculated_failed += 1
        for key, counter in (("stale", "stale_feed_count"), ("missing", "missing_feed_count")):
            if key in item and type(item[key]) is not bool:
                raise _invalid("feed_status_invalid")
            if item.get(key) is True:
                if counter == "stale_feed_count":
                    calculated_stale += 1
                else:
                    calculated_missing += 1
    if (feed_count, successful, failed, stale, missing) != (
        len(value["feeds"]),
        calculated_successful,
        calculated_failed,
        calculated_stale,
        calculated_missing,
    ):
        raise _invalid("feed_status_mismatch")
    try:
        return WeeklyFeedStatus(feed_count, successful, failed, stale, missing, True)
    except WeeklyContractError:
        raise


def _contract_from_files(
    artifact_paths: Sequence[str | Path],
    *,
    feed_status_path: str | Path,
    base_dir: str | Path,
    period_start: date,
    as_of: date,
    generated_at: datetime,
    run_mode: str,
    producer_ref: str,
    source_provenance: str,
) -> WeeklySourceContract:
    if isinstance(artifact_paths, (str, bytes)) or not isinstance(artifact_paths, Sequence) or not artifact_paths:
        raise _invalid("producer_inputs_invalid")
    if type(period_start) is not date or type(as_of) is not date or type(generated_at) is not datetime:
        raise _invalid("producer_inputs_invalid")
    base = _checked_base(base_dir)
    seen: set[str] = set()
    artifacts: list[WeeklySourceArtifact] = []
    status_key: str | None = None
    status_file: Path | None = None
    for raw_path in artifact_paths:
        key, path = _relative_input(raw_path, base)
        if key in seen:
            raise _invalid("producer_input_duplicate")
        seen.add(key)
        artifacts.append(WeeklySourceArtifact(key, _sha256(path), _row_count(path)))
    status_key, status_file = _relative_input(feed_status_path, base)
    if status_key not in seen or status_file is None:
        raise _invalid("feed_status_missing")
    status = _feed_status(status_file)
    try:
        period_end_exclusive = period_start + timedelta(days=7)
    except OverflowError:
        raise _invalid("period_invalid") from None
    try:
        return WeeklySourceContract(
            as_of,
            period_start,
            period_end_exclusive,
            generated_at,
            run_mode,
            producer_ref,
            source_provenance,
            tuple(artifacts),
            status,
        )
    except WeeklyContractError:
        raise


def build_weekly_manifest_from_files(
    artifact_paths: Sequence[str | Path],
    *,
    feed_status_path: str | Path,
    base_dir: str | Path,
    period_start: date | str,
    as_of: date | str,
    generated_at: datetime,
    run_mode: str,
    producer_ref: str,
    source_provenance: str,
    expected_manifest: Mapping[str, object] | None = None,
) -> bytes:
    """Build canonical manifest bytes from explicitly supplied, local inputs.

    Date strings are accepted only for CLI-friendly construction and are parsed
    strictly by the merged weekly contract.  No date or timestamp is inferred.
    """
    parsed_period_start = _date(period_start) if isinstance(period_start, str) else period_start
    parsed_as_of = _date(as_of) if isinstance(as_of, str) else as_of
    contract = _contract_from_files(
        artifact_paths,
        feed_status_path=feed_status_path,
        base_dir=base_dir,
        period_start=parsed_period_start,
        as_of=parsed_as_of,
        generated_at=generated_at,
        run_mode=run_mode,
        producer_ref=producer_ref,
        source_provenance=source_provenance,
    )
    content = serialize_weekly_manifest(contract)
    if expected_manifest is not None:
        try:
            expected = parse_weekly_manifest(expected_manifest)
            if serialize_weekly_manifest(expected) != content:
                raise _invalid("manifest_input_mismatch")
        except WeeklyContractError:
            raise
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise _invalid("manifest_input_mismatch") from None
    return content


def write_weekly_artifact_from_files(
    artifact_paths: Sequence[str | Path],
    *,
    output_dir: str | Path,
    expected_manifest: Mapping[str, object] | None = None,
    **kwargs: Any,
) -> Path:
    """Write one validated manifest file without overwriting an existing artifact."""
    content = build_weekly_manifest_from_files(artifact_paths, expected_manifest=expected_manifest, **kwargs)
    output = Path(output_dir)
    created_output = False
    try:
        if output.is_symlink():
            raise _invalid("artifact_output_invalid")
        if output.exists():
            if not output.is_dir() or any(output.iterdir()):
                raise _invalid("artifact_output_exists")
        else:
            output.mkdir(parents=True)
            created_output = True
        target = output / WEEKLY_ARTIFACT_FILE
        with target.open("xb") as handle:
            handle.write(content)
        members = list(output.iterdir())
        if [member.name for member in members] != [WEEKLY_ARTIFACT_FILE] or not stat.S_ISREG(target.lstat().st_mode):
            raise _invalid("artifact_output_invalid")
        from .weekly_manifest import parse_weekly_manifest_bytes  # noqa: PLC0415 - avoid import cycle at module load

        parse_weekly_manifest_bytes(target.read_bytes())
    except WeeklyContractError:
        if created_output:
            shutil.rmtree(output, ignore_errors=True)
        raise
    except (OSError, TypeError, ValueError):
        if created_output:
            shutil.rmtree(output, ignore_errors=True)
        raise _invalid("artifact_write_invalid") from None
    return target
