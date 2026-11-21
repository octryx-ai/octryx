"""The live values of the governed policy lists, as the synchronous runtime reads them (W22b).

The runtime consumers are synchronous (tool surface, runtime requirement, compaction tier), so
the live values are one immutable process snapshot. It is refreshed from
the database at every turn-preparation boundary (``prepare_turn_in_session`` and
``prepare_agent_run``) and right after an admin write, so every process picks up an edit before
its next turn. Before the first refresh the snapshot is the seed, which is exactly what an
untouched database holds. A turn records what it used (``tool_surface_set`` names the set
key and version), so the decision stays explainable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncSession

from ..governed_default_tool_sets import GovernedToolSet
from .default_tool_sets import DEFAULT_TOOL_SET_SPECS, tool_set_from_state
from .model_capabilities import MODEL_CAPABILITIES_SPEC
from .records import PolicyListSpec, PolicyListState, read_policy_list_states, state_from_raw
from .weak_model_families import WEAK_MODEL_FAMILIES_SPEC

ALL_POLICY_LIST_SPECS: tuple[PolicyListSpec, ...] = (
    *DEFAULT_TOOL_SET_SPECS.values(),
    WEAK_MODEL_FAMILIES_SPEC,
    MODEL_CAPABILITIES_SPEC,
)


@dataclass(frozen=True, slots=True)
class LivePolicyLists:
    default_tool_sets: Mapping[str, GovernedToolSet]
    weak_coding_model_families: tuple[str, ...]
    model_capabilities: Mapping[str, str]


def _build(states: Mapping[str, PolicyListState]) -> LivePolicyLists:
    return LivePolicyLists(
        default_tool_sets=MappingProxyType(
            {
                capability_type: tool_set_from_state(capability_type, states[spec.list_id])
                for capability_type, spec in DEFAULT_TOOL_SET_SPECS.items()
            }
        ),
        weak_coding_model_families=tuple(states[WEAK_MODEL_FAMILIES_SPEC.list_id].values),
        model_capabilities=MappingProxyType(
            {entry["key"]: entry["label"] for entry in states[MODEL_CAPABILITIES_SPEC.list_id].values}
        ),
    )


def seed_policy_lists() -> LivePolicyLists:
    return _build({spec.list_id: state_from_raw(spec, None) for spec in ALL_POLICY_LIST_SPECS})


_live: LivePolicyLists | None = None


def live_policy_lists() -> LivePolicyLists:
    """The current snapshot (the seed until the first refresh)."""
    global _live
    if _live is None:
        _live = seed_policy_lists()
    return _live


async def refresh_live_policy_lists(db: AsyncSession) -> LivePolicyLists:
    """Re-read every list from the database and publish the new snapshot."""
    global _live
    _live = _build(await read_policy_list_states(db, ALL_POLICY_LIST_SPECS))
    return _live


def reset_live_policy_lists() -> None:
    """Drop the snapshot so the next read is the seed (test isolation)."""
    global _live
    _live = None


__all__ = [
    "ALL_POLICY_LIST_SPECS",
    "LivePolicyLists",
    "live_policy_lists",
    "refresh_live_policy_lists",
    "reset_live_policy_lists",
    "seed_policy_lists",
]
