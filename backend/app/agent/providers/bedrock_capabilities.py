"""Tool-use capability of Bedrock foundation models.

``ListFoundationModels`` reports modalities and streaming but not whether a model
accepts tools through the Converse API. Without that fact every synced model was
stored as not tool-capable, and the runtime selection policy refused it for every
tool-requiring turn.

This table is the explicit evidence instead: the model families that the Amazon
Bedrock "supported models and model features" documentation lists for Converse
tool use. It is deliberately narrow. A model id that matches no rule returns
``None`` (unknown), which the selection policy treats as ``tool_support_unknown``
and an administrator can decide per model; nothing is guessed from a name that is
merely similar.
"""

from __future__ import annotations

import re

# (pattern over the base model id, supports tools). First match wins, so the
# explicit "no" rules for legacy generations come before the family "yes" rules.
_TOOL_SUPPORT_RULES: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"^anthropic\.claude-(v2|instant)"), False),
    (re.compile(r"^anthropic\.claude-"), True),
    (re.compile(r"^amazon\.titan-"), False),
    (re.compile(r"^amazon\.nova-(2-)?(micro|lite|pro|premier)"), True),
    (re.compile(r"^meta\.llama3-(8b|70b)-instruct"), False),
    (re.compile(r"^meta\.llama(3-[1-9]|4)"), True),
    (re.compile(r"^mistral\.(mistral-large|pixtral-large)"), True),
    (re.compile(r"^cohere\.command-r"), True),
    (re.compile(r"^ai21\.jamba"), True),
)

# Cross-region inference profile prefixes (``eu.``, ``us.``, ``apac.`` ...) name the
# same model; the capability belongs to the base model id.
_PROFILE_PREFIX = re.compile(r"^(?:[a-z]{2,5})\.(?=[a-z0-9-]+\.)")


def bedrock_tool_support(model_id: str) -> bool | None:
    """Return True/False when the documented family is known, otherwise None."""
    base = _PROFILE_PREFIX.sub("", str(model_id or "").strip().lower(), count=1)
    for pattern, supported in _TOOL_SUPPORT_RULES:
        if pattern.match(base):
            return supported
    return None


__all__ = ["bedrock_tool_support"]
