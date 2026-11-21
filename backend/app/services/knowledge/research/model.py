"""One governed JSON answer from the Model Control Plane, for Knowledge research (packages).

The research of a knowledge package asks a model to plan search queries and to choose sources. It
never gets a provider of its own: the control-plane runtimes are resolved, admitted for the one
Workspace the package belongs to (``knowledge_research`` is a registered dispatch owner), and tried
in priority order, ``research``-tagged runtimes first. The answer must contain a JSON object; the
first complete one is taken. No prompt, answer or provider message is logged.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.model_call_scope import ModelCallScope, model_call_scope, workspace_call
from ...model_gateway.dispatch_admission import admit_runtimes_for_dispatch

logger = logging.getLogger(__name__)

DISPATCH_OWNER = "knowledge_research"
ROLE = "research"
_DECODER = json.JSONDecoder()


class ResearchModelUnavailableError(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"research model {state}: {reason}")
        self.state = state
        self.reason = reason


@dataclass(slots=True)
class ResearchUsage:
    calls: int = 0
    models: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, model: str, usage: object) -> None:
        self.calls += 1
        if model not in self.models:
            self.models.append(model)
        if isinstance(usage, dict):
            self.input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "models": self.models,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


def first_json_object(text: str) -> dict[str, Any] | None:
    position = text.find("{")
    while position >= 0:
        try:
            value, _ = _DECODER.raw_decode(text, position)
        except json.JSONDecodeError:
            position = text.find("{", position + 1)
            continue
        if isinstance(value, dict):
            return value
        position = text.find("{", position + 1)
    return None


class ResearchModel:
    def __init__(self, runtimes: list[dict[str, Any]], *, scope: ModelCallScope) -> None:
        self._runtimes = runtimes
        self._scope = scope
        self.usage = ResearchUsage()

    async def json(self, *, system: str, user: str, max_tokens: int = 4096) -> dict[str, Any]:
        from ....agent.providers import get_provider

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for runtime in self._runtimes:
            client = None
            try:
                client = get_provider(**{key: value for key, value in runtime.items() if key != "use_case_tags"})
                model = str(runtime.get("model") or "")
                with model_call_scope(self._scope):
                    result = await client.chat(messages=messages, model=model, temperature=0.0,
                                               max_tokens=max_tokens)
            except Exception:  # noqa: BLE001 - the next governed runtime is tried; no provider text is kept
                logger.warning("Knowledge research model runtime failed: provider=%s", runtime.get("provider_name"))
                continue
            finally:
                close = getattr(client, "close", None) if client is not None else None
                if close:
                    await close()
            self.usage.add(model, result.get("usage"))
            answer = first_json_object(str(result.get("content") or ""))
            if answer is not None:
                return answer
            logger.warning("Knowledge research model answer held no JSON object")
        raise ResearchModelUnavailableError("unavailable", "no_usable_answer")


async def governed_research_model(db: AsyncSession, *, project_id: str) -> ResearchModel:
    from ...control_plane_service import resolve_control_plane_runtimes

    runtimes = await resolve_control_plane_runtimes(db)
    if not runtimes:
        raise ResearchModelUnavailableError("needs_configuration", "no_runtime_configured")
    admission = await admit_runtimes_for_dispatch(db, runtimes, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise ResearchModelUnavailableError(str(admission.state), str(admission.reason))
    admitted = list(admission.dispatchable_runtimes())
    tagged = [
        runtime for runtime in admitted if ROLE in {str(tag).lower() for tag in runtime.get("use_case_tags") or ()}
    ]
    return ResearchModel(tagged or admitted, scope=workspace_call(project_id))


__all__ = ["ResearchModel", "ResearchModelUnavailableError", "first_json_object", "governed_research_model"]
