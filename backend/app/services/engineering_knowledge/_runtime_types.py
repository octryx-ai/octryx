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
    """The explicit migration target: a stack and its exact versions.

    ``source`` names where it came from: the structured fields of a request
    (``TARGET_SOURCE_REQUEST``). It is never parsed from prompt text.
    """

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

    def context_bundle(self) -> dict[str, Any]:
        pack_version = self.pack_resolution.pack_version if self.pack_resolution else None
        pack = self.pack_resolution.pack if self.pack_resolution else None
        assignment = self.pack_resolution.assignment if self.pack_resolution else None
        return {
            "schema_version": 1,
            "state": self.state,
            "prompt_contract": {
                "intent": self.request.intent,
                "stack_key": self.request.stack_key,
                "source_versions": self.request.source_versions,
                "target_versions": self.request.target_versions,
                "target_source": self.request.target_source,
            },
            "repository": serialize_repository_match(self.repository_resolution),
            "engineering_knowledge_pack": {
                "pack_id": pack.id if pack else None,
                "pack_key": pack.key if pack else None,
                "version_id": pack_version.id if pack_version else None,
                "version": pack_version.version if pack_version else None,
                "status": pack_version.status if pack_version else None,
                "quality_status": pack_version.quality_status if pack_version else None,
                "source_versions": dict(pack_version.source_versions or {}) if pack_version else {},
                "target_versions": dict(pack_version.target_versions or {}) if pack_version else {},
                "toolchain_policy": dict(pack.toolchain_policy or {}) if pack else {},
                "assignment_id": assignment.id if assignment else None,
                "match_reason": self.pack_resolution.match_reason if self.pack_resolution else "",
            },
            "retrieval": {
                "budget_tokens": self.budget_tokens,
                "item_count": len(self.items),
                "source_ids": list(self.source_ids),
                "freshness_status": dict(self.source_freshness_counts),
            },
            "engineering_pack_retrieval": {
                "items": list(self.engineering_pack_retrieval.get("items") or []),
                "facts": list(self.engineering_pack_retrieval.get("facts") or []),
                "sources": list(self.engineering_pack_retrieval.get("sources") or []),
            },
            "project_knowledge": {
                "source": "project_knowledge_base",
                "boundary": "internal project facts are loaded separately from vendor Engineering Pack facts",
            },
            "knowledge_build_request": build_knowledge_build_request_payload(self),
            "items": list(self.items),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "clarification_questions": list(self.clarification_questions),
        }


def serialize_repository_match(resolution: RepositoryResolution | None) -> dict[str, Any]:
    if resolution is None or resolution.repository is None:
        return {
            "id": None,
            "name": None,
            "repo_root": None,
            "match_reason": resolution.match_reason if resolution else "",
            "candidates": list(resolution.candidates) if resolution else [],
        }
    repo = resolution.repository
    return {
        "id": repo.id,
        "name": repo.name,
        "repo_root": repo.repo_root,
        "project_id": repo.project_id,
        "match_reason": resolution.match_reason,
        "detected_stack_key": resolution.detected_stack_key,
        "detected_source_versions": dict(resolution.detected_source_versions),
        "candidates": [],
    }


def build_knowledge_build_request_payload(resolution: EngineeringKnowledgeRuntimeResolution) -> dict[str, Any]:
    codes = {str(blocker.get("code") or "").strip() for blocker in resolution.blockers}
    if not codes.intersection({"missing_engineering_knowledge_pack", "stale_engineering_knowledge_pack"}):
        return {}
    source_versions = dict(resolution.request.source_versions or {})
    target_versions = dict(resolution.request.target_versions or {})
    if not target_versions:
        return {}
    return {
        "required": True,
        "reason": "missing_or_stale_exact_version_pack",
        "description": build_knowledge_build_prompt(source_versions=source_versions, target_versions=target_versions),
        # The structured `build_engineering_knowledge_pack` arguments; the tool never parses prompt text.
        "tool_arguments": {
            "stack_key": resolution.request.stack_key,
            "source_versions": source_versions,
            "target_versions": target_versions,
        },
        "source_versions": source_versions,
        "target_versions": target_versions,
        "requires_source_version_discovery": not bool(source_versions),
    }


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
