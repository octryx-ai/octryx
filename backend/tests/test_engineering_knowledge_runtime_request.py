"""Runtime requests, upgrade targets, module POM detection and the runtime prompt for delegated coding children."""

from __future__ import annotations

import pytest

from app.services.engineering_knowledge import build_engineering_runtime_request, resolve_engineering_runtime_context
from app.services.engineering_knowledge._runtime_types import EngineeringUpgradeTarget
from app.services.engineering_knowledge.runtime_prompt_renderer import resolve_engineering_knowledge_runtime_prompt
from app.services.engineering_knowledge.runtime_target import upgrade_target_from_request
from tests.engineering_knowledge_runtime_resolution_support import _java_spring, _write_spring_pom


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


@pytest.mark.asyncio
async def test_runtime_prompt_reuses_parent_resolution_for_delegated_coding_children(db, tmp_path):
    repo_root = tmp_path / "spring-petclinic-rest-openrewrite-lab"
    _write_spring_pom(repo_root)
    parent_resolution = {
        "schema_version": 1,
        "prompt_contract": {
            "intent": "coding_migration",
            "stack_key": "java-spring",
            "source_versions": {"java": "21", "spring_boot": "3.4.x"},
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
        },
        "repository": {
            "id": "repo-1",
            "name": "spring-petclinic-rest",
            "repo_root": str(repo_root),
            "match_reason": "parent resolved repository",
        },
        "engineering_knowledge_pack": {
            "pack_key": "java-21-to-25-spring-boot-3.4-to-4.0.3",
            "version_id": "version-1",
            "quality_status": "passed",
        },
        "retrieval": {"source_ids": [], "freshness_status": {}},
        "items": [],
        "blockers": [],
        "clarification_questions": [],
    }

    prompt, metadata = await resolve_engineering_knowledge_runtime_prompt(
        db=db,
        project_id=None,
        session_metadata={"parent_engineering_knowledge_runtime_resolution": parent_resolution},
    )

    assert metadata == parent_resolution
    assert "Intent: coding_migration" in prompt
    assert "Repository: spring-petclinic-rest" in prompt
    assert "build_engineering_knowledge_pack" not in prompt
