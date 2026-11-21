"""One governed JSON answer for the Knowledge Search answer.

Like the research model (``knowledge/research/model.py``) the answer never gets a provider of its own: the
control-plane runtimes are resolved, admitted for the searched Workspace under the registered dispatch owner
``knowledge_search_answer`` and tried in priority order. No prompt, answer or provider message is logged.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.model_call_scope import ModelCallScope, model_call_scope, workspace_call
from ...model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from ..research.model import first_json_object

logger = logging.getLogger(__name__)

DISPATCH_OWNER = "knowledge_search_answer"
_MAX_TOKENS = 900


class AnswerModelUnavailableError(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"answer model {state}: {reason}")
        self.state = state
        self.reason = reason


class AnswerModel:
    def __init__(self, runtimes: list[dict[str, Any]], *, scope: ModelCallScope) -> None:
        self._runtimes = runtimes
        self._scope = scope

    async def json(self, *, system: str, user: str) -> dict[str, Any]:
        from ....agent.providers import get_provider

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for runtime in self._runtimes:
            client = None
            try:
                client = get_provider(**{key: value for key, value in runtime.items() if key != "use_case_tags"})
                with model_call_scope(self._scope):
                    result = await client.chat(messages=messages, model=str(runtime.get("model") or ""),
                                               temperature=0.0, max_tokens=_MAX_TOKENS)
            except Exception:  # noqa: BLE001 - the next governed runtime is tried; no provider text is kept
                logger.warning("Knowledge search answer runtime failed: provider=%s", runtime.get("provider_name"))
                continue
            finally:
                close = getattr(client, "close", None) if client is not None else None
                if close:
                    await close()
            answer = first_json_object(str(result.get("content") or ""))
            if answer is not None:
                return answer
            logger.warning("Knowledge search answer held no JSON object")
        raise AnswerModelUnavailableError("unavailable", "no_usable_answer")


async def governed_answer_model(db: AsyncSession, *, project_id: str) -> AnswerModel:
    from ...control_plane_service import resolve_control_plane_runtimes

    runtimes = await resolve_control_plane_runtimes(db)
    if not runtimes:
        raise AnswerModelUnavailableError("needs_configuration", "no_runtime_configured")
    admission = await admit_runtimes_for_dispatch(db, runtimes, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise AnswerModelUnavailableError(str(admission.state), str(admission.reason))
    return AnswerModel(list(admission.dispatchable_runtimes()), scope=workspace_call(project_id))


__all__ = ["AnswerModel", "AnswerModelUnavailableError", "DISPATCH_OWNER", "governed_answer_model"]
