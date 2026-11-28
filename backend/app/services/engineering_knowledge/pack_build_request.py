"""The explicit Engineering Knowledge Pack build request: structured fields, never prompt text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ._runtime_types import build_knowledge_build_prompt

PACK_BUILD_NOT_REQUESTED = "not_requested"
VERSION_COORDINATES = ("java", "spring_boot", "python")
STACK_KEYS = ("java", "java-spring", "python")
_VERSION = re.compile(r"^\d+(?:\.\d+){0,3}(?:\.x)?$")
_SLUG_INVALID = re.compile(r"[^a-z0-9._-]+")
_SLUG_REPEAT = re.compile(r"-{2,}")


@dataclass(slots=True)
class EngineeringKnowledgePackBuildRequest:
    prompt: str
    is_pack_build_request: bool
    stack_key: str = ""
    source_versions: dict[str, str] = field(default_factory=dict)
    target_versions: dict[str, str] = field(default_factory=dict)
    pack_key: str = ""
    pack_name: str = ""
    source_policy: dict[str, Any] = field(default_factory=dict)
    freshness_policy: dict[str, Any] = field(default_factory=dict)
    review_policy: dict[str, Any] = field(default_factory=dict)
    blockers: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.is_pack_build_request and not self.blockers


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _versions(value: Any, blockers: list[dict[str, str]], *, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        blockers.append(_blocker("invalid_versions", f"{label} must map coordinates to exact versions."))
        return {}
    versions: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        version = str(raw_value if raw_value is not None else "").strip()
        if not version:
            continue
        if key not in VERSION_COORDINATES or not _VERSION.fullmatch(version):
            blockers.append(
                _blocker(
                    "invalid_versions",
                    f"{label} accepts only {', '.join(VERSION_COORDINATES)} with exact versions such as 25 or 4.0.3.",
                )
            )
            continue
        versions[key] = version
    return versions


def stack_key_for_coordinates(source_versions: dict[str, str], target_versions: dict[str, str]) -> str:
    coordinates = set(source_versions) | set(target_versions)
    if "spring_boot" in coordinates:
        return "java-spring"
    if "java" in coordinates:
        return "java"
    if "python" in coordinates:
        return "python"
    return ""


def _slug(value: object) -> str:
    text = _SLUG_INVALID.sub("-", str(value or "").strip().lower())
    return _SLUG_REPEAT.sub("-", text).strip("-._") or "unknown"


def build_pack_key(source_versions: dict[str, str], target_versions: dict[str, str]) -> str:
    parts: list[str] = []
    if "java" in source_versions or "java" in target_versions:
        parts.append(f"java-{_slug(source_versions.get('java'))}-to-{_slug(target_versions.get('java'))}")
    if "spring_boot" in source_versions or "spring_boot" in target_versions:
        parts.append(
            f"spring-boot-{_slug(source_versions.get('spring_boot'))}-to-{_slug(target_versions.get('spring_boot'))}"
        )
    if "python" in source_versions or "python" in target_versions:
        parts.append(f"python-{_slug(source_versions.get('python'))}-to-{_slug(target_versions.get('python'))}")
    return "-".join(parts) or "engineering-knowledge-pack"


def build_pack_name(source_versions: dict[str, str], target_versions: dict[str, str]) -> str:
    parts: list[str] = []
    if "java" in source_versions or "java" in target_versions:
        parts.append(f"Java {source_versions.get('java', '?')} to {target_versions.get('java', '?')}")
    if "spring_boot" in source_versions or "spring_boot" in target_versions:
        parts.append(
            f"Spring Boot {source_versions.get('spring_boot', '?')} to {target_versions.get('spring_boot', '?')}"
        )
    if "python" in source_versions or "python" in target_versions:
        parts.append(f"Python {source_versions.get('python', '?')} to {target_versions.get('python', '?')}")
    return " / ".join(parts) + " Engineering Knowledge Pack" if parts else "Engineering Knowledge Pack"


def pack_build_request_from_fields(
    fields: dict[str, Any] | None,
    *,
    source_policy: dict[str, Any] | None = None,
    freshness_policy: dict[str, Any] | None = None,
    publish_policy: dict[str, Any] | None = None,
    review_policy: dict[str, Any] | None = None,
) -> EngineeringKnowledgePackBuildRequest:
    """The pack build named by structured ``fields``; ``not_requested`` when none are given."""
    values = fields if isinstance(fields, dict) else {}
    requested_stack = str(values.get("stack_key") or "").strip()
    if not requested_stack and not values.get("source_versions") and not values.get("target_versions"):
        return _not_requested()

    blockers: list[dict[str, str]] = []
    source_versions = _versions(values.get("source_versions"), blockers, label="source_versions")
    target_versions = _versions(values.get("target_versions"), blockers, label="target_versions")
    _append_field_blockers(
        blockers, requested_stack=requested_stack, source_versions=source_versions, target_versions=target_versions
    )
    return EngineeringKnowledgePackBuildRequest(
        prompt=build_knowledge_build_prompt(source_versions=source_versions, target_versions=target_versions),
        is_pack_build_request=True,
        stack_key=requested_stack or stack_key_for_coordinates(source_versions, target_versions),
        source_versions=source_versions,
        target_versions=target_versions,
        pack_key=build_pack_key(source_versions, target_versions),
        pack_name=build_pack_name(source_versions, target_versions),
        source_policy={
            "trust_tiers": ["official", "vendor", "internal"],
            "allow_community_sources": False,
            **dict(source_policy or {}),
        },
        freshness_policy={"ttl_days": 30, "warning_days": 21, **dict(freshness_policy or {})},
        review_policy={
            "approval_required": True,
            "auto_publish": False,
            **dict(publish_policy or {}),
            **dict(review_policy or {}),
        },
        blockers=blockers,
    )


def _not_requested() -> EngineeringKnowledgePackBuildRequest:
    return EngineeringKnowledgePackBuildRequest(
        prompt="",
        is_pack_build_request=False,
        blockers=[
            _blocker(
                PACK_BUILD_NOT_REQUESTED,
                "No pack build was requested: pass target_versions (and source_versions); "
                "versions are not read from prompt text.",
            )
        ],
    )


def _append_field_blockers(
    blockers: list[dict[str, str]],
    *,
    requested_stack: str,
    source_versions: dict[str, str],
    target_versions: dict[str, str],
) -> None:
    if requested_stack and requested_stack not in STACK_KEYS:
        blockers.append(_blocker("unsupported_stack_key", f"stack_key must be one of: {', '.join(STACK_KEYS)}."))
    if not target_versions:
        blockers.append(
            _blocker(
                "missing_source_target_versions",
                "Ask the user for exact source and target versions before creating the pack.",
            )
        )
    elif not source_versions:
        blockers.append(
            _blocker("missing_source_versions", "Target versions were given, but source versions are missing.")
        )


__all__ = [
    "PACK_BUILD_NOT_REQUESTED",
    "STACK_KEYS",
    "VERSION_COORDINATES",
    "EngineeringKnowledgePackBuildRequest",
    "build_pack_key",
    "build_pack_name",
    "pack_build_request_from_fields",
    "stack_key_for_coordinates",
]
