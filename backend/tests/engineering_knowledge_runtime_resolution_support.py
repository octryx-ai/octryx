"""Shared helpers for the test_engineering_knowledge_runtime_resolution_* modules."""

from __future__ import annotations

from app.services.engineering_knowledge._runtime_types import EngineeringUpgradeTarget


def _java_spring(spring_boot: str) -> EngineeringUpgradeTarget:
    return EngineeringUpgradeTarget(stack_key="java-spring", target_versions={"java": "25", "spring_boot": spring_boot})


def _selected_profile_metadata(profile_key: str) -> dict:
    return {"workflow_routing_policy_resolution": {"workflow_contract": {"upgrade_profile": profile_key}}}


def _write_spring_pom(repo_root) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pom.xml").write_text(
        """
<project>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.4.12</version>
  </parent>
  <properties>
    <java.version>21</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>
""".strip(),
        encoding="utf-8",
    )
