"""Prepare generated research data for protected-branch publication.

Scheduled workflows must not push generated data directly to ``main``.  This
repository-local adapter can create an auditable patch and HUMAN_REQUIRED
receipt without mutating the repository or remote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path


class PublishError(RuntimeError):
    """Raised when a generated-data PR cannot be created safely."""


def run(command: Sequence[str], *, capture: bool = False, strip: bool = True) -> str:
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
    output = completed.stdout or ""
    return output.strip() if strip else output


def staged_changes_present() -> bool:
    return subprocess.run(["git", "diff", "--cached", "--quiet"], check=False).returncode != 0


def write_handoff(handoff_dir: Path, branch: str, title: str) -> None:
    handoff_dir.mkdir(parents=True, exist_ok=True)
    patch_path = handoff_dir / "generated-live-output.patch"
    patch = run(
        ["git", "diff", "--binary", "--full-index", "--cached"],
        capture=True,
        strip=False,
    )
    patch_path.write_text(patch, encoding="utf-8")
    staged_paths = run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture=True,
    ).splitlines()
    receipt = {
        "schema_version": 1,
        "status": "HUMAN_REQUIRED",
        "reason_code": "PR_CREATION_IDENTITY_UNAVAILABLE",
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "source_sha": os.environ.get("GITHUB_SHA", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "target_branch": "main",
        "proposed_branch": branch,
        "title": title,
        "staged_paths": staged_paths,
        "patch_path": patch_path.name,
        "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        "next_action": "A maintainer must review and apply the patch through the protected branch process.",
    }
    (handoff_dir / "publication-handoff.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def publish(
    branch: str,
    title: str,
    body: str,
    commit_message: str,
    *,
    handoff_dir: Path | None = None,
) -> str:
    if handoff_dir is None:
        raise PublishError("--handoff-dir is required; remote publication is disabled")

    if not staged_changes_present():
        return "No generated data changes to publish."

    write_handoff(handoff_dir, branch, title)
    return "HUMAN_REQUIRED: generated publication handoff artifact."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--commit-message", required=True)
    parser.add_argument("--handoff-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        publish(
            args.branch,
            args.title,
            args.body,
            args.commit_message,
            handoff_dir=args.handoff_dir,
        )
    )


if __name__ == "__main__":
    main()
