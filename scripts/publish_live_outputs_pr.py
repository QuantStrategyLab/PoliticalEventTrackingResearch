#!/usr/bin/env python3
"""Publish generated research data through a protected-branch pull request.

Scheduled workflows must not push generated data directly to ``main``.  This
small, repository-local adapter commits only the paths staged by its caller to
an automation branch and creates (or reuses) a pull request for the normal CI
and branch-protection path.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence


class PublishError(RuntimeError):
    """Raised when a generated-data PR cannot be created safely."""


def run(command: Sequence[str], *, capture: bool = False) -> str:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise PublishError(f"{' '.join(command)}: {detail}")
    return (completed.stdout or "").strip()


def staged_changes_present() -> bool:
    return subprocess.run(["git", "diff", "--cached", "--quiet"], check=False).returncode != 0


def existing_pull_request(branch: str) -> str:
    return run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            os.environ["GITHUB_REPOSITORY"],
            "--state",
            "open",
            "--head",
            branch,
            "--json",
            "url",
            "--jq",
            ".[0].url // \"\"",
        ],
        capture=True,
    )


def publish(branch: str, title: str, body: str, commit_message: str) -> str:
    if not staged_changes_present():
        return "No generated data changes to publish."

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "switch", "-C", branch])
    run(["git", "commit", "-m", commit_message])
    run(["git", "push", "--force-with-lease", "origin", f"HEAD:refs/heads/{branch}"])

    existing_url = existing_pull_request(branch)
    if existing_url:
        return f"Updated generated-data PR: {existing_url}"

    url = run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            os.environ["GITHUB_REPOSITORY"],
            "--head",
            branch,
            "--base",
            "main",
            "--title",
            title,
            "--body",
            body,
        ],
        capture=True,
    )
    return f"Created generated-data PR: {url}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--commit-message", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(publish(args.branch, args.title, args.body, args.commit_message))


if __name__ == "__main__":
    main()
