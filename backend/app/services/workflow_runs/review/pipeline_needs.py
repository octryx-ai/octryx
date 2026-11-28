"""What the run's pipeline needs, for the independent reviewer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_CHARS = 6000

PIPELINE_NEEDS_RULE = (
    "The pipeline ran the declared commands of the environment file listed in the task. Its setup, checks, path, "
    "browser and serve entries are what those commands need (a virtual environment, a browser for the system tests, "
    "a package cache): they are the run's environment, not scope. Never ask to remove or narrow them; a finding on "
    "them names a concrete defect (wrong, unsafe or failing), not that they exceed the story.")


def declared(run: Any, root: Path | None) -> str:
    pipeline = dict(dict(run.context or {}).get("pipeline") or {})
    audit = dict(pipeline.get("audit") or {})
    if audit.get("source") != "environment_file" or not audit.get("file"):
        return ""
    lines = [f"environment file: {audit['file']} (app folder {audit.get('app_folder') or '.'})",
             "declared commands the pipeline ran:", *[f"- {command}" for command in audit.get("commands") or []]]
    path = (root / str(audit["file"])) if root is not None else None
    if path is not None and path.resolve().is_relative_to(root.resolve()) and path.is_file():
        try:
            content = json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=1)
        except (OSError, ValueError):
            content = ""
        if content:
            lines += ["the file:", content]
    return "\n".join(lines)[:MAX_CHARS]


__all__ = ["PIPELINE_NEEDS_RULE", "declared"]
