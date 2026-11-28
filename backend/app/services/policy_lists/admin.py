"""Admin reads and writes of the governed policy lists (W22b)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..governed_default_tool_sets import TOOL_SET_BY_CAPABILITY_CLASS
from .default_tool_sets import (
    DEFAULT_TOOL_SET_SPECS,
    catalog_tool_names,
    describe_tool_set,
    validate_tool_set_families,
)
from .errors import UNKNOWN_POLICY_LIST, PolicyListError
from .live import refresh_live_policy_lists
from .model_capabilities import (
    CODE_PINNED_MODEL_CAPABILITIES,
    MODEL_CAPABILITIES_SPEC,
    refuse_removed_capabilities_in_use,
    validate_model_capabilities,
)
from .records import (
    PolicyListSpec,
    PolicyListState,
    policy_list_history,
    read_policy_list_state,
    read_policy_list_states,
    write_policy_list,
)
from .weak_model_families import WEAK_MODEL_FAMILIES_SPEC, validate_weak_model_families
from .workflow_proposal_settings import WORKFLOW_PROPOSAL_SETTINGS_SPEC, validate_workflow_proposal_settings

POLICY_LIST_SOURCE = "admin_policy_list"
POLICY_LIST_OVERRIDE = "supported"

Validator = Callable[[AsyncSession, Any, PolicyListState], Awaitable[Any]]


async def _validate_weak_families(_db: AsyncSession, raw: Any, _current: PolicyListState) -> Any:
    return validate_weak_model_families(raw)


async def _validate_capabilities(db: AsyncSession, raw: Any, current: PolicyListState) -> Any:
    proposed = validate_model_capabilities(raw)
    await refuse_removed_capabilities_in_use(
        db,
        current=[entry["key"] for entry in current.values],
        proposed=[entry["key"] for entry in proposed],
    )
    return proposed


async def _validate_proposal_settings(_db: AsyncSession, raw: Any, _current: PolicyListState) -> Any:
    return validate_workflow_proposal_settings(raw)


# The generic lists of the "Policy lists" admin view; the tool sets have their own view.
_GENERIC_LISTS: dict[str, tuple[PolicyListSpec, Validator]] = {
    WEAK_MODEL_FAMILIES_SPEC.list_id: (WEAK_MODEL_FAMILIES_SPEC, _validate_weak_families),
    MODEL_CAPABILITIES_SPEC.list_id: (MODEL_CAPABILITIES_SPEC, _validate_capabilities),
    # A settings record (an object, not a list) on the same versioned, audited mechanism.
    WORKFLOW_PROPOSAL_SETTINGS_SPEC.list_id: (WORKFLOW_PROPOSAL_SETTINGS_SPEC, _validate_proposal_settings),
}


def _generic_list(list_id: str) -> tuple[PolicyListSpec, Validator]:
    try:
        return _GENERIC_LISTS[list_id]
    except KeyError:
        raise PolicyListError(UNKNOWN_POLICY_LIST, "There is no such policy list.", [list_id]) from None


def _tool_set_spec(capability_type: str) -> tuple[str, PolicyListSpec]:
    key = str(capability_type or "").strip().lower()
    if key not in DEFAULT_TOOL_SET_SPECS:
        raise PolicyListError(UNKNOWN_POLICY_LIST, "There is no default tool set for this capability.", [key])
    return key, DEFAULT_TOOL_SET_SPECS[key]


async def _commit_and_refresh(db: AsyncSession) -> None:
    await db.commit()
    await refresh_live_policy_lists(db)


# ── Default tool sets ─────────────────────────────────────────────────────────
async def default_tool_sets_payload(db: AsyncSession) -> dict[str, Any]:
    states = await read_policy_list_states(db, DEFAULT_TOOL_SET_SPECS.values())
    sets = []
    for capability_type, spec in DEFAULT_TOOL_SET_SPECS.items():
        described = describe_tool_set(capability_type, states[spec.list_id], catalog_tool_names(capability_type))
        sets.append({
            **described,
            "history": await policy_list_history(db, spec.list_id),
            # The capability classes whose turns get this set ([] = no run uses it).
            "capability_classes": [cls for cls, key in TOOL_SET_BY_CAPABILITY_CLASS.items() if key == capability_type],
        })
    return {"source": POLICY_LIST_SOURCE, "override": POLICY_LIST_OVERRIDE, "sets": sets}


async def save_default_tool_set(
    db: AsyncSession, capability_type: str, families: Any, *, actor_id: str, expected_version: int | None
) -> dict[str, Any]:
    capability, spec = _tool_set_spec(capability_type)
    validated = validate_tool_set_families(families, catalog=catalog_tool_names(capability))
    state = await write_policy_list(db, spec, validated, actor_id=actor_id, expected_version=expected_version)
    await _commit_and_refresh(db)
    return state.describe()


async def reset_default_tool_set(db: AsyncSession, capability_type: str, *, actor_id: str) -> dict[str, Any]:
    _capability, spec = _tool_set_spec(capability_type)
    state = await write_policy_list(db, spec, spec.seed_values(), actor_id=actor_id, reset=True)
    await _commit_and_refresh(db)
    return state.describe()


# ── Generic lists ─────────────────────────────────────────────────────────────
async def policy_lists_payload(db: AsyncSession) -> dict[str, Any]:
    states = await read_policy_list_states(db, (spec for spec, _validator in _GENERIC_LISTS.values()))
    lists = []
    for list_id, state in states.items():
        entry = {**state.describe(), "history": await policy_list_history(db, list_id)}
        if list_id == MODEL_CAPABILITIES_SPEC.list_id:
            entry["pinned"] = sorted(CODE_PINNED_MODEL_CAPABILITIES)
        lists.append(entry)
    return {"source": POLICY_LIST_SOURCE, "lists": lists}


async def save_policy_list(
    db: AsyncSession, list_id: str, values: Any, *, actor_id: str, expected_version: int | None
) -> dict[str, Any]:
    spec, validator = _generic_list(list_id)
    validated = await validator(db, values, await read_policy_list_state(db, spec))
    state = await write_policy_list(db, spec, validated, actor_id=actor_id, expected_version=expected_version)
    await _commit_and_refresh(db)
    return state.describe()


async def reset_policy_list(db: AsyncSession, list_id: str, *, actor_id: str) -> dict[str, Any]:
    spec, validator = _generic_list(list_id)
    # A reset is validated like an edit: removing a capability still in use is refused.
    seed = await validator(db, spec.seed_values(), await read_policy_list_state(db, spec))
    state = await write_policy_list(db, spec, seed, actor_id=actor_id, reset=True)
    await _commit_and_refresh(db)
    return state.describe()


__all__ = [
    "default_tool_sets_payload",
    "policy_lists_payload",
    "reset_default_tool_set",
    "reset_policy_list",
    "save_default_tool_set",
    "save_policy_list",
]
