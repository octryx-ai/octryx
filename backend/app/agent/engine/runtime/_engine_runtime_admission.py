"""Engine records for runtime dispatches that deliberately did not happen.

Two refusals are recorded here, both driver-agnostic:

- a runtime target that a policy owner denied before dispatch (the generic
  ``admission_denial`` contract in ``agent/core/runtime/runtime_admission_contract``);
  the chain then continues with the targets that *are* admitted, so a policy gap
  on one target cannot hard-fail a whole chain;
- a chain that stopped because a served response violated a pinned contract, so
  the remaining targets were never tried.

Neither refusal may be silent: both leave an explicit zero-dispatch attempt in
the turn's runtime attempts. The engine loop keeps only the control flow.
"""

from __future__ import annotations

from typing import Any

from ...core.runtime.runtime_admission_contract import build_admission_denied_attempt

CHAIN_HALT_ERROR_CLASS = "fallback_denied_by_runtime_contract"


def record_admission_denial(
    runtime: dict[str, Any],
    denial: dict[str, Any],
    *,
    retry_cycle_index: int,
    attempts: list[dict[str, Any]],
    cycle_errors: list[str],
) -> None:
    """Record a target refused at the runtime boundary. No client, no request."""

    attempts.append(build_admission_denied_attempt(runtime, denial, retry_cycle_index=retry_cycle_index))
    cycle_errors.append(
        f"{runtime.get('provider_name')}:{runtime.get('model')}: "
        f"{denial.get('message') or 'runtime target admission denied'}"
    )


def record_chain_halt(
    *,
    runtime_count: int,
    runtime_index: int,
    retry_cycle_index: int,
    error_class: str,
    attempts: list[dict[str, Any]],
) -> None:
    """Record that the chain stopped instead of buying a second billable answer.

    Nothing is recorded when the halted target was already the last one: there
    were no further runtimes to skip.
    """

    skipped_runtime_count = max(0, runtime_count - runtime_index - 1)
    if skipped_runtime_count <= 0:
        return
    attempts.append(
        {
            "provider": "runtime-fallback",
            "model": "fallback-policy",
            "status": "fallback_denied",
            "retry_cycle_index": retry_cycle_index,
            "retry_decision": "final_error",
            "error_class": error_class,
            "error": (
                "Runtime chain stopped by an explicit runtime contract violation; "
                f"{skipped_runtime_count} configured fallback runtime(s) were not tried."
            ),
            "skipped_runtime_count": skipped_runtime_count,
        }
    )


__all__ = [
    "CHAIN_HALT_ERROR_CLASS",
    "record_admission_denial",
    "record_chain_halt",
]
