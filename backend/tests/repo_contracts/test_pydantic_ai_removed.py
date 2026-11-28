"""Pydantic AI is removed (the pinned release carried CVE-2026-107286 and CVE-2026-107287); these checks keep it out,
offline: backend/.venv/bin/python -m pytest backend/tests/repo_contracts/test_pydantic_ai_removed.py -q --noconftest"""

from __future__ import annotations

import tomllib
from pathlib import Path

from dependency_gates.manifest import PYPROJECT_PATH, canonical_name
from dependency_gates.repository_drift import read_lock_graph

REMOVED = "pydantic-ai-slim"
APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def test_the_distribution_is_neither_declared_nor_locked():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    requirements = list(pyproject["project"]["dependencies"])
    for section in (pyproject["project"].get("optional-dependencies") or {}).values():
        requirements += section
    for section in (pyproject.get("dependency-groups") or {}).values():
        requirements += [item for item in section if isinstance(item, str)]
    declared = {canonical_name(requirement.split(";")[0].split("[")[0].split("=")[0].split(">")[0].split("<")[0]
                               .strip()) for requirement in requirements}
    assert REMOVED not in declared, "pydantic-ai-slim is declared again: that needs a new adoption gate"
    assert canonical_name(REMOVED) not in read_lock_graph(), "pydantic-ai-slim entered uv.lock again"


def test_no_application_module_imports_the_framework():
    offenders = [str(path.relative_to(APP_ROOT)) for path in APP_ROOT.rglob("*.py")
                 if "import pydantic_ai" in (text := path.read_text(encoding="utf-8"))
                 or "from pydantic_ai" in text]
    assert offenders == []
