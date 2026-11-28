"""The live values of the governed policy lists, as the synchronous runtime reads them (W22b)."""

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
    global _live
    if _live is None:
        _live = seed_policy_lists()
    return _live


async def refresh_live_policy_lists(db: AsyncSession) -> LivePolicyLists:
    global _live
    _live = _build(await read_policy_list_states(db, ALL_POLICY_LIST_SPECS))
    return _live


def reset_live_policy_lists() -> None:
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
