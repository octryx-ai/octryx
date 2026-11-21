"""Runtime-target admission contract shared by policy producers and the engine.

A policy owner (for example the governed LiteLLM gateway's project
``model_policy``) may decide that a resolved runtime target must not be
dispatched. It annotates the runtime dict with ``admission_denial`` instead of
removing it: a removed runtime would silently slide the turn onto the next
target, which is the degradation explicit admission exists to prevent.

The engine reads only this contract. It stays free of any per-driver knowledge.
"""

from __future__ import annotations

from typing import Any

from .runtime_errors import (
    CLASSIFICATION_SOURCE_EXPLICIT,
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_CONTENT_POLICY_DENIED,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
)

RUNTIME_ADMISSION_DENIAL_KEY = "admission_denial"

RUNTIME_ADMISSION_DENIED_STATUS = "admission_denied"
RUNTIME_ADMISSION_DENIED_STAGE = "runtime_admission"


def runtime_admission_denial(runtime: Any) -> dict[str, Any] | None:
    """Return the admission denial attached to a runtime target, if any."""

    if not isinstance(runtime, dict):
        return None
    denial = runtime.get(RUNTIME_ADMISSION_DENIAL_KEY)
    return denial if isinstance(denial, dict) and denial else None


def build_admission_denied_attempt(
    runtime: dict[str, Any],
    denial: dict[str, Any],
    *,
    retry_cycle_index: int,
) -> dict[str, Any]:
    """Build the zero-dispatch runtime attempt record for a denied target."""

    attempt: dict[str, Any] = {
        "provider": runtime.get("provider_name"),
        "model": runtime.get("model"),
        "target_id": runtime.get("target_id"),
        "priority": runtime.get("priority"),
        "status": RUNTIME_ADMISSION_DENIED_STATUS,
        "attempt_stage": RUNTIME_ADMISSION_DENIED_STAGE,
        "retry_index": 0,
        "retry_decision": "final_error",
        "retry_cycle_index": retry_cycle_index,
        "error": str(denial.get("message") or "Runtime target admission denied."),
        "error_class": str(denial.get("error_class") or "permanent"),
        "error_class_source": "explicit",
        "dispatched": False,
    }
    reason = str(denial.get("reason") or "").strip()
    if reason:
        attempt["admission_reason"] = reason
    evidence = denial.get("evidence")
    if isinstance(evidence, dict) and evidence:
        attempt["admission_evidence"] = dict(evidence)
    return attempt


# Strongest first: a content refusal and a data-policy prohibition cannot be lifted by granting an alias.
_REFUSAL_PRECEDENCE = (RUNTIME_ERROR_CONTENT_POLICY_DENIED, RUNTIME_ERROR_DATA_POLICY_DENIED, RUNTIME_ERROR_ALIAS_DENIED)


def admission_refusal_of_attempts(runtime_attempts: Any) -> str | None:
    """The admission class that refused *every* target of a failed dispatch, or ``None``.

    Decided from typed attempt facts only: the error class of each attempt must be
    a governed admission class (``alias_denied`` / ``data_policy_denied``) with an
    ``explicit`` classification source, i.e. set by the ``admission_denial``
    contract or by a typed ``ProviderRuntimeError`` raised before any request.
    Messages are never read. One attempt that is anything else (a dispatched
    request, a timeout, a skipped target, a truncated record) means admission
    alone did not stop the turn, and the caller keeps its provider-failure outcome.

    ``data_policy_denied`` wins over ``alias_denied``: a data-policy prohibition
    cannot be lifted by granting an alias.
    """

    if not isinstance(runtime_attempts, list) or not runtime_attempts:
        return None
    classes: set[str] = set()
    for attempt in runtime_attempts:
        if not isinstance(attempt, dict) or attempt.get("error_class_source") != CLASSIFICATION_SOURCE_EXPLICIT:
            return None
        error_class = attempt.get("error_class")
        if error_class not in _REFUSAL_PRECEDENCE:
            return None
        classes.add(error_class)
    return next(item for item in _REFUSAL_PRECEDENCE if item in classes)


__all__ = [
    "RUNTIME_ADMISSION_DENIAL_KEY",
    "RUNTIME_ADMISSION_DENIED_STAGE",
    "RUNTIME_ADMISSION_DENIED_STATUS",
    "admission_refusal_of_attempts",
    "build_admission_denied_attempt",
    "runtime_admission_denial",
]
