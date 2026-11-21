"""Connector-registered evidence-salvage hooks for budget-exhausted runs.

The loop core knows only this registry: a salvage renderer takes the user's
request plus the recent tool calls and returns a message when — and only
when — the evidence it owns applies (an empty string means "not mine").
Connector-specific knowledge (which tools, which payload shapes) stays with
the connector that registered the renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

SalvageRenderer = Callable[..., str]

_RENDERERS: dict[str, SalvageRenderer] = {}


def register_salvage_renderer(name: str, renderer: SalvageRenderer) -> None:
    _RENDERERS[str(name).strip()] = renderer


def render_evidence_salvage_message(*, user_request: str, recent_tool_calls: list[Any]) -> str:
    """Return the first applicable connector salvage message, else ''."""
    for renderer in _RENDERERS.values():
        message = renderer(user_request=user_request, recent_tool_calls=recent_tool_calls)
        if message:
            return message
    return ""


def _register_builtin_renderers() -> None:
    from ....tools.connectors.aws_evidence_salvage import build_runtime_salvage_aws_evidence_message

    register_salvage_renderer("aws_evidence", build_runtime_salvage_aws_evidence_message)


_register_builtin_renderers()

__all__ = [
    "register_salvage_renderer",
    "render_evidence_salvage_message",
]
