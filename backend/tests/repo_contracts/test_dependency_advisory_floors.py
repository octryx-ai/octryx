"""The repository's own dependency contract must satisfy the advisory remediation floors its gates recorded."""

from __future__ import annotations

import tomllib

import pytest

from dependency_gates.manifest import PYPROJECT_PATH, canonical_name, satisfies_floor
from dependency_gates.repository_drift import read_lock_graph

# The floors the repository enforces as invariants (the anyio minimum).
RECORDED_FLOORS = [("anyio", "4.14.2")]


def _declared_floors(section: list[str], distribution: str) -> list[str]:
    floors = []
    for requirement in section:
        head, _, tail = requirement.partition(">=")
        if canonical_name(head.strip()) == canonical_name(distribution) and tail:
            floors.append(tail.split(",")[0].strip())
    return floors


@pytest.mark.parametrize(("distribution", "floor"), RECORDED_FLOORS)
def test_the_lock_satisfies_every_recorded_advisory_remediation_floor(distribution: str, floor: str):
    locked = read_lock_graph().get(canonical_name(distribution))
    assert locked is not None, f"{distribution} carries a recorded advisory floor but is absent from uv.lock"
    assert satisfies_floor(locked.version, floor), (
        f"uv.lock pins {distribution} {locked.version}, below the recorded advisory remediation floor >={floor}"
    )


@pytest.mark.parametrize(("distribution", "floor"), RECORDED_FLOORS)
def test_the_project_declares_every_recorded_advisory_remediation_floor(distribution: str, floor: str):
    project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]
    declared = _declared_floors(project["dependencies"], distribution)
    assert declared, f"{distribution} has a recorded advisory floor >={floor} but no declared project requirement"
    assert all(satisfies_floor(candidate, floor) for candidate in declared), (
        f"pyproject.toml declares {distribution}>={declared} below the recorded advisory floor >={floor}"
    )


@pytest.mark.parametrize(("distribution", "floor"), RECORDED_FLOORS)
def test_no_dependency_group_undercuts_a_recorded_advisory_floor(distribution: str, floor: str):
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    sections = list((pyproject.get("dependency-groups") or {}).items())
    sections += list((pyproject["project"].get("optional-dependencies") or {}).items())
    for name, requirements in sections:
        for candidate in _declared_floors(requirements, distribution):
            assert satisfies_floor(candidate, floor), (
                f"dependency group {name} declares {distribution}>={candidate}, below the recorded floor >={floor}"
            )
