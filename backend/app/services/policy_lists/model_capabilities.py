"""The model capability catalog as admin-editable data (W22b, R3).

A workflow definition may require a model capability (``required_model_capability``); an admin
tags runtime targets with the capabilities they serve (``capability_tags``). Both are validated
against this catalog (``unknown_capability``). The seed is the one capability R3 introduced,
``coding``.

``coding`` is pinned (``CODE_PINNED_MODEL_CAPABILITIES``, justified in code): the platform's
governed coding run (``workflow_routing/platform_selection``) and the seeded coding definitions
require it, and it is the one capability with an implicit rule for untagged runtimes (a model
outside the weak coding families). Its label may change; it cannot be removed. Any other
capability is removable only while no active definition requires it and no runtime target carries
it (``capability_in_use``).

Closed validation: ``invalid_payload``, ``empty_list``, ``invalid_entry`` (key outside
``[a-z][a-z0-9_]{1,39}``, label empty or longer than 80 characters), ``duplicate_entry``,
``capability_in_use``.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import (
    CAPABILITY_IN_USE,
    EMPTY_LIST,
    INVALID_ENTRY,
    INVALID_PAYLOAD,
    UNKNOWN_CAPABILITY,
    PolicyListError,
    refuse_duplicates,
)
from .records import PolicyListSpec

MODEL_CAPABILITY_CODING = "coding"
CODE_PINNED_MODEL_CAPABILITIES = frozenset({MODEL_CAPABILITY_CODING})
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_LABEL_MAX = 80
_SEED = ({"key": MODEL_CAPABILITY_CODING, "label": "Coding"},)


def _read(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("capabilities")
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or not _KEY.fullmatch(str(item.get("key") or "")):
            raise ValueError("capability")
        entries.append({"key": item["key"], "label": str(item.get("label") or item["key"])})
    return entries


MODEL_CAPABILITIES_SPEC = PolicyListSpec(
    list_id="model_capabilities",
    config_key="policy.model_capabilities",
    key_prefix="model_capabilities",
    title="Model capabilities",
    description=(
        "Capabilities a workflow definition may require of its runtime and an admin may tag runtime targets with."
    ),
    seed_values=lambda: [dict(entry) for entry in _SEED],
    read_values=_read,
)


def validate_model_capabilities(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise PolicyListError(INVALID_PAYLOAD, "values must be a list of {key, label} objects.")
    if not raw:
        raise PolicyListError(EMPTY_LIST, "The capability catalog needs at least one capability.")
    entries: list[dict[str, str]] = []
    for item in raw:
        key = str(item.get("key") or "").strip().lower()
        label = str(item.get("label") or "").strip()
        if not _KEY.fullmatch(key):
            raise PolicyListError(INVALID_ENTRY, "A capability key is a lower-case identifier.", [key])
        if not label or len(label) > _LABEL_MAX or not label.isprintable():
            raise PolicyListError(INVALID_ENTRY, f"A capability label is 1-{_LABEL_MAX} printable characters.", [key])
        entries.append({"key": key, "label": label})
    refuse_duplicates((entry["key"] for entry in entries), what="The capability catalog")
    return entries


def required_model_capability_errors(workflow_contract: Any) -> list[dict[str, str]]:
    """A definition's ``required_model_capability`` must be in the live catalog (``unknown_capability``)."""
    from .live import live_policy_lists

    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    capability = str(contract.get("required_model_capability") or "").strip().lower()
    if not capability or capability in live_policy_lists().model_capabilities:
        return []
    return [
        {
            "code": UNKNOWN_CAPABILITY,
            "message": f"workflow_contract.required_model_capability '{capability}' is not in the model capability "
            "catalog (Admin > Policy lists).",
        }
    ]


async def validate_runtime_capability_tags(db: AsyncSession, raw: Any) -> list[str]:
    """A runtime target's capability tags, each in the live catalog (``unknown_capability``)."""
    from .live import refresh_live_policy_lists

    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise PolicyListError(INVALID_PAYLOAD, "capability_tags must be a list of capability keys.")
    tags = list(dict.fromkeys(item.strip().lower() for item in raw if item.strip()))
    catalog = (await refresh_live_policy_lists(db)).model_capabilities
    unknown = [tag for tag in tags if tag not in catalog]
    if unknown:
        raise PolicyListError(UNKNOWN_CAPABILITY, "These capabilities are not in the capability catalog.", unknown)
    return tags


async def model_capabilities_in_use(db: AsyncSession) -> set[str]:
    """Capabilities something depends on: pinned ones, the phases of active workflows, tagged runtime targets."""
    from ...models import ControlPlaneRuntimeTarget, FlowDefinition, FlowDefinitionVersion

    used = set(CODE_PINNED_MODEL_CAPABILITIES)
    definitions = (
        await db.execute(
            select(FlowDefinitionVersion.definition_json)
            .join(FlowDefinition, FlowDefinition.current_version_id == FlowDefinitionVersion.id)
            .where(FlowDefinition.is_active.is_(True))
        )
    ).scalars()
    for definition in definitions:
        for node in (definition or {}).get("nodes") or []:
            config = node.get("config") if isinstance(node, dict) else None
            contract = config.get("workflow_contract") if isinstance(config, dict) else None
            capability = str((contract or {}).get("required_model_capability") or "").strip().lower()
            if capability:
                used.add(capability)
    for target in (await db.execute(select(ControlPlaneRuntimeTarget))).scalars():
        used.update(target.capability_tags)
    return used


async def refuse_removed_capabilities_in_use(db: AsyncSession, *, current: list[str], proposed: list[str]) -> None:
    removed = set(current) - set(proposed)
    blocked = removed & await model_capabilities_in_use(db)
    if blocked:
        raise PolicyListError(
            CAPABILITY_IN_USE,
            "These capabilities are pinned by code, required by an active workflow definition or carried by a "
            "runtime target; remove those uses first.",
            blocked,
        )


__all__ = [
    "CODE_PINNED_MODEL_CAPABILITIES",
    "MODEL_CAPABILITIES_SPEC",
    "MODEL_CAPABILITY_CODING",
    "model_capabilities_in_use",
    "refuse_removed_capabilities_in_use",
    "required_model_capability_errors",
    "validate_model_capabilities",
    "validate_runtime_capability_tags",
]
