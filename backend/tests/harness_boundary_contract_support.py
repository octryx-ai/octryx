"""Shared helpers for the test_harness_boundary_contract_* modules."""

from __future__ import annotations

from pathlib import Path

from dependency_gates.harness_boundary import BOUNDARY_PACKAGE, Violation, scan_boundary

BOUNDARY_MODULE = f"{BOUNDARY_PACKAGE}/runtime.py"


OUTSIDE_MODULE = "agent/engine/__init__.py"


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a synthetic source tree and return its root."""
    root = tmp_path / "app"
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def _rules(violations: list[Violation]) -> set[str]:
    return {violation.rule for violation in violations}


def _scan(tmp_path: Path, files: dict[str, str]) -> list[Violation]:
    return scan_boundary(_tree(tmp_path, files))
