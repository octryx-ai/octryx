"""Terraform connector helpers."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext
from .common import _normalize_string_list, _string


def _terraform_workspace_root(context: ToolContext) -> Path:
    root = Path(context.workspace_root or Path.cwd()).resolve()
    configured = _string(context.project_config.get("terraform_root"))
    if not configured:
        return root
    candidate = Path(configured)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"terraform_root must stay inside workspace root: {root}")
    return resolved


def _terraform_binary(context: ToolContext) -> str:
    explicit = _string(context.project_config.get("terraform_binary"))
    if explicit:
        return explicit
    return "tofu" if bool(context.project_config.get("terraform_use_opentofu")) else "terraform"


def _terraform_allowed_workspaces(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("terraform_allowed_workspaces"))


def _terraform_effective_workspace(context: ToolContext, params: dict[str, Any]) -> str:
    workspace = _string(params.get("workspace") or context.project_config.get("terraform_workspace"))
    allowed = _terraform_allowed_workspaces(context)
    if not workspace and len(allowed) == 1:
        workspace = allowed[0]
    if allowed and workspace and workspace not in allowed:
        raise ValueError(f"workspace '{workspace}' is not allowed")
    return workspace


def _terraform_var_file(context: ToolContext, params: dict[str, Any]) -> str:
    return _string(params.get("var_file") or context.project_config.get("terraform_var_file"))


def _terraform_env(context: ToolContext) -> dict[str, str]:
    env = dict(os.environ)
    plugin_cache_dir = _string(context.project_config.get("terraform_plugin_cache_dir"))
    if plugin_cache_dir:
        env["TF_PLUGIN_CACHE_DIR"] = plugin_cache_dir
    return env


async def _terraform_run(
    context: ToolContext,
    args: list[str],
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 120,
    allow_exit_codes: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    cwd = _terraform_workspace_root(context)
    binary = _terraform_binary(context)
    if shutil.which(binary) is None and not Path(binary).exists():
        return {"error": f"{binary} is not available on PATH"}
    params = params or {}
    command = [binary]
    workspace = _terraform_effective_workspace(context, params)
    if workspace:
        command.extend(["workspace", "select", workspace])
        select_proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=_terraform_env(context),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(select_proc.communicate(), timeout=timeout)
        except TimeoutError:
            select_proc.kill()
            await select_proc.communicate()
            return {"error": f"{binary} workspace select timed out"}
        if select_proc.returncode != 0:
            # A pre-step of the requested command: reported as facts, its output is not kept.
            return {
                "error": f"terraform_workspace_select_failed exit_code={select_proc.returncode}",
                "error_code": "terraform_workspace_select_failed",
                "exit_code": select_proc.returncode,
            }
        command = [binary]
    command.extend(args)
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=_terraform_env(context),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"error": f"{binary} {' '.join(args)} timed out"}
    # Plan/apply/state/output text is the product the agent reads, and a failed plan's diagnostics are
    # what it must fix: kept, but only through the redactor. The ``error`` key carries facts only.
    stdout_text = redact_process_output(stdout)
    stderr_text = redact_process_output(stderr)
    shown_command = redact_process_output(" ".join([binary, *args]))
    if proc.returncode not in allow_exit_codes:
        return {
            "error": f"terraform_command_failed exit_code={proc.returncode}",
            "error_code": "terraform_command_failed",
            "exit_code": proc.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "cwd": str(cwd),
            "command": shown_command,
        }
    return {
        "exit_code": proc.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "cwd": str(cwd),
        "command": shown_command,
        "workspace": workspace,
        "binary": binary,
    }
