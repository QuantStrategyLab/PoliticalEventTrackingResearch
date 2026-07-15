from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/rss_source_pipeline.yml"


def test_legacy_live_publication_precedes_weekly_artifact_failure_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("Publish live CSV outputs to repository") < text.index("Build completed weekly producer artifact")


def test_dedicated_artifact_is_separate_from_legacy_source_artifact() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "path: data/output/rss_source_pipeline/" in text
    assert "path: data/output/political-event-weekly-v1/" in text
    assert text.index("Upload RSS source artifact") < text.index("Upload political weekly artifact")
