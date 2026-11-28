"""Which coding engine an octryx session runs on, by platform, Workspace and person: keys and validation.
Free of database imports: ``policy`` validates the Workspace section on every admin write."""

from __future__ import annotations

from typing import Any

ENGINES_KEY = "engines"
ENGINE_CLAUDE_CODE = "claude_code"
ENGINE_CODEX = "codex"
# The order is the fallback order when a Workspace's default is not among its allowed engines.
ENGINES: tuple[str, ...] = (ENGINE_CLAUDE_CODE, ENGINE_CODEX)
PLATFORM_CONFIG_KEY = "agent_gateway.default_engine"
_FIELDS = frozenset({"allowed", "default"})

REASON_ENGINE_UNKNOWN = "engine_unknown"
REASON_ENGINE_NOT_ALLOWED = "engine_not_allowed_in_workspace"


class EnginePolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


def engine_name(value: Any, path: str) -> str:
    if type(value) is not str or value not in ENGINES:
        raise EnginePolicyError(REASON_ENGINE_UNKNOWN, path)
    return value


def normalize_engine_section(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EnginePolicyError("not_an_object", path)
    unknown = sorted(set(value) - _FIELDS)
    if unknown:
        raise EnginePolicyError("unknown_field", f"{path}.{unknown[0]}")
    allowed_raw = value.get("allowed", list(ENGINES))
    if not isinstance(allowed_raw, list) or not allowed_raw:
        raise EnginePolicyError("allowed_must_name_an_engine", f"{path}.allowed")
    allowed = [engine_name(item, f"{path}.allowed[{index}]") for index, item in enumerate(allowed_raw)]
    if len(set(allowed)) != len(allowed):
        raise EnginePolicyError("duplicate_engine", f"{path}.allowed")
    normalized: dict[str, Any] = {"allowed": [engine for engine in ENGINES if engine in allowed]}
    default = value.get("default")
    if default is not None:
        if engine_name(default, f"{path}.default") not in allowed:
            raise EnginePolicyError("default_not_allowed", f"{path}.default")
        normalized["default"] = default
    return normalized


__all__ = [
    "SESSION_ENGINE_KEY",
    "ENGINES",
    "ENGINES_KEY",
    "ENGINE_CLAUDE_CODE",
    "ENGINE_CODEX",
    "EnginePolicyError",
    "PLATFORM_CONFIG_KEY",
    "REASON_ENGINE_NOT_ALLOWED",
    "REASON_ENGINE_UNKNOWN",
    "engine_name",
    "normalize_engine_section",
]

# ``sessions.metadata[SESSION_ENGINE_KEY]``: the engine a gateway session's launcher registered with (``codex``).
SESSION_ENGINE_KEY = "engine"
