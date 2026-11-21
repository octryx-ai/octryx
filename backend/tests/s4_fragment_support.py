"""Fixtures for the S4.2 fragment store tests: two small fragments, their composites and the service calls.

``probe`` is the live-acceptance fragment (contract §5 step 2): one ``user_confirmation subject: advance`` with the
ports ``go`` (next, any), ``back`` and ``stop`` (next, outcome). ``work`` is a one-phase fragment for the phased
editor. Both are valid fragments and compose into valid phased graphs under the real compiler (S4.1).
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from app.models import FlowDefinitionVersion, User
from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version
from app.services.flow_draft_service import save_flow_draft
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.seeding import definition_digest
from tests.phased_workflow_fixtures import PHASE

FLOWS = "/api/v1/flows"


def probe_fragment(*, label: str = "Go on?") -> dict[str, Any]:
    return {
        "execution_kind": "phased_fragment", "schema_version": "fragment/v1", "entry": "confirm",
        "ports": {"go": {"edge": "next", "accepts": "any"}, "back": {"edge": "next", "accepts": "outcome"},
                  "stop": {"edge": "next", "accepts": "outcome"}},
        "requires": [], "provides": [], "instance": "single",
        "nodes": [{"id": "confirm", "type": "user_confirmation", "label": label, "config": {"subject": "advance"}}],
        "edges": [
            {"id": "e-go", "source_node_id": "confirm", "target_port": "go", "when": "confirmed"},
            {"id": "e-back", "source_node_id": "confirm", "target_port": "back", "when": "changed"},
            {"id": "e-stop", "source_node_id": "confirm", "target_port": "stop", "when": "stopped"},
        ],
    }


def work_fragment() -> dict[str, Any]:
    return {
        "execution_kind": "phased_fragment", "schema_version": "fragment/v1", "entry": "work",
        "ports": {"done": {"edge": "next", "accepts": "any"}}, "requires": [], "provides": [], "instance": "single",
        "nodes": [{"id": "work", "type": "phase", "label": "Fragment work", "config": copy.deepcopy(PHASE)}],
        "edges": [{"id": "e-done", "source_node_id": "work", "target_port": "done"}],
    }


def ref_node(node_id: str, key: str, version_id: str | None, checksum: str, ports: dict[str, str],
             **extra: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"fragment_key": key, "fragment_checksum": checksum, "ports": ports, **extra}
    if version_id is not None:
        config["fragment_version_id"] = version_id
    return {"id": node_id, "type": "fragment", "label": "Probe", "config": config}


def outcome(node_id: str, value: str) -> dict[str, Any]:
    return {"id": node_id, "type": "outcome", "label": node_id.title(), "config": {"outcome": value}}


def probe_composite(key: str, version_id: str | None, checksum: str, *,
                    ports: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start", "label": "Start"},
                  ref_node("probe", key, version_id, checksum,
                           ports if ports is not None else {"go": "done", "back": "blocked", "stop": "stopped"}),
                  outcome("done", "done"), outcome("blocked", "blocked"), outcome("stopped", "stopped")],
        "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "probe"}],
    }


def work_composite(key: str, version_id: str, checksum: str) -> dict[str, Any]:
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start", "label": "Start"},
                  ref_node("w", key, version_id, checksum, {"done": "own"}),
                  {"id": "own", "type": "phase", "label": "Own work", "config": copy.deepcopy(PHASE)},
                  outcome("done", "done")],
        "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "w"},
                  {"id": "e1", "source_node_id": "own", "target_node_id": "done"}],
    }


def checksum(definition: dict[str, Any]) -> str:
    return canonical_hash(definition)


def digest(definition: dict[str, Any]) -> str:
    return definition_digest(definition)


def node_types(definition: dict[str, Any]) -> set[str]:
    return {str(node.get("type")) for node in definition.get("nodes") or []}


def unique_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def make_admin(db) -> User:
    from sqlalchemy import select

    from app.models import Role, UserRole

    handle = f"s4-{uuid.uuid4().hex[:8]}"
    user = User(id=str(uuid.uuid4()), username=handle, email=f"{handle}@example.com", password_hash="x",
                is_active=True)
    db.add(user)
    await db.flush()
    role_id = (await db.execute(select(Role.id).where(Role.name == "admin"))).scalar_one_or_none()
    if role_id is not None:
        db.add(UserRole(user_id=user.id, role_id=role_id))
        await db.flush()
    return user


async def create(db, user: User, key: str, definition: dict[str, Any], **payload: Any) -> dict[str, Any]:
    return await create_flow_definition(db, current_user=user, payload={
        "key": key, "name": key, "definition": definition, **payload})


async def publish(db, version_id: str, user: User) -> dict[str, Any]:
    return await publish_flow_definition_version(db, version_id=version_id, current_user=user)


async def published_fragment(db, author: User, reviewer: User, *, key: str | None = None,
                             definition: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
    """Create a fragment as ``author`` and publish it as ``reviewer``: ``(key, flow_id, version_id, checksum)``."""
    key = key or unique_key("s4-probe-confirm")
    definition = definition or probe_fragment()
    created = await create(db, author, key, definition)
    version_id = created["versions"][0]["id"]
    await publish(db, version_id, reviewer)
    return key, created["id"], version_id, checksum(definition)


async def new_fragment_version(db, flow_id: str, base_version_id: str, author: User, reviewer: User,
                               definition: dict[str, Any], *, name: str) -> str:
    saved = await save_flow_draft(db, flow_id=flow_id, current_user=author, payload={
        "expected_latest_version_id": base_version_id, "definition": definition, "name": name})
    version_id = max(saved["versions"], key=lambda item: item["version"])["id"]
    await publish(db, version_id, reviewer)
    return version_id


async def version_row(db, version_id: str) -> FlowDefinitionVersion:
    row = await db.get(FlowDefinitionVersion, version_id)
    await db.refresh(row)
    return row
