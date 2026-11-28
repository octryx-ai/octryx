"""The governed model call that writes a session's episode summary at the end of a platform turn. No prompt, answer or
provider message is logged."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.model_call_scope import workspace_call
from ...model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from ..memory.capture_model import CaptureModel, CaptureModelUnavailableError

DISPATCH_OWNER = "knowledge_episode_summary"
ROLE = "memory"
MAX_ANSWER_TOKENS = 1500


async def governed_summary_model(db: AsyncSession, *, project_id: str) -> CaptureModel:
    from ...control_plane_service import resolve_control_plane_runtimes

    runtimes = await resolve_control_plane_runtimes(db)
    if not runtimes:
        raise CaptureModelUnavailableError("needs_configuration", "no_runtime_configured")
    admission = await admit_runtimes_for_dispatch(db, runtimes, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise CaptureModelUnavailableError(str(admission.state), str(admission.reason))
    admitted = list(admission.dispatchable_runtimes())
    tagged = [
        runtime for runtime in admitted if ROLE in {str(tag).lower() for tag in runtime.get("use_case_tags") or ()}
    ]
    return CaptureModel(tagged or admitted, scope=workspace_call(project_id), log_label=DISPATCH_OWNER,
                        max_tokens=MAX_ANSWER_TOKENS)


__all__ = ["DISPATCH_OWNER", "governed_summary_model"]
