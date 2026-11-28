"""The chat offers what the Octryx client's MCP server offers: core tools in full, the rest by name through
``tool_search`` (this keeps cheap and weak models usable)."""

from __future__ import annotations

import json

from tests.chat_session_tools_support import ACTIVE, CHAT_STATE, chat_context  # noqa: F401

CLIENT_READS = {
    "k8s": {"list_k8s_pods", "describe_k8s_pod", "get_k8s_deployments", "list_k8s_nodes"},
    "aws": {"list_aws_ec2_instances", "aws_topology_snapshot"},
    "servicenow": {"get_servicenow_record", "list_servicenow_incidents", "list_servicenow_changes"},
    "platform": {"graph_neighbors", "config_vs_manual", "ops_chain", "create_diagram", "edit_diagram"},
}






class _Message:
    def __init__(self, *calls: tuple[str, dict]):
        self.tool_calls = [{"function": {"name": name, "arguments": json.dumps(args)}} for name, args in calls]












