"""Shared helpers for the test_chat_connector_writes_* modules."""

from __future__ import annotations

JIRA = {"jira_url": "https://jira.example.test"}


EPIC = {"project_key": "CHEF", "issue_type": "Epic", "summary": "Kitchen helper v1", "description": "Kitchen helper v1 as a local web app."}


CHAT_STATE = {"class": "read_only", "enforced": True, "source": "chat_default", "escalation_decision": None,
              "chat_connector_writes": True}


PHASE_STATE = {"class": "read_only", "enforced": True, "source": "workflow_definition", "escalation_decision": None}


# AWS and Kubernetes connectors disable some tools: the policy filter then judges every offered tool, Jira's too.
WORKSPACE_WITH_DENY_RULES = {**JIRA, "connector_policies": {"aws": {"disabled_tools": ["invoke_aws_lambda"]},
                                                            "jira": {"disabled_tools": ["update_jira_ticket"]}}}


