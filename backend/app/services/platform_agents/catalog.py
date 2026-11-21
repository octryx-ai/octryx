"""The closed vocabulary of the platform agents: keys, ceilings and runtime preferences."""

from __future__ import annotations

ASSISTANT = "assistant"
ENGINEER = "engineer"
REVIEWER = "reviewer"
PLATFORM_AGENT_KEYS: tuple[str, ...] = (ASSISTANT, ENGINEER, REVIEWER)

RUNTIME_GENERAL = "general"
RUNTIME_CODING = "coding"
RUNTIME_PREFERENCES: frozenset[str] = frozenset({RUNTIME_GENERAL, RUNTIME_CODING})

#: Closed order of the capability classes; a ceiling caps, never grants.
CLASS_ORDER: tuple[str, ...] = ("read_only", "change", "deliver")


def is_platform_agent_key(key: object) -> bool:
    return str(key or "") in PLATFORM_AGENT_KEYS


def class_rank(value: object) -> int:
    text = str(value or "read_only")
    return CLASS_ORDER.index(text) if text in CLASS_ORDER else 0


def ceiling_covers(ceiling: object, capability_class: object) -> bool:
    """True when an agent with ``ceiling`` may run a phase of ``capability_class``."""
    return class_rank(ceiling) >= class_rank(capability_class)


def agent_mode_of(payload: object) -> str:
    """The agent's own mode (``agentType``); a platform agent has none — the run, phase or chat sets the mode."""
    data = payload if isinstance(payload, dict) else {}
    if is_platform_agent_key(data.get("builtinKey")):
        return ""
    return str(data.get("agentType") or data.get("agent_type") or "")
