"""The per-policy read model of a policy-set version."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicySetVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
)
from .baseline import load_baseline
from .builder_parse import parse_est
from .builder_sentence import scope as builder_scope
from .builder_sentence import sentence as builder_sentence
from .catalog import action_ids, action_info, point_of
from .entity_listing import NameIndex, load_name_index
from .policy_sentence import outline, scope_label, warnings
from .policy_text import Statement, index_statements
from .schema import ID_CLASSIFICATION, ID_PLATFORM, ID_WORKSPACE

SOURCE_BUILDER = "builder"
SOURCE_HAND_WRITTEN = "hand_written"
CHANGE_NEW = "new"
CHANGE_CHANGED = "changed"
CHANGE_UNCHANGED = "unchanged"
CHANGE_REMOVED = "removed"

_GENERATED = ((ID_PLATFORM, "platform", None),
              (ID_CLASSIFICATION, "classification", "Settings → Governance → Classification"),
              (ID_WORKSPACE, "workspace", "Workspace → Agent gateway policy / Model policy"))


def index(text: str) -> list[Statement]:
    return index_statements(str(text or ""), every_action=action_ids())


def builder_model_of(statement: Statement):
    return parse_est(statement.est, statement.text)


def custom_source(statement: Statement) -> str:
    return SOURCE_BUILDER if builder_model_of(statement) is not None else SOURCE_HAND_WRITTEN


def _action_facts(actions: tuple[str, ...]) -> dict[str, list[str]]:
    groups: list[str] = []
    points: list[str] = []
    for action in actions:
        try:
            groups.append(action_info(action)["group"])
            points.append(point_of(action)["label"])
        except KeyError:
            continue
    return {"groups": list(dict.fromkeys(groups)), "points": list(dict.fromkeys(points))}


def describe(statement: Statement, names: NameIndex, *, source: str | None = None) -> dict[str, Any]:
    model = builder_model_of(statement) if source is None else None
    source = source or (SOURCE_BUILDER if model is not None else SOURCE_HAND_WRITTEN)
    annotations = statement.annotations
    item = {
        "id": statement.policy_id,
        "name": annotations.get("name") or statement.policy_id,
        "description": annotations.get("description", ""),
        "template": annotations.get("template"),
        "source": source,
        "editable": source in (SOURCE_BUILDER, SOURCE_HAND_WRITTEN),
        "effect": statement.effect,
        "actions": list(statement.actions),
        **_action_facts(statement.actions),
        "text": statement.text,
        "digest": statement.digest,
        "sentence": outline(statement, names),
        "scope": scope_label(statement, names),
        "references": statement.references.to_dict(),
        "warnings": warnings(statement, names) if source in (SOURCE_BUILDER, SOURCE_HAND_WRITTEN) else [],
        "model": None,
    }
    if model is not None:
        item.update(sentence=builder_sentence(model, names), scope=builder_scope(model, names), model=model.to_json())
    return item


async def _published(db: AsyncSession) -> PolicySetVersion | None:
    stmt = select(PolicySetVersion).where(PolicySetVersion.state == REVISION_STATE_PUBLISHED)
    return (await db.execute(stmt.order_by(PolicySetVersion.version.desc()).limit(1))).scalar_one_or_none()


async def working_version(db: AsyncSession) -> PolicySetVersion | None:
    stmt = (select(PolicySetVersion)
            .where(PolicySetVersion.state.in_([REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW]))
            .order_by(PolicySetVersion.version.desc()).limit(1))
    return (await db.execute(stmt)).scalar_one_or_none() or await _published(db)


async def _history_versions(db: AsyncSession, upto: PolicySetVersion | None) -> list[PolicySetVersion]:
    rows = (await db.execute(select(PolicySetVersion).order_by(PolicySetVersion.version))).scalars()
    chosen = [row for row in rows if row.published_at is not None and (upto is None or row.version <= upto.version)]
    if upto is not None and upto.published_at is None:
        chosen.append(upto)
    return chosen


def _last_changed(history: list[tuple[PolicySetVersion, dict[str, str]]], names: NameIndex) -> dict[str, dict]:
    last: dict[str, dict] = {}
    previous: dict[str, str] = {}
    for row, digests in history:
        for policy_id, digest in digests.items():
            if previous.get(policy_id) != digest:
                stamp = row.updated_at or row.created_at
                last[policy_id] = {"version": row.version, "by": row.created_by,
                                   "by_name": names.user(str(row.created_by or "")) or None,
                                   "at": stamp.isoformat() if stamp else None}
        previous = digests
    return last


def _digests(row: PolicySetVersion) -> dict[str, str]:
    try:
        return {item.policy_id: item.digest for item in index(row.policies_text)}
    except ValueError:
        return {}


async def generated_items(db: AsyncSession, names: NameIndex) -> list[dict[str, Any]]:
    baseline = await load_baseline(db)
    items = []
    for statement in index(baseline.text):
        source, edit_where = next(((name, where) for prefix, name, where in _GENERATED
                                   if statement.policy_id.startswith(prefix)), ("platform", None))
        item = describe(statement, names, source=source)
        item.update(change=None, last_changed=None, edit_where=edit_where)
        items.append(item)
    return items


def edit_target(row: PolicySetVersion | None) -> dict[str, Any] | None:
    from .custom_policies import custom_digest

    if row is None:
        return {"version": 0, "digest": custom_digest(""), "creates_draft": True}
    if row.state == REVISION_STATE_DRAFT:
        return {"version": row.version, "digest": row.digest, "creates_draft": False}
    if row.state == REVISION_STATE_PUBLISHED:
        return {"version": row.version, "digest": row.digest, "creates_draft": True}
    return None


async def policies_view(
    db: AsyncSession, row: PolicySetVersion | None, *, include_generated: bool = False
) -> dict[str, Any]:
    from .store import serialize_version

    names = await load_name_index(db)
    published = await _published(db)
    current = index(row.policies_text) if row is not None else []
    viewing_published = row is not None and published is not None and row.version == published.version
    base = {item.policy_id: item for item in index(published.policies_text)} if published is not None else {}
    history = [(version, _digests(version)) for version in await _history_versions(db, row)]
    last = _last_changed(history, names)
    items: list[dict[str, Any]] = []
    present = set()
    for statement in current:
        present.add(statement.policy_id)
        item = describe(statement, names)
        before = base.get(statement.policy_id)
        if viewing_published or (before is not None and before.digest == statement.digest):
            item["change"] = CHANGE_UNCHANGED
        else:
            item["change"] = CHANGE_CHANGED if before is not None else CHANGE_NEW
        item["last_changed"] = last.get(statement.policy_id)
        items.append(item)
    if not viewing_published:
        for policy_id, statement in base.items():
            if policy_id in present:
                continue
            item = describe(statement, names)
            item.update(change=CHANGE_REMOVED, last_changed=last.get(policy_id))
            items.append(item)
    counts = {state: sum(1 for item in items if item["change"] == state)
              for state in (CHANGE_NEW, CHANGE_CHANGED, CHANGE_REMOVED)}
    payload: dict[str, Any] = {
        "version": serialize_version(row, include_text=False) if row is not None else None,
        "published_version": published.version if published is not None else None,
        "author_name": names.user(str(row.created_by or "")) if row is not None else None,
        "items": items,
        "changes": counts,
        "edit_target": edit_target(row),
    }
    if include_generated:
        payload["generated"] = await generated_items(db, names)
    return payload


async def policy_history(db: AsyncSession, policy_id: str) -> list[dict[str, Any]]:
    names = await load_name_index(db)
    rows = (await db.execute(select(PolicySetVersion).order_by(PolicySetVersion.version))).scalars()
    history: list[dict[str, Any]] = []
    previous: str | None = None
    for version in rows:
        digest = _digests(version).get(policy_id)
        if digest is None and previous is None:
            continue
        change = (CHANGE_REMOVED if digest is None else CHANGE_NEW if previous is None
                  else CHANGE_UNCHANGED if digest == previous else CHANGE_CHANGED)
        history.append({"version": version.version, "state": version.state, "change": change, "digest": digest,
                        "by": version.created_by, "by_name": names.user(str(version.created_by or "")) or None,
                        "published_at": version.published_at.isoformat() if version.published_at else None})
        previous = digest
    return history


__all__ = [
    "CHANGE_CHANGED",
    "CHANGE_NEW",
    "CHANGE_REMOVED",
    "CHANGE_UNCHANGED",
    "SOURCE_BUILDER",
    "SOURCE_HAND_WRITTEN",
    "custom_source",
    "describe",
    "edit_target",
    "generated_items",
    "index",
    "policies_view",
    "policy_history",
    "working_version",
]
