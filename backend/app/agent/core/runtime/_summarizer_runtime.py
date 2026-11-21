"""Which runtime the rolling session summarizer is allowed to dispatch to.

The summarizer is a background task whose failures are swallowed by design, so a
model refusal would otherwise be invisible. It is a registered ``admitted``
dispatch owner, and this module is the seam that makes that real:

- The *Conversation summaries* Task model (Runtime → Default & fallback → Task
  models; its runtime carries the ``summarize`` role tag) is used when set.
- Otherwise the platform default: the first runtime of the platform order. There
  is no hard-coded model; an install without any runtime
  gets a refusal, not a guess.

Either way the decision goes through ``services/model_gateway/dispatch_admission``
with the session's own project as the Workspace, and a refusal is returned as a
bounded payload the caller records on the session instead of a missing summary
with no explanation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The registered provider-dispatch owner key
# (``services/model_gateway/dispatch_owners.py``).
DISPATCH_OWNER = "session_summarizer"

# The control-plane use-case tag an operator sets to govern summarization.
SUMMARY_ROLE = "summarize"

_RUNTIME_ONLY_KEYS = ("use_case_tags", "model", "target_id", "priority")


@dataclass(frozen=True, slots=True)
class SummarizerRuntime:
    """The admitted client kwargs and model, or the bounded refusal payload."""

    model: str
    client_kwargs: dict[str, Any] = field(default_factory=dict)
    denial: dict[str, Any] | None = None

    @property
    def admitted(self) -> bool:
        return self.denial is None


async def resolve_summarizer_runtime(db: AsyncSession, *, project_id: Any) -> SummarizerRuntime:
    """Resolve the Workspace-admitted summarizer runtime for one session."""

    from ....services.model_gateway.dispatch_admission import admit_runtimes_for_dispatch

    runtimes = await _control_plane_runtimes(db)
    tagged = [runtime for runtime in runtimes if SUMMARY_ROLE in _tags(runtime)]
    chosen = tagged or runtimes[:1]
    admission = await admit_runtimes_for_dispatch(db, chosen, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        return SummarizerRuntime(model="", denial=admission.to_result())
    runtime = dict(admission.first_dispatchable_runtime() or {})
    model = str(runtime.get("model") or "").strip()
    if not model:
        return SummarizerRuntime(model="", denial={"status": "needs_configuration", "admission_reason": "no_runtime"})
    return SummarizerRuntime(
        model=model,
        client_kwargs={key: value for key, value in runtime.items() if key not in _RUNTIME_ONLY_KEYS},
    )


def _tags(runtime: dict[str, Any]) -> set[str]:
    return {str(tag).strip().lower() for tag in (runtime.get("use_case_tags") or [])}


async def _control_plane_runtimes(db: AsyncSession) -> list[dict[str, Any]]:
    """The platform order's runtimes (with their Task-model role tags), or none when the lookup fails."""

    from ....services.control_plane_service import resolve_control_plane_runtimes

    try:
        return [dict(runtime) for runtime in (await resolve_control_plane_runtimes(db)) or []]
    except Exception:  # noqa: BLE001 - a summary is optional; the refusal below is recorded on the session
        logger.warning("summarizer.control_plane_unavailable", exc_info=True)
        return []


__all__ = [
    "DISPATCH_OWNER",
    "SUMMARY_ROLE",
    "SummarizerRuntime",
    "resolve_summarizer_runtime",
]
