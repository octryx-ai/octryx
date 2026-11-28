"""Runtime requests, upgrade targets, module POM detection and the runtime prompt for delegated coding children."""

from __future__ import annotations

import pytest

from app.services.engineering_knowledge import build_engineering_runtime_request, resolve_engineering_runtime_context
from app.services.engineering_knowledge._runtime_types import EngineeringUpgradeTarget
from app.services.engineering_knowledge.runtime_target import upgrade_target_from_request
from tests.services.engineering_knowledge.engineering_knowledge_runtime_resolution_support import (
    _java_spring,
)


def _write_module_spring_pom(repo_root) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pom.xml").write_text(
        """
<project>
  <packaging>pom</packaging>
  <modules>
    <module>app</module>
  </modules>
</project>
""".strip(),
        encoding="utf-8",
    )
    module_root = repo_root / "app"
    module_root.mkdir()
    (module_root / "pom.xml").write_text(
        """
<project>
  <properties>
    <java.version>21</java.version>
    <spring-boot.version>3.4.12</spring-boot.version>
  </properties>
</project>
""".strip(),
        encoding="utf-8",
    )


def test_runtime_request_without_a_target_is_not_specified():
    # The builder has no prompt parameter; only an explicit target makes a migration request.
    request = build_engineering_runtime_request()

    assert request.intent == "general"
    assert request.target_source == "not_specified"
    assert request.target_versions == {} and request.source_versions == {}
    assert request.blockers == []


def test_runtime_request_takes_the_explicit_target():
    request = build_engineering_runtime_request(
        target=EngineeringUpgradeTarget(
            stack_key="python", target_versions={"python": "3.12"}, source_versions={"python": "3.11"}
        ),
    )

    assert request.intent == "coding_migration"
    assert request.stack_key == "python"
    assert request.source_versions == {"python": "3.11"}
    assert request.target_versions == {"python": "3.12"}
    assert request.target_source == "request"
    assert request.blockers == []

    missing = build_engineering_runtime_request(target=EngineeringUpgradeTarget(stack_key="java", target_versions={}))
    assert [blocker["code"] for blocker in missing.blockers] == ["missing_target_versions"]


def test_upgrade_target_comes_only_from_structured_fields():
    assert upgrade_target_from_request({"prompt": "Java 25"}) is None
    assert upgrade_target_from_request({"stack_key": "java", "target_versions": {"java": 25}}).target_versions == {
        "java": "25"
    }


@pytest.mark.asyncio
async def test_runtime_repository_detection_reads_module_poms_and_spring_boot_property(db, tmp_path):
    external_root = tmp_path / "externalrepos"
    repo_root = external_root / "acme-orders-access-proxy"
    _write_module_spring_pom(repo_root)

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.99"),
        local_search_roots=[str(external_root)],
    )

    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.detected_stack_key == "java-spring"
    assert resolution.request.source_versions == {"java": "21", "spring_boot": "3.4.12"}


