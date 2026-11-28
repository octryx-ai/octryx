"""HTTP application wiring for middleware, routes, and exception handlers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.exceptions.api import AuthenticationError, AuthorizationError, ConflictError
from app.exceptions.api import ValidationError as DomainValidationError
from app.exceptions.base import NotFoundError, OctryxError

from .api.routes import observability as observability_routes
from .api.routes.agent_board import agent_board as agent_board_routes
from .api.routes.agent_gateway import agent_engines as agent_engines_routes
from .api.routes.agent_gateway import agent_gateway as agent_gateway_routes
from .api.routes.agent_gateway import agent_gateway_git as agent_gateway_git_routes
from .api.routes.agent_gateway import agent_gateway_handoff_policy as agent_gateway_handoff_policy_routes
from .api.routes.agent_gateway import agent_gateway_hook_key as agent_gateway_hook_key_routes
from .api.routes.agent_gateway import agent_gateway_repository as agent_gateway_repository_routes
from .api.routes.agent_gateway import agent_gateway_runs as agent_gateway_runs_routes
from .api.routes.agent_gateway import agent_gateway_sandbox as agent_gateway_sandbox_routes
from .api.routes.agent_gateway import agent_gateway_workspace as agent_gateway_workspace_routes
from .api.routes.channels import channels, connector_watchers, speakers, stt, teams, teams_calling, webhooks
from .api.routes.devices import device_archives as device_archives_routes
from .api.routes.devices import device_channel as device_channel_routes
from .api.routes.devices import device_jobs as device_job_routes
from .api.routes.devices import device_policy as device_policy_routes
from .api.routes.devices import device_runners as device_runner_routes
from .api.routes.devices import devices as device_routes
from .api.routes.devices import octryx_client_install as octryx_client_install_routes
from .api.routes.devices import terminal as terminal_api
from .api.routes.error_contracts import (
    authentication_handler,
    authorization_handler,
    conflict_handler,
    domain_error_handler,
    domain_validation_handler,
    http_exception_handler,
    not_found_handler,
    validation_exception_handler,
)
from .api.routes.identity import api_keys, auth, auth_users, invitations, privacy
from .api.routes.identity import linked_accounts as linked_account_routes
from .api.routes.identity import oauth_provider as oauth_provider_routes
from .api.routes.knowledge import (
    knowledge_bindings,
    knowledge_connection_repositories,
    knowledge_episodes,
    knowledge_evidence_search,
    knowledge_evidence_sources,
    knowledge_evidence_workspace,
    knowledge_feedback,
    knowledge_graph,
    knowledge_memory,
    knowledge_object_retention,
    knowledge_packages,
    knowledge_projection_recovery,
    knowledge_repositories,
    knowledge_search_answer,
    knowledge_source_connectors,
    knowledge_source_originals,
    knowledge_source_settings,
    knowledge_structured_graph,
    mcp_knowledge,
)
from .api.routes.mobile import mobile as mobile_routes
from .api.routes.mobile import mobile_live as mobile_live_routes
from .api.routes.models import model_catalog as model_catalog_routes
from .api.routes.models import model_gateway_inbound, model_gateway_openai, model_policies, providers
from .api.routes.models import model_selection as model_selection_routes
from .api.routes.models import unpriced_model_policy as unpriced_model_policy_routes
from .api.routes.platform import (
    admin_notifications,
    analytics,
    audit,
    data_transfer,
    entity_versions,
    feature_flags,
    instructions,
    packages,
    personalities,
    prompt_catalog,
)
from .api.routes.platform import operations_live as operations_live_routes
from .api.routes.platform import plugins as plugins_routes
from .api.routes.platform import problems as problems_routes
from .api.routes.policy import classification_policy as classification_policy_routes
from .api.routes.policy import coding_governance
from .api.routes.policy import command_safety as command_safety_routes
from .api.routes.policy import compliance_audit as compliance_audit_routes
from .api.routes.policy import content_security as content_security_routes
from .api.routes.policy import data_classification as data_classification_routes
from .api.routes.policy import governance_approval_rule as governance_approval_rule_routes
from .api.routes.policy import policy_engine as policy_engine_routes
from .api.routes.policy import policy_engine_bench as policy_engine_bench_routes
from .api.routes.policy import policy_engine_builder as policy_engine_builder_routes
from .api.routes.policy import policy_engine_catalog as policy_engine_catalog_routes
from .api.routes.policy import policy_engine_detectors as policy_engine_detectors_routes
from .api.routes.secure_work import (
    secure_work,
    secure_work_change_plans,
    secure_work_close,
    secure_work_intake,
    secure_work_intake_setup,
    secure_work_platform_items,
    secure_work_servicenow,
    secure_work_workflows,
)
from .api.routes.sessions import approvals, call_agent, canvas, clarifications, notifications, sessions
from .api.routes.sessions import attention as attention_routes
from .api.routes.sessions import inbox as inbox_routes
from .api.routes.sessions import session_handovers as session_handover_routes
from .api.routes.sessions import session_transcripts as session_transcripts_routes
from .api.routes.sessions import tool_approvals as tool_approvals_routes
from .api.routes.skills import skill_catalog_router as skill_catalog_routes
from .api.routes.workers import workers
from .api.routes.workflows import (
    agent_chains,
    agent_definition_revisions,
    check_proposals,
    flow_definitions,
    tasks,
    workflow_checks,
)
from .api.routes.workflows import phased_workflows as phased_workflow_routes
from .api.routes.workflows import pr_review_bot as pr_review_bot_routes
from .api.routes.workflows import review_defaults as review_defaults_routes
from .api.routes.workflows import work_item_analysis as work_item_analysis_routes
from .api.routes.workflows import workflow_handoffs as workflow_handoff_routes
from .api.routes.workflows import workflow_run_emergency_stop as workflow_run_emergency_stop_routes
from .api.routes.workflows import workflow_runs as workflow_run_routes
from .api.routes.workspaces import code_graph_admin as code_graph_admin_routes
from .api.routes.workspaces import code_style as code_style_routes
from .api.routes.workspaces import connections_admin as connections_admin_routes
from .api.routes.workspaces import effective_setup, projects, web_search_sources, workspace_repositories
from .api.routes.workspaces import limits_overview as limits_overview_routes
from .api.routes.workspaces import mcp_workspace_allow as mcp_workspace_allow_routes
from .api.routes.workspaces import setup_onboarding as setup_onboarding_routes
from .api.routes.workspaces import work_roles_admin as work_roles_admin_routes
from .api.routes.workspaces import workspace_connections as workspace_connections_routes
from .api.routes.workspaces import workspace_content_handling as workspace_content_handling_routes
from .api.routes.workspaces import workspace_members as workspace_members_routes
from .api.routes.workspaces import workspace_models as workspace_models_routes
from .api.routes.workspaces import workspace_settings as workspace_settings_routes
from .api.routes.workspaces import workspace_work_me as workspace_work_me_routes
from .config import get_settings
from .http_security import parse_cors_allowed_origins
from .mash.master.routers.auth import router as mash_auth_router
from .mash.master.routers.platforms import router as mash_platforms_router
from .mash.master.routers.policies import router as mash_policies_router
from .mash.master.routers.sync import router as mash_sync_router
from .middleware.audit import audit_middleware
from .middleware.context import DataViewerScopeMiddleware, request_context_middleware
from .middleware.security import (
    MultipartAdmissionMiddleware,
    PanelCsrfBoundaryMiddleware,
    TrustedProxyBoundaryMiddleware,
    log_admission_configuration,
    log_rate_limit_retention_configuration,
    rate_limit_middleware,
)
from .middleware.telemetry import observability_middleware
from .middleware.transport.compression import ResponseCompressionMiddleware
from .runtime_toggles import host_terminal_enabled
from .services.mcp_knowledge_protocol import KNOWLEDGE_MCP_MOUNT_PATH, create_knowledge_mcp_protocol_app
from .trusted_proxy_policy import log_boundary_configuration
from .web import router as web_router
from .web._helpers.admin_surface_gate import with_admin_surface_gate
from .web._helpers.private_workspace_gate import with_private_workspace_gate
from .web.static_files import SpaStaticFiles


def configure_http(app: FastAPI, *, static_dir: Path) -> None:
    _configure_middleware(app)
    _configure_routes(app, static_dir=static_dir)
    _configure_exception_handlers(app)


def _configure_middleware(app: FastAPI) -> None:
    settings = get_settings()
    allowed_origins = parse_cors_allowed_origins(settings.cors_allowed_origins)

    # Validate each request's Origin against the explicit allow-list.
    # allow_credentials=True requires Origin to be in the explicit list — we
    # enforce that explicitly rather than relying on browser behavior.
    async def _validate_origin(request: Request, call_next):
        origin = str(request.headers.get("origin") or "")
        if origin and origin not in allowed_origins:
            # Origin not in allow-list: reject preflight and vary accordingly
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = "null"
            response.headers["Vary"] = "origin"
            return response
        return await call_next(request)

    # Registered first, therefore innermost of this group — directly above
    # the router. Starlette's form parser, and its ``SpooledTemporaryFile`` for a
    # part over 1 MiB, runs while resolving a route's body, i.e. before that
    # route's dependencies authenticate anyone, so the byte budget has to sit
    # between the router and everything else. Nothing between here and the
    # trusted-proxy boundary reads the request body, so the parser boundary stays
    # intact while request context, audit and the rate limiter still wrap a
    # rejection, and CORS still labels it for an allowed origin.
    app.add_middleware(MultipartAdmissionMiddleware)
    # Registered next, therefore directly outside the multipart boundary and
    # inside CORS. A cross-site panel mutation is refused above every body parser
    # and above the router, so it never reaches routing, authentication,
    # authorization, audit attribution or persistence.
    app.add_middleware(PanelCsrfBoundaryMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-API-Key"],
    )
    # Response compression: outside the pure ASGI boundaries above (they pass a route's body through as sent)
    # and inside every ``app.middleware("http")`` layer below, which re-streams a body, so compression placed
    # outside them would never see a complete one. It never reads the request body.
    app.add_middleware(ResponseCompressionMiddleware)
    # names the route of every request over OCTRYX_SLOW_REQUEST_SECONDS (a stall had no name).
    from .middleware.telemetry.slow_requests import SlowRequestLogMiddleware

    app.add_middleware(SlowRequestLogMiddleware)
    app.add_middleware(DataViewerScopeMiddleware)
    app.middleware("http")(_validate_origin)
    app.middleware("http")(request_context_middleware)
    app.middleware("http")(observability_middleware)
    app.middleware("http")(audit_middleware)
    app.middleware("http")(rate_limit_middleware)
    # Added last, therefore outermost. Every middleware and route below
    # sees the effective client address and scheme decided by the validated
    # trusted-proxy allowlist instead of a raw forwarded header. The allowlist is
    # read per request from the current settings, like the cookie policy.
    app.add_middleware(TrustedProxyBoundaryMiddleware)
    log_boundary_configuration(settings)
    log_admission_configuration(settings)
    log_rate_limit_retention_configuration(settings)


def _configure_routes(app: FastAPI, *, static_dir: Path) -> None:
    @app.get("/favicon.ico", include_in_schema=False)
    async def _favicon_redirect() -> RedirectResponse:
        return RedirectResponse(url="/chat/static/chat/favicon.svg", status_code=307)

    for router in (
        auth.router,
        auth_users.router,
        personalities.router,
        sessions.router,
        tasks.router,
        knowledge_bindings.router,
        knowledge_evidence_search.router,
        knowledge_search_answer.router,
        knowledge_evidence_sources.router,
        knowledge_source_originals.router,
        knowledge_packages.router,
        web_search_sources.router,
        knowledge_graph.router,
        knowledge_structured_graph.router,
        knowledge_evidence_workspace.router,
        knowledge_memory.router,
        knowledge_feedback.router,
        knowledge_episodes.router,
        knowledge_object_retention.router,
        knowledge_projection_recovery.router,
        knowledge_repositories.router,
        knowledge_source_connectors.router,
        knowledge_source_settings.router,
        knowledge_connection_repositories.router,
        mcp_knowledge.router,
        providers.router,
        model_gateway_inbound.router,
        model_gateway_openai.router,
        approvals.router,
        audit.router,
        projects.router,
        webhooks.router,
        channels.router,
        clarifications.router,
        connector_watchers.router,
        teams.router,
        notifications.router,
        invitations.router,
        privacy.router,
        admin_notifications.router,
        api_keys.router,
        analytics.router,
        feature_flags.router,
        data_transfer.router,
        packages.router,
        instructions.router,
        flow_definitions.router,
        entity_versions.router,
        workers.router,
        workflow_checks.router,
        effective_setup.router,
        secure_work.router,
        secure_work_change_plans.router,
        secure_work_close.router,
        secure_work_platform_items.router,
        secure_work_intake.router,
        secure_work_intake_setup.router,
        coding_governance.router,
        workspace_repositories.router,
        check_proposals.router,
        secure_work_servicenow.router,
        secure_work_workflows.router,
        agent_chains.router,
        agent_definition_revisions.router,
        model_policies.router,
        prompt_catalog.router,
        stt.router,
        call_agent.router,
        teams_calling.router,
        observability_routes.router,
        unpriced_model_policy_routes.router,
        inbox_routes.router,
        attention_routes.router,
        workspace_members_routes.router,
        workspace_work_me_routes.router,
        workflow_run_routes.router,
        workflow_run_emergency_stop_routes.router, session_handover_routes.router, workflow_handoff_routes.router,
        work_roles_admin_routes.router,
        phased_workflow_routes.router,
        speakers.router,
        canvas.router,
        oauth_provider_routes.router,
        octryx_client_install_routes.router,
        agent_gateway_routes.router,
        agent_board_routes.router,
        agent_gateway_handoff_policy_routes.router,
        session_transcripts_routes.router,
        agent_engines_routes.router,
        work_item_analysis_routes.router,
        work_item_analysis_routes.items_router,
        agent_gateway_repository_routes.router,
        agent_gateway_hook_key_routes.router,
        agent_gateway_git_routes.router,
        agent_gateway_runs_routes.router,
        agent_gateway_sandbox_routes.router,
        agent_gateway_workspace_routes.router,
        data_classification_routes.router,
        device_routes.router,
        device_runner_routes.router,
        linked_account_routes.router,
        device_channel_routes.router,
        device_job_routes.router,
        device_policy_routes.router,
        code_style_routes.router,
        device_archives_routes.router,
        code_graph_admin_routes.router,
        review_defaults_routes.router,
        pr_review_bot_routes.router,
        mobile_routes.router,
        mobile_live_routes.router,
        classification_policy_routes.router,
        command_safety_routes.router,
        content_security_routes.router,
        tool_approvals_routes.router,
        workspace_models_routes.router,
        connections_admin_routes.router,
        workspace_connections_routes.router,
        workspace_content_handling_routes.router,
        workspace_settings_routes.router,
        policy_engine_routes.router,
        policy_engine_bench_routes.router,
        policy_engine_catalog_routes.router,
        policy_engine_builder_routes.router,
        skill_catalog_routes.router,
        policy_engine_detectors_routes.router,
        governance_approval_rule_routes.router,
        model_catalog_routes.router,
        model_selection_routes.router,
        limits_overview_routes.router,
        problems_routes.admin_router,
        problems_routes.workspace_router,
        operations_live_routes.admin_router,
        operations_live_routes.workspace_router,
        plugins_routes.router,
        plugins_routes.ui_router,
        setup_onboarding_routes.router,
        mcp_workspace_allow_routes.router,
        compliance_audit_routes.router,
        mash_auth_router,
        mash_platforms_router,
        mash_sync_router,
        mash_policies_router,
        web_router,
    ):
        app.include_router(with_private_workspace_gate(with_admin_surface_gate(router)))
    if host_terminal_enabled():
        # The host terminal is off by default: nothing uses it, and it is a shell on the host.
        # Its session_id names a PTY, not a chat session, and it names no Workspace.
        app.include_router(with_admin_surface_gate(terminal_api.router))
    knowledge_mcp_protocol_app = create_knowledge_mcp_protocol_app()
    app.state.knowledge_mcp_protocol_app = knowledge_mcp_protocol_app
    app.mount(KNOWLEDGE_MCP_MOUNT_PATH, knowledge_mcp_protocol_app, name="knowledge-mcp-protocol")
    if static_dir.exists():
        app.mount("/chat/static", SpaStaticFiles(directory=str(static_dir)), name="chat-static")
        app.mount("/admin/static", SpaStaticFiles(directory=str(static_dir)), name="admin-static")


def _configure_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(DomainValidationError, domain_validation_handler)
    app.add_exception_handler(ConflictError, conflict_handler)
    app.add_exception_handler(AuthenticationError, authentication_handler)
    app.add_exception_handler(AuthorizationError, authorization_handler)
    app.add_exception_handler(OctryxError, domain_error_handler)
