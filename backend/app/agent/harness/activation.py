"""Which loop runs an allowed turn: always the native standard loop.

The configuration is normalized to the native harness. The configured ``harness_runtime`` is read
and reported as one of these reasons:

- missing or empty flag, or ``native``            -> ``flag_off``
- the settings object cannot be read              -> ``flag_unreadable`` (logged as a warning)
- any other value                                 -> ``flag_unrecognized`` (logged as a warning)

The governed tool-calling run of the work item analysis is :class:`~app.agent.harness.runtime.HarnessRuntime`, an Octryx-owned loop without a framework.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

HARNESS_RUNTIME_NATIVE = "native"

REASON_FLAG_OFF = "flag_off"
REASON_FLAG_UNREADABLE = "flag_unreadable"
REASON_FLAG_UNRECOGNIZED = "flag_unrecognized"


@dataclass(frozen=True, slots=True)
class HarnessActivation:
    """Which runtime executes this turn, and why."""

    runtime: str
    reason: str
    configured_value: str

    def to_trace(self) -> dict[str, Any]:
        return {"runtime": self.runtime, "reason": self.reason, "configured_value": self.configured_value}


@dataclass(frozen=True, slots=True)
class ConfiguredHarnessRuntime:
    value: str
    readable: bool


def read_configured_harness_runtime() -> ConfiguredHarnessRuntime:
    """Read the flag from the application settings; an unreadable settings object is recorded, not raised."""
    try:
        from ...config import get_settings

        raw = getattr(get_settings(), "harness_runtime", None)
    except Exception:  # noqa: BLE001 - any failure to read configuration must resolve to the native loop
        return ConfiguredHarnessRuntime(value="", readable=False)
    return ConfiguredHarnessRuntime(value=raw.strip().lower() if isinstance(raw, str) else "", readable=True)


def resolve_harness_activation(
    *,
    configured: ConfiguredHarnessRuntime,
    execution_profile: Any,
    agent_definition: Any,
) -> HarnessActivation:
    """Resolve the activation decision for one turn. Pure: no I/O, no framework import."""
    value = configured.value
    if not configured.readable:
        return HarnessActivation(HARNESS_RUNTIME_NATIVE, REASON_FLAG_UNREADABLE, value)
    if value in {"", HARNESS_RUNTIME_NATIVE}:
        return HarnessActivation(HARNESS_RUNTIME_NATIVE, REASON_FLAG_OFF, value)
    return HarnessActivation(HARNESS_RUNTIME_NATIVE, REASON_FLAG_UNRECOGNIZED, value)


def select_turn_loop(
    native_loop: Callable[..., Any],
    *,
    prepared: Any,
    agent_definition: dict | None,
) -> Callable[..., Any]:
    """Return the loop that runs this allowed turn: ``native_loop`` unless the harness is activated."""
    session_metadata = getattr(prepared, "session_metadata", None)
    execution_profile = session_metadata.get("execution_profile") if isinstance(session_metadata, Mapping) else None
    activation = resolve_harness_activation(
        configured=read_configured_harness_runtime(),
        execution_profile=execution_profile,
        agent_definition=agent_definition,
    )
    session_id = getattr(getattr(prepared, "tool_context", None), "session_id", None)
    log = logger.info if activation.reason == REASON_FLAG_OFF else logger.warning
    log("agent.harness.activation", extra={"session_id": session_id, **activation.to_trace()})
    return native_loop


__all__ = [
    "HARNESS_RUNTIME_NATIVE",
    "ConfiguredHarnessRuntime",
    "HarnessActivation",
    "read_configured_harness_runtime",
    "resolve_harness_activation",
    "select_turn_loop",
]
