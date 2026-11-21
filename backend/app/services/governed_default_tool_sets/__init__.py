"""The governed default tool set of a turn, per capability class.

A turn without a selected definition, a selected workflow, a fully declared agent blueprint or a
Workspace allow policy offers the governed default (``turn_tool_surface``). Not the capability's whole
catalog (up to 244 visible tools, about 25-30k tokens per request), but a
closed, versioned set per capability class:

- the class is the turn's ``capability_type`` (``diagnosis``, ``plan``, ``change``, ``admin``),
  which the agent mode declares (chat, knowledge and diagnosis modes are ``diagnosis``; change,
  coding and documentation modes are ``change``);
- the set names explicit tools, grouped in named families; the declaration order is the priority
  order under a provider cap (``tool_surface_budget_policy``);
- the set is still filtered by the capability catalog, connector visibility and the Workspace tool
  policy at build time, exactly like every other surface level;
- ``select_workflow`` is in every set, so the model can propose a workflow from the catalog.
- a chat turn adds the connector write tools after its set (``run_capability/chat_writes.py``);
  its connections decide which are offered, and the person confirms each call.

The sets below are the *seed* (``diagnosis.v1`` …). The live sets are admin data (
``services/policy_lists``): an admin edits a set in the Tool Catalog, the edit is validated against
the capability's catalog and stored as the next version (``diagnosis.v2``) with an audit row, and a
reset stores the seed again as a new version. :func:`governed_default_tool_set` returns the live set.
"""

from __future__ import annotations

from .model import GovernedToolSet, ToolFamily
from .seed import GOVERNED_DEFAULT_TOOL_SETS


def governed_default_tool_set(capability_type: str | None) -> GovernedToolSet:
    """The live governed default set of ``capability_type`` (the seed until an admin edits it).

    The capability is normalized upstream (``normalize_capability_type``) to one of the four
    classes, so an unknown value is a programming error and raises instead of falling back.
    """
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
