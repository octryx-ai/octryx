"""Source spec and source audit value types for Engineering Knowledge source ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EngineeringKnowledgeSourceSpec:
    source_key: str
    title: str
    source_uri: str
    source_type: str = "documentation"
    trust_tier: str = "official"
    version_label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> EngineeringKnowledgeSourceSpec:
        return cls(
            source_key=str(payload.get("source_key") or payload.get("key") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            source_uri=str(payload.get("source_uri") or payload.get("uri") or payload.get("url") or "").strip(),
            source_type=str(payload.get("source_type") or "documentation").strip(),
            trust_tier=str(payload.get("trust_tier") or "official").strip(),
            version_label=str(payload.get("version_label") or "").strip(),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class EngineeringKnowledgeSourceAudit:
    status: str
    reason: str
    canonical_uri: str
    coverage_areas: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "canonical_uri": self.canonical_uri,
            "coverage_areas": list(self.coverage_areas),
            "blockers": list(self.blockers),
        }
