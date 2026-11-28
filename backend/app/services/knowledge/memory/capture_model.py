"""One bounded governed JSON answer from the Model Control Plane, for automatic memory capture. No prompt, answer or
provider message is logged."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.model_call_scope import ModelCallScope, model_call_scope, workspace_call
from ...model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from ..research.model import first_json_object

logger = logging.getLogger(__name__)

DISPATCH_OWNER = "knowledge_memory_capture"
ROLE = "memory"
MAX_RUNTIME_ATTEMPTS = 2
MAX_ANSWER_TOKENS = 800


class CaptureModelUnavailableError(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"memory capture model {state}: {reason}")
        self.state = state
        self.reason = reason


class CaptureModel:
    def __init__(
        self,
        runtimes: list[dict[str, Any]],
        *,
        scope: ModelCallScope,
        log_label: str = DISPATCH_OWNER,
        max_tokens: int = MAX_ANSWER_TOKENS,
    ) -> None:
        self._runtimes = runtimes[:MAX_RUNTIME_ATTEMPTS]
        self._scope = scope
        self._log_label = log_label
        self._max_tokens = max_tokens

    async def json(self, *, system: str, user: str) -> dict[str, Any]:
        from ....agent.providers import get_provider

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for runtime in self._runtimes:
            client = None
            try:
                client = get_provider(**{key: value for key, value in runtime.items() if key != "use_case_tags"})
                with model_call_scope(self._scope):
                    result = await client.chat(
                        messages=messages,
                        model=str(runtime.get("model") or ""),
                        temperature=0.0,
                        max_tokens=self._max_tokens,
                    )
            except Exception:  # noqa: BLE001 - the next governed runtime is tried; no provider text is kept
                logger.warning("%s runtime_failed", self._log_label)
                continue
            finally:
                close = getattr(client, "close", None) if client is not None else None
                if close:
                    await close()
            answer = first_json_object(str(result.get("content") or ""))
            if answer is not None:
                return answer
            logger.warning("%s answer_without_json", self._log_label)
        raise CaptureModelUnavailableError("unavailable", "no_usable_answer")


async def governed_capture_model(db: AsyncSession, *, project_id: str) -> CaptureModel:
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
    return CaptureModel(tagged or admitted, scope=workspace_call(project_id))


__all__ = ["CaptureModel", "CaptureModelUnavailableError", "governed_capture_model"]
