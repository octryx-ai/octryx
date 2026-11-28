"""The governed default tool set of a turn, per capability class."""

from __future__ import annotations

from .model import GovernedToolSet, ToolFamily
from .seed import GOVERNED_DEFAULT_TOOL_SETS


def governed_default_tool_set(capability_type: str | None) -> GovernedToolSet:
    """The live governed default set of ``capability_type`` (the seed until an admin edits it)."""
    from ..policy_lists.live import live_policy_lists

    key = str(capability_type or "").strip().lower()
    try:
        return live_policy_lists().default_tool_sets[key]
    except KeyError as exc:
        raise ValueError(f"No governed default tool set for capability '{key}'.") from exc


# The set a turn gets follows its run capability class, not a
# mode. Read-only runs get the diagnosis set; change runs the change set; a deliver run always comes from
# a workflow, whose step tools replace the default, so it falls back to the change set.
TOOL_SET_BY_CAPABILITY_CLASS: dict[str, str] = {"read_only": "diagnosis", "change": "change", "deliver": "change"}


def default_tool_set_key_for_class(capability_class: str | None) -> str | None:
    return TOOL_SET_BY_CAPABILITY_CLASS.get(str(capability_class or "").strip().lower())


__all__ = [
    "GOVERNED_DEFAULT_TOOL_SETS",
    "TOOL_SET_BY_CAPABILITY_CLASS",
    "default_tool_set_key_for_class",
    "GovernedToolSet",
    "ToolFamily",
    "governed_default_tool_set",
]
