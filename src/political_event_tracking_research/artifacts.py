from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_row_count(path: str | Path) -> int:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def build_live_manifest(paths: list[str | Path], *, base_dir: str | Path | None = None) -> dict[str, Any]:
    base = Path(base_dir).resolve() if base_dir else None
    artifacts: dict[str, Any] = {}
    for raw_path in paths:
        path = Path(raw_path)
        key = path.name
        display_path = str(path)
        if base:
            try:
                display_path = str(path.resolve().relative_to(base))
            except ValueError:
                display_path = str(path)
        artifacts[key] = {
            "path": display_path,
            "sha256": sha256_file(path),
            "row_count": csv_row_count(path) if path.suffix.lower() == ".csv" else None,
        }
    return {
        "manifest_type": "political_event_live_outputs",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def write_live_manifest(paths: list[str | Path], output_path: str | Path, *, base_dir: str | Path | None = None) -> Path:
    payload = build_live_manifest(paths, base_dir=base_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
