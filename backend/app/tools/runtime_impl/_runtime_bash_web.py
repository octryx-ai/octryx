"""Bash, web fetch, HTML conversion and batch tools."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx

from app.tools.context import ToolContext
from app.tools.evidence_fields import source_fields

from ...services.change_preview import build_command_change_preview
from ...services.execution_runtime.foreign_build_guard import runtime_refusal
from ...services.outbound_egress.public_web import public_web_client
from ...services.outbound_url_policy import OutboundURLPolicyError
from ...services.process_output_redaction import redact_process_output
from ..markup import html_to_markdown
from ._runtime_cli_helpers import _command_resolution_error, _resolve_effective_command, _truncate, _workspace_root
from ._runtime_cli_script_resolution import _maybe_resolve_script_command
from ._runtime_command_policy import _policy_block_result
from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_execution_resolution import _resolve_execute_with_runtime
from ._runtime_web_evidence import html_title
from ._runtime_web_fetch_formatting import format_web_fetch_content

# web_fetch: a connection that cannot be opened is tried again after these pauses.
FETCH_RETRY_DELAYS = (1.0, 3.0)


def _bash_runtime_result(runtime_result: Any, *, command: str, effective_command: str, effective_cwd: Path,
                         resolution: dict[str, Any] | None, timeout_sec: int) -> dict:
    if (refusal := runtime_refusal(runtime_result, command=command)) is not None:
        return refusal | {"cwd": str(effective_cwd)}  # the server-build backstop (resolved script): nothing ran
    # A timeout or an unavailable runtime carries runtime/exception text in stderr: fixed facts only.
    if runtime_result.timed_out:
        return {
            "error": f"bash_command_timed_out timeout_sec={timeout_sec}",
            "error_code": "bash_command_timed_out",
            "command": command,
            "execution_runtime": runtime_result.metadata,
        }
    if runtime_result.exit_code is None:
        return {
            "error": "bash_command_not_started",
            "error_code": "bash_command_not_started",
            "command": command,
            "execution_runtime": runtime_result.metadata,
        }

    # The agent ran this command and must read its output, stderr included, to debug it:
    # kept as the product result, but only through the process output redactor.
    out = redact_process_output(runtime_result.stdout)
    err = redact_process_output(runtime_result.stderr)
    combined = (out + err).strip()

    return {
        "command": command,
        "effective_command": effective_command,
        "cwd": str(effective_cwd),
        "returncode": runtime_result.exit_code,
        "stdout": _truncate(out),
        "stderr": _truncate(err),
        "output": _truncate(combined),
        "execution_runtime": runtime_result.metadata,
        **({"script_resolution": resolution} if resolution else {}),
    }


class BashTool:
    name = "bash"
    description = (
        "Execute a shell command in the workspace and return stdout + stderr. "
        "Default working directory is the workspace root. "
        "Use for git operations and read-only inspection (ls, cat, grep, rg, find). "
        "Builds, tests, package installs and repository scripts do not run on the Octryx server; "
        "they run on the user's device. Timeout: 120 seconds."
    )

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        command = str(params.get("command") or "").strip()
        if not command:
            return {"kind": "shell", "title": "Shell command", "summary": "", "details": ["No command provided."]}
        requested_cwd = str(params.get("cwd") or "").strip() or None
        try:
            cwd = _resolve_cwd(context.workspace_root, requested_cwd)
        except ValueError:
            cwd = _workspace_root(context)
        return build_command_change_preview(self.name, command, cwd=str(cwd))

    async def execute(self, params: dict, context: ToolContext) -> dict:
        command = str(params.get("command") or "").strip()
        if not command:
            return {"error": "command is required"}

        requested_cwd = str(params.get("cwd") or "").strip() or None
        timeout_sec = int(params.get("timeout_sec") or 120)

        try:
            cwd = _resolve_cwd(context.workspace_root, requested_cwd)
        except ValueError as e:
            return {"error": str(e)}

        blocked = await _policy_block_result(self.name, command, context)
        if blocked is not None:
            return blocked | {"cwd": str(cwd)}

        workspace_root = _workspace_root(context)
        effective_command, resolution, effective_cwd = _resolve_effective_command(
            command, cwd=cwd, context=context, script_resolver=_maybe_resolve_script_command
        )
        resolution_error = _command_resolution_error(command=command, cwd=cwd, resolution=resolution)
        if resolution_error is not None:
            return resolution_error
        runtime_result = await _resolve_execute_with_runtime()(
            db=context.db,
            project_config=context.project_config,
            command=effective_command,
            cwd=effective_cwd,
            workspace_root=workspace_root,
            timeout_sec=timeout_sec,
            shell=True,
            env={**os.environ, "TERM": "dumb"},
        )
        return _bash_runtime_result(runtime_result, command=command, effective_command=effective_command,
                                    effective_cwd=effective_cwd, resolution=resolution, timeout_sec=timeout_sec)


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Fetch a URL and return its content as markdown (default), plain text, or raw HTML. "
        "Max 2 MB. Converts HTML to readable markdown using html2text if available. The result carries "
        "source_url and a cite_as markdown link to cite the page by."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict:
        url = str(params.get("url") or "").strip()
        if not url:
            return {"error": "url is required"}
        # The governed source registry first (blocklist, trusted_only), the same check as over MCP.
        from ...services.web_search.fetch_policy import web_fetch_refusal

        project_config = getattr(context, "project_config", None) or {}
        project_id = str(project_config.get("project_id") or "").strip() or None
        refusal = await web_fetch_refusal(getattr(context, "db", None), project_id=project_id, url=url)
        if refusal is not None:
            return {**refusal, "url": url[:300]}

        fmt = str(params.get("format") or "markdown").lower()
        timeout_sec = int(params.get("timeout") or 30)
        max_bytes = 2 * 1024 * 1024  # 2 MB

        # A connection that cannot be opened is tried again (e.g. intermittent "All connection attempts
        # failed" on Wikipedia, intermittently); any answer, a refusal or a policy stop is final.
        for delay in (*FETCH_RETRY_DELAYS, None):
            try:
                async with public_web_client(timeout=timeout_sec,
                                             headers={"User-Agent": "Octryx/1.0"}) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    raw = resp.content[:max_bytes]
                    content_type = resp.headers.get("content-type", "")
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if delay is None:
                    return {"error": f"Fetch failed: {e}", "url": url}
                await asyncio.sleep(delay)
            except (OutboundURLPolicyError, Exception) as e:
                return {"error": f"Fetch failed: {e}", "url": url}

        text = raw.decode("utf-8", errors="replace")
        formatted = format_web_fetch_content(text, content_type=content_type, requested_format=fmt)
        # The fetched page is the source: cite it by its cite_as link (same shape as Knowledge evidence).
        return {"url": url, **source_fields(title=html_title(text, content_type), url=url), **formatted}


class HtmlToMarkdownTool:
    name = "html_to_markdown"
    description = "Convert raw HTML into readable markdown for storage in the knowledge base or reuse in later prompts."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        raw_html = params.get("html")
        if not isinstance(raw_html, str) or not raw_html.strip():
            return {"error": "html is required"}

        markdown = html_to_markdown(raw_html)
        markdown = _truncate(markdown)
        return {
            "markdown": markdown,
            "length": len(markdown),
        }


class BatchTool:
    name = "batch"
    description = (
        "Execute multiple tools in parallel (up to 25). "
        "Each invocation specifies a tool_name and params dict. "
        "Returns results in the same order as inputs, with per-tool success/error status. "
        "Use to parallelise independent operations and reduce round-trips."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict:
        from ..registry import execute_tool  # local import to avoid circular

        invocations = params.get("invocations") or []
        if not invocations:
            return {"error": "invocations list is required"}
        if len(invocations) > 25:
            return {"error": "Maximum 25 invocations per batch call"}

        async def _run_one(inv: dict) -> dict:
            tool_name = str(inv.get("tool_name") or "").strip()
            tool_params = inv.get("params") or {}
            if not tool_name:
                return {"tool_name": "", "status": "error", "error": "tool_name is required"}
            try:
                result = await execute_tool(tool_name, tool_params, context)
                return {"tool_name": tool_name, "status": "ok", "result": result}
            except Exception as e:
                return {"tool_name": tool_name, "status": "error", "error": str(e)}

        results = await asyncio.gather(*[_run_one(inv) for inv in invocations])
        return {
            "count": len(results),
            "results": list(results),
        }


__all__ = [name for name in vars() if not name.startswith("_")]
