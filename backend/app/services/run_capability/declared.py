"""The capability a run declares when it does not come from a chat workflow selection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from ...tools.capability_requirements import CAPABILITY_READ_ONLY, is_known_tool, tool_required_capability
from .chat_writes import CHAT_CONNECTOR_WRITES_KEY
from .classes import CAPABILITY_CLASSES, RUN_CAPABILITY_CLASS_KEY, capability_covers, normalize_capability_class

DECLARED_CAPABILITY_KEY = "capability_class"
# Session metadata a programmatic caller of ``run_agent`` sets (see ``resolution``).
DECLARED_RUN_CAPABILITY_METADATA_KEY = "declared_run_capability"

SOURCE_FLOW_DEFINITION = "flow_definition"
SOURCE_SCHEDULE_DEFINITION = "schedule_definition"
SOURCE_WORKER_PROFILE = "worker_profile"
SOURCE_RUN_PROFILE = "run_profile"
SOURCE_SUB_AGENT_PARENT = "sub_agent_parent"
SOURCE_UNDECLARED_READ_ONLY = "undeclared_read_only"
# No declaration at all: the run has no profile origin and does not run.
SOURCE_MISSING_DECLARATION = "missing_declaration"
DECLARATION_SOURCES = frozenset(
    {
        SOURCE_FLOW_DEFINITION,
        SOURCE_SCHEDULE_DEFINITION,
        SOURCE_WORKER_PROFILE,
        SOURCE_RUN_PROFILE,
        SOURCE_SUB_AGENT_PARENT,
    }
)

STATUS_NEEDS_CONFIGURATION = "needs_configuration"


@dataclass(frozen=True, slots=True)
class DeclaredRunCapability:
    capability_class: str | None
    source: str
    error: str = ""
    capped_by_parent: bool = False
    # a chat turn's recorded permission to write through connectors per confirmed call
    # (``chat_writes.py``); only :func:`capability_from_run_profile` carries it, never a declaration.
    chat_connector_writes: bool = False

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {RUN_CAPABILITY_CLASS_KEY: self.capability_class, "source": self.source}
        if self.error:
            payload["status"] = STATUS_NEEDS_CONFIGURATION
            payload["error"] = self.error
        if self.capped_by_parent:
            payload["capped_by_parent"] = True
        return payload

    def tool_context_state(self) -> dict[str, Any]:
        state = {
            RUN_CAPABILITY_CLASS_KEY: self.capability_class,
            "enforced": True,
            "source": self.source,
            "escalation_decision": None,
        }
        if self.error:
            state["status"] = STATUS_NEEDS_CONFIGURATION
        if self.chat_connector_writes:
            state[CHAT_CONNECTOR_WRITES_KEY] = True
        return state


def declared_run_capability(raw_class: Any, *, source: str) -> DeclaredRunCapability:
    if raw_class is None or raw_class == "":
        return DeclaredRunCapability(capability_class=CAPABILITY_READ_ONLY, source=SOURCE_UNDECLARED_READ_ONLY)
    capability_class = normalize_capability_class(raw_class)
    if capability_class is None:
        return DeclaredRunCapability(
            capability_class=None,
            source=source,
            error=(
                "The declared capability_class is unsupported; an admin must set one of: "
                f"{', '.join(CAPABILITY_CLASSES)}."
            ),
        )
    return DeclaredRunCapability(capability_class=capability_class, source=source)


def capped_by_parent(declared: DeclaredRunCapability, parent_class: str | None) -> DeclaredRunCapability:
    parent = normalize_capability_class(parent_class)
    if declared.capability_class is None or parent is None or capability_covers(parent, declared.capability_class):
        return declared
    return replace(declared, capability_class=parent, capped_by_parent=True)


def declared_from_metadata(value: Any) -> DeclaredRunCapability | None:
    if not isinstance(value, dict):
        return None
    source = str(value.get("source") or "").strip()
    if source == SOURCE_UNDECLARED_READ_ONLY:
        return DeclaredRunCapability(capability_class=CAPABILITY_READ_ONLY, source=source)
    if source not in DECLARATION_SOURCES:
        return DeclaredRunCapability(
            capability_class=None, source=source or "unknown", error="The declared capability names no known source."
        )
    declared = declared_run_capability(value.get(RUN_CAPABILITY_CLASS_KEY), source=source)
    if declared.source == SOURCE_UNDECLARED_READ_ONLY:
        # A declaration record without a class is not a declaration of read_only; it is broken.
        return DeclaredRunCapability(
            capability_class=None, source=source, error="The declared capability has no class."
        )
    return declared


def capability_from_run_profile(execution_profile: Any) -> DeclaredRunCapability:
    profile = execution_profile if isinstance(execution_profile, dict) else {}
    capability = profile.get("capability") if isinstance(profile.get("capability"), dict) else {}
    recorded = normalize_capability_class(capability.get(RUN_CAPABILITY_CLASS_KEY))
    if capability.get("enforced") is True and recorded is not None:
        return DeclaredRunCapability(capability_class=recorded, source=SOURCE_RUN_PROFILE,
                                     chat_connector_writes=capability.get(CHAT_CONNECTOR_WRITES_KEY) is True)
    return DeclaredRunCapability(capability_class=CAPABILITY_READ_ONLY, source=SOURCE_UNDECLARED_READ_ONLY)


def resumed_run_capability_metadata(session_metadata: Any) -> dict[str, Any]:
    metadata = session_metadata if isinstance(session_metadata, dict) else {}
    if DECLARED_RUN_CAPABILITY_METADATA_KEY in metadata:
        return {}
    recorded = capability_from_run_profile(metadata.get("execution_profile"))
    if recorded.source != SOURCE_RUN_PROFILE:
        return {}
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: recorded.to_metadata()}


def validate_declared_capability_class(
    raw_class: Any, *, tool_names: Iterable[str], subject: str
) -> list[dict[str, str]]:
    declared = declared_run_capability(raw_class, source=SOURCE_FLOW_DEFINITION)
    if declared.capability_class is None:
        return [{"code": "unsupported_capability_class", "message": f"{subject}: {declared.error}"}]
    exceeding: dict[str, list[str]] = {}
    unknown: list[str] = []
    for name in sorted({str(item).strip() for item in tool_names if str(item or "").strip()}):
        if not is_known_tool(name):
            unknown.append(name)
            continue
        required = tool_required_capability(name)
        if not capability_covers(declared.capability_class, required):
            exceeding.setdefault(required, []).append(name)
    hint = (
        " Nothing is declared, so it runs 'read_only'; declare capability_class."
        if declared.source == SOURCE_UNDECLARED_READ_ONLY
        else ""
    )
    return [
        {"code": "unknown_tool", "message": f"{subject}: unknown tool: {name}."} for name in unknown
    ] + [
        {
            "code": "capability_class_exceeded",
            "message": (
                f"{subject}: a '{declared.capability_class}' run cannot use tools that need '{required}': "
                f"{', '.join(names)}.{hint}"
            ),
        }
        for required, names in sorted(exceeding.items())
    ]


__all__ = [
    "DECLARATION_SOURCES",
    "DECLARED_CAPABILITY_KEY",
    "DECLARED_RUN_CAPABILITY_METADATA_KEY",
    "SOURCE_FLOW_DEFINITION",
    "SOURCE_MISSING_DECLARATION",
    "SOURCE_RUN_PROFILE",
    "SOURCE_SCHEDULE_DEFINITION",
    "SOURCE_SUB_AGENT_PARENT",
    "SOURCE_UNDECLARED_READ_ONLY",
    "SOURCE_WORKER_PROFILE",
    "STATUS_NEEDS_CONFIGURATION",
    "DeclaredRunCapability",
    "capability_from_run_profile",
    "capped_by_parent",
    "declared_from_metadata",
    "declared_run_capability",
    "resumed_run_capability_metadata",
    "validate_declared_capability_class",
]
