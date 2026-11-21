"""Runtime readiness gate enforced before any provider is initialized for a turn.

The control-plane resolver returns an empty executable runtime list when runtime
targets are configured but readiness or capability checks skip every one of them
(``services/control_plane/resolution.py``). ``run_agent`` evaluates this gate after
the execution-profile gate and must not start the model/tool loop when it blocks;
the turn ends with an explicit ``needs_configuration`` message instead of a
provider error attributed to a runtime the user never selected.

Diagnostics are built from an explicit field allowlist of the resolver's
``include_skipped`` payloads so provider credentials, client kwargs, and raw
provider configuration never reach the persisted message or trace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.services.execution_profile_status import EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION

from ..trace_gate_outcome import gate_outcome_marker

GATE_SOURCE_RUNTIME_READINESS = "runtime_readiness"
# Turn-trace provider of a persisted gate explanation. Model-visible history
# (``agent/core/context/runtime_readiness_history.py``) reads it to leave the blocked
# prompt and its explanation out of later turns and session summaries.
RUNTIME_READINESS_GATE_TRACE_PROVIDER = "runtime-readiness-gate"
RUNTIME_READINESS_STATUS_READY = "ready"

_SKIPPED_TARGET_FIELDS = (
    "target_id",
    "provider_id",
    "provider_name",
    "model",
    "selection_reason",
    "readiness_status",
    "readiness_reason",
)

ResolveRuntimesFunc = Callable[..., Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True, slots=True)
class RuntimeReadinessDecision:
    """Whether the turn has at least one executable runtime, with secret-free reasons."""

    allowed: bool
    status: str
    reason: str
    skipped_targets: tuple[dict[str, Any], ...]
    user_message: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source": GATE_SOURCE_RUNTIME_READINESS,
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "skipped_targets": [dict(item) for item in self.skipped_targets],
        }

    def trace_output(self) -> dict[str, Any]:
        """Raw output persisted with a blocked turn's trace, marked as an explicit gate outcome."""
        return {
            **self.to_metadata(),
            **gate_outcome_marker(
                gate=GATE_SOURCE_RUNTIME_READINESS,
                label="runtime readiness gate",
                status=self.status,
                reason=self.reason,
            ),
        }


def evaluate_runtime_readiness(
    runtimes: list[dict[str, Any]] | None,
    *,
    skipped_runtimes: list[dict[str, Any]] | None = None,
) -> RuntimeReadinessDecision:
    """Block the turn when no executable runtime was resolved."""
    if runtimes:
        return RuntimeReadinessDecision(
            allowed=True,
            status=RUNTIME_READINESS_STATUS_READY,
            reason="At least one runtime target is executable.",
            skipped_targets=(),
            user_message="",
        )
    skipped_targets = tuple(
        _secret_free_skipped_target(item)
        for item in skipped_runtimes or []
        if isinstance(item, dict) and item.get("selection_status") != "selected"
    )
    lines = [
        "This request requires configuration before it can run. It was not executed. "
        "No configured runtime target is ready to execute it; an administrator must "
        "complete the runtime or provider configuration, then send the request again."
    ]
    if skipped_targets:
        lines.append("")
        lines.append("Unavailable runtime targets:")
        lines.extend(
            f"- {item.get('provider_name') or 'unknown provider'} / {item.get('model') or 'unknown model'}: "
            f"{', '.join(item['skipped_reasons']) or 'not_selected'}"
            for item in skipped_targets
        )
    return RuntimeReadinessDecision(
        allowed=False,
        status=EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
        reason="No configured runtime target is ready for execution.",
        skipped_targets=skipped_targets,
        user_message="\n".join(lines),
    )


async def resolve_runtime_readiness(
    db: Any,
    *,
    runtimes: list[dict[str, Any]] | None,
    runtime_target_id: str | None,
    resolve_runtimes_func: ResolveRuntimesFunc,
) -> RuntimeReadinessDecision:
    """Evaluate the gate, re-resolving with skipped targets only when it blocks."""
    if runtimes:
        return evaluate_runtime_readiness(runtimes)
    skipped_runtimes = await resolve_runtimes_func(db, runtime_target_id=runtime_target_id, include_skipped=True)
    return evaluate_runtime_readiness(runtimes, skipped_runtimes=list(skipped_runtimes or []))


def _secret_free_skipped_target(payload: dict[str, Any]) -> dict[str, Any]:
    item = {field: payload.get(field) for field in _SKIPPED_TARGET_FIELDS}
    decision = payload.get("selection_decision")
    reasons = decision.get("skipped_reasons") if isinstance(decision, dict) else None
    item["skipped_reasons"] = [str(reason) for reason in reasons or [] if str(reason or "").strip()]
    return item


__all__ = [
    "GATE_SOURCE_RUNTIME_READINESS",
    "RUNTIME_READINESS_GATE_TRACE_PROVIDER",
    "RUNTIME_READINESS_STATUS_READY",
    "RuntimeReadinessDecision",
    "evaluate_runtime_readiness",
    "resolve_runtime_readiness",
]
