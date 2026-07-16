from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import build_observed_weekly_artifact as producer


REFERENCE = "2026-07-13T12:45:00Z"
RSS = (
    b"<rss version='2.0'><channel><item><title>$ABC event</title>"
    b"<link>https://agency.gov/event</link>"
    b"<pubDate>Sun, 12 Jul 2026 12:00:00 GMT</pubDate>"
    b"<description>Observed event</description></item></channel></rss>"
)
NO_EVENT_RSS = (
    b"<rss version='2.0'><channel><item><title>$ABC future</title>"
    b"<link>https://agency.gov/future</link>"
    b"<pubDate>Mon, 13 Jul 2026 12:00:00 GMT</pubDate>"
    b"</item></channel></rss>"
)
EMPTY_RSS = b"<rss version='2.0'><channel/></rss>"
MISSING_DATE_RSS = b"<rss version='2.0'><channel><item><title>Missing</title><link>https://agency.test/missing</link></item></channel></rss>"


def write_inputs(root: Path) -> tuple[Path, Path, Path]:
    feeds = root / "feeds.csv"
    feeds.write_text("feed_id,feed_url,source_type,author\nfeed-a,https://agency.test/feed,government_policy,\n", encoding="utf-8")
    aliases = root / "aliases.csv"
    aliases.write_text("symbol,aliases\nABC,ABC\n", encoding="utf-8")
    watchlist = root / "watchlist.csv"
    watchlist.write_text("symbol,name,bucket,research_status,thesis,source_url\nABC,Alpha,named_mentioned,watch,thesis,https://example.test\n", encoding="utf-8")
    return feeds, aliases, watchlist


def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes, *, attempt: int = 1) -> Path:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: payload)
    return producer.build_observed_weekly_artifact(
        feeds_path=feeds,
        aliases_path=aliases,
        watchlist_path=watchlist,
        output_dir=tmp_path / "artifact",
        retrieved_at=REFERENCE,
        source_run_id="123",
        source_attempt=attempt,
        producer_ref="a" * 40,
        run_mode="scheduled",
    )


def test_success_emits_exact_five_files_and_observed_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = build(tmp_path, monkeypatch, RSS)
    assert {item.name for item in output.iterdir()} == set(producer.ARTIFACT_FILES)
    manifest = producer.read_observed_manifest((output / "weekly_manifest.json").read_bytes())
    assert manifest["observed_snapshot"]["coverage_semantics"] == "configured_source_observed"
    assert manifest["observed_snapshot"]["provider_freshness"] == "unverified"
    assert manifest["observed_snapshot"]["private_research_only"] is True
    assert manifest["observed_snapshot"]["selected_period_count"] == 1
    assert manifest["observed_snapshot"]["source_run_id"] == "123"


def test_accepted_feed_with_zero_period_rows_is_legal_no_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = build(tmp_path, monkeypatch, NO_EVENT_RSS)
    manifest = producer.read_observed_manifest((output / "weekly_manifest.json").read_bytes())
    assert manifest["observed_snapshot"]["selected_period_count"] == 0


def test_zero_entry_feed_quarantines_and_emits_no_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(producer.ObservedArtifactError, match="source_incomplete"):
        build(tmp_path, monkeypatch, EMPTY_RSS)
    assert not (tmp_path / "artifact").exists()


def test_missing_event_date_does_not_fallback_to_now(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(producer.ObservedArtifactError, match="source_incomplete"):
        build(tmp_path, monkeypatch, MISSING_DATE_RSS)


def test_attempt_two_fails_before_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: pytest.fail("fetch must not run"))
    with pytest.raises(producer.ObservedArtifactError, match="source_attempt_invalid"):
        producer.build_observed_weekly_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "artifact",
            retrieved_at=REFERENCE,
            source_run_id="123",
            source_attempt=2,
            producer_ref="a" * 40,
            run_mode="manual",
        )


def test_manual_period_must_match_immediate_prior_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = write_inputs(tmp_path)
    monkeypatch.setattr(producer, "fetch_url", lambda _url: RSS)
    with pytest.raises(producer.ObservedArtifactError, match="manual_period_mismatch"):
        producer.build_observed_weekly_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "artifact",
            retrieved_at=REFERENCE,
            source_run_id="123",
            source_attempt=1,
            producer_ref="a" * 40,
            run_mode="manual",
            period_start="2026-06-29",
            as_of="2026-07-05",
        )


def test_workflow_is_private_observed_only() -> None:
    workflow = Path(__file__).parents[1] / ".github/workflows/pert_weekly_observed_snapshot.yml"
    text = workflow.read_text(encoding="utf-8")
    assert 'cron: "45 12 * * 1"' in text
    assert "name: political-event-weekly-v1" in text
    assert "retention-days: 30" in text
    assert "contents: read" in text
    assert "actions: read" not in text
    assert "private_research_only" in (Path(__file__).parents[1] / "docs/pert_weekly_observed_snapshot_artifact.md").read_text(encoding="utf-8") or "private" in text


def test_workflow_actions_are_immutable_full_sha_pinned() -> None:
    workflow = Path(__file__).parents[1] / ".github/workflows/pert_weekly_observed_snapshot.yml"
    text = workflow.read_text(encoding="utf-8")
    refs = re.findall(r"uses:\s*actions/(checkout|setup-python|upload-artifact)@([^\s#]+)", text)

    assert {name for name, _ in refs} == {"checkout", "setup-python", "upload-artifact"}
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for _, ref in refs)
