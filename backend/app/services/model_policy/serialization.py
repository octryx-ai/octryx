"""API views of Model Policy rows. Identifiers, states and content only; no approval reasons."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...models import ModelPolicy, ModelPolicyRevision


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _lifecycle(revision: ModelPolicyRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "revision": revision.revision,
        "state": revision.state,
        "digest": revision.digest,
        "created_by": revision.created_by,
        "created_at": _iso(revision.created_at),
        "updated_at": _iso(revision.updated_at),
        "submitted_by": revision.submitted_by,
        "submitted_at": _iso(revision.submitted_at),
        "approval_id": revision.approval_id,
        "published_by": revision.published_by,
        "published_at": _iso(revision.published_at),
        "retired_by": revision.retired_by,
        "retired_at": _iso(revision.retired_at),
    }


def serialize_policy_revision(revision: ModelPolicyRevision) -> dict[str, Any]:
    return {**_lifecycle(revision), "entries": revision.entries_json}


def serialize_policy(policy: ModelPolicy, revisions: list[ModelPolicyRevision] | None = None) -> dict[str, Any]:
    payload = {
        "id": policy.id,
        "workspace_id": policy.workspace_id,
        "name": policy.name,
        "status": policy.status,
        "created_by": policy.created_by,
        "created_at": _iso(policy.created_at),
        "updated_at": _iso(policy.updated_at),
    }
    if revisions is not None:
        payload["revisions"] = [serialize_policy_revision(item) for item in revisions]
    return payload


__all__ = ["serialize_policy", "serialize_policy_revision"]
