"""A repository record from a Knowledge git source: the offered sources and the governed binding.

``source_catalog`` lists the Workspace's active Knowledge git sources a repository record can be created from;
``bind_source`` creates that record (``provider = knowledge_snapshot``) once per source, with its URL and branch read
from the source, never typed again. Nothing here starts or changes a sync.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ....models import (
    AuditLog,
    CodeRepository,
    ConnectorNamedConnection,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
    Project,
)
from ...knowledge.sources.repository_snapshot.remote import parse_remote
from ...knowledge.sources.sync.git_config import ACCESS_MODE, FETCH_REMOTE_GIT, validate_access_mode
from ...workflow_runs.platform.repo_ref import SNAPSHOT_PROVIDER


async def source_catalog(db, authorized) -> dict:
    rows = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == authorized.project_id,
        KnowledgeSourceConnector.kind == "git_repository", KnowledgeSourceConnector.state == "active",
    ).order_by(KnowledgeSourceConnector.connector_key).limit(100))).scalars().all()
    # Each source reports how it is read (``fetch_mode``), through which connection (its name and type, never its
    # config), what agents may do on it (``access_mode``, a source linked to a connection only; unset there means
    # read_only, repository_access.py) and how its last sync ended (state and fixed reason, not the report).
    # Two bounded lookups for the at most 100 rows.
    connection_ids = {row.connection_id for row in rows if row.connection_id}
    connections = {item.id: item for item in (await db.execute(select(ConnectorNamedConnection).where(
        ConnectorNamedConnection.id.in_(connection_ids)))).scalars().all()} if connection_ids else {}
    run_ids = {row.last_run_id for row in rows if row.last_run_id}
    runs = {run.id: run for run in (await db.execute(select(KnowledgeSourceSyncRun).where(
        KnowledgeSourceSyncRun.id.in_(run_ids)))).scalars().all()} if run_ids else {}
    items = []
    for row in rows:
        scope = dict(row.scope or {})
        try:
            location = parse_remote(scope.get("remote"))
        except Exception:
            continue
        items.append({"id": row.id, "name": location.path, "commit": scope.get("head_commit"),
                      **_source_state(row, scope, connections.get(row.connection_id), runs.get(row.last_run_id))})
    return {"items": items}


def _source_state(row, scope, connection, run) -> dict:
    try:
        access = validate_access_mode(scope.get(ACCESS_MODE)) if row.connection_id else None
    except Exception:
        access = None  # A stored value outside the closed set is not shown as either mode.
    return {
        "fetch_mode": scope.get("fetch_mode") or FETCH_REMOTE_GIT,
        "access_mode": access,
        "connection": {"name": connection.name, "type": connection.tool_name} if connection is not None else None,
        "last_sync": {"state": run.state, "reason": run.reason}
        if run is not None and run.connector_id == row.id else None,
    }


async def bind_source(db, authorized, actor_id, connector_id) -> dict:
    # Serialize duplicate bindings on the existing workspace row.
    project = (await db.execute(select(Project).where(
        Project.id == authorized.project_id, Project.is_active.is_(True),
    ).with_for_update())).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Workspace not found")
    sources = await source_catalog(db, authorized)
    selected = next((item for item in sources["items"] if item["id"] == connector_id), None)
    if selected is None:
        raise HTTPException(404, "Repository source not found")
    existing = (await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == authorized.project_id, CodeRepository.provider == SNAPSHOT_PROVIDER,
        CodeRepository.config_json["central_source"]["connector_id"].as_string() == connector_id,
    ).limit(1))).scalar_one_or_none()
    if existing:
        return {"repository_id": existing.id}
    repository_id = str(uuid4())
    repo = CodeRepository(
        id=repository_id, project_id=authorized.project_id, name=selected["name"],
        repo_root=f"/knowledge-repositories/{repository_id}", provider=SNAPSHOT_PROVIDER,
        is_active=True, last_index_status="not_indexed",
        config_json={
            "central_source": {"mode": SNAPSHOT_PROVIDER, "connector_id": connector_id},
            "operation_policy": {"read": True, "index": True, "branch": False, "write": False,
                                 "pr": False, "migration": False},
        },
    )
    db.add(repo)
    db.add(AuditLog(user_id=actor_id, action="code_repository.source_bound", resource_type="code_repository",
                    resource_id=repo.id, details={"workspace_id": authorized.project_id, "connector_id": connector_id}))
    await db.commit()
    return {"repository_id": repo.id}
