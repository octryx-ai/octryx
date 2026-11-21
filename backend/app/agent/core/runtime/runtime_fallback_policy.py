"""Cross-runtime fallback mode contract.

Cross-runtime fallback is an explicit policy decision, not implicit behavior:
``all_runtimes`` ("try the next allowed model", also the meaning of unset for
every driver) and ``first_runtime_only`` ("stop with an error"), which turns the
first runtime's exhaustion into a final, visible error. The chain itself is
bounded by the Workspace allowlist and the data clearance.

The contract lives here — free of engine imports — so the governed runtime
settings surface can normalize the mode without importing the agent engine.
"""

from __future__ import annotations

from typing import Any

RUNTIME_FALLBACK_MODE_ALL_RUNTIMES = "all_runtimes"
RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY = "first_runtime_only"
RUNTIME_FALLBACK_MODES = frozenset(
    {RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY}
)

FALLBACK_MODE_SOURCE_GOVERNED_SETTING = "governed_setting"
FALLBACK_MODE_SOURCE_DEFAULT = "default"
# A stored value that is not in the closed mode set. It is recorded as invalid
# instead of being normalized into the permissive mode, so the retry-policy
# evidence says what actually happened and the per-driver default survives.
FALLBACK_MODE_SOURCE_INVALID_SETTING = "invalid_setting"



def is_runtime_fallback_mode(value: Any) -> bool:
    """True only for a value inside the closed mode set. No normalization."""

    return str(value or "").strip().lower() in RUNTIME_FALLBACK_MODES


__all__ = [
    "FALLBACK_MODE_SOURCE_DEFAULT",
    "FALLBACK_MODE_SOURCE_GOVERNED_SETTING",
    "FALLBACK_MODE_SOURCE_INVALID_SETTING",
    "RUNTIME_FALLBACK_MODES",
    "RUNTIME_FALLBACK_MODE_ALL_RUNTIMES",
    "RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY",
    "is_runtime_fallback_mode",
]
