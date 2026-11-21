"""Ansible connector tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ...models import AnsibleJobRun
from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext
from .ansible_command import _run_ansible_command
from .ansible_runtime import (
    _ansible_binary,
    _ansible_extra_vars,
    _ansible_inventory_path,
    _ansible_tags,
    _ansible_workspace_root,
    _maybe_block_ansible_playbook_with_approval,
    _resolve_ansible_host_pattern,
    _resolve_ansible_playbook,
)
from .common import _string


class ListAnsibleInventoryTool:
    name = "list_inventory"
    description = "List Ansible inventory hosts and groups."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        inventory_path = _ansible_inventory_path(context)
        binary = _ansible_binary(context, "ansible_inventory_binary", "ansible-inventory")
        result = await _run_ansible_command(
            context,
            [binary, "-i", str(inventory_path), "--list", "--json"],
            cwd=_ansible_workspace_root(context),
            timeout=int(params.get("timeout_sec") or 60),
            command_type="list_inventory",
            inventory_path=str(inventory_path),
        )
        if result.get("error"):
            return result
        payload = json.loads(result["stdout"] or "{}")
        groups = [key for key, value in payload.items() if isinstance(value, dict) and key not in {"_meta"}]
        hosts = sorted(
            {host for value in payload.values() if isinstance(value, dict) for host in value.get("hosts") or []}
        )
        return {
            "job_id": result.get("job_id"),
            "inventory_path": str(inventory_path),
            "group_count": len(groups),
            "host_count": len(hosts),
            "groups": groups,
            "hosts": hosts,
            "inventory": payload,
        }


class GetAnsibleFactsTool:
    name = "get_facts"
    description = "Gather Ansible facts for an allowed host pattern."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        inventory_path = _ansible_inventory_path(context)
        binary = _ansible_binary(context, "ansible_binary", "ansible")
        host_pattern = _resolve_ansible_host_pattern(context, params)
        timeout = int(params.get("timeout_sec") or 120)
        with tempfile.TemporaryDirectory(prefix="octryx-ansible-facts-") as tree_dir:
            command = [
                binary,
                host_pattern,
                "-i",
                str(inventory_path),
                "-m",
                "setup",
                "-a",
                "gather_subset=min",
                "--tree",
                tree_dir,
            ]

            async def load_facts():
                facts: dict[str, Any] = {}
                for item in Path(tree_dir).glob("*"):
                    try:
                        facts[item.name] = json.loads(item.read_text(encoding="utf-8"))
                    except Exception:
                        facts[item.name] = {"raw": item.read_text(encoding="utf-8", errors="replace")}
                return facts

            result = await _run_ansible_command(
                context,
                command,
                cwd=_ansible_workspace_root(context),
                timeout=timeout,
                command_type="get_facts",
                inventory_path=str(inventory_path),
                host_pattern=host_pattern,
                facts_loader=load_facts,
            )
            if result.get("error"):
                return result
            facts = result.get("facts") or {}
            return {
                "job_id": result.get("job_id"),
                "inventory_path": str(inventory_path),
                "host_pattern": host_pattern,
                "count": len(facts),
                "facts": facts,
            }


class RunAnsiblePlaybookTool:
    name = "run_playbook"
    description = "Run an Ansible playbook with approval gating."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        playbook = _resolve_ansible_playbook(context, params)
        inventory_path = _ansible_inventory_path(context)
        binary = _ansible_binary(context, "ansible_playbook_binary", "ansible-playbook")
        host_pattern = _resolve_ansible_host_pattern(context, params, default="")
        command = [binary, "-i", str(inventory_path), str(playbook)]
        extra_vars = _ansible_extra_vars(params)
        tags = _ansible_tags(params)
        if host_pattern:
            command.extend(["--limit", host_pattern])
        if extra_vars:
            command.extend(["--extra-vars", extra_vars])
        if tags:
            command.extend(["--tags", tags])
        blocked = await _maybe_block_ansible_playbook_with_approval(
            self.name, params, context, command=command, cwd=str(_ansible_workspace_root(context))
        )
        if blocked:
            return blocked
        result = await _run_ansible_command(
            context,
            command,
            cwd=_ansible_workspace_root(context),
            timeout=int(params.get("timeout_sec") or 180),
            command_type="run_playbook",
            playbook=str(playbook),
            inventory_path=str(inventory_path),
            host_pattern=host_pattern or None,
            metadata_json={"check_mode": False},
        )
        if result.get("error"):
            return result
        return {
            "job_id": result.get("job_id"),
            "status": "completed",
            "playbook": str(playbook),
            "inventory_path": str(inventory_path),
            "host_pattern": host_pattern or None,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }


class CheckModeAnsiblePlaybookTool:
    name = "check_mode"
    description = "Run an Ansible playbook in dry-run check mode."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        playbook = _resolve_ansible_playbook(context, params)
        inventory_path = _ansible_inventory_path(context)
        binary = _ansible_binary(context, "ansible_playbook_binary", "ansible-playbook")
        host_pattern = _resolve_ansible_host_pattern(context, params, default="")
        command = [binary, "-i", str(inventory_path), str(playbook), "--check", "--diff"]
        extra_vars = _ansible_extra_vars(params)
        tags = _ansible_tags(params)
        if host_pattern:
            command.extend(["--limit", host_pattern])
        if extra_vars:
            command.extend(["--extra-vars", extra_vars])
        if tags:
            command.extend(["--tags", tags])
        result = await _run_ansible_command(
            context,
            command,
            cwd=_ansible_workspace_root(context),
            timeout=int(params.get("timeout_sec") or 180),
            command_type="check_mode",
            playbook=str(playbook),
            inventory_path=str(inventory_path),
            host_pattern=host_pattern or None,
            metadata_json={"check_mode": True},
        )
        if result.get("error"):
            return result
        return {
            "job_id": result.get("job_id"),
            "status": "completed",
            "playbook": str(playbook),
            "check_mode": True,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }


class GetAnsibleJobOutputTool:
    name = "get_job_output"
    description = "Return stored output for a previous Ansible job run."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        job_id = _string(params.get("job_id"))
        if not job_id:
            return {"error": "job_id is required"}
        job = await context.db.get(AnsibleJobRun, job_id)
        if job is None:
            return {"error": "job_id was not found"}
        if context.user_id and job.user_id and job.user_id != context.user_id and job.session_id != context.session_id:
            return {"error": "job_id is not accessible in this context"}
        return {
            "job_id": job.id,
            "status": job.status,
            "command_type": job.command_type,
            "playbook": job.playbook,
            "inventory_path": job.inventory_path,
            "host_pattern": job.host_pattern,
            # Rows are redacted when stored and again on the way out, with the redaction rules in force.
            "command": redact_process_output(job.command),
            "exit_code": job.exit_code,
            "stdout": redact_process_output(job.stdout),
            "stderr": redact_process_output(job.stderr),
            "facts": job.facts_json or {},
            "metadata": job.metadata_json or {},
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }
