"""Tool classes: batch, discovery, LSP, worktrees, admin, composers and orchestration."""

from __future__ import annotations

from app.tools.admin_impl._admin_agents import (
    AdminCreateAgentTool,
    AdminGetAgentTool,
    AdminListAgentsTool,
    AdminUpdateAgentTool,
)
from app.tools.admin_impl._admin_channels import AdminCreateChannelTool, AdminListChannelsTool, AdminUpdateChannelTool
from app.tools.admin_impl._admin_diagnostics import (
    AdminGetThreadDiagnosticsTool,
    AdminGetUsageStatsTool,
    AdminListSessionsTool,
    AdminViewAuditLogTool,
)
from app.tools.admin_impl._admin_platform import (
    AdminListWebhooksTool,
    AdminPlatformStatusTool,
)
from app.tools.admin_impl._admin_roles import AdminAssignRoleTool, AdminCreateRoleTool, AdminListRolesTool
from app.tools.admin_impl._admin_tasks import AdminListTasksTool, AdminUpdateTaskTool
from app.tools.admin_impl._admin_user_accounts import (
    AdminCreateUserTool,
    AdminDeleteUserTool,
    AdminListUsersTool,
    AdminUpdateUserTool,
)
from app.tools.clarification import AskClarificationTool
from app.tools.diagram import AppendDiagramTool, CreateDiagramTool, EditDiagramTool, GetShapeLibraryTool
from app.tools.discovery_tools import ToolSchemaGetTool, ToolSearchTool
from app.tools.document import CreateDocumentTool
from app.tools.jira_release_status import JiraReleaseStatusTool
from app.tools.lsp import (
    LspDiagnosticsTool,
    LspDocumentSymbolsTool,
    LspFindReferencesTool,
    LspGoToDefinitionTool,
    LspHoverTool,
    LspWorkspaceSymbolsTool,
)
from app.tools.mcp_bridge import CallMcpServerToolTool, ListMcpServersTool, ListMcpServerToolsTool
from app.tools.mcp_resource_bridge import (
    GetMcpServerPromptTool,
    ListMcpServerPromptsTool,
    ListMcpServerResourcesTool,
    ReadMcpServerResourceTool,
)
from app.tools.orchestration import CompleteOrchestratorTool, StartOrchestratorTool
from app.tools.presentation import CreatePresentationTool
from app.tools.runtime_impl._runtime_bash_web import BatchTool
from app.tools.runtime_impl._runtime_web_search_tools import CodeSearchTool
from app.tools.worktree import (
    WorktreeCleanupTool,
    WorktreeCommitTool,
    WorktreeCreateTool,
    WorktreeDiffTool,
    WorktreeListTool,
    WorktreeMergeTool,
)
from app.tools.write_plan_tool import ProposeWritePlanTool

TOOL_CLASSES_AUX = [
    # Batch + code search
    BatchTool,
    CodeSearchTool,
    # Tool discovery (lazy runtime)
    ToolSearchTool,
    ToolSchemaGetTool,
    # LSP
    LspGoToDefinitionTool,
    LspFindReferencesTool,
    LspHoverTool,
    LspDocumentSymbolsTool,
    LspWorkspaceSymbolsTool,
    LspDiagnosticsTool,
    # Worktree
    WorktreeCreateTool,
    WorktreeListTool,
    WorktreeDiffTool,
    WorktreeCommitTool,
    WorktreeCleanupTool,
    WorktreeMergeTool,
    # Admin / RBAC
    AdminListUsersTool,
    AdminCreateUserTool,
    AdminUpdateUserTool,
    AdminDeleteUserTool,
    AdminListRolesTool,
    AdminCreateRoleTool,
    AdminAssignRoleTool,
    AdminListAgentsTool,
    AdminGetAgentTool,
    AdminListTasksTool,
    AdminListChannelsTool,
    AdminCreateChannelTool,
    AdminUpdateChannelTool,
    AdminUpdateTaskTool,
    AdminCreateAgentTool,
    AdminUpdateAgentTool,
    AdminGetThreadDiagnosticsTool,
    AdminViewAuditLogTool,
    AdminGetUsageStatsTool,
    AdminListSessionsTool,
    AdminListWebhooksTool,
    AdminPlatformStatusTool,
    ListMcpServersTool,
    ListMcpServerToolsTool,
    CallMcpServerToolTool,
    ListMcpServerResourcesTool,
    ReadMcpServerResourceTool,
    ListMcpServerPromptsTool,
    GetMcpServerPromptTool,
    # Diagram
    GetShapeLibraryTool,
    CreateDiagramTool,
    AppendDiagramTool,
    EditDiagramTool,
    # Presentation composer
    CreatePresentationTool,
    # Document composer
    CreateDocumentTool,
    # Live Jira release status (read-only)
    JiraReleaseStatusTool,
    # Clarification
    AskClarificationTool,
    # One confirmation per chat request
    ProposeWritePlanTool,
    # Orchestration
    StartOrchestratorTool,
    CompleteOrchestratorTool,
]
