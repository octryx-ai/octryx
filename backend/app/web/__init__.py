"""Web Admin UI package with lazy router loading."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from fastapi import APIRouter
from fastapi.responses import RedirectResponse as _RedirectResponse

_ROUTER: APIRouter | None = None


def _build_router() -> APIRouter:
    router = APIRouter(tags=["web"])
    admin_router = APIRouter(prefix="/admin", tags=["web"])

    async def _redirect_admin_root():
        return _RedirectResponse(url="/chat", status_code=303)

    auth = import_module(".routers.auth", __name__)
    chat_api_v1 = import_module(".routers.chat_api_v1", __name__)
    chat_approvals = import_module(".routers.chat_approvals", __name__)
    chat_artifact_image = import_module(".routers.chat_artifact_image", __name__)
    chat_main = import_module(".routers.chat_main", __name__)
    mobile_app = import_module(".routers.mobile_app", __name__)
    chat_turn_execution = import_module(".routers.chat_turn_execution", __name__)
    chat_sessions_actions = import_module(".routers.chat_sessions_actions", __name__)
    chat_sessions_threads = import_module(".routers.chat_sessions_threads", __name__)
    chat_thread_bulk = import_module(".routers.chat_thread_bulk", __name__)
    chat_thread_list = import_module(".routers.chat_thread_list", __name__)
    chat_session_view = import_module(".routers.chat_session_view", __name__)
    panel_agents = import_module(".routers.panel_agents", __name__)
    panel_agent_designer = import_module(".routers.panel_agent_designer", __name__)
    panel_analytics = import_module(".routers.panel_analytics", __name__)
    panel_channels = import_module(".routers.panel_channels", __name__)
    panel_calls = import_module(".routers.panel_calls", __name__)
    panel_connectors = import_module(".routers.panel_connectors", __name__)
    panel_connector_lifecycle = import_module(".routers.panel_connector_lifecycle", __name__)
    panel_egress = import_module(".routers.panel_egress", __name__)
    panel_engineering_knowledge = import_module(".routers.panel_engineering_knowledge", __name__)
    panel_mcp_capabilities = import_module(".routers.panel_mcp_capabilities", __name__)
    panel_entity_graph = import_module(".routers.panel_entity_graph", __name__)
    panel_office = import_module(".routers.panel_office", __name__)
    panel_corp_identity_workspace = import_module(".routers.panel_corp_identity_workspace", __name__)
    panel_policy_lists = import_module(".routers.panel_policy_lists", __name__)
    panel_projects_a = import_module(".routers.panel_projects_a", __name__)
    panel_projects_b = import_module(".routers.panel_projects_b", __name__)
    panel_projects_c = import_module(".routers.panel_projects_c", __name__)
    panel_named_connections = import_module(".routers.panel_named_connections", __name__)
    panel_rest_connectors = import_module(".routers.panel_rest_connectors", __name__)
    panel_confluence_pages = import_module(".routers.panel_confluence_pages", __name__)
    panel_providers = import_module(".routers.panel_providers", __name__)
    panel_model_routes = import_module(".routers.panel_model_routes", __name__)
    panel_research_policies = import_module(".routers.panel_research_policies", __name__)
    panel_tasks = import_module(".routers.panel_tasks", __name__)
    panel_users = import_module(".routers.panel_users", __name__)
    panel_webhooks = import_module(".routers.panel_webhooks", __name__)
    panel_inbound_webhooks = import_module(".routers.panel_inbound_webhooks", __name__)
    oauth_authorize = import_module(".routers.oauth_authorize", __name__)
    plugins = import_module(".routers.plugins", __name__)
    tools_scripts = import_module(".routers.tools_scripts", __name__)
    ui_pages = import_module(".routers.ui_pages", __name__)

    admin_router.include_router(auth.router)
    admin_router.add_api_route("", _redirect_admin_root, methods=["GET", "HEAD"])
    admin_router.include_router(ui_pages.router)
    admin_router.include_router(chat_main.router)
    admin_router.include_router(chat_turn_execution.router)
    admin_router.include_router(chat_artifact_image.router)
    admin_router.include_router(chat_sessions_threads.router)
    admin_router.include_router(chat_thread_bulk.router)
    admin_router.include_router(chat_thread_list.router)
    admin_router.include_router(chat_session_view.router)
    admin_router.include_router(chat_approvals.router)
    admin_router.include_router(chat_sessions_actions.router)
    admin_router.include_router(tools_scripts.router)
    admin_router.include_router(plugins.router)
    admin_router.include_router(panel_users.router)
    admin_router.include_router(panel_projects_a.router)
    admin_router.include_router(panel_projects_b.router)
    admin_router.include_router(panel_projects_c.router)
    admin_router.include_router(panel_named_connections.router)
    admin_router.include_router(panel_confluence_pages.router)
    admin_router.include_router(panel_providers.router)
    admin_router.include_router(panel_model_routes.router)
    admin_router.include_router(panel_research_policies.router)
    admin_router.include_router(panel_engineering_knowledge.router)
    admin_router.include_router(panel_office.router)
    admin_router.include_router(panel_corp_identity_workspace.router)
    admin_router.include_router(panel_connector_lifecycle.router)
    admin_router.include_router(panel_connectors.router)
    admin_router.include_router(panel_rest_connectors.router)
    admin_router.include_router(panel_policy_lists.router)
    admin_router.include_router(panel_egress.router)
    admin_router.include_router(panel_tasks.router)
    admin_router.include_router(panel_agents.router)
    admin_router.include_router(panel_agent_designer.router)
    admin_router.include_router(panel_entity_graph.router)
    admin_router.include_router(panel_inbound_webhooks.router)
    admin_router.include_router(panel_webhooks.router)
    admin_router.include_router(panel_channels.router)
    admin_router.include_router(panel_mcp_capabilities.router)
    admin_router.include_router(panel_calls.router)
    admin_router.include_router(chat_api_v1.router)
    admin_router.include_router(panel_analytics.router)

    router.include_router(admin_router)
    router.include_router(auth.router, prefix="/chat")
    router.include_router(oauth_authorize.router)
    router.include_router(chat_main.router)
    router.include_router(chat_turn_execution.router)
    router.include_router(chat_artifact_image.router)
    router.include_router(chat_sessions_threads.router)
    router.include_router(chat_thread_bulk.router)
    router.include_router(chat_thread_list.router)
    router.include_router(chat_session_view.router)
    router.include_router(chat_approvals.router)
    router.include_router(chat_sessions_actions.router)
    router.include_router(chat_api_v1.router)
    # Octryx Mobile: the Home Screen app under /m (its page, manifest and service worker).
    router.include_router(mobile_app.router)

    return router


def __getattr__(name: str) -> Any:
    global _ROUTER
    if name == "router":
        if _ROUTER is None:
            _ROUTER = _build_router()
        return _ROUTER
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["router"]
