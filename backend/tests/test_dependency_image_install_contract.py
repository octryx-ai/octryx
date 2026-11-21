"""The image must install the locked closure and resolve nothing -- not even its own build backend.

`pip install .` alone is a fresh unlocked resolution of the pyproject ranges that ignores
`backend/uv.lock`, so two builds of one commit could differ in every Python package. The fix
is a locked export installed with `pip install --require-hashes`, which pins every artifact by digest and implies
`--no-deps`.

That leaves one resolution the hashes do not cover: PEP 517 build isolation. `pip install .` builds the project in a
throwaway environment that pip populates by resolving `[build-system].requires` from PyPI on every build -- unpinned,
unhashed, outside the lock and outside the audit. So the build backend is locked as a `build` dependency group,
exported with hashes like everything else, installed first, and the project install runs `--no-build-isolation`.

These tests read the `Dockerfile` and `backend/pyproject.toml` as text. They assert the shape of the install, which is
what a reviewer cannot see from a green build: a build that resolves freshly still succeeds, it just succeeds
differently every time. The mechanism itself (wrong digest, missing digest, stale lock) is proven by the recorded
container runs, not here, because it needs a container engine.

Offline, without the application fixtures:

    backend/.venv/bin/python -m pytest backend/tests/test_dependency_image_install_contract.py -q --noconftest
"""

from __future__ import annotations

import re
import tomllib

import pytest

from dependency_gates.manifest import BACKEND_ROOT, PYPROJECT_PATH, canonical_name

DOCKERFILE_PATH = BACKEND_ROOT.parent / "Dockerfile"

BUILD_GROUP = "build"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _pip_install_commands(dockerfile: str) -> list[str]:
    """Return every `pip install ...` invocation, with shell line continuations joined."""
    joined = re.sub(r"\\\s*\n\s*", " ", dockerfile)
    return [re.sub(r"\s+", " ", line).strip() for line in re.findall(r"pip install [^\n&|]+", joined)]


# --- the locked closure is the only source of third-party artifacts -----------------------------------------------


def test_the_dockerfile_exports_the_locked_runtime_and_build_sets(dockerfile: str):
    for flags in (
        # The runtime closure plus the in-process embedding option.
        "uv export --locked --format requirements-txt --no-dev --extra knowledge --no-emit-project",
        f"uv export --locked --format requirements-txt --only-group {BUILD_GROUP} --no-emit-project",
    ):
        assert flags in re.sub(r"\\\s*\n\s*", " ", dockerfile), f"the image no longer exports with: {flags}"


def test_every_requirements_install_requires_hashes(dockerfile: str):
    """Without --require-hashes pip resolves, and an unpinned transitive package reaches the image."""
    from_file = [command for command in _pip_install_commands(dockerfile) if " -r " in command]
    assert from_file, "no requirements-file install found in the Dockerfile"
    unpinned = [command for command in from_file if "--require-hashes" not in command]
    assert not unpinned, f"requirements installed without --require-hashes: {unpinned}"


def test_the_project_install_neither_resolves_dependencies_nor_a_build_backend(dockerfile: str):
    """Unlocked `pip install .` is the defect; `--no-deps` alone still leaves build isolation resolving from PyPI."""
    project_installs = [
        command for command in _pip_install_commands(dockerfile) if re.search(r"(?:^|\s)\.\s*$", command)
    ]
    assert project_installs, "the Dockerfile no longer installs the project itself"
    for command in project_installs:
        assert "--no-deps" in command, f"project install resolves dependencies: {command}"
        assert "--no-build-isolation" in command, f"project install resolves a build backend from PyPI: {command}"


def test_uv_is_installed_only_in_the_export_stage(dockerfile: str):
    """uv must not reach a shipped image; the export stage is discarded."""
    stages = re.split(r"^FROM ", dockerfile, flags=re.MULTILINE)
    with_uv = [stage.split("\n", 1)[0].strip() for stage in stages if re.search(r'pip install[^\n]*"?uv==', stage)]
    assert with_uv == ["--platform=$BUILDPLATFORM python:3.12-slim AS python-deps"], with_uv


def test_the_export_stage_pins_the_uv_version(dockerfile: str):
    assert re.search(r"^ARG UV_VERSION=\d+\.\d+\.\d+$", dockerfile, flags=re.MULTILINE), (
        "UV_VERSION must be pinned so two builds of one commit export the same requirement set"
    )


# --- the build group is the [build-system] backend, and only that ---------------------------------------------------


def test_the_build_group_matches_the_declared_build_backend(pyproject: dict):
    """A build group that does not cover [build-system].requires would make --no-build-isolation fail or drift."""
    required = {canonical_name(item.split(">=")[0].strip()) for item in pyproject["build-system"]["requires"]}
    group = pyproject["dependency-groups"][BUILD_GROUP]
    assert {canonical_name(item.split(">=")[0].strip()) for item in group} == required


@pytest.mark.parametrize("requirement_source", ["build-system", "dependency-group"])
def test_the_build_backend_floor_provides_bdist_wheel_itself(pyproject: dict, requirement_source: str):
    """Below setuptools 70.1 the wheel build needs the separate `wheel` distribution, which the group does not carry."""
    requirements = (
        pyproject["build-system"]["requires"]
        if requirement_source == "build-system"
        else pyproject["dependency-groups"][BUILD_GROUP]
    )
    floors = [item.split(">=")[1].strip() for item in requirements if item.startswith("setuptools>=")]
    assert floors, f"{requirement_source} declares no setuptools floor"
    for floor in floors:
        major, minor = (int(part) for part in floor.split(".")[:2])
        assert (major, minor) >= (70, 1), f"setuptools>={floor} is below the bdist_wheel-in-setuptools floor"


def test_the_build_group_is_not_installed_by_a_plain_sync(pyproject: dict):
    """It is a build-time set: a developer venv that carries it would disagree with the image for no benefit."""
    default_groups = (pyproject.get("tool", {}).get("uv") or {}).get("default-groups")
    if default_groups is not None:
        assert BUILD_GROUP not in default_groups, "the build group must stay opt-in via --only-group/--group"


def test_the_runtime_closure_does_not_declare_the_build_backend(pyproject: dict):
    """setuptools belongs to the build, not to the served closure; declaring it would ship it to every image path."""
    declared = {canonical_name(item.split(">=")[0].strip()) for item in pyproject["project"]["dependencies"]}
    assert "setuptools" not in declared
