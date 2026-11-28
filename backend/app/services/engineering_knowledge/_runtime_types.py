"""Runtime resolution contracts for Engineering Knowledge Pack injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...models import (
    CodeRepository,
    EngineeringKnowledgePack,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackVersion,
)

TARGET_SOURCE_NOT_SPECIFIED = "not_specified"
TARGET_SOURCE_REQUEST = "request"
# The closed resolution states: an unresolved input is never filled with a default.
STATE_READY = "ready"
STATE_NEEDS_CLARIFICATION = "needs_clarification"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_NEEDS_KNOWLEDGE_BUILD = "needs_knowledge_build"
_KNOWLEDGE_BUILD_BLOCKERS = frozenset({"missing_engineering_knowledge_pack", "stale_engineering_knowledge_pack"})
_CONFIGURATION_BLOCKERS = frozenset({"repository_migration_disabled"})


@dataclass(slots=True)
class EngineeringUpgradeTarget:
    stack_key: str
    target_versions: dict[str, str]
    source_versions: dict[str, str] = field(default_factory=dict)
    source: str = TARGET_SOURCE_REQUEST


@dataclass(slots=True)
class EngineeringKnowledgeRuntimeRequest:
    intent: str
    stack_key: str = ""
    source_versions: dict[str, str] = field(default_factory=dict)
    target_versions: dict[str, str] = field(default_factory=dict)
    blockers: list[dict[str, str]] = field(default_factory=list)
    target_source: str = TARGET_SOURCE_NOT_SPECIFIED


@dataclass(slots=True)
class RepositoryResolution:
    repository: CodeRepository | None
    match_reason: str
    detected_stack_key: str = ""
    detected_source_versions: dict[str, str] = field(default_factory=dict)
    candidates: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class PackResolution:
    pack: EngineeringKnowledgePack | None
    pack_version: EngineeringKnowledgePackVersion | None
    assignment: EngineeringKnowledgePackAssignment | None
    match_reason: str


@dataclass(slots=True)
class EngineeringKnowledgeRuntimeResolution:
    request: EngineeringKnowledgeRuntimeRequest
    repository_resolution: RepositoryResolution | None = None
    pack_resolution: PackResolution | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    engineering_pack_retrieval: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    source_freshness_counts: dict[str, int] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    blockers: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    budget_tokens: int = 12_000

    @property
    def is_ready(self) -> bool:
        return (
            not self.blockers
            and self.repository_resolution is not None
            and self.repository_resolution.repository is not None
            and self.pack_resolution is not None
            and self.pack_resolution.pack_version is not None
        )

    @property
    def state(self) -> str:
        codes = {str(blocker.get("code") or "") for blocker in self.blockers}
        if not codes:
            return STATE_READY
        if codes & _CONFIGURATION_BLOCKERS:
            return STATE_NEEDS_CONFIGURATION
        if codes <= _KNOWLEDGE_BUILD_BLOCKERS:
            return STATE_NEEDS_KNOWLEDGE_BUILD
        return STATE_NEEDS_CLARIFICATION


def build_knowledge_build_prompt(*, source_versions: dict[str, str], target_versions: dict[str, str]) -> str:
    coordinates: list[str] = []
    if "java" in source_versions or "java" in target_versions:
        source = source_versions.get("java", "?")
        target = target_versions.get("java", "?")
        coordinates.append(f"from Java {source} to Java {target}")
    if "spring_boot" in source_versions or "spring_boot" in target_versions:
        source = source_versions.get("spring_boot", "?")
        target = target_versions.get("spring_boot", "?")
        coordinates.append(f"from Spring Boot {source} to Spring Boot {target}")
    if "python" in source_versions or "python" in target_versions:
        source = source_versions.get("python", "?")
        target = target_versions.get("python", "?")
        coordinates.append(f"from Python {source} to Python {target}")
    version_text = " and ".join(coordinates) if coordinates else "to the target versions"
    return f"Build an Engineering Knowledge Pack to migrate {version_text}."
