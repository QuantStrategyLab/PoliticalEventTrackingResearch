from __future__ import annotations

import importlib.util
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
