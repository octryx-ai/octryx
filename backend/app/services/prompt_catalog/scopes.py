"""Scope spelling of the prompt catalog: ``global``, ``workspace:<id>``, ``workflow:<flow key>``."""

from __future__ import annotations

from ...models.runtime.prompt_template import PROMPT_SCOPE_GLOBAL, PROMPT_SCOPE_TYPES

SCOPE_REFUSED = "prompt_scope_invalid"


class PromptScopeError(ValueError):
    """A scope that is not one of the closed shapes."""

    code = SCOPE_REFUSED


def normalized_scope(scope_type: str | None, scope_id: str | None) -> tuple[str, str | None]:
    kind = str(scope_type or PROMPT_SCOPE_GLOBAL).strip()
    ident = str(scope_id or "").strip() or None
    if kind not in PROMPT_SCOPE_TYPES:
        raise PromptScopeError(SCOPE_REFUSED)
    if kind == PROMPT_SCOPE_GLOBAL and ident is not None:
        raise PromptScopeError(SCOPE_REFUSED)
    if kind != PROMPT_SCOPE_GLOBAL and ident is None:
        raise PromptScopeError(SCOPE_REFUSED)
    return kind, ident


def scope_key(scope_type: str, scope_id: str | None) -> str:
    kind, ident = normalized_scope(scope_type, scope_id)
    return kind if ident is None else f"{kind}:{ident}"


__all__ = ["SCOPE_REFUSED", "PromptScopeError", "normalized_scope", "scope_key"]
