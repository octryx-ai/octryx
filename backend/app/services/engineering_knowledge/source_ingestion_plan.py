"""Source acquisition plan: which official and vendor sources a pack needs for its target versions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .source_ingestion_specs import EngineeringKnowledgeSourceSpec


def _source_key(prefix: str, version: str, suffix: str) -> str:
    normalized_version = str(version or "").strip().replace(".", "-").lower()
    return f"{prefix}-{normalized_version}-{suffix}".strip("-")


def _target_source(
    coordinate: str,
    version: str,
    *,
    source_key: str,
    title: str,
    source_uri: str,
    source_type: str,
    trust_tier: str = "official",
) -> dict[str, Any]:
    return asdict(
        EngineeringKnowledgeSourceSpec(
            source_key=source_key,
            title=title,
            source_uri=source_uri,
            source_type=source_type,
            trust_tier=trust_tier,
            version_label=version,
            metadata={"coordinate": coordinate, "target_version": version},
        )
    )


def _java_sources(java_target: str) -> list[dict[str, Any]]:
    docs_base = f"https://docs.oracle.com/en/java/javase/{java_target}"
    return [
        _target_source(
            "java",
            java_target,
            source_key=_source_key("openjdk-jdk", java_target, "project"),
            title=f"OpenJDK JDK {java_target} — Features and JEPs",
            source_uri=f"https://openjdk.org/projects/jdk/{java_target}/",
            source_type="release_notes",
        ),
        _target_source(
            "java",
            java_target,
            source_key=_source_key("oracle-java", java_target, "api"),
            title=f"Oracle Java {java_target} API Documentation",
            source_uri=f"{docs_base}/docs/api/",
            source_type="documentation",
        ),
        _target_source(
            "java",
            java_target,
            source_key=_source_key("oracle-java", java_target, "release-notes"),
            title=f"Oracle JDK {java_target} Release Notes",
            source_uri=f"https://www.oracle.com/java/technologies/javase/{java_target}all-relnotes.html",
            source_type="release_notes",
        ),
        *_java_migration_sources(java_target, docs_base),
    ]


def _java_migration_sources(java_target: str, docs_base: str) -> list[dict[str, Any]]:
    guides = [
        ("migration-preparing", "Preparing for Migration", "preparing-migration.html"),
        ("removed-apis", "Removed APIs", "removed-apis.html"),
        ("removed-tools", "Removed Tools and Components", "removed-tools-and-components.html"),
    ]
    return [
        _target_source(
            "java",
            java_target,
            source_key=_source_key("oracle-java", java_target, suffix),
            title=f"Oracle JDK {java_target} Migration Guide — {topic}",
            source_uri=f"{docs_base}/migrate/{page}",
            source_type="migration_guide",
        )
        for suffix, topic, page in guides
    ]


def _spring_boot_sources(boot_target: str) -> list[dict[str, Any]]:
    boot_base = f"https://docs.spring.io/spring-boot/{boot_target}"
    return [
        _target_source(
            "spring_boot",
            boot_target,
            source_key=_source_key("spring-boot", boot_target, "reference"),
            title=f"Spring Boot {boot_target} Reference Documentation",
            source_uri=f"{boot_base}/reference/index.html",
            source_type="documentation",
        ),
        _target_source(
            "spring_boot",
            boot_target,
            source_key=_source_key("spring-boot", boot_target, "dependencies"),
            title=f"Spring Boot {boot_target} Dependency Versions",
            source_uri=f"{boot_base}/appendix/dependency-versions/index.html",
            source_type="bom",
        ),
        _target_source(
            "spring_boot",
            boot_target,
            source_key=_source_key("openrewrite-spring-boot", boot_target, "recipes"),
            title="OpenRewrite Spring Boot 4 Migration Recipes",
            source_uri="https://docs.openrewrite.org/recipes/java/spring/boot4",
            source_type="recipe_catalog",
            trust_tier="vendor",
        ),
    ]


def _python_sources(python_target: str) -> list[dict[str, Any]]:
    python_base = f"https://docs.python.org/{python_target}"
    return [
        _target_source(
            "python",
            python_target,
            source_key=_source_key("python", python_target, "docs"),
            title=f"Python {python_target} Documentation",
            source_uri=f"{python_base}/",
            source_type="documentation",
        ),
        _target_source(
            "python",
            python_target,
            source_key=_source_key("python", python_target, "whats-new"),
            title=f"What's New In Python {python_target}",
            source_uri=f"{python_base}/whatsnew/{python_target}.html",
            source_type="release_notes",
        ),
        asdict(
            EngineeringKnowledgeSourceSpec(
                source_key="python-packaging-user-guide",
                title="Python Packaging User Guide",
                source_uri="https://packaging.python.org/en/latest/",
                source_type="documentation",
                version_label="latest",
                metadata={"coordinate": "python_packaging", "target_version_source": "python"},
            )
        ),
        asdict(
            EngineeringKnowledgeSourceSpec(
                source_key="ruff-documentation",
                title="Ruff Documentation",
                source_uri="https://docs.astral.sh/ruff/",
                source_type="tooling_documentation",
                trust_tier="vendor",
                version_label="current",
                metadata={"coordinate": "ruff", "target_version_source": "toolchain_policy"},
            )
        ),
    ]


def generate_source_acquisition_plan(
    *,
    stack_key: str,
    source_versions: dict[str, Any] | None,
    target_versions: dict[str, Any] | None,
    source_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_versions = dict(source_versions or {})
    target_versions = dict(target_versions or {})
    source_policy = dict(source_policy or {})
    sources: list[dict[str, Any]] = []
    java_target = str(target_versions.get("java") or "").strip()
    boot_target = str(target_versions.get("spring_boot") or target_versions.get("spring-boot") or "").strip()
    python_target = str(target_versions.get("python") or "").strip()

    if java_target:
        sources.extend(_java_sources(java_target))
    if boot_target:
        sources.extend(_spring_boot_sources(boot_target))
    if python_target:
        sources.extend(_python_sources(python_target))
    return {
        "schema_version": 1,
        "stack_key": str(stack_key or "").strip(),
        "source_versions": source_versions,
        "target_versions": target_versions,
        "source_policy": source_policy,
        "sources": sources,
        "requires_online_acquisition": bool(sources),
        "allow_community_sources": bool(source_policy.get("allow_community_sources", False)),
    }
