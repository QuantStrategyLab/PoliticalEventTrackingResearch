from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import copy
import io
import re
import textwrap
import urllib.request

import pytest


def load_module():
    path = Path(__file__).parents[1] / "scripts" / "publish_live_outputs_pr.py"
    spec = importlib.util.spec_from_file_location("publish_live_outputs_pr", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_does_not_create_branch_or_pr_without_staged_changes(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    monkeypatch.setattr(module, "staged_changes_present", lambda: False)

    result = module.publish(
        "automation/generated",
        "Generated",
        "body",
        "commit",
        handoff_dir=tmp_path,
    )

    assert result == "No generated data changes to publish."


def test_publish_requires_handoff_before_repository_or_remote_mutation(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setenv("GITHUB_REPOSITORY", "QuantStrategyLab/example")
    monkeypatch.setattr(module, "staged_changes_present", lambda: pytest.fail("git diff must not run"))
    monkeypatch.setattr(module, "run", lambda *_args, **_kwargs: pytest.fail("git command must not run"))

    with pytest.raises(module.PublishError, match="handoff"):
        module.publish("automation/generated", "Generated", "body", "commit")


def test_cli_requires_handoff_dir(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_live_outputs_pr.py",
            "--branch",
            "automation/generated",
            "--title",
            "Generated",
            "--body",
            "body",
            "--commit-message",
            "commit",
        ],
    )

    with pytest.raises(SystemExit):
        module.parse_args()


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
    assert commands == [
        ["git", "diff", "--binary", "--full-index", "--cached"],
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
    ]

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
        permissions = text.split("permissions:\n", 1)[1].split("\n\n", 1)[0]
        assert permissions == "  contents: read"
        assert f"--handoff-dir {output_dir}" in text
        assert "if: ${{ always() }}" in text or "if: ${{ always() && !inputs.identity_only }}" in text


IDENTITY_REPOSITORY = "QuantStrategyLab/PoliticalEventTrackingResearch"
IDENTITY_WORKFLOW = "rss_source_pipeline.yml"


# Identity-only tests execute the reviewed inline Python with mocked HTTP only.


IDENTITY_ACTION = "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1"
IDENTITY_URL = "https://api.github.com/installation/repositories?per_page=100"


def identity_workflow():
    return Path(__file__).parents[1] / ".github" / "workflows" / IDENTITY_WORKFLOW


def identity_steps():
    return ["      - " + block for block in re.split(r"(?m)^      - ", identity_workflow().read_text())[1:]]


def identity_step(step_id):
    return next(block for block in identity_steps() if f"        id: {step_id}\n" in block)


def identity_python(step_id):
    block = identity_step(step_id).split("        run: |\n", 1)[1]
    script = textwrap.dedent(block)
    assert script.startswith("python - <<'PY'\n")
    return script.removeprefix("python - <<'PY'\n").rsplit("\nPY", 1)[0]


def identity_env(monkeypatch, tmp_path):
    values = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": IDENTITY_REPOSITORY,
        "GITHUB_REPOSITORY_ID": "123456",
        "GITHUB_WORKFLOW_REF": f"{IDENTITY_REPOSITORY}/.github/workflows/{IDENTITY_WORKFLOW}@refs/heads/main",
        "RESEARCH_PUBLISHER_APP_ID": "5214420",
        "RESEARCH_PUBLISHER_INSTALLATION_ID": "168603414",
        "RESEARCH_PUBLISHER_TOKEN": "synthetic-test-token-never-real",
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def run_identity_python(step_id):
    exec(compile(identity_python(step_id), f"<mocked-{step_id}>", "exec"), {"__name__": "__main__"})


def identity_payload():
    return {"total_count": 1, "repositories": [{"id": 123456, "full_name": IDENTITY_REPOSITORY}]}


def mock_identity_http(monkeypatch, payload=None, *, body=None, status=200, headers=None, error=None):
    calls = []
    raw = body if body is not None else json.dumps(payload or identity_payload()).encode()

    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(raw)
            self.status = status
            self.headers = headers or {}

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert request.full_url == IDENTITY_URL
            assert request.get_method() == "GET"
            assert request.data is None
            assert request.get_header("Authorization") == "Bearer synthetic-test-token-never-real"
            assert timeout == 20
            if error:
                raise error
            return Response()

    def build_opener(handler):
        assert isinstance(handler, urllib.request.HTTPRedirectHandler)
        assert handler.redirect_request(None, None, 302, "", {}, "https://untrusted.example/") is None
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    return calls


def test_identity_only_is_opt_in_and_isolates_all_normal_steps():
    text = identity_workflow().read_text()
    assert "      identity_only:\n" in text
    assert "        default: false\n        type: boolean" in text
    steps = identity_steps()
    identity = [step for step in steps if "        id: publisher_identity_" in step]
    assert len(identity) == 4
    for step in steps:
        if step not in identity:
            assert "if: ${{ !inputs.identity_only }}" in step or "if: ${{ always() && !inputs.identity_only }}" in step
    for step in identity:
        assert "github.event_name == 'workflow_dispatch' && inputs.identity_only" in step
    assert "always()" in identity_step("publisher_identity_summary")
    mint = identity_step("publisher_identity_token")
    assert IDENTITY_ACTION in mint
    assert f"          repositories: {IDENTITY_REPOSITORY.split('/')[1]}\n" in mint
    assert "          owner: QuantStrategyLab\n" in mint
    assert "          permission-contents: write\n" in mint
    assert "          permission-pull-requests: write\n" in mint
    assert mint.count("          permission-") == 2
    assert "skip-token-revoke" not in mint
    assert "CROSS_REPO" not in "".join(identity)
    assert "persist-credentials" not in "".join(identity)
    assert "steps.publisher_identity_token.outputs.token" in identity_step("publisher_identity_verify")


def test_identity_preflight_succeeds_without_network(monkeypatch, tmp_path):
    values = identity_env(monkeypatch, tmp_path)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: pytest.fail("preflight must not use HTTP"))
    run_identity_python("publisher_identity_preflight")
    assert Path(values["GITHUB_OUTPUT"]).read_text() == "app_id_matches=true\n"


@pytest.mark.parametrize(("key", "value"), [
    ("GITHUB_EVENT_NAME", "schedule"),
    ("GITHUB_REF", "refs/heads/unreviewed"),
    ("GITHUB_REPOSITORY", "other/other"),
    ("GITHUB_REPOSITORY_ID", "not-an-id"),
    ("GITHUB_WORKFLOW_REF", "other/other/.github/workflows/test.yml@refs/heads/main"),
    ("RESEARCH_PUBLISHER_APP_ID", "123"),
])
def test_identity_preflight_fails_closed(monkeypatch, tmp_path, capsys, key, value):
    identity_env(monkeypatch, tmp_path)
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: pytest.fail("preflight must not use HTTP"))
    with pytest.raises(SystemExit, match="1"):
        run_identity_python("publisher_identity_preflight")
    assert "PUBLISHER_IDENTITY_PREFLIGHT_FAILED" in capsys.readouterr().out


def test_identity_checks_single_repository_without_writing(monkeypatch, tmp_path, capsys):
    values = identity_env(monkeypatch, tmp_path)
    calls = mock_identity_http(monkeypatch)
    run_identity_python("publisher_identity_verify")
    assert len(calls) == 1
    output = Path(values["GITHUB_OUTPUT"]).read_text()
    assert "installation_matches=true\n" in output
    assert "single_repo_scope_matches=true\n" in output
    assert "identity_verified=true\n" in output
    assert "synthetic-test-token" not in capsys.readouterr().out + output


@pytest.mark.parametrize("mutation", ["extra_repo", "wrong_name", "wrong_id", "bool_id", "bool_count", "wrong_count", "no_repo"])
def test_identity_rejects_wrong_repository_scope(monkeypatch, tmp_path, capsys, mutation):
    values = identity_env(monkeypatch, tmp_path)
    payload = copy.deepcopy(identity_payload())
    if mutation == "extra_repo":
        payload["repositories"].append({"id": 44, "full_name": "other/other"})
    elif mutation == "wrong_name":
        payload["repositories"][0]["full_name"] = "other/other"
    elif mutation == "wrong_id":
        payload["repositories"][0]["id"] = 44
    elif mutation == "bool_id":
        payload["repositories"][0]["id"] = True
    elif mutation == "bool_count":
        payload["total_count"] = True
    elif mutation == "wrong_count":
        payload["total_count"] = 2
    else:
        payload["repositories"] = []
    mock_identity_http(monkeypatch, payload)
    with pytest.raises(SystemExit, match="1"):
        run_identity_python("publisher_identity_verify")
    assert "identity_verified=false" in Path(values["GITHUB_OUTPUT"]).read_text()
    assert "synthetic-test-token" not in capsys.readouterr().out


@pytest.mark.parametrize("kwargs", [
    {"headers": {"Link": '<https://api.github.com/installation/repositories?page=2>; rel="next"'}},
    {"status": 302},
    {"body": b"invalid JSON synthetic-test-token-never-real"},
    {"body": b"x" * (1024 * 1024 + 1)},
    {"error": OSError("sensitive-response synthetic-test-token-never-real")},
])
def test_identity_failures_do_not_leak_responses(monkeypatch, tmp_path, capsys, kwargs):
    values = identity_env(monkeypatch, tmp_path)
    mock_identity_http(monkeypatch, **kwargs)
    with pytest.raises(SystemExit, match="1"):
        run_identity_python("publisher_identity_verify")
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == "PUBLISHER_IDENTITY_VERIFICATION_FAILED\n"
    assert "identity_verified=false" in Path(values["GITHUB_OUTPUT"]).read_text()


@pytest.mark.parametrize(("key", "value"), [("RESEARCH_PUBLISHER_INSTALLATION_ID", "1"), ("RESEARCH_PUBLISHER_TOKEN", "")])
def test_identity_rejects_bad_installation_or_missing_token_before_http(monkeypatch, tmp_path, key, value):
    identity_env(monkeypatch, tmp_path)
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: pytest.fail("HTTP must not run"))
    with pytest.raises(SystemExit, match="1"):
        run_identity_python("publisher_identity_verify")


def test_identity_summary_defaults_to_unpublished_and_unverified(monkeypatch, tmp_path, capsys):
    values = identity_env(monkeypatch, tmp_path)
    for key in ["APP_ID_MATCHES", "INSTALLATION_MATCHES", "SINGLE_REPO_SCOPE_MATCHES", "IDENTITY_VERIFIED"]:
        monkeypatch.delenv(key, raising=False)
    run_identity_python("publisher_identity_summary")
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"app_id_matches": False, "installation_matches": False, "single_repo_scope_matches": False, "identity_verified": False, "published": False}
    assert "synthetic-test-token" not in Path(values["GITHUB_STEP_SUMMARY"]).read_text()
