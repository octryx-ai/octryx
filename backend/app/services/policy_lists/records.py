"""Stored, versioned admin records of the governed policy lists (W22b)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig
from ...time_utils import utc_now
from .errors import VERSION_CONFLICT, PolicyListError

logger = logging.getLogger(__name__)

ORIGIN_SEED = "seed"
ORIGIN_ADMIN = "admin"
ORIGIN_SEED_RESET = "seed_reset"
RECORD_ABSENT = "absent"
RECORD_PRESENT = "present"
RECORD_UNREADABLE = "unreadable"
AUDIT_RESOURCE_TYPE = "policy_list"
AUDIT_ACTION_UPDATED = "policy_list.updated"
AUDIT_ACTION_RESET = "policy_list.reset"
_HISTORY_LIMIT = 10


@dataclass(frozen=True, slots=True)
class PolicyListSpec:
    list_id: str
    config_key: str
    key_prefix: str
    title: str
    description: str
    seed_values: Callable[[], Any]
    read_values: Callable[[Any], Any]
    seed_version: int = 1


@dataclass(frozen=True, slots=True)
class PolicyListState:
    spec: PolicyListSpec
    version: int
    values: Any
    origin: str
    record_state: str
    updated_by: str | None = None
    updated_at: str | None = None

    @property
    def key(self) -> str:
        return f"{self.spec.key_prefix}.v{self.version}"

    @property
    def matches_seed(self) -> bool:
        return self.values == self.spec.seed_values()

    def describe(self) -> dict[str, Any]:
        return {
            "list_id": self.spec.list_id,
            "key": self.key,
            "version": self.version,
            "seed_key": f"{self.spec.key_prefix}.v{self.spec.seed_version}",
            "origin": self.origin,
            "record_state": self.record_state,
            "matches_seed": self.matches_seed,
            "title": self.spec.title,
            "description": self.spec.description,
            "values": self.values,
            "seed_values": self.spec.seed_values(),
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


def _seed_state(spec: PolicyListSpec, record_state: str) -> PolicyListState:
    return PolicyListState(spec, spec.seed_version, spec.seed_values(), ORIGIN_SEED, record_state)


def state_from_raw(spec: PolicyListSpec, raw: str | None) -> PolicyListState:
    if not raw:
        return _seed_state(spec, RECORD_ABSENT)
    try:
        record = json.loads(raw)
        version = record["version"]
        origin = record["origin"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("version")
        if origin not in {ORIGIN_ADMIN, ORIGIN_SEED_RESET}:
            raise ValueError("origin")
        values = spec.read_values(record["values"])
    except (TypeError, ValueError, KeyError):
        logger.warning("policy_lists.record_unreadable", extra={"list_id": spec.list_id})
        return _seed_state(spec, RECORD_UNREADABLE)
    return PolicyListState(
        spec,
        version,
        values,
        origin,
        RECORD_PRESENT,
        updated_by=record.get("updated_by") if isinstance(record.get("updated_by"), str) else None,
        updated_at=record.get("updated_at") if isinstance(record.get("updated_at"), str) else None,
    )


async def read_policy_list_states(db: AsyncSession, specs: Iterable[PolicyListSpec]) -> dict[str, PolicyListState]:
    by_key = {spec.config_key: spec for spec in specs}
    rows = (await db.execute(select(SystemConfig.key, SystemConfig.value).where(SystemConfig.key.in_(by_key)))).all()
    raw_by_key = {str(key): value for key, value in rows}
    return {spec.list_id: state_from_raw(spec, raw_by_key.get(config_key)) for config_key, spec in by_key.items()}


async def read_policy_list_state(db: AsyncSession, spec: PolicyListSpec) -> PolicyListState:
    return (await read_policy_list_states(db, [spec]))[spec.list_id]


async def write_policy_list(
    db: AsyncSession,
    spec: PolicyListSpec,
    values: Any,
    *,
    actor_id: str,
    reset: bool = False,
    expected_version: int | None = None,
) -> PolicyListState:
    current = await read_policy_list_state(db, spec)
    if expected_version is not None and expected_version != current.version:
        raise PolicyListError(
            VERSION_CONFLICT,
            f"{spec.title} changed meanwhile: the live version is {current.key}. Reload and edit again.",
            [current.key],
        )
    origin = ORIGIN_SEED_RESET if reset else ORIGIN_ADMIN
    version = max(current.version, spec.seed_version) + 1
    updated_at = utc_now().isoformat()
    record = {"version": version, "origin": origin, "values": values, "updated_by": actor_id, "updated_at": updated_at}
    row = (await db.execute(select(SystemConfig).where(SystemConfig.key == spec.config_key))).scalar_one_or_none()
    text = json.dumps(record, sort_keys=True)
    if row is None:
        db.add(SystemConfig(key=spec.config_key, value=text, description=f"Governed policy list: {spec.title}"))
    else:
        row.value = text
    new_state = PolicyListState(spec, version, values, origin, RECORD_PRESENT, actor_id, updated_at)
    db.add(
        AuditLog(
            user_id=actor_id,
            action=AUDIT_ACTION_RESET if reset else AUDIT_ACTION_UPDATED,
            resource_type=AUDIT_RESOURCE_TYPE,
            resource_id=spec.list_id,
            details={"key": new_state.key, "previous_key": current.key, "origin": origin, "values": values},
        )
    )
    await db.flush()
    return new_state


async def policy_list_history(db: AsyncSession, list_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == AUDIT_RESOURCE_TYPE, AuditLog.resource_id == list_id)
            .order_by(AuditLog.created_at.desc())
            .limit(_HISTORY_LIMIT)
        )
    ).scalars()
    return [
        {
            "key": (row.details or {}).get("key"),
            "previous_key": (row.details or {}).get("previous_key"),
            "action": row.action,
            "user_id": row.user_id,
            "at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


__all__ = [
    "AUDIT_ACTION_RESET",
    "AUDIT_ACTION_UPDATED",
    "AUDIT_RESOURCE_TYPE",
    "ORIGIN_ADMIN",
    "ORIGIN_SEED",
    "ORIGIN_SEED_RESET",
    "RECORD_ABSENT",
    "RECORD_PRESENT",
    "RECORD_UNREADABLE",
    "PolicyListSpec",
    "PolicyListState",
    "policy_list_history",
    "read_policy_list_state",
    "read_policy_list_states",
    "state_from_raw",
    "write_policy_list",
]
