from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.tool_result_compression.strategy_aws import _compress_aws_topology_snapshot
from app.services.tool_result_compression.strategy_code_structure import _compress_code_structure_snapshot
from app.services.tool_result_compression.strategy_documents import (
    _compress_document_ingest,
    _compress_subthread_context,
)
from app.services.tool_result_compression.strategy_knowledge import (
    _compress_confluence_page,
    _compress_confluence_search,
    _compress_jira_search,
)
from app.services.tool_result_compression.strategy_kubernetes import _compress_kubernetes_topology_snapshot
from app.services.tool_result_compression.strategy_observability import (
    _compress_grafana_alerts,
    _compress_loki_logs,
    _extract_kubectl_failed_pods,
)
from app.services.tool_result_compression.strategy_office import (
    _compress_office_document_view,
    _compress_office_element,
    _compress_office_html,
    _compress_office_query,
)
from app.services.tool_result_compression.strategy_vcs import (
    _compress_bitbucket_pull_requests,
    _compress_recent_bitbucket_commits,
    _compress_workspace_git_commits,
)

StrategyHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]

OBSERVABILITY_STRATEGIES: dict[str, StrategyHandler] = {
    "k8s_pod_failures": _extract_kubectl_failed_pods,
    "kubernetes_topology_snapshot_summary": _compress_kubernetes_topology_snapshot,
    "grafana_firing_only": _compress_grafana_alerts,
    "loki_tail_errors": _compress_loki_logs,
}

KNOWLEDGE_STRATEGIES: dict[str, StrategyHandler] = {
    "jira_extract_fields": _compress_jira_search,
    "confluence_search_summary": _compress_confluence_search,
    "confluence_page_summary": _compress_confluence_page,
}

VCS_STRATEGIES: dict[str, StrategyHandler] = {
    "bitbucket_recent_commit_summary": _compress_recent_bitbucket_commits,
    "bitbucket_pull_request_summary": _compress_bitbucket_pull_requests,
    "workspace_git_commit_summary": _compress_workspace_git_commits,
}

OFFICE_STRATEGIES: dict[str, StrategyHandler] = {
    "office_document_view_summary": _compress_office_document_view,
    "office_element_summary": _compress_office_element,
    "office_query_summary": _compress_office_query,
    "office_html_summary": _compress_office_html,
}

DOCUMENT_STRATEGIES: dict[str, StrategyHandler] = {
    "document_ingest_summary": _compress_document_ingest,
    "subthread_context_summary": _compress_subthread_context,
}

AWS_STRATEGIES: dict[str, StrategyHandler] = {
    "aws_topology_snapshot_summary": _compress_aws_topology_snapshot,
}

CODE_STRUCTURE_STRATEGIES: dict[str, StrategyHandler] = {
    "code_structure_snapshot_summary": _compress_code_structure_snapshot,
}

STRATEGY_HANDLERS: dict[str, StrategyHandler] = {
    **OBSERVABILITY_STRATEGIES,
    **KNOWLEDGE_STRATEGIES,
    **VCS_STRATEGIES,
    **OFFICE_STRATEGIES,
    **DOCUMENT_STRATEGIES,
    **AWS_STRATEGIES,
    **CODE_STRUCTURE_STRATEGIES,
}


def get_strategy_handler(strategy: str | None) -> StrategyHandler | None:
    normalized = str(strategy or "").strip()
    if not normalized:
        return None
    return STRATEGY_HANDLERS.get(normalized)


def is_supported_strategy(strategy: str | None) -> bool:
    return get_strategy_handler(strategy) is not None
