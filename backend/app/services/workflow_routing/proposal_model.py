"""One bounded governed JSON answer from the Model Control Plane, for workflow proposals."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..content_security.model_call_scope import ModelCallScope, model_call_scope, session_call
from ..content_security.refusal import ContentPolicyRefusedError
from ..knowledge.research.model import first_json_object
from ..model_gateway.dispatch_admission import admit_runtimes_for_dispatch

logger = logging.getLogger(__name__)

DISPATCH_OWNER = "workflow_proposal"
ROLE = "routing"
MAX_RUNTIME_ATTEMPTS = 2
MAX_ANSWER_TOKENS = 300


class ProposalModelUnavailableError(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"workflow proposal model {state}: {reason}")
        self.state = state
        self.reason = reason


@dataclass(slots=True)
class ProposalUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    models: list[str] = field(default_factory=list)
    provider: str = ""
    driver: str = ""
    usage_id: str = ""

    def add(self, model: str, usage: object, *, provider: str = "", driver: str = "") -> None:
        self.calls += 1
        if model and model not in self.models:
            self.models.append(model)
        self.provider = self.provider or provider[:100]
        self.driver = self.driver or driver[:64]
        self.usage_id = self.usage_id or uuid.uuid4().hex
        if isinstance(usage, dict):
            self.input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatch_owner": DISPATCH_OWNER,
            "calls": self.calls,
            "models": list(self.models[:MAX_RUNTIME_ATTEMPTS]),
            "provider": self.provider or None,
            "driver": self.driver or None,
            "usage_id": self.usage_id or None,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True, slots=True)
class ProposalModelAnswer:
    answer: dict[str, Any] | None


class ProposalModel:
    def __init__(self, runtimes: list[dict[str, Any]], *, scope: ModelCallScope) -> None:
        self._runtimes = runtimes[:MAX_RUNTIME_ATTEMPTS]
        self._scope = scope
        self.usage = ProposalUsage()

    async def answer(self, *, system: str, user: str) -> ProposalModelAnswer:
        from ...agent.providers import get_provider

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for runtime in self._runtimes:
            client = None
            model = str(runtime.get("model") or "")
            try:
                client = get_provider(**{key: value for key, value in runtime.items() if key != "use_case_tags"})
                with model_call_scope(self._scope):
                    result = await client.chat(
                        messages=messages,
                        model=model,
                        temperature=0.0,
                        max_tokens=MAX_ANSWER_TOKENS,
                    )
            except ContentPolicyRefusedError:
                raise  # the content is refused on every runtime
            except Exception:  # noqa: BLE001 - the next governed runtime is tried; no provider text is kept
                logger.warning("workflow_proposal runtime_failed")
                continue
            finally:
                close = getattr(client, "close", None) if client is not None else None
                if close:
                    await close()
            self.usage.add(
                model,
                result.get("usage") if isinstance(result, dict) else None,
                provider=str(runtime.get("provider_name") or ""),
                driver=str(runtime.get("driver") or ""),
            )
            content = str((result or {}).get("content") or "") if isinstance(result, dict) else ""
            # A runtime that answered decides: an answer without a JSON object is the
            # model declining to answer in the contract, not a transport failure.
            return ProposalModelAnswer(first_json_object(content))
        raise ProposalModelUnavailableError("unavailable", "model_unavailable")


async def _workspace_runtimes(db: AsyncSession, project_id: str | None) -> list[dict[str, Any]]:
    from ..control_plane_service import resolve_control_plane_runtimes
    from ..workspace_composition import get_workspace_default_runtime_target_id, get_workspace_execution_view
    from ..workspace_composition.assignment_policy import runtime_assignment_mode, selected_runtime_target_ids

    view = (
        await get_workspace_execution_view(db, workspace_id=project_id, ensure_foundation=False)
        if project_id
        else None
    )
    default_target_id = get_workspace_default_runtime_target_id(view) or None
    runtimes = await resolve_control_plane_runtimes(db, runtime_target_id=default_target_id)
    if runtime_assignment_mode(view) == "selected_only":
        allowed = selected_runtime_target_ids(view)
        runtimes = [runtime for runtime in runtimes if str(runtime.get("target_id") or "") in allowed]
    return runtimes


async def governed_proposal_model(db: AsyncSession, *, project_id: str | None) -> ProposalModel:
    runtimes = await _workspace_runtimes(db, project_id)
    if not runtimes:
        raise ProposalModelUnavailableError("needs_configuration", "no_runtime_configured")
    admission = await admit_runtimes_for_dispatch(db, runtimes, project_ids=project_id, owner=DISPATCH_OWNER)
    if not admission.allowed:
        raise ProposalModelUnavailableError(str(admission.state), str(admission.reason))
    admitted = list(admission.dispatchable_runtimes())
    if not admitted:
        raise ProposalModelUnavailableError("denied", "no_admitted_runtime")
    tagged = [
        runtime for runtime in admitted if ROLE in {str(tag).lower() for tag in runtime.get("use_case_tags") or ()}
    ]
    # The proposal answers a chat message: the Workspace it was admitted for, or a session without one.
    return ProposalModel(tagged or admitted, scope=session_call(project_id))


__all__ = [
    "DISPATCH_OWNER",
    "MAX_RUNTIME_ATTEMPTS",
    "ProposalModel",
    "ProposalModelAnswer",
    "ProposalModelUnavailableError",
    "ProposalUsage",
    "governed_proposal_model",
]
