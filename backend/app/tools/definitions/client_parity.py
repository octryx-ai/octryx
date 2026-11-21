"""Definitions of the client's workflow-run, approval and task tools in the chat.

Same names and arguments as the Octryx client's MCP tools (``mcp_parity_registration``, ``mcp_knowledge_protocol``);
the handlers are the client's (``tools/client_parity_tools``). The Workspace is always the chat's.
"""

from __future__ import annotations

_CONFIRMED = " In a chat it runs under the write plan the person confirmed (propose_write_plan)."


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or []}}}


_STR = {"type": "string"}


def get_client_run_definitions() -> dict[str, dict]:
    return {
        "workflow_catalog": _fn(
            "workflow_catalog",
            "List the Workspace's governed workflows with their capability_class, whether running one needs a "
            "confirmation, and whether one is phased (needs a Work item). Start one with select_workflow or "
            "start_workflow."),
        "workflow_run_status": _fn(
            "workflow_run_status",
            "The workflow run this chat follows (or run_id): its current phase, loop i of n, what it waits for and "
            "where the person decides (with the decision's payload_hash), and what the next gate needs; detail=true "
            "adds the code style and the earlier change.",
            {"run_id": _STR, "detail": {"type": "boolean"}}),
        "workflow_select": _fn(
            "workflow_select",
            "Continue an active workflow run in this chat, by run_id or its Work item (work_item). Only the run's "
            "requester continues it. A new run starts with start_workflow." + _CONFIRMED,
            {"run_id": _STR, "work_item": _STR}),
        "workflow_decide": _fn(
            "workflow_decide",
            "Take the person's decision of what the run this chat follows waits for, when workflow_run_status says "
            "the decision is in_terminal: a confirmation (action confirm, change or stop), a question (action reply "
            "with reply text) or a paused run (continue with k, retry_action, change_plan, abort). Stop and abort "
            "carry the person's reason. Pass the decision's payload_hash. Only call it after the person told you "
            "their decision. Approvals by another person are decided in Octryx." + _CONFIRMED,
            {"run_id": _STR, "action": _STR, "payload_hash": _STR, "k": {"type": "integer"}, "reply": _STR,
             "human_verified_criteria": {"type": "array", "items": _STR}, "reason": _STR},
            ["run_id", "action", "payload_hash"]),
        "workflow_action_request": _fn(
            "workflow_action_request",
            "Ask the platform to act for the run this chat follows: action is one of jira.create_issue, "
            "jira.comment, jira.transition (params.work_state, never a Jira status), scm.create_branch, scm.push, "
            "scm.open_pr, ci.status. It runs on the server with the Workspace's connections, only within the current "
            "phase's class." + _CONFIRMED,
            {"action": _STR, "params": {"type": "object"}}, ["action"]),
        "approval_get": _fn("approval_get", "Read one approval you may see (status, action, session or run).",
                            {"approval_id": _STR}, ["approval_id"]),
        "approval_list": _fn("approval_list", "List approvals you may see (status pending, approved or rejected).",
                             {"status": {"type": "string", "enum": ["pending", "approved", "rejected"]}}),
        "product_run_list": _fn(
            "product_run_list",
            "List the Workspace's newest workflow runs (workflow_runs) and scheduled task runs (runs) you may read, "
            "newest first. Chat turns are not runs and are left out; include_chat_turns (rarely needed) adds them.",
            {"include_chat_turns": {"type": "boolean"}}),
        "task_list": _fn("task_list", "List your scheduled tasks (optionally of one Workspace).",
                         {"project_id": _STR}),
        "task_runs": _fn("task_runs", "The recent runs of one of your scheduled tasks.", {"task_id": _STR},
                         ["task_id"]),
        "policy_effective": _fn(
            "policy_effective",
            "A Workspace's effective command policy: read-only enforcement, always-deny patterns, the diagnosis "
            "read-only commands.", {"project_id": _STR}, ["project_id"]),
        **get_client_knowledge_definitions(),
    }


def get_client_knowledge_definitions() -> dict[str, dict]:
    """The client's Knowledge extras (gap B group 4)."""
    return {
        "knowledge_sources": _fn(
            "knowledge_sources",
            "List the Workspace's Knowledge sources (title, source key, current revision, source_url and cite_as "
            "where known), newest first; page with limit (1-200) and offset.",
            {"limit": {"type": "integer"}, "offset": {"type": "integer"}}),
        "knowledge_projects": _fn("knowledge_projects", "List the Workspaces you may target (id and name)."),
        "entity_search": _fn(
            "entity_search",
            "Search knowledge-graph entities (person, repository, system, ticket, concept, ...) by name or key. "
            "Each node carries its trust_level (bronze single source, silver confirmed, gold curated).",
            {"query": _STR, "project_id": _STR, "node_type": _STR, "limit": {"type": "integer"}}, ["query"]),
        "entity_neighbors": _fn(
            "entity_neighbors",
            "Load an entity's graph neighborhood (edges and neighbor nodes) by id, node_key or display name.",
            {"node": _STR, "limit": {"type": "integer"}}, ["node"]),
        "knowledge_feedback": _fn(
            "knowledge_feedback",
            "Rate an Octryx answer (session_id, message_id of an assistant message in this Workspace) like "
            "the chat's thumbs: rating good|bad, optional liked/disliked texts and aspects {correctness|sources|"
            "completeness|clarity|tool_use|speed: liked|disliked}. Re-rating replaces it. Only when the person asks."
            + _CONFIRMED,
            {"session_id": _STR, "message_id": _STR, "rating": {"type": "string", "enum": ["good", "bad"]},
             "liked": _STR, "disliked": _STR, "aspects": {"type": "object"}},
            ["session_id", "message_id", "rating"]),
    }


__all__ = ["get_client_knowledge_definitions", "get_client_run_definitions"]
