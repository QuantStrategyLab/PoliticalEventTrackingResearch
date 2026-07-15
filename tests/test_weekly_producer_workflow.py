import re
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "rss_source_pipeline.yml"


def test_weekly_workflow_uses_pinned_actions_and_explicit_contract_inputs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10" in text
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in text
    assert text.count("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a") == 2
    assert "period_start:" in text and "as_of:" in text
    assert "--period-start \"${PERIOD_START}\"" in text
    assert "--as-of \"${AS_OF}\"" in text
    assert "--generated-at \"${GENERATED_AT}\"" in text
    assert "retention-days: 30" in text
    assert "if-no-files-found: error" in text
    assert 'cron: "15 0 * * 1"' in text
    upload_steps = re.findall(r"^      - name: Upload.*?(?=^      - name:|\Z)", text, re.MULTILINE | re.DOTALL)
    assert len(upload_steps) == 2
    broad, dedicated = upload_steps
    assert "weekly_manifest.json" not in broad
    assert "source_items.csv" in broad
    assert "source_events.csv" in broad
    assert "source_tracker.csv" in broad
    assert "source_fetch_status.json" in broad
    assert dedicated.count("weekly_manifest.json") == 1
    assert "name: political-event-weekly-v1" in dedicated
    assert "path: data/output/rss_source_pipeline/weekly-artifact/weekly_manifest.json" in dedicated
    for line in text.splitlines():
        if "uses: actions/" in line:
            assert len(line.split("@", 1)[1].split()[0]) == 40
