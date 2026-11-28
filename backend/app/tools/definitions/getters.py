"""The getter of every built-in tool definition domain, in catalog order."""

from __future__ import annotations

from .admin import get_admin_definitions
from .bitbucket import get_bitbucket_definitions
from .cicd import get_cicd_definitions
from .clarification import get_clarification_definitions
from .confluence import get_confluence_definitions
from .connectors import get_connectors_definitions
from .database import get_database_definitions
from .development import get_development_definitions
from .diagram import get_diagram_definitions
from .discovery import get_discovery_definitions
from .document import get_document_definitions
from .execution import get_execution_definitions
from .git import get_git_definitions
from .github import get_github_definitions
from .gitlab import get_gitlab_definitions
from .grafana import get_grafana_definitions
from .hr import get_hr_definitions
from .incident_management import get_incident_management_definitions
from .infrastructure import get_infrastructure_definitions
from .instructions import get_instruction_definitions
from .integrations import get_integrations_definitions
from .jira import get_jira_definitions
from .knowledge import get_knowledge_definitions
from .knowledge_evidence import get_knowledge_evidence_definitions
from .knowledge_memory import get_knowledge_memory_definitions
from .kubernetes import get_kubernetes_definitions
from .loki import get_loki_definitions
from .mcp import get_mcp_definitions
from .observability import get_observability_definitions
from .office import get_office_definitions
from .planning import get_orchestration_definitions, get_planning_definitions
from .presentation import get_presentation_definitions
from .prometheus import get_prometheus_definitions
from .quality import get_quality_definitions
from .secure_work import get_client_work_definitions, get_secure_work_definitions
from .session_platform import get_session_run_definitions
from .skills import get_skills_definitions
from .specification_outputs import get_specification_output_definitions
from .workflow_outputs import get_workflow_output_definitions
from .workspace import get_workspace_definitions
from .write_plan import get_write_plan_definitions

DEFINITION_GETTERS = (
    get_admin_definitions,
    get_clarification_definitions,
    get_write_plan_definitions,
    get_bitbucket_definitions,
    get_confluence_definitions,
    get_connectors_definitions,
    get_instruction_definitions,
    get_database_definitions,
    get_diagram_definitions,
    get_discovery_definitions,
    get_document_definitions,
    get_cicd_definitions,
    get_development_definitions,
    get_hr_definitions,
    get_incident_management_definitions,
    get_infrastructure_definitions,
    get_integrations_definitions,
    get_observability_definitions,
    get_office_definitions,
    get_presentation_definitions,
    get_quality_definitions,
    get_execution_definitions,
    get_git_definitions,
    get_github_definitions,
    get_gitlab_definitions,
    get_grafana_definitions,
    get_jira_definitions,
    get_knowledge_definitions,
    get_knowledge_evidence_definitions,
    get_knowledge_memory_definitions,
    get_kubernetes_definitions,
    get_loki_definitions,
    get_mcp_definitions,
    get_planning_definitions,
    get_orchestration_definitions,
    get_prometheus_definitions,
    get_secure_work_definitions,
    get_client_work_definitions,
    get_session_run_definitions,
    get_skills_definitions,
    get_workspace_definitions,
    get_workflow_output_definitions,
    get_specification_output_definitions,
)
