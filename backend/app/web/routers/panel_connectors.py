"""Auto-extracted router module: panel_connectors."""

from functools import partial

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._connectors import (
    ConnectorSaveRequest,
    DatabaseConnectorRequest,
    DatabaseConnectorUpdateRequest,
    DatabaseQueryToolRequest,
    DatabaseQueryToolUpdateRequest,
)
from app.schemas.admin.admin_panel._repositories import GitHubRepositoryCreateRequest
from app.services.database_tool import query_tool_admin

from ...db import get_db
from ...services import connector_test_service, database_tool_service
from ...services.access_control import require_existing_workspace
from ...services.admin.connector import _admin_connector_activation, admin_connector_service
from ...services.admin.project.named_connection_workspaces import with_workspace_connection_counts
from ...services.agent_mode import list_agent_modes, serialize_agent_mode
from ...services.github_connector import service as github_connector_service
from ...services.secure_work.servicenow.known_values import known_values
from ...services.secure_work.servicenow.source import IntakeSourceError, connector_config, source_error
from .._helpers.api_guards import _require_admin_api
from .._helpers.panel_serializers import _serialize_connector

router = APIRouter()


@router.get("/chat/api/panel/connectors")
async def panel_list_connectors(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    connectors = await admin_connector_service.list_connectors(db, serialize_connector=_serialize_connector)
    return JSONResponse(await with_workspace_connection_counts(db, connectors))


@router.get("/chat/api/panel/tool-catalog")
async def panel_list_tool_catalog(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await _admin_connector_activation.list_tool_catalog_payload(db))


@router.get("/chat/api/panel/database-connectors")
async def panel_list_database_connectors(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await database_tool_service.list_database_connectors(db))


@router.post("/chat/api/panel/database-connectors")
async def panel_create_database_connector(
    payload: DatabaseConnectorRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await database_tool_service.create_database_connector(
            db,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.put("/chat/api/panel/database-connectors/{connector_id}")
async def panel_update_database_connector(
    connector_id: str,
    payload: DatabaseConnectorUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await database_tool_service.update_database_connector(
            db, connector_id=connector_id, payload=payload.model_dump(exclude_none=True)
        )
    )


@router.post("/chat/api/panel/database-connectors/{connector_id}/test")
async def panel_test_database_connector(connector_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    from app.services.database_tool.health import test_and_record_database

    result = await test_and_record_database(db, connector_id)
    await db.commit()
    return JSONResponse(result)


@router.delete("/chat/api/panel/database-connectors/{connector_id}")
async def panel_delete_database_connector(connector_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Audited; releases the stored password/DSN (automation V4)."""
    user = await _require_admin_api(request, db)
    from ...services.database_tool.lifecycle import remove_database

    return JSONResponse(await remove_database(db, connector_id=connector_id, actor_user_id=user.id))


@router.get("/chat/api/panel/database-query-runs")
async def panel_recent_database_queries(request: Request, limit: int = 20, db: AsyncSession = Depends(get_db)):
    from ...services.database_tool.lifecycle import recent_query_runs

    await _require_admin_api(request, db)
    return JSONResponse(await recent_query_runs(db, limit=limit))


@router.get("/chat/api/panel/database-tools")
async def panel_list_database_tools(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await query_tool_admin.list_database_query_tools(db))


@router.post("/chat/api/panel/database-tools")
async def panel_create_database_tool(
    payload: DatabaseQueryToolRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await query_tool_admin.create_database_query_tool(
            db,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.put("/chat/api/panel/database-tools/{tool_id}")
async def panel_update_database_tool(
    tool_id: str,
    payload: DatabaseQueryToolUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await query_tool_admin.update_database_query_tool(
            db,
            tool_id=tool_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.delete("/chat/api/panel/database-tools/{tool_id}")
async def panel_delete_database_tool(tool_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await query_tool_admin.delete_database_query_tool(db, tool_id=tool_id))


@router.get("/chat/api/panel/modes")
async def panel_list_run_modes(request: Request, db: AsyncSession = Depends(get_db)):
    """The shipped run modes, read only: Actions and webhooks label their runs with one."""
    await _require_admin_api(request, db)
    return JSONResponse([serialize_agent_mode(mode) for mode in list_agent_modes()])


@router.put("/chat/api/panel/connectors/{tool_name}")
async def panel_save_connector(
    tool_name: str,
    payload: ConnectorSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_connector_service.save_connector(
            db,
            tool_name=tool_name,
            payload=payload.model_dump(exclude_none=True),
            serialize_connector=_serialize_connector,
            owner_id=user.id,
        )
    )


@router.post("/chat/api/panel/connectors/{tool_name}/test")
async def panel_test_connector(tool_name: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_connector_service.test_connector(
            db,
            tool_name=tool_name,
            run_connection_test=partial(connector_test_service.run_connector_connection_test, db=db, scope_check=True),
        )
    )


@router.get("/chat/api/panel/connectors/{tool_name}/health-log")
async def panel_connector_health_log(
    tool_name: str,
    request: Request,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_connector_service.list_connector_health_history(
            db,
            tool_name=tool_name,
            limit=limit,
        )
    )


@router.get("/chat/api/panel/connectors/servicenow/limit-values")
async def panel_servicenow_limit_values(request: Request, table: str = "incident", db: AsyncSession = Depends(get_db)):
    """Groups and services of the global connection's last records (read-only suggestions for its limit)."""
    await _require_admin_api(request, db)
    try:
        return JSONResponse(await known_values(await connector_config(db, None), limited=False, table=table))
    except IntakeSourceError as error:
        raise source_error(error) from None


@router.get("/chat/api/panel/connectors/github/repositories")
async def panel_list_github_connector_repositories(
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await github_connector_service.list_github_connector_repositories(db, limit=limit))


@router.post("/chat/api/panel/connectors/github/repositories")
async def panel_create_github_connector_repository(
    payload: GitHubRepositoryCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await github_connector_service.create_github_connector_repository(
            db,
            payload.model_dump(exclude_none=True),
        )
    )


@router.delete("/chat/api/panel/connectors/{tool_name}")
async def panel_delete_connector(
    tool_name: str, request: Request, confirm_name: str = "", db: AsyncSession = Depends(get_db)
):
    """Refused while anything uses the connector; the caller repeats its name (automation V2)."""
    user = await _require_admin_api(request, db)
    from ...services.admin.connector.connector_lifecycle import guarded_delete_connector

    return JSONResponse(
        await guarded_delete_connector(db, tool_name=tool_name, confirm_name=confirm_name, actor_user_id=user.id)
    )


