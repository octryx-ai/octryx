"""Configure the display name and version label of a Workspace repository source.

``PUT /api/v1/workspaces/{id}/knowledge/repositories/{connector_key}/label`` lets an author name a
``git_repository`` source (a launcher's ``local_snapshot`` or a ``remote_git`` one) as its binding may.
A blank value keeps the stored one. The change is audited with field names only. Files ingested from now on
are titled with the new name; already indexed files keep their title until their content changes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .....models import AuditLog
from .binding import repository_connector
from .labels import SCOPE_DISPLAY_NAME, SCOPE_VERSION_LABEL, display_label, validate_labels, with_labels

LABEL_AUDIT_ACTION = "knowledge.repository_source.labelled"


async def set_repository_labels(
    db: AsyncSession, *, project_id: str, connector_key: str, name: object, version: object, actor_id: str
) -> dict[str, Any] | None:
    """The source's labels after the change, or ``None`` for an unknown source. Raises on an invalid label."""
    new_name, new_version = validate_labels(name, version)
    connector = await repository_connector(db, project_id, connector_key)
    if connector is None:
        return None
    scope = with_labels(dict(connector.scope or {}), new_name, new_version)
    connector.scope = scope
    flag_modified(connector, "scope")
    changed = [field for field, value in (("name", new_name), ("version", new_version)) if value is not None]
    db.add(AuditLog(
        user_id=actor_id, action=LABEL_AUDIT_ACTION, resource_type="knowledge_source_connector",
        resource_id=connector.id, details={"workspace_id": project_id, "connector_key": connector_key,
                                           "fields": changed},
    ))
    await db.flush()
    return {
        "connector_key": connector_key,
        "name": scope.get(SCOPE_DISPLAY_NAME),
        "version": scope.get(SCOPE_VERSION_LABEL),
        "label": display_label(scope),
    }


__all__ = ["LABEL_AUDIT_ACTION", "set_repository_labels"]
