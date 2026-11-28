from .channels.connector_watchers import router as connector_watchers_router
from .channels.webhooks import router as webhooks_router
from .identity.api_keys import router as api_keys_router
from .identity.auth import router as auth_router
from .knowledge.mcp_knowledge import router as mcp_knowledge_router
from .models.providers import router as providers_router
from .platform.analytics import router as analytics_router
from .platform.audit import router as audit_router
from .platform.data_transfer import router as data_transfer_router
from .platform.entity_versions import router as entity_versions_router
from .platform.packages import router as packages_router
from .platform.personalities import router as personalities_router
from .sessions.approvals import router as approvals_router
from .sessions.sessions import router as sessions_router
from .workers.workers import router as workers_router
from .workflows.agent_chains import router as agent_chains_router
from .workflows.tasks import router as tasks_router
from .workspaces.projects import router as projects_router

__all__ = [
    "auth_router",
    "personalities_router",
    "sessions_router",
    "tasks_router",
    "mcp_knowledge_router",
    "providers_router",
    "approvals_router",
    "audit_router",
    "connector_watchers_router",
    "projects_router",
    "webhooks_router",
    "api_keys_router",
    "analytics_router",
    "packages_router",
    "data_transfer_router",
    "entity_versions_router",
    "workers_router",
    "agent_chains_router",
]
