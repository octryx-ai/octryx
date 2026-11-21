"""Compare recorded adoption-gate evidence against the repository state it was evaluated against.

Offline only: this module reads ``backend/pyproject.toml`` and ``backend/uv.lock`` and never resolves dependencies.

Two rules define what this checker may fail on.

**Scope.** A gate judges the dependency closure it gated, not the whole repository. An excluded distribution or a
closure member that is present in ``backend/uv.lock`` for an unrelated reason — a different root dependency, another
extra, a development group — is outside this gate's evidence and is not a gate finding. ``fastembed`` legitimately
brings ``huggingface-hub``; ``opentelemetry-api`` may arrive through unrelated instrumentation work. What the gate does
judge is the set of distributions reachable from the gated distribution in the lock's own dependency graph. While the
gate is unapproved that set is empty, so the only thing the exclusion policy can fail on is a closure that actually
entered the lock through the gated distribution.

**Versions.** ``lock_version_at_gate`` is evidence of the state the gate was evaluated against, not a pin. A later
patch or minor release of a dependency the repository already owns — a security upgrade such as ``anyio`` 4.12.1 ->
4.14.2 — must not fail the gate. Drift is a regression below the recorded version, a major-version change that
invalidates the recorded closure evidence, a violated recorded compatibility floor, or, once the gate is approved, a
violated advisory remediation floor.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .manifest import (
    PYPROJECT_PATH,
    UV_LOCK_PATH,
    GateDriftError,
    GateManifest,
    canonical_name,
    satisfies_floor,
)


@dataclass(frozen=True, slots=True)
class LockedPackage:
    """One ``[[package]]`` entry of a uv lock, reduced to what a closure check needs."""

    version: str
    dependencies: frozenset[str]


def read_lock_graph(lock_path: Path = UV_LOCK_PATH) -> dict[str, LockedPackage]:
    """Return the locked dependency graph keyed by canonical name.

    Required dependencies and recorded optional-dependency edges are both edges: a uv lock records an extra's
    requirements only when the resolution actually selected that extra.
    """
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    graph: dict[str, LockedPackage] = {}
    for package in lock.get("package", []):
        name, version = package.get("name"), package.get("version")
        if not name or not version:
            continue
        edges: set[str] = set()
        edge_lists: list[list[dict[str, object]]] = [package.get("dependencies") or []]
        edge_lists.extend((package.get("optional-dependencies") or {}).values())
        for edge_list in edge_lists:
            for edge in edge_list or []:
                if edge.get("name"):
                    edges.add(canonical_name(str(edge["name"])))
        graph[canonical_name(name)] = LockedPackage(version=version, dependencies=frozenset(edges))
    return graph


def reachable_closure(graph: dict[str, LockedPackage], roots: list[str]) -> set[str]:
    """Return the canonical names reachable from ``roots`` in ``graph``, including the roots that exist in it."""
    pending = [canonical_name(root) for root in roots if canonical_name(root) in graph]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(name for name in graph[current].dependencies if name in graph and name not in seen)
    return seen


def declared_dependency_names(pyproject_path: Path = PYPROJECT_PATH) -> set[str]:
    """Return every distribution name declared in project dependencies, extras or dependency groups."""
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    requirements: list[str] = list(project.get("project", {}).get("dependencies", []))
    for extra in project.get("project", {}).get("optional-dependencies", {}).values():
        requirements.extend(extra)
    for group in project.get("dependency-groups", {}).values():
        requirements.extend(group)
    names = set()
    for requirement in requirements:
        head = requirement.split(";")[0].strip()
        for separator in ("[", "=", ">", "<", "!", "~", " "):
            head = head.split(separator)[0]
        if head:
            names.add(canonical_name(head.strip()))
    return names


def _major(version: str) -> int:
    head = version.split(".")[0]
    digits = "".join(character for character in head if character.isdigit())
    return int(digits) if digits else 0


def _version_problems(name: str, recorded: str, actual: str | None) -> list[str]:
    if actual is None:
        return [f"{name} was locked at {recorded} when the gate ran but is absent from uv.lock"]
    if not satisfies_floor(actual, recorded):
        return [
            f"{name} regressed below the state the gate was evaluated against: gate evidence recorded {recorded}, "
            f"lock now has {actual}"
        ]
    if _major(actual) != _major(recorded):
        return [
            f"{name} changed major version since the gate ran: gate evidence recorded {recorded}, lock now has "
            f"{actual}; the recorded closure evidence no longer applies"
        ]
    return []


def check_manifest_against_repository(
    manifest: GateManifest,
    *,
    lock_path: Path = UV_LOCK_PATH,
    pyproject_path: Path = PYPROJECT_PATH,
) -> None:
    """Fail when the repository has moved away from what this gate's recorded evidence still covers."""
    graph = read_lock_graph(lock_path)
    locked = {name: package.version for name, package in graph.items()}
    declared = declared_dependency_names(pyproject_path)
    gated = canonical_name(manifest.distribution)
    gated_closure = reachable_closure(graph, [gated])
    problems: list[str] = []

    if not manifest.approved_for_installation:
        if gated in declared:
            problems.append(
                f"{manifest.distribution} is declared in pyproject.toml although the adoption gate is not approved"
            )
        if gated in locked:
            problems.append(
                f"{manifest.distribution} is present in uv.lock at {locked[gated]} although the adoption gate is "
                f"not approved"
            )
        for entry in manifest.closure:
            key = canonical_name(entry["name"])
            if entry["origin"] == "introduced" and key != gated and key in gated_closure:
                problems.append(
                    f"{entry['name']} entered uv.lock through the unapproved {manifest.distribution} closure"
                )

    for entry in manifest.closure:
        recorded = entry.get("lock_version_at_gate")
        if recorded is None:
            continue
        problems.extend(_version_problems(entry["name"], recorded, locked.get(canonical_name(entry["name"]))))

    for name, floor in sorted(manifest.compatibility_floors.items()):
        actual = locked.get(canonical_name(name))
        if actual is None:
            problems.append(f"compatibility floor {name}>={floor} cannot be checked: {name} is absent from uv.lock")
        elif not satisfies_floor(actual, floor):
            problems.append(f"{name} {actual} in uv.lock no longer satisfies the recorded floor >={floor}")

    problems.extend(_advisory_floor_problems(manifest, locked))

    for name in manifest.excluded_distributions:
        key = canonical_name(name)
        if key in gated_closure:
            problems.append(
                f"excluded distribution {name} is present in uv.lock at {locked[key]} inside the "
                f"{manifest.distribution} dependency closure"
            )

    if problems:
        raise GateDriftError(
            f"{manifest.path.name}: gate evidence no longer covers the repository state, re-run the gate:\n  - "
            + "\n  - ".join(problems)
        )


def _advisory_floor_problems(manifest: GateManifest, locked: dict[str, str]) -> list[str]:
    """Advisory remediation floors are approval preconditions, enforced once the gate claims approval.

    While the gate is blocked the recorded findings are the evidence for the advisory blocker, and the unremediated
    version legitimately stays in the lock as a separately tracked pre-existing defect.
    """
    if not manifest.approved_for_installation:
        return []
    problems: list[str] = []
    for name, decision in sorted(manifest.advisory_remediation.items()):
        if not decision.get("required_before_approval"):
            continue
        floor = decision["enforced_floor"]
        advisories = ", ".join(decision.get("advisories") or [])
        actual = locked.get(canonical_name(name))
        if actual is None:
            problems.append(
                f"advisory remediation floor {name}>={floor} cannot be checked: {name} is absent from uv.lock"
            )
        elif not satisfies_floor(actual, floor):
            problems.append(
                f"{name} {actual} in uv.lock is below the advisory remediation floor >={floor} that approval of this "
                f"gate requires ({advisories})"
            )
    return problems
