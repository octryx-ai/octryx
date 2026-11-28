"""Source Sync connectors of a Workspace: list, configure, delete, run once now, last run."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.sources.sync.confluence_scope import InvalidPageTreeError
from app.services.knowledge.sources.sync.service_describe import (
    connection_candidates,
    describe_connector,
    describe_run,
    last_run,
    list_connectors,
)
from app.services.knowledge.sources.sync.service_run import run_connector

from ....db import get_db
from ....models import User
from ....models.project.knowledge_source_sync import CONNECTOR_KIND_CUSTOM_REST
from ....services.auth import get_current_user
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.projection.workspace_knowledge_state import ensure_knowledge_enabled, knowledge_state
from ....services.knowledge.runtime import get_evidence_runtime
from ....services.knowledge.sources.sync.config import validate_config
from ....services.knowledge.sources.sync.contract import ConnectorError
from ....services.knowledge.sources.sync.git_autolink import ConnectionChoiceRequiredError, unlinked_scope
from ....services.knowledge.sources.sync.git_token_service import clear_git_token, replace_git_token
from ....services.knowledge.sources.sync.jira_release_config import InvalidReleaseConfigError
from ....services.knowledge.sources.sync.owner_rules import SourceRuleRefusedError
from ....services.knowledge.sources.sync.removal import delete_connector
from ....services.knowledge.sources.sync.rest_config import InvalidRestSourceError
from ....services.knowledge.sources.sync.rest_preview import sample_rest_source
from ....services.knowledge.sources.sync.runner import SyncRefusedError
from ....services.knowledge.sources.sync.scheduler import instance_scheduler_enabled
from ....services.knowledge.sources.sync.service import configure_connector, set_access_mode
from ._knowledge_connector_http import (
    AccessModeBody,
    ConnectorConfigBody,
    GitTokenBody,
    _authorized,
    _choice_required,
    _connector,
    _field_refusal,
    _refusal,
    _secret,
    release_config_refusal,
)
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/connectors", tags=["workspace-knowledge"])


@router.get("")
async def list_workspace_connectors(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    return {
        "connectors": await list_connectors(db, authorized),
        "may_author": authorized.may_author,
        # Read-only: whether this instance runs scheduled syncs at all.
        "instance_scheduler_enabled": instance_scheduler_enabled(),
        # Whether Knowledge is enabled for this Workspace (last recorded enablement).
        "knowledge": await knowledge_state(db, authorized.project_id),
    }


@router.put("/{connector_key}")
async def configure_workspace_connector(
    workspace_id: str,
    connector_key: str,
    body: ConnectorConfigBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    try:
        config = validate_config(connector_key=connector_key, **body.model_dump())
        row = await configure_connector(db, authorized=authorized, config=config, actor_id=current_user.id,
                                        git_token=_secret(body.git_token))
    except SourceRuleRefusedError as error:
        raise HTTPException(status_code=403, detail=error.detail()) from None
    except ConnectionChoiceRequiredError as error:
        raise _choice_required(error) from None
    except ConnectorError as error:
        raise _refusal(error.reason) from None
    except InvalidReleaseConfigError as error:
        raise release_config_refusal(error) from None
    except (InvalidPageTreeError, InvalidRestSourceError) as error:
        raise _field_refusal(error) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    # A configured connector needs Knowledge; enabling it is idempotent and audited.
    knowledge = await ensure_knowledge_enabled(db, authorized=authorized, actor_id=current_user.id)
    return await describe_connector(db, row) | {"knowledge": knowledge}


@router.get("/_git-connection-candidates")
async def git_connection_candidates_for_repository(
    workspace_id: str,
    repository_url: str = Query(..., max_length=300),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The connections a repository form offers for ``repository_url`` (authors): usable here for Knowledge, with a
    credential, on the repository's host and with it inside their ``knowledge`` scope (``git_autolink.py``)."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    try:
        scope = unlinked_scope(repository_url)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return {"repository_url": scope["remote"],
            "candidates": await connection_candidates(db, authorized.project_id, scope)}


@router.get("/{connector_key}")
async def get_workspace_connector(
    workspace_id: str,
    connector_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One connector's status: configuration, schedule, freshness, last run (and, per kind, e.g. its ACL state)."""
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    return await describe_connector(db, await _connector(db, authorized, connector_key))


@router.post("/{connector_key}/sample")
async def sample_workspace_connector(
    workspace_id: str,
    connector_key: str,
    body: ConnectorConfigBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dry run of a ``custom_rest`` draft (authors): one page mapped to items, nothing ingested or saved."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    if body.kind != CONNECTOR_KIND_CUSTOM_REST:
        raise _refusal("sample_not_supported")
    try:
        config = validate_config(connector_key=connector_key, **body.model_dump())
        return await sample_rest_source(db, authorized=authorized, config=config, actor_id=current_user.id)
    except SourceRuleRefusedError as error:
        raise HTTPException(status_code=403, detail=error.detail()) from None
    except ConnectorError as error:
        raise _refusal(error.reason) from None
    except InvalidRestSourceError as error:
        raise _field_refusal(error) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


@router.put("/{connector_key}/access-mode")
async def set_workspace_connector_access_mode(
    workspace_id: str,
    connector_key: str,
    body: AccessModeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """``read_only`` | ``read_write`` of a repository source linked to a connection (authors; audited)."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    row = await _connector(db, authorized, connector_key)
    try:
        row = await set_access_mode(db, authorized=authorized, row=row, access_mode=body.access_mode,
                                    actor_id=current_user.id)
    except ConnectorError as error:
        raise _refusal(error.reason) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await describe_connector(db, row)


@router.put("/{connector_key}/git-token")
async def replace_workspace_connector_git_token(
    workspace_id: str,
    connector_key: str,
    body: GitTokenBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set or replace a Data Center repository source's own Git token (authors; checked first; audited)."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    row = await _connector(db, authorized, connector_key)
    try:
        row = await replace_git_token(db, authorized=authorized, row=row, git_token=_secret(body.git_token),
                                      actor_id=current_user.id)
    except ConnectorError as error:
        raise _refusal(error.reason) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await describe_connector(db, row)


@router.delete("/{connector_key}/git-token")
async def remove_workspace_connector_git_token(
    workspace_id: str,
    connector_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove the source's own Git token; Git signs in with the connection again (authors; audited)."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    row = await _connector(db, authorized, connector_key)
    try:
        row = await clear_git_token(db, authorized=authorized, row=row, actor_id=current_user.id)
    except ConnectorError as error:
        raise _refusal(error.reason) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await describe_connector(db, row)


@router.delete("/{connector_key}")
async def delete_workspace_connector(
    workspace_id: str,
    connector_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stop the schedule and remove the connector; the sources it already synced stay in the ledger."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    await _connector(db, authorized, connector_key)
    try:
        return await delete_connector(db, authorized=authorized, connector_key=connector_key, actor_id=current_user.id)
    except SyncRefusedError as error:
        raise _refusal(error.reason) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


@router.post("/{connector_key}/runs")
async def run_workspace_connector(
    workspace_id: str,
    connector_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run one bounded sync now and answer its report."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    row = await _connector(db, authorized, connector_key)
    # Before the run projects anything, Knowledge is enabled (idempotent, audited).
    knowledge = await ensure_knowledge_enabled(db, authorized=authorized, actor_id=current_user.id)
    try:
        runtime = get_evidence_runtime()
        run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=current_user.id)
    except SyncRefusedError as error:
        raise _refusal(error.reason) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return describe_run(run) | {"knowledge": knowledge}


@router.get("/{connector_key}/runs/last")
async def last_workspace_connector_run(
    workspace_id: str,
    connector_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The last run with its per-item outcomes (bounded; a withheld item is listed without its title)."""
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    row = await _connector(db, authorized, connector_key)
    return {"connector_key": row.connector_key, "run": describe_run(await last_run(db, row), with_outcomes=True)}
