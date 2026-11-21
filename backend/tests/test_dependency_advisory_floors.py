"""The repository's own dependency contract must satisfy the advisory remediation floors its gates recorded.

`dependency_gates.repository_drift` deliberately enforces a recorded advisory floor only once a gate claims approval:
while a gate is blocked, an unremediated pre-existing finding legitimately stays in the lock as separately tracked
repository state. The `anyio` finding of a gate (CVE-2026-63374 CRITICAL, CVE-2026-64847, fixed in 4.14.2) is
remediated, so for the repository the floor is no longer a future approval precondition but a current invariant,
and nothing in the gate machinery would notice a regression below it while that gate stays blocked.

These tests are that guard, and they are generic over the recorded findings: any future gate that records an advisory
remediation floor the repository has acted on is covered without a new test. A floor that is knowingly *not* met yet
has to be recorded as a waiver in the gate manifest, which the gate's own consistency check already forces to carry a
rationale.

Both files are checked, because they answer different questions. `backend/uv.lock` says which version is installed:
every install path reads it — the image build, CI, and `dev-setup.sh`. `backend/pyproject.toml` says
which versions a resolver is *allowed* to pick, and it is the only thing that still binds when the lock is refreshed:
a floor recorded only in the lock would be silently undone by the next `uv lock`.

Run offline, without the backend application fixtures (see the gate test modules for why `--noconftest` is scope, not
a workaround):

    backend/.venv/bin/python -m pytest backend/tests/test_dependency_advisory_floors.py -q --noconftest
"""

from __future__ import annotations

import tomllib

import pytest

from dependency_gates.manifest import PYPROJECT_PATH, canonical_name, satisfies_floor
from dependency_gates.repository_drift import read_lock_graph

# The floors the repository enforces as invariants (the anyio minimum).
RECORDED_FLOORS = [("anyio", "4.14.2")]


def _declared_floors(section: list[str], distribution: str) -> list[str]:
    """Return the `>=` floors declared for ``distribution`` in one requirement list of `backend/pyproject.toml`."""
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
    """A lock-only floor would not reach the pip-based image build, which installs from pyproject alone."""
    project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]
    declared = _declared_floors(project["dependencies"], distribution)
    assert declared, f"{distribution} has a recorded advisory floor >={floor} but no declared project requirement"
    assert all(satisfies_floor(candidate, floor) for candidate in declared), (
        f"pyproject.toml declares {distribution}>={declared} below the recorded advisory floor >={floor}"
    )


@pytest.mark.parametrize(("distribution", "floor"), RECORDED_FLOORS)
def test_no_dependency_group_undercuts_a_recorded_advisory_floor(distribution: str, floor: str):
    """A development group floor below the remediation floor would let a group-only resolution pick a fixed-below release."""
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    sections = list((pyproject.get("dependency-groups") or {}).items())
    sections += list((pyproject["project"].get("optional-dependencies") or {}).items())
    for name, requirements in sections:
        for candidate in _declared_floors(requirements, distribution):
            assert satisfies_floor(candidate, floor), (
                f"dependency group {name} declares {distribution}>={candidate}, below the recorded floor >={floor}"
            )
