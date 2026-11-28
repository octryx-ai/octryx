"""Repository-root helper shared by the package layout tests."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    # backend/tests -> repo_root/backend
    return Path(__file__).resolve().parents[2]
