from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import build_weekly_producer_artifact as producer


REFERENCE = "2026-07-13T12:45:00Z"
RSS = (
    b"<?xml version='1.0'?><rss version='2.0'><channel><title>Feed</title>"
    b"<item><title>$ABC contract</title><link>https://agency.gov/item</link>"
    b"<pubDate>Sun, 12 Jul 2026 12:00:00 GMT</pubDate><description>contract award</description>"
    b"</item></channel></rss>"
)
EMPTY_RSS = b"<?xml version='1.0'?><rss version='2.0'><channel><title>Feed</title></channel></rss>"


def write_inputs(root: Path) -> tuple[Path, Path, Path]:
    feeds = root / "feeds.csv"
    feeds.write_text(
        "feed_id,feed_url,source_type,author\nfeed-a,https://agency.gov/feed,government_policy,\n",
        encoding="utf-8",
    )
    aliases = root / "aliases.csv"
    aliases.write_text("symbol,aliases\nABC,ABC\n", encoding="utf-8")
    watchlist = root / "watchlist.csv"
    watchlist.write_text(
        "symbol,name,bucket,research_status,thesis,source_url\nABC,Alpha,named_mentioned,watch,thesis,https://example.test\n",
        encoding="utf-8",
    )
    return feeds, aliases, watchlist


def test_immediate_prior_period_and_manual_match() -> None:
    assert producer.expected_period(REFERENCE) == (
        producer.dt.date(2026, 7, 6),
        producer.dt.date(2026, 7, 13),
        producer.dt.date(2026, 7, 12),
    )
    assert producer.validate_requested_period(
        REFERENCE, "2026-07-06", "2026-07-12"
    ) == producer.expected_period(REFERENCE)
    with pytest.raises(producer.WeeklyArtifactError, match="manual_period_mismatch"):
        producer.validate_requested_period(REFERENCE, "2026-06-29", "2026-07-05")


def test_run_attempt_two_fails_before_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: pytest.fail("fetch must not run"))
    with pytest.raises(producer.WeeklyArtifactError, match="run_attempt_invalid"):
        producer.build_weekly_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "artifact",
            reference_time=REFERENCE,
            source_run_id="123",
            source_attempt=2,
            producer_ref="a" * 40,
            run_mode="scheduled",
        )


def test_successful_snapshot_emits_exact_five_files_and_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: RSS)
    output = producer.build_weekly_artifact(
        feeds_path=feeds,
        aliases_path=aliases,
        watchlist_path=watchlist,
        output_dir=tmp_path / "artifact",
        reference_time=REFERENCE,
        source_run_id="123",
        source_attempt=1,
        producer_ref="a" * 40,
        run_mode="scheduled",
    )
    assert {path.name for path in output.iterdir()} == set(producer.ARTIFACT_FILES)
    assert producer.parse_period_lock_bytes((output / "period_lock.json").read_bytes()).source_run_id == "123"
    manifest = producer.parse_weekly_manifest_bytes((output / "weekly_manifest.json").read_bytes())
    assert manifest.as_of.isoformat() == "2026-07-12"
    assert {item.path for item in manifest.source_artifacts} == {
        "period_lock.json",
        "political_events.csv",
        "political_watchlist.csv",
        "political_event_weekly.json",
    }


def test_zero_entry_feed_cannot_emit_success_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: EMPTY_RSS)
    with pytest.raises(producer.WeeklyArtifactError, match="weekly_source_incomplete"):
        producer.build_weekly_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "artifact",
            reference_time=REFERENCE,
            source_run_id="123",
            source_attempt=1,
            producer_ref="a" * 40,
            run_mode="scheduled",
        )
    assert not (tmp_path / "artifact").exists()


def test_stale_feed_is_failed_and_does_not_emit_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    old_rss = RSS.replace(b"12 Jul 2026", b"28 Jun 2026")
    monkeypatch.setattr(producer, "fetch_url", lambda _url: old_rss)
    with pytest.raises(producer.WeeklyArtifactError, match="weekly_source_incomplete"):
        producer.build_weekly_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "artifact",
            reference_time=REFERENCE,
            source_run_id="123",
            source_attempt=1,
            producer_ref="a" * 40,
            run_mode="scheduled",
        )
    assert not (tmp_path / "artifact").exists()


def test_period_override_does_not_derive_run_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: RSS)
    output = producer.build_weekly_artifact(
        feeds_path=feeds,
        aliases_path=aliases,
        watchlist_path=watchlist,
        output_dir=tmp_path / "artifact",
        reference_time=REFERENCE,
        source_run_id="123",
        source_attempt=1,
        producer_ref="a" * 40,
        run_mode="scheduled",
        period_start="2026-07-06",
        as_of="2026-07-12",
    )
    manifest = producer.parse_weekly_manifest_bytes((output / "weekly_manifest.json").read_bytes())
    assert manifest.run_mode == "scheduled"


def test_weekly_workflow_isolated_and_retained() -> None:
    workflow = Path(__file__).parents[1].joinpath(".github/workflows/pert_weekly_producer.yml").read_text()
    assert 'cron: "45 12 * * 1"' in workflow
    assert "name: political-event-weekly-v1" in workflow
    assert "retention-days: 30" in workflow
    assert "run_attempt" in workflow
    assert "contents: read" in workflow
    assert "actions: read" not in workflow
    assert "id-token" not in workflow
