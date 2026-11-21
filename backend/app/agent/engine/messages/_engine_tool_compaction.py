"""Neutral tool result compaction to keep model context concise.

Engine-owned module: it compacts only connector-neutral mechanics — workflow
capability runs, workspace files and directories, runtime commands, the MCP
bridge, and the generic fallback truncation. Connector-specific payload
knowledge (Jira, Bitbucket, Confluence, diagrams, ...) lives with the
connector modules that register their compactors in
``._tool_compaction_registry``; the dispatch here consults that registry
before falling back to the neutral handlers.
"""

from typing import Any

from ....services.prompt_catalog import render_prompt
from ....tools.tool_names import ToolName
from ...core.runtime.trace_runtime import compact_trace_value
from ._engine_message_helpers import _path_tail, _truncate_for_model
from ._tool_compaction_registry import resolve_tool_result_compactor


def _compact_workflow_capability_result(result: dict[str, Any]) -> dict[str, Any]:
    capability = result.get("workflow_capability") if isinstance(result.get("workflow_capability"), dict) else {}
    flow_run = result.get("flow_run") if isinstance(result.get("flow_run"), dict) else {}
    evidence_summary = result.get("evidence_summary") if isinstance(result.get("evidence_summary"), dict) else {}
    observations = evidence_summary.get("observations") if isinstance(evidence_summary.get("observations"), list) else []
    compact_observations = [
        _compact_workflow_observation(item)
        for item in observations[:12]
        if isinstance(item, dict)
    ]
    compact_evidence_summary = {
        "observations": compact_observations,
        "omitted_observation_count": max(0, len(observations) - len(compact_observations)),
        "answer_guidance": [
            *[
                str(item)
                for item in evidence_summary.get("answer_guidance") or []
                if str(item).strip()
            ][:6],
            render_prompt("tool_guard.workflow_result.no_invention"),
            render_prompt("tool_guard.workflow_result.missing_source"),
        ],
    }
    release_context = _compact_workflow_release_context(evidence_summary.get("release_context"))
    if release_context:
        compact_evidence_summary["release_context"] = release_context

    return {
        "workflow_capability": {
            "tool_name": capability.get("tool_name"),
            "name": capability.get("name"),
            "version": capability.get("version"),
            "flow_id": capability.get("flow_id"),
            "version_id": capability.get("version_id"),
        },
        "flow_run": {
            "id": flow_run.get("id"),
            "status": flow_run.get("status"),
            "pattern_type": flow_run.get("pattern_type"),
            "project_id": flow_run.get("project_id"),
            "total_steps": flow_run.get("total_steps"),
            "current_step_index": flow_run.get("current_step_index"),
            "last_error": flow_run.get("last_error"),
        },
        "evidence_summary": compact_evidence_summary,
        "answer_contract": {
            "raw_payload_available_as_artifact": True,
            "cite_workflow_tool": True,
            "quality_priority": render_prompt("tool_guard.workflow_result.quality_priority"),
        },
        "_compact_result_token_budget": 6000,
    }


def _compact_workflow_release_context(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    compact: dict[str, Any] = {}
    for key in ("release_name", "release_id", "release_date", "release_project_key", "release_status"):
        raw_value = source.get(key)
        if raw_value not in (None, ""):
            compact[key] = _truncate_for_model(raw_value, 160) if isinstance(raw_value, str) else raw_value
    return compact


def _compact_workflow_observation(observation: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "node_id",
        "tool",
        "query",
        "jql",
        "cql",
        "matched_user",
        "total",
        "count",
        "total_matches",
        "source_counts",
        "author_filter",
        "total_commit_count",
    ):
        if key in observation:
            value = observation.get(key)
            compact[key] = _truncate_for_model(value, 320) if isinstance(value, str) else value
    for key in ("user_examples", "result_examples", "repository_examples"):
        value = observation.get(key)
        if isinstance(value, list):
            compact[key] = compact_trace_value(value[:3])
    return compact


def _compact_workspace_file_result(result: dict[str, Any]) -> dict[str, Any]:
    content = str(result.get("content") or "")
    lines = content.splitlines()
    return {
        "path": result.get("path"),
        "relative_path": result.get("relative_path") or _path_tail(result.get("path")),
        "size_bytes": result.get("size_bytes"),
        "returned_chars": len(content),
        "returned_line_count": len(lines),
        "content_excerpt": _truncate_for_model(content, 2200),
        "content_truncated": content.endswith("\n...[truncated]"),
        "answer_guidance": {
            "raw_payload_available_as_artifact": True,
            "use_targeted_follow_up_reads": True,
            "cite_relative_path": True,
        },
    }


def _compact_workspace_directory_result(result: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for item in (result.get("entries") or [])[:120]:
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "name": item.get("name"),
                "relative_path": item.get("relative_path") or _path_tail(item.get("path")),
                "type": item.get("type"),
            }
        )
    return {
        "path": result.get("path"),
        "relative_path": result.get("relative_path") or _path_tail(result.get("path")),
        "count": result.get("count"),
        "returned_count": len(entries),
        "omitted_count": max(0, int(result.get("count") or 0) - len(entries)),
        "entries": entries,
        "answer_guidance": {
            "raw_payload_available_as_artifact": True,
            "prefer_relative_paths": True,
        },
    }


def _compact_runtime_command_result(result: dict[str, Any]) -> dict[str, Any]:
    stdout = result.get("stdout") or result.get("output") or ""
    stderr = result.get("stderr") or ""
    return {
        "command": result.get("command") or result.get("argv"),
        "cwd": result.get("cwd"),
        "exit_code": result.get("exit_code"),
        "status": result.get("status"),
        "duration_ms": result.get("duration_ms"),
        "stdout_excerpt": _truncate_for_model(stdout, 1800),
        "stderr_excerpt": _truncate_for_model(stderr, 1200),
        "stdout_truncated": len(str(stdout)) > 1800,
        "stderr_truncated": len(str(stderr)) > 1200,
        "answer_guidance": {
            "raw_payload_available_as_artifact": True,
            "do_not_ignore_nonzero_exit_code": True,
        },
    }


def _compact_tool_result_for_model(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"value": compact_trace_value(result)}
    if "error" in result:
        return {"error": result.get("error")}

    connector_compactor = resolve_tool_result_compactor(tool_name)
    if connector_compactor is not None:
        return connector_compactor(result)

    if tool_name.startswith("run_flow_"):
        return _compact_workflow_capability_result(result)

    if tool_name == ToolName.READ_WORKSPACE_FILE:
        return _compact_workspace_file_result(result)

    if tool_name == ToolName.LIST_WORKSPACE_DIRECTORY:
        return _compact_workspace_directory_result(result)

    if tool_name == ToolName.RUN_CLI_COMMAND:
        return _compact_runtime_command_result(result)

    if tool_name == ToolName.LIST_MCP_SERVERS:
        return {
            "count": result.get("count"),
            "servers": [
                {
                    "name": item.get("name"),
                    "vendor": item.get("vendor"),
                    "transport": item.get("transport"),
                    "connected": item.get("connected"),
                    "tool_count": item.get("tool_count"),
                    "catalog_slug": item.get("catalog_slug"),
                }
                for item in (result.get("servers") or [])[:20]
            ],
        }

    if tool_name == ToolName.LIST_MCP_SERVER_TOOLS:
        return {
            "server_name": result.get("server_name"),
            "connected": result.get("connected"),
            "search": result.get("search"),
            "count": result.get("count"),
            "tools": [
                {
                    "name": item.get("name"),
                    "description": _truncate_for_model(item.get("description") or "", 180),
                    "arguments": [
                        {
                            "name": arg.get("name"),
                            "type": arg.get("type"),
                            "required": arg.get("required"),
                        }
                        for arg in (item.get("arguments") or [])[:12]
                    ],
                }
                for item in (result.get("tools") or [])[:50]
            ],
        }

    if tool_name == ToolName.CALL_MCP_SERVER_TOOL:
        content = result.get("content")
        compact_content: list[dict[str, Any]] = []
        if isinstance(content, list):
            for item in content[:20]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    compact_content.append({"type": "text", "text": _truncate_for_model(item.get("text") or "", 600)})
                elif item.get("type") == "data":
                    compact_content.append({"type": "data", "data": compact_trace_value(item.get("data"))})
        return {
            "server_name": result.get("server_name"),
            "tool_name": result.get("tool_name"),
            "success": result.get("success"),
            "content": compact_content,
            "result": compact_trace_value(result.get("result")),
        }

    if tool_name == ToolName.LIST_MCP_SERVER_RESOURCES:
        return {
            "server_name": result.get("server_name"),
            "connected": result.get("connected"),
            "search": result.get("search"),
            "count": result.get("count"),
            "resources": [
                {
                    "uri": item.get("uri"),
                    "name": item.get("name"),
                    "mime_type": item.get("mime_type"),
                    "description": _truncate_for_model(item.get("description") or "", 180),
                }
                for item in (result.get("resources") or [])[:50]
            ],
        }

    if tool_name == ToolName.READ_MCP_SERVER_RESOURCE:
        contents = result.get("contents")
        compact_contents: list[dict[str, Any]] = []
        if isinstance(contents, list):
            for item in contents[:20]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    compact_contents.append({"type": "text", "text": _truncate_for_model(item.get("text") or "", 600)})
                elif item.get("type") == "data":
                    compact_contents.append({"type": "data", "data": compact_trace_value(item.get("data"))})
        return {
            "server_name": result.get("server_name"),
            "uri": result.get("uri"),
            "success": result.get("success"),
            "contents": compact_contents,
        }

    if tool_name == ToolName.LIST_MCP_SERVER_PROMPTS:
        return {
            "server_name": result.get("server_name"),
            "connected": result.get("connected"),
            "search": result.get("search"),
            "count": result.get("count"),
            "prompts": [
                {
                    "name": item.get("name"),
                    "description": _truncate_for_model(item.get("description") or "", 180),
                    "arguments": [
                        {
                            "name": arg.get("name"),
                            "description": _truncate_for_model(arg.get("description") or "", 120),
                        }
                        for arg in (item.get("arguments") or [])[:12]
                    ],
                }
                for item in (result.get("prompts") or [])[:50]
            ],
        }

    if tool_name == ToolName.GET_MCP_SERVER_PROMPT:
        return {
            "server_name": result.get("server_name"),
            "prompt_name": result.get("prompt_name"),
            "success": result.get("success"),
            "messages": [
                {
                    "role": item.get("role"),
                    "content": compact_trace_value(item.get("content")),
                }
                for item in (result.get("messages") or [])[:20]
                if isinstance(item, dict)
            ],
        }

    if tool_name == ToolName.GET_CURRENT_TIME:
        return {
            "local_time_iso": result.get("local_time_iso"),
            "utc_time_iso": result.get("utc_time_iso"),
            "timezone_name": result.get("timezone_name"),
        }

    return compact_trace_value(result)
