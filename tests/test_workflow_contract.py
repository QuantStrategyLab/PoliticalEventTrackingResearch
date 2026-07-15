from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/rss_source_pipeline.yml"


def test_guard_and_legacy_upload_precede_weekly_build() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("Validate workflow dispatch before side effects") < text.index("Fetch RSS sources and extract mentions")
    assert text.index("Upload RSS source artifact") < text.index("Build completed weekly producer artifact")


def test_schedule_uses_actions_api_and_no_period_wall_clock() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions: read" in text
    assert "actions/runs/${GITHUB_RUN_ID}" in text
    assert "--run-payload" in text
    assert "--scheduled-today" not in text


def test_dedicated_artifact_contract_is_fixed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'name: political-event-weekly-v1' in text
    assert 'retention-days: 30' in text
    assert 'path: data/output/political-event-weekly-v1/' in text
