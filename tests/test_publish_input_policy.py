from __future__ import annotations

import json
from pathlib import Path

import pytest

from political_event_tracking_research.publish_input_policy import (
    CANONICAL_INPUT_PATHS,
    PUBLISH_MAX_ITEMS_PER_FEED,
    PublishInputPolicyError,
    build_input_policy_evidence,
    build_publication_evidence,
    read_input_policy_evidence,
    read_publication_evidence,
)


def write_inputs(root: Path) -> None:
    for path in CANONICAL_INPUT_PATHS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path + "\n", encoding="utf-8")


def test_publish_requires_exact_50_and_binds_input_digests(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    evidence = build_input_policy_evidence(
        mode="PUBLISH",
        raw_max_items_per_feed="50",
        commit_outputs=True,
        source_sha="a" * 40,
        workflow_ref=(
            "QuantStrategyLab/PoliticalEventTrackingResearch/"
            ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
        ),
        root=tmp_path,
    )
    assert evidence["effective_max_items_per_feed"] == PUBLISH_MAX_ITEMS_PER_FEED
    assert evidence["eligible_for_live_publication"] is True
    assert len(evidence["input_sha256"]) == 3
    assert read_input_policy_evidence(evidence) == evidence


@pytest.mark.parametrize("value", ["25", "49", "51", "050", "50.0", "true", True, False, 50, None, ""])
def test_publish_rejects_noncanonical_max(value: object, tmp_path: Path) -> None:
    write_inputs(tmp_path)
    with pytest.raises(PublishInputPolicyError, match="max_items_per_feed_invalid"):
        build_input_policy_evidence(
            mode="PUBLISH",
            raw_max_items_per_feed=value,
            commit_outputs=True,
            source_sha="a" * 40,
            workflow_ref=(
                "QuantStrategyLab/PoliticalEventTrackingResearch/"
                ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
            ),
            root=tmp_path,
        )


def test_debug_override_is_explicitly_nonpublishable(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    evidence = build_input_policy_evidence(
        mode="DEBUG",
        raw_max_items_per_feed="25",
        commit_outputs=False,
        source_sha="b" * 40,
        workflow_ref=(
            "QuantStrategyLab/PoliticalEventTrackingResearch/"
            ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
        ),
        root=tmp_path,
    )
    assert evidence["effective_max_items_per_feed"] == 25
    assert evidence["eligible_for_live_publication"] is False
    with pytest.raises(PublishInputPolicyError, match="publish_mode_invalid"):
        build_input_policy_evidence(
            mode="DEBUG",
            raw_max_items_per_feed="25",
            commit_outputs=True,
            source_sha="b" * 40,
            workflow_ref=(
                "QuantStrategyLab/PoliticalEventTrackingResearch/"
                ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
            ),
            root=tmp_path,
        )


def test_input_mutation_and_evidence_tamper_fail_closed(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    policy = build_input_policy_evidence(
        mode="PUBLISH",
        raw_max_items_per_feed="50",
        commit_outputs=True,
        source_sha="c" * 40,
        workflow_ref=(
            "QuantStrategyLab/PoliticalEventTrackingResearch/"
            ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
        ),
        root=tmp_path,
    )
    (tmp_path / CANONICAL_INPUT_PATHS[0]).write_text("mutated\n", encoding="utf-8")
    with pytest.raises(PublishInputPolicyError, match="input_digest_mismatch"):
        build_publication_evidence(
            policy,
            root=tmp_path,
            source_items_bytes=b"items",
            status_bytes=b"status",
            status_eligible=True,
            source_items_row_count=0,
            aggregate_row_digest="e" * 64,
        )
    tampered = dict(policy)
    tampered["effective_max_items_per_feed"] = 25
    with pytest.raises(PublishInputPolicyError, match="max_items_per_feed_invalid"):
        read_input_policy_evidence(tampered)


def test_publication_evidence_binds_status_and_source_bytes(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    policy = build_input_policy_evidence(
        mode="PUBLISH",
        raw_max_items_per_feed="50",
        commit_outputs=True,
        source_sha="d" * 40,
        workflow_ref=(
            "QuantStrategyLab/PoliticalEventTrackingResearch/"
            ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
        ),
        root=tmp_path,
    )
    evidence = build_publication_evidence(
        policy,
        root=tmp_path,
        source_items_bytes=b"items",
        status_bytes=b"status",
        status_eligible=True,
        source_items_row_count=2,
        aggregate_row_digest="e" * 64,
    )
    assert read_publication_evidence(evidence) == evidence
    assert evidence["source_items_row_count"] == 2
    assert json.dumps(evidence, sort_keys=True)


def test_debug_evidence_can_readback_without_becoming_publishable(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    policy = build_input_policy_evidence(
        mode="DEBUG",
        raw_max_items_per_feed="25",
        commit_outputs=False,
        source_sha="f" * 40,
        workflow_ref=(
            "QuantStrategyLab/PoliticalEventTrackingResearch/"
            ".github/workflows/rss_source_pipeline.yml@refs/heads/main"
        ),
        root=tmp_path,
    )
    evidence = build_publication_evidence(
        policy,
        root=tmp_path,
        source_items_bytes=b"items",
        status_bytes=b"status",
        status_eligible=True,
        source_items_row_count=1,
        aggregate_row_digest="a" * 64,
    )
    assert evidence["eligible_for_live_publication"] is False
    assert evidence["status_eligible_for_live_publication"] is True


def test_workflow_guard_and_evidence_precede_fetch_and_publish() -> None:
    workflow = Path(__file__).parents[1].joinpath(".github/workflows/rss_source_pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.index("validate-workflow-boundary") < workflow.index(
        "Validate publish input policy before fetch"
    )
    assert workflow.index("Validate publish input policy before fetch") < workflow.index("fetch_rss_sources.py")
    assert workflow.index("Upload RSS source artifact") < workflow.index("Build and validate publication evidence")
    assert workflow.index("Build and validate publication evidence") < workflow.index("Publish live CSV outputs")
    assert '--max-items-per-feed "${MAX_ITEMS_PER_FEED}"' in workflow
    assert "git push origin HEAD:refs/heads/main" in workflow
