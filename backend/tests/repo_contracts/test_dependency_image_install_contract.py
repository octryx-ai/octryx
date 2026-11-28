"""The image must install the locked closure and resolve nothing -- not even its own build backend."""

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
    joined = re.sub(r"\\\s*\n\s*", " ", dockerfile)
    return [re.sub(r"\s+", " ", line).strip() for line in re.findall(r"pip install [^\n&|]+", joined)]


def test_the_dockerfile_exports_the_locked_runtime_and_build_sets(dockerfile: str):
    for flags in (
        # The runtime closure plus the in-process embedding option.
        "uv export --locked --format requirements-txt --no-dev --extra knowledge --no-emit-project",
        f"uv export --locked --format requirements-txt --only-group {BUILD_GROUP} --no-emit-project",
    ):
        assert flags in re.sub(r"\\\s*\n\s*", " ", dockerfile), f"the image no longer exports with: {flags}"


def test_every_requirements_install_requires_hashes(dockerfile: str):
    from_file = [command for command in _pip_install_commands(dockerfile) if " -r " in command]
    assert from_file, "no requirements-file install found in the Dockerfile"
    unpinned = [command for command in from_file if "--require-hashes" not in command]
    assert not unpinned, f"requirements installed without --require-hashes: {unpinned}"


def test_the_project_install_neither_resolves_dependencies_nor_a_build_backend(dockerfile: str):
    project_installs = [
        command for command in _pip_install_commands(dockerfile) if re.search(r"(?:^|\s)\.\s*$", command)
    ]
    assert project_installs, "the Dockerfile no longer installs the project itself"
    for command in project_installs:
        assert "--no-deps" in command, f"project install resolves dependencies: {command}"
        assert "--no-build-isolation" in command, f"project install resolves a build backend from PyPI: {command}"


def test_uv_is_installed_only_in_the_export_stage(dockerfile: str):
    stages = re.split(r"^FROM ", dockerfile, flags=re.MULTILINE)
    with_uv = [stage.split("\n", 1)[0].strip() for stage in stages if re.search(r'pip install[^\n]*"?uv==', stage)]
    assert with_uv == ["--platform=$BUILDPLATFORM python:3.12-slim AS python-deps"], with_uv


def test_the_export_stage_pins_the_uv_version(dockerfile: str):
    assert re.search(r"^ARG UV_VERSION=\d+\.\d+\.\d+$", dockerfile, flags=re.MULTILINE), (
        "UV_VERSION must be pinned so two builds of one commit export the same requirement set"
    )


def test_the_build_group_matches_the_declared_build_backend(pyproject: dict):
    required = {canonical_name(item.split(">=")[0].strip()) for item in pyproject["build-system"]["requires"]}
    group = pyproject["dependency-groups"][BUILD_GROUP]
    assert {canonical_name(item.split(">=")[0].strip()) for item in group} == required


@pytest.mark.parametrize("requirement_source", ["build-system", "dependency-group"])
def test_the_build_backend_floor_provides_bdist_wheel_itself(pyproject: dict, requirement_source: str):
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
    default_groups = (pyproject.get("tool", {}).get("uv") or {}).get("default-groups")
    if default_groups is not None:
        assert BUILD_GROUP not in default_groups, "the build group must stay opt-in via --only-group/--group"


def test_the_runtime_closure_does_not_declare_the_build_backend(pyproject: dict):
    declared = {canonical_name(item.split(">=")[0].strip()) for item in pyproject["project"]["dependencies"]}
    assert "setuptools" not in declared
