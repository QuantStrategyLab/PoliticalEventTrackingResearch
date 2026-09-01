from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_module():
    path = Path(__file__).parents[1] / "scripts" / "publish_live_outputs_pr.py"
    spec = importlib.util.spec_from_file_location("publish_live_outputs_pr", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_does_not_create_branch_or_pr_without_staged_changes(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(module, "staged_changes_present", lambda: False)

    assert module.publish("automation/generated", "Generated", "body", "commit") == "No generated data changes to publish."


def test_publish_uses_an_automation_branch_and_reuses_existing_pr(monkeypatch) -> None:
    module = load_module()
    commands: list[list[str]] = []
    monkeypatch.setattr(module, "staged_changes_present", lambda: True)
    monkeypatch.setattr(module, "existing_pull_request", lambda branch: "https://example.test/pr/1")

    def fake_run(command, *, capture=False):
        commands.append(list(command))
        return ""

    monkeypatch.setattr(module, "run", fake_run)

    result = module.publish("automation/generated", "Generated", "body", "commit")

    assert result == "Updated generated-data PR: https://example.test/pr/1"
    assert ["git", "switch", "-C", "automation/generated"] in commands
    assert ["git", "push", "--force-with-lease", "origin", "HEAD:refs/heads/automation/generated"] in commands
    assert all("main" not in command[-1:] for command in commands if command[:2] == ["git", "push"])


def test_publish_creates_pull_request_after_pushing_branch(monkeypatch) -> None:
    module = load_module()
    commands: list[list[str]] = []
    monkeypatch.setenv("GITHUB_REPOSITORY", "QuantStrategyLab/example")
    monkeypatch.setattr(module, "staged_changes_present", lambda: True)
    monkeypatch.setattr(module, "existing_pull_request", lambda branch: "")

    def fake_run(command, *, capture=False):
        commands.append(list(command))
        return "https://example.test/pr/2" if command[:3] == ["gh", "pr", "create"] else ""

    monkeypatch.setattr(module, "run", fake_run)

    result = module.publish("automation/generated", "Generated", "body", "commit")

    assert result == "Created generated-data PR: https://example.test/pr/2"
    create = next(command for command in commands if command[:3] == ["gh", "pr", "create"])
    assert ["--head", "automation/generated"] == create[create.index("--head") : create.index("--head") + 2]
    assert ["--base", "main"] == create[create.index("--base") : create.index("--base") + 2]


def test_publish_writes_human_handoff_without_remote_mutation(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    commands: list[list[str]] = []
    monkeypatch.setenv("GITHUB_REPOSITORY", "QuantStrategyLab/example")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(module, "staged_changes_present", lambda: True)

    def fake_run(command, *, capture=False, strip=True):
        commands.append(list(command))
        if command[-3:] == ["--binary", "--full-index", "--cached"]:
            assert strip is False
            return "diff --git a/data/live/example.csv b/data/live/example.csv\n"
        if command[-3:] == ["--cached", "--name-only", "--diff-filter=ACMR"]:
            return "data/live/example.csv"
        return ""

    monkeypatch.setattr(module, "run", fake_run)

    result = module.publish(
        "automation/generated",
        "Generated",
        "body",
        "commit",
        handoff_dir=tmp_path,
    )

    assert result == "HUMAN_REQUIRED: generated publication handoff artifact."
    assert not any(command[:2] == ["git", "push"] for command in commands)
    assert not any(command[:3] == ["gh", "pr", "create"] for command in commands)

    patch = tmp_path / "generated-live-output.patch"
    receipt = json.loads((tmp_path / "publication-handoff.json").read_text(encoding="utf-8"))
    assert patch.read_text(encoding="utf-8").startswith("diff --git")
    assert patch.read_bytes().endswith(b"\n")
    assert receipt == {
        "schema_version": 1,
        "status": "HUMAN_REQUIRED",
        "reason_code": "PR_CREATION_IDENTITY_UNAVAILABLE",
        "repository": "QuantStrategyLab/example",
        "source_sha": "a" * 40,
        "run_id": "123",
        "target_branch": "main",
        "proposed_branch": "automation/generated",
        "title": "Generated",
        "staged_paths": ["data/live/example.csv"],
        "patch_path": "generated-live-output.patch",
        "patch_sha256": module.hashlib.sha256(patch.read_bytes()).hexdigest(),
        "next_action": "A maintainer must review and apply the patch through the protected branch process.",
    }


def test_source_workflows_use_read_only_handoff_artifacts() -> None:
    root = Path(__file__).parents[1]
    workflows = {
        "rss_source_pipeline.yml": "data/output/rss_source_pipeline",
        "source_event_pipeline.yml": "data/output/source_event_pipeline",
    }

    for filename, output_dir in workflows.items():
        text = (root / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        assert "permissions:\n  contents: read" in text
        assert "contents: write" not in text
        assert "pull-requests: write" not in text
        assert f"--handoff-dir {output_dir}" in text
        assert "if: ${{ always() }}" in text
