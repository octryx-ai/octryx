"""Who a model call is made for: the scope every driver call carries into the provider wrapper."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .handling import (
    KIND_IDS,
    PLATFORM_SESSION_WITHOUT_WORKSPACE,
    REASON_HANDLING_SCOPE_MISSING,
    HandlingPlan,
    PlatformScope,
    content_handling_isolated,
)
from .refusal import ContentPolicyRefusedError

REASON_HANDLING_CONFLICT = "content_handling_conflict"


class ModelCallScopeMissingError(ContentPolicyRefusedError):
    def __init__(self, detail: str, model: str = "", decision_id: str | None = None) -> None:
        super().__init__((), {"kind": "block", "reason": REASON_HANDLING_SCOPE_MISSING, "found": {}, "masked": 0,
                              "policies": [], "decision_id": decision_id, "model_from": model, "model_to": ""})
        self.detail = detail


class ContentHandlingConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelCallScope:
    workspace_ids: tuple[str, ...] = ()
    platform: PlatformScope | None = None
    session_id: str | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        if bool(self.workspace_ids) == (self.platform is not None):
            raise ModelCallScopeMissingError("a model call scope names Workspaces or a platform scope, not both")

    @property
    def workspace_id(self) -> str | None:
        return self.workspace_ids[0] if self.workspace_ids else None


def _ids(workspace_ids: str | Iterable[str] | None) -> tuple[str, ...]:
    values = [workspace_ids] if isinstance(workspace_ids, str) else list(workspace_ids or ())
    return tuple(dict.fromkeys(text for value in values if (text := str(value or "").strip())))


def workspace_call(workspace_ids: str | Iterable[str], *, session_id: str | None = None,
                   user_id: str | None = None) -> ModelCallScope:
    ids = _ids(workspace_ids)
    if not ids:
        raise ModelCallScopeMissingError("a Workspace call without a Workspace")
    return ModelCallScope(ids, None, session_id or None, user_id or None)


def platform_call(reason: str, *, session_id: str | None = None, user_id: str | None = None) -> ModelCallScope:
    return ModelCallScope((), PlatformScope(reason), session_id or None, user_id or None)


def call_scope(workspace_ids: str | Iterable[str] | None, *, without_workspace: str, session_id: str | None = None,
               user_id: str | None = None) -> ModelCallScope:
    if _ids(workspace_ids):
        return workspace_call(workspace_ids, session_id=session_id, user_id=user_id)  # type: ignore[arg-type]
    return platform_call(without_workspace, session_id=session_id, user_id=user_id)


def session_call(workspace_id: str | None, *, session_id: str | None = None,
                 user_id: str | None = None) -> ModelCallScope:
    # A session without a Workspace is a personal session by design, not a missing scope.
    return call_scope(workspace_id, without_workspace=PLATFORM_SESSION_WITHOUT_WORKSPACE, session_id=session_id,
                      user_id=user_id)


_SCOPE: ContextVar[ModelCallScope | None] = ContextVar("octryx_model_call_scope", default=None)


@contextmanager
def model_call_scope(scope: ModelCallScope) -> Iterator[None]:
    if not isinstance(scope, ModelCallScope):
        raise ModelCallScopeMissingError("model_call_scope needs a ModelCallScope")
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def bound_scope() -> ModelCallScope | None:
    return _SCOPE.get()


def _handling(plan: HandlingPlan) -> tuple[str, tuple[tuple[str, str], ...]]:
    return plan.governance_alias or "", tuple((item.kind, item.action) for item in plan.items if item.kind in KIND_IDS)


async def scope_plan(scope: ModelCallScope, surface: str) -> HandlingPlan:
    if scope.platform is not None:
        return await content_handling_isolated(scope.platform, surface)
    plans = [await content_handling_isolated(workspace_id, surface) for workspace_id in scope.workspace_ids]
    if len({_handling(plan) for plan in plans}) > 1:
        raise ContentHandlingConflictError(scope.workspace_ids)
    return plans[0]


__all__ = [
    "REASON_HANDLING_CONFLICT",
    "ContentHandlingConflictError",
    "ModelCallScope",
    "ModelCallScopeMissingError",
    "bound_scope",
    "call_scope",
    "model_call_scope",
    "platform_call",
    "scope_plan",
    "session_call",
    "workspace_call",
]
