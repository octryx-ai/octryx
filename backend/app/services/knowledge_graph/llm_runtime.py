"""Governed LLM generate function for knowledge extraction/summarization.

Builds a ``generate(prompt) -> str`` callable backed by the control plane:
runtime targets tagged with the requested role (``use_case_tags``, e.g.
``extract`` or ``summarize``) are preferred; otherwise the normal prioritized
runtime order applies. Runtimes are tried in order; if all fail (or none is
configured) the call raises loudly — extraction never silently degrades.

``project_ids`` is a required Workspace scope, not an optional hint: every caller
knows which Workspace (or federated candidate set) it is extracting for, and the
admission boundary admits a governed gateway alias only when *every* project in
that scope grants it. An empty scope is a configuration gap, so it raises
:class:`KnowledgeLLMUnavailableError` with the explicit admission state instead of
resolving to an unverifiable admission that could only fail at dispatch.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..content_security.handling import PLATFORM_RETRIEVAL_WITHOUT_WORKSPACE
from ..content_security.model_call_scope import ModelCallScope, call_scope, model_call_scope
from ..error_facts import error_code, error_type
from ..model_gateway.dispatch_admission import admit_runtimes_for_dispatch

logger = logging.getLogger(__name__)

ROLE_EXTRACT = "extract"
ROLE_SUMMARIZE = "summarize"
ROLE_KEYWORDS = "keywords"


class KnowledgeLLMUnavailableError(RuntimeError):
    """No governed LLM runtime could serve the knowledge role.

    A Workspace-policy refusal carries the boundary's bounded
    ``DispatchAdmission.to_result()`` payload, so a caller can report the explicit
    admission state instead of flattening it into a free-text error. The payload is
    empty for an ordinary configuration or provider outcome.
    """

    def __init__(self, message: str, *, admission_result: Mapping[str, Any] | None = None):
        super().__init__(message)
        self._admission_result = dict(admission_result or {})

    def to_result(self) -> dict[str, Any]:
        return dict(self._admission_result)

    @property
    def state_reason(self) -> str:
        """Closed-vocabulary ``<state>:<reason>`` label, or an empty string."""

        result = self._admission_result
        if not result:
            return ""
        return f"{result.get('status', '')}:{result.get('admission_reason', '')}"


KNOWLEDGE_RUNTIME_FAILED = "knowledge_runtime_failed"


class KnowledgeLLMRuntimeFailedError(KnowledgeLLMUnavailableError):
    """Every admitted runtime failed; carries a closed code and the last error's class only.

    The provider's own error stays reachable as ``__cause__`` (for tracebacks in operator
    logs); its message never enters this error's message, a stored record or a response.
    """

    def __init__(
        self,
        *,
        role: str,
        last_error: BaseException | None,
        attempts: int,
        admission_result: Mapping[str, Any] | None = None,
    ):
        self.error_code = KNOWLEDGE_RUNTIME_FAILED
        self.role = error_code(role)
        self.error_type = error_type(last_error) if last_error is not None else None
        self.attempts = int(attempts)
        facts = f"{self.error_code} role={self.role} attempts={self.attempts}"
        if self.error_type:
            facts = f"{facts} error_type={self.error_type}"
        super().__init__(facts, admission_result=admission_result)


async def _admitted_runtimes(
    db: AsyncSession, project_ids: Sequence[str] | str | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``(dispatchable runtimes, refusal result)`` after the Workspace admission boundary."""
    # Imported lazily: control_plane_service and the provider registry pull large
    # dependency graphs and this module sits on the knowledge hot path.
    from ..control_plane_service import resolve_control_plane_runtimes

    runtimes = await resolve_control_plane_runtimes(db)
    if not runtimes:
        raise KnowledgeLLMUnavailableError(
            "No active LLM runtime is configured for knowledge extraction; "
            "configure a control-plane runtime target."
        )

    admission = await admit_runtimes_for_dispatch(
        db,
        runtimes,
        project_ids=project_ids,
        owner="knowledge_graph_runtime",
    )
    if not admission.allowed:
        raise KnowledgeLLMUnavailableError(
            "No LLM runtime is admitted for this Workspace: "
            f"{admission.state}/{admission.reason}.",
            admission_result=admission.to_result(),
        )
    # A partially refused chain stays dispatchable, but the refusal must not be
    # lost behind whatever the admitted runtimes do next.
    refusal_result = admission.to_result() if admission.partially_refused else {}
    return list(admission.dispatchable_runtimes()), refusal_result


def _role_ordered(
    runtimes: list[dict[str, Any]], normalized_role: str, require_role_match: bool
) -> list[dict[str, Any]]:
    role_matches = [
        runtime
        for runtime in runtimes
        if normalized_role in {str(tag).strip().lower() for tag in (runtime.get("use_case_tags") or [])}
    ]
    if require_role_match and not role_matches:
        raise KnowledgeLLMUnavailableError(
            f"No runtime target is tagged for knowledge role '{normalized_role}'; "
            f"tag a control-plane runtime with use_case_tags=['{normalized_role}'] to enable it."
        )
    return role_matches or list(runtimes)


async def _generate_in_order(
    prompt: str,
    *,
    ordered: list[dict[str, Any]],
    normalized_role: str,
    temperature: float,
    max_tokens: int,
    refusal_result: dict[str, Any],
    scope: ModelCallScope,
) -> str:
    from ...agent.providers import get_provider

    last_error: Exception | None = None
    attempts = 0
    for runtime in ordered:
        client = None
        try:
            # Client construction stays inside the try: a misconfigured
            # runtime (e.g. missing api key) must fall through to the next
            # governed runtime instead of aborting the chain.
            client = get_provider(**{k: v for k, v in runtime.items() if k != "use_case_tags"})
            with model_call_scope(scope):
                result = await client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=str(runtime.get("model") or ""),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return str(result.get("content") or "")
        except Exception as exc:  # noqa: BLE001 - try the next governed runtime
            last_error = exc
            attempts += 1
            logger.warning(
                "Knowledge %s runtime %s/%s failed: error_type=%s",
                normalized_role,
                runtime.get("provider_name"),
                runtime.get("model"),
                error_type(exc),
            )
        finally:
            close = getattr(client, "close", None) if client is not None else None
            if close:
                await close()
    raise KnowledgeLLMRuntimeFailedError(
        role=normalized_role,
        last_error=last_error,
        attempts=attempts,
        admission_result=refusal_result,
    ) from last_error


async def build_generate_fn(
    db: AsyncSession,
    *,
    project_ids: Sequence[str] | str | None,
    role: str = ROLE_EXTRACT,
    temperature: float = 0.1,
    max_tokens: int = 1600,
    require_role_match: bool = False,
) -> Callable[[str], Awaitable[str]]:
    """Resolve governed runtimes now; return an async generate(prompt) callable.

    Resolution happens eagerly so a missing configuration surfaces immediately
    (needs_configuration semantics), not in the middle of an ingestion run.
    ``require_role_match=True`` restricts to runtimes explicitly tagged with the
    role — for per-query features (keyword split, global synthesis) that must be
    an explicit admin opt-in rather than silently consuming the default runtime.
    """
    runtimes, refusal_result = await _admitted_runtimes(db, project_ids)

    normalized_role = str(role or "").strip().lower()
    ordered = _role_ordered(runtimes, normalized_role, require_role_match)
    # Every Workspace the runtimes were admitted for (a federated synthesis: one common content handling), or a
    # retrieval without a Workspace filter.
    scope = call_scope(project_ids, without_workspace=PLATFORM_RETRIEVAL_WITHOUT_WORKSPACE)

    async def generate(prompt: str) -> str:
        return await _generate_in_order(
            prompt,
            ordered=ordered,
            normalized_role=normalized_role,
            temperature=temperature,
            max_tokens=max_tokens,
            refusal_result=refusal_result,
            scope=scope,
        )

    return generate
