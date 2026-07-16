from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from political_event_tracking_research import bounded_observed_weekly as observed
from political_event_tracking_research.bounded_observed_weekly import BoundedObservedError


REFERENCE = "2026-07-13T12:45:00Z"
GENERATED = "2026-07-13T12:46:00Z"
PRODUCER_SHA = "a" * 40

RSS = b"""<rss version='2.0'><channel><item>
<title>$ABC policy event</title><link>https://agency.gov/event</link>
<pubDate>Sun, 12 Jul 2026 12:00:00 GMT</pubDate>
<description>Policy event for $ABC.</description>
</item></channel></rss>"""
RSS_OLDER = b"""<rss version='2.0'><channel><item>
<title>$ABC old event</title><link>https://agency.gov/old</link>
<pubDate>Sun, 28 Jun 2026 12:00:00 GMT</pubDate>
<description>Old event for $ABC.</description>
</item></channel></rss>"""
ATOM = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry>
<title>$ABC Atom event</title><link href='https://example.test/atom'/>
<published>2026-07-04T12:00:00Z</published><summary>Atom event for $ABC.</summary>
</entry></feed>"""
DC_RSS = b"""<rss version='2.0' xmlns:dc='http://purl.org/dc/elements/1.1/'><channel><item>
<title>$ABC DC event</title><link>https://example.test/dc</link>
<dc:date>2026-07-03T12:00:00Z</dc:date><description>DC event for $ABC.</description>
</item></channel></rss>"""


def _inputs(tmp_path: Path, feed_count: int = 1) -> tuple[Path, Path, Path]:
    feeds = tmp_path / "feeds.csv"
    feed_rows = [
        f"feed-{index},https://agency.gov/{index},official_remarks,Example\n" for index in range(feed_count)
    ]
    feeds.write_text("feed_id,feed_url,source_type,author\n" + "".join(feed_rows), encoding="utf-8")
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("symbol,aliases\nABC,ABC\n", encoding="utf-8")
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("symbol,name,bucket,research_status,thesis,source_url\nABC,Alpha,named_mentioned,watch,Test,https://example.test\n", encoding="utf-8")
    return feeds, aliases, watchlist


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payloads: dict[str, bytes], **kwargs: object) -> Path:
    feeds, aliases, watchlist = _inputs(tmp_path, len(payloads))

    def fetcher(url: str) -> bytes:
        return payloads[url.rsplit("/", 1)[-1]]

    monkeypatch.setattr(observed, "fetch_url", fetcher)
    return observed.build_weekly_observed_artifact(
        feeds_path=feeds,
        aliases_path=aliases,
        watchlist_path=watchlist,
        output_dir=tmp_path / "artifact",
        retrieved_at=REFERENCE,
        generated_at=GENERATED,
        source_run_id="123",
        source_attempt=1,
        producer_ref=PRODUCER_SHA,
        run_mode="manual",
        **kwargs,
    )


def test_success_emits_exact_five_files_and_bounded_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _build(tmp_path, monkeypatch, {"0": RSS})

    assert {path.name for path in output.iterdir()} == set(observed.ARTIFACT_FILES)
    manifest = observed.read_observed_manifest((output / "weekly_manifest.json").read_bytes())
    assert manifest["coverage_completeness"] == "bounded_unverified"
    assert manifest["max_items_per_feed"] == 50
    assert manifest["truncation_possible"] is True
    assert manifest["private_research_only"] is True
    assert manifest["provider_freshness"] == "unverified"
    assert manifest["source_run_id"] == "123"
    assert manifest["source_attempt"] == 1
    assert manifest["selected_period_count"] == 1
    assert set(manifest["files"]) == set(observed.ARTIFACT_FILES[:-1])
    assert manifest["files"]["political_events.csv"]["sha256"] == hashlib.sha256((output / "political_events.csv").read_bytes()).hexdigest()


def test_accepted_feeds_with_zero_selected_rows_is_legal_no_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _build(tmp_path, monkeypatch, {"0": RSS_OLDER})

    manifest = observed.read_observed_manifest((output / "weekly_manifest.json").read_bytes())
    assert manifest["selected_period_count"] == 0
    assert (output / "political_events.csv").read_text(encoding="utf-8").count("\n") == 1


def test_zero_entry_feed_is_quarantined_and_no_success_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = b"<rss version='2.0'><channel/></rss>"
    with pytest.raises(BoundedObservedError, match="source_incomplete"):
        _build(tmp_path, monkeypatch, {"0": empty})
    assert not (tmp_path / "artifact").exists()


def test_event_date_namespaces_are_strict_and_dc_is_explicitly_supported() -> None:
    feed = observed.FeedConfig("x", "https://example.test", "official", "")
    assert observed.parse_bounded_feed_snapshot(RSS, feed).kind == "rss2"
    assert observed.parse_bounded_feed_snapshot(ATOM, feed).kind == "atom"
    assert observed.parse_bounded_feed_snapshot(DC_RSS, feed).kind == "rss2"
    with pytest.raises(BoundedObservedError, match="event_date_invalid"):
        observed.parse_bounded_feed_snapshot(
            b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>x</title><updated>2026-07-04</updated></entry></feed>",
            feed,
        )
    with pytest.raises(BoundedObservedError, match="event_date_invalid"):
        observed.parse_bounded_feed_snapshot(
            b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>x</title><updated>2026-07-04T12:00:00</updated></entry></feed>",
            feed,
        )


def test_bounded_parser_reports_observed_count_without_claiming_completeness() -> None:
    feed = observed.FeedConfig("x", "https://example.test", "official", "")
    payload = b"<rss version='2.0'><channel>" + b"".join(
        f"<item><title>$ABC {index}</title><link>https://example.test/{index}</link><pubDate>Sun, 12 Jul 2026 12:00:00 GMT</pubDate></item>".encode()
        for index in range(51)
    ) + b"</channel></rss>"

    snapshot = observed.parse_bounded_feed_snapshot(payload, feed)

    assert snapshot.observed_count == 50
    assert snapshot.truncation_possible is True


def test_tampered_manifest_and_coverage_values_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _build(tmp_path, monkeypatch, {"0": RSS})
    wire = (output / "weekly_manifest.json").read_bytes().replace(b"bounded_unverified", b"complete")
    with pytest.raises(BoundedObservedError):
        observed.read_observed_manifest(wire)


def test_feed_snapshot_url_must_be_exact_nonempty_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _build(tmp_path, monkeypatch, {"0": RSS})
    manifest = observed.read_observed_manifest((output / "weekly_manifest.json").read_bytes())
    manifest["feed_snapshots"][0]["feed_url"] = ""
    with pytest.raises(BoundedObservedError, match="feed_snapshot_invalid"):
        observed.serialize_observed_manifest(manifest)

    manifest["feed_snapshots"][0]["feed_url"] = 123
    with pytest.raises(BoundedObservedError, match="feed_snapshot_invalid"):
        observed.serialize_observed_manifest(manifest)


def test_readback_compares_every_exported_h2c_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _build(tmp_path, monkeypatch, {"0": RSS})
    manifest_bytes = (output / "weekly_manifest.json").read_bytes()
    manifest = observed.read_observed_manifest(manifest_bytes)
    manifest["h2c"]["aggregate_row_digest"] = "b" * 64
    tampered_manifest = observed.serialize_observed_manifest(manifest)
    with pytest.raises(BoundedObservedError, match="artifact_readback_invalid"):
        observed._readback(
            output,
            (output / "period_lock.json").read_bytes(),
            (output / "political_event_weekly.json").read_bytes(),
            tampered_manifest,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("feed_count", 0), ("rejected_row_count", 1), ("accepted_row_count", 0)),
)
def test_manifest_h2c_totals_must_match_success_invariants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: int,
) -> None:
    output = _build(tmp_path, monkeypatch, {"0": RSS})
    manifest = observed.read_observed_manifest((output / "weekly_manifest.json").read_bytes())
    manifest["h2c"][field] = value
    with pytest.raises(BoundedObservedError):
        observed.serialize_observed_manifest(manifest)


def test_manual_period_mismatch_and_attempt_two_fail_before_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, aliases, watchlist = _inputs(tmp_path)
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return RSS

    with pytest.raises(BoundedObservedError, match="manual_period_mismatch"):
        observed.build_weekly_observed_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "period-mismatch",
            retrieved_at=REFERENCE,
            generated_at=GENERATED,
            source_run_id="123",
            source_attempt=1,
            producer_ref=PRODUCER_SHA,
            run_mode="manual",
            period_start="2026-06-29",
            as_of="2026-07-05",
            fetcher=fetcher,
        )
    assert calls == []

    with pytest.raises(BoundedObservedError, match="source_attempt_invalid"):
        observed.build_weekly_observed_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "attempt-two",
            retrieved_at=REFERENCE,
            generated_at=GENERATED,
            source_run_id="123",
            source_attempt=2,
            producer_ref=PRODUCER_SHA,
            run_mode="scheduled",
            fetcher=fetcher,
        )
    assert calls == []


def test_failed_feed_does_not_emit_success_artifact(tmp_path: Path) -> None:
    feeds, aliases, watchlist = _inputs(tmp_path)

    def fetcher(_url: str) -> bytes:
        raise OSError("network detail must not escape")

    with pytest.raises(BoundedObservedError, match="source_incomplete"):
        observed.build_weekly_observed_artifact(
            feeds_path=feeds,
            aliases_path=aliases,
            watchlist_path=watchlist,
            output_dir=tmp_path / "failed",
            retrieved_at=REFERENCE,
            generated_at=GENERATED,
            source_run_id="123",
            source_attempt=1,
            producer_ref=PRODUCER_SHA,
            run_mode="scheduled",
            fetcher=fetcher,
        )
    assert not (tmp_path / "failed").exists()


def test_workflow_is_private_and_actions_are_full_sha_pinned() -> None:
    workflow = Path(__file__).parents[1] / ".github/workflows/pert_weekly_bounded_observed_artifact.yml"
    text = workflow.read_text(encoding="utf-8")
    refs = re.findall(r"uses:\s*actions/(checkout|setup-python|upload-artifact)@([^\s#]+)", text)
    assert {name for name, _ in refs} == {"checkout", "setup-python", "upload-artifact"}
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for _, ref in refs)
    assert "retention-days: 30" in text
    assert "contents: read" in text
    assert "actions: read" not in text
    assert "political-event-weekly-v1" in text
    assert "legacy" not in text.lower()
