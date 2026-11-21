"""Current receiver resource proof, with actual identity and no grants or connector I/O."""
from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.named_connections.workspace_routes import active_workspace_entries, workspace_routes

from ....models import CodeRepository, ConnectorNamedConnection, User
from ....models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceHead
from ...knowledge.access.authorization import authorize_workspace
from ...knowledge.access.source_acl import visible_source
from ...project_resource_policy import require_repository_operation
from ...secure_work.access import get_scoped_work_item
from ..access import require_start_scope
from ..records import WorkflowRunError
from ..runtime_target.target import validate_target
from ..work_roles import active_human, workspace_humans
from .contract import SCOPE_KEYS, canonical_hash, refuse


def _scope(scope: dict, envelopes: dict) -> None:
    if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS or not isinstance(envelopes, dict) or not envelopes:
        refuse("needs_configuration", "Exact approved scope and artefact evidence is required")
    for kind, proof in envelopes.items():
        envelope = proof.get("envelope") if isinstance(proof, dict) else None
        record = envelope.get("record") if isinstance(envelope, dict) else None
        if not isinstance(record, dict):
            refuse("needs_configuration", "A confirmed artefact body is required")
        repository = record.get("repository")
        # Definition-of-Ready normalization uses exactly "" for an absent repository.
        if (kind == "definition_of_ready" and envelope.get("kind") == "definition_of_ready"
                and scope["repository"] is None and repository == ""):
            repository = None
        if repository not in (None, scope["repository"]):
            refuse("needs_configuration", "The artefact repository is outside the approved scope")
        for field in ("source_ids", "connection_ids", "service_ids"):
            references = record.get(field)
            if references is not None and (not isinstance(references, list)
                    or any(not isinstance(value, str) for value in references)
                    or set(references) - set(scope[field])):
                refuse("needs_configuration", "The artefact has no exact approved resource scope binding")
        for field, plural in (("source_id", "source_ids"), ("connection_id", "connection_ids"),
                              ("service_id", "service_ids")):
            if record.get(field) is not None and record[field] not in scope[plural]:
                refuse("needs_configuration", "An artefact resource is outside the approved scope")
        if record.get("work_item_id") not in (None, scope["work_item_id"]):
            refuse("needs_configuration", "The artefact Work item is outside the approved scope")
        # An untyped citation is not a document identity. Never infer ACL permission from its display URL.
        if record.get("sources"):
            refuse("needs_configuration", "Citation URLs require typed document source bindings before handoff")


def _repository_matches(repository: CodeRepository, path: str) -> bool:
    if str(repository.name or "").strip().lower() == path.lower():
        return True
    remote = urlsplit(str(repository.remote_url or ""))
    actual = remote.path.strip("/").removesuffix(".git")
    if actual.startswith("scm/"):
        actual = actual[4:]
    return bool(remote.hostname) and actual.lower() == path.lower()


async def _repository(db: AsyncSession, scope: dict) -> None:
    if scope["repository"] is None:
        return
    from ..platform.repo_ref import parse_repository

    ref = parse_repository(scope["repository"])
    if ref is None:
        refuse("needs_configuration", "The approved repository reference is invalid")
    rows = (await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == scope["workspace_id"], CodeRepository.provider == ref.provider,
        CodeRepository.is_active.is_(True)).with_for_update()
        .execution_options(populate_existing=True))).scalars().all()
    matching = [row for row in rows if _repository_matches(row, ref.path)]
    if len(matching) != 1:
        refuse("needs_configuration", "Exactly one configured repository must prove the approved reference")
    # This is metadata/read authority, not a grant to branch, write or push; those keep their dispatch checks.
    require_repository_operation(matching[0], "read")
    if ref.provider not in await active_workspace_entries(db, [ref.provider], scope["workspace_id"]):
        refuse("needs_configuration", "The repository connector is not active in the approved workspace")


async def _connections(db: AsyncSession, scope: dict) -> None:
    if not scope["connection_ids"]:
        return
    rows = (await db.execute(select(ConnectorNamedConnection).where(
        ConnectorNamedConnection.id.in_(scope["connection_ids"])).with_for_update()
        .execution_options(populate_existing=True))).scalars().all()
    if len(rows) != len(scope["connection_ids"]) or any(
            row.project_id not in (None, scope["workspace_id"]) for row in rows):
        refuse("needs_configuration", "The approved connector identities are not configured in this workspace")
    routes = await workspace_routes(db, scope["workspace_id"], {row.tool_name for row in rows}, secrets=False)
    usable = {route.id for route in routes.connections if route.bound_scopes}
    if set(scope["connection_ids"]) - usable:
        refuse("needs_configuration", "An approved connector is inactive or has no effective workspace scope")


async def _sources(db: AsyncSession, scope: dict, actor: User) -> None:
    if not scope["source_ids"]:
        return
    authorized = await authorize_workspace(db, current_user=actor, workspace_id=scope["workspace_id"])
    sources = (await db.execute(select(KnowledgeEvidenceSource).where(
        KnowledgeEvidenceSource.id.in_(scope["source_ids"]),
        KnowledgeEvidenceSource.project_id == scope["workspace_id"],
        visible_source(scope["workspace_id"], KnowledgeEvidenceSource.source_key, authorized.principal_keys))
        .with_for_update().execution_options(populate_existing=True))).scalars().all()
    if len(sources) != len(scope["source_ids"]):
        refuse("source_forbidden", "The receiver cannot read every approved source", 403)
    heads = (await db.execute(select(KnowledgeSourceHead).where(
        KnowledgeSourceHead.source_id.in_(scope["source_ids"]),
        KnowledgeSourceHead.project_id == scope["workspace_id"]).with_for_update()
        .execution_options(populate_existing=True))).scalars().all()
    if len(heads) != len(sources) or any(not head.wanted_revision_id or not head.current_revision_id
            or head.current_revision_id != head.wanted_revision_id for head in heads):
        refuse("needs_configuration", "Current, non-withdrawn document source evidence is required")


async def rights_evaluator(*, db: AsyncSession, actor: User, scope: dict, envelopes: dict,
                           runtime_target: dict | None) -> dict:
    """Prove ordinary resource scope, not model/provider admission.

    Model dispatch still admits the actual receiver under its normal provider policy;
    acceptance may therefore hold before agent execution. Work roles grant no rights.
    """
    _scope(scope, envelopes)
    current = await active_human(db, actor.id)
    if current is None or current.id not in await workspace_humans(db, scope["workspace_id"]):
        refuse("receiver_forbidden", "The receiver is not a current human workspace member", 403)
    item = await get_scoped_work_item(db, current, scope["work_item_id"]) if scope["work_item_id"] else None
    if item is not None and item.project_id != scope["workspace_id"]:
        refuse("receiver_forbidden", "The approved Work item is outside the receiver workspace", 403)
    await require_start_scope(db, current, project_id=scope["workspace_id"], item=item)
    if scope["service_ids"]:
        refuse("needs_configuration", "A declared per-service access evaluator is required")
    from .specification import validate_spec_envelopes

    await validate_spec_envelopes(db, actor=current, scope=scope, envelopes=envelopes)
    await _repository(db, scope)
    await _connections(db, scope)
    await _sources(db, scope, current)
    try:
        normalized = await validate_target(db, user=current, project_id=scope["workspace_id"], raw=runtime_target)
    except WorkflowRunError as error:
        refuse(error.code, str(error), error.status_code)
    return {"allowed": True, "actor_id": current.id,
            "scope_digest": canonical_hash({"scope": scope, "envelopes": envelopes}),
            "runtime_target": normalized}


__all__ = ["rights_evaluator"]
