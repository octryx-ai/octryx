"""Saved Python script tools: save, list, fetch and run reusable scripts stored in the database."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ...services.script import get_saved_script, list_saved_scripts, run_saved_script, save_python_script


class SavePythonScriptTool:
    name = "save_python_script"
    description = (
        "Save or update a reusable Python script in the database. Prefer this over recreating temporary scripts."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database context is required"}

        name = (params.get("name") or "").strip()
        purpose = (params.get("purpose") or "").strip()
        code = params.get("code") or ""
        if not name or not purpose or not code:
            return {"error": "name, purpose, and code are required"}

        script = await save_python_script(
            context.db,
            user_id=context.user_id,
            name=name,
            purpose=purpose,
            code=code,
            description=params.get("description") or "",
            arguments_schema=params.get("arguments_schema") or {},
            tags=params.get("tags") or [],
            is_active=params.get("is_active", True),
        )
        return {
            "script_id": script.id,
            "name": script.name,
            "purpose": script.purpose,
            "description": script.description,
        }


class ListSavedPythonScriptsTool:
    name = "list_saved_python_scripts"
    description = "List reusable Python scripts stored in the database."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database context is required"}

        scripts = await list_saved_scripts(context.db, active_only=params.get("active_only", True))
        return {
            "scripts": [
                {
                    "id": script.id,
                    "name": script.name,
                    "purpose": script.purpose,
                    "description": script.description,
                    "usage_count": script.usage_count,
                    "last_used_at": script.last_used_at.isoformat() if script.last_used_at else None,
                    "tags": script.tags or [],
                }
                for script in scripts
            ]
        }


class GetSavedPythonScriptTool:
    name = "get_saved_python_script"
    description = "Fetch metadata for a saved Python script. Include code only when necessary."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database context is required"}

        script = await get_saved_script(
            context.db,
            script_id=params.get("script_id"),
            name=params.get("name"),
        )
        if not script:
            return {"error": "Saved script not found"}

        result = {
            "id": script.id,
            "name": script.name,
            "purpose": script.purpose,
            "description": script.description,
            "arguments_schema": script.arguments_schema or {},
            "usage_count": script.usage_count,
            "last_used_at": script.last_used_at.isoformat() if script.last_used_at else None,
        }
        if params.get("include_code"):
            result["code"] = script.code
        return result


class RunSavedPythonScriptTool:
    name = "run_saved_python_script"
    description = "Execute a saved Python script by id or name. Saved scripts should define main(args)."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database context is required"}

        script = await get_saved_script(
            context.db,
            script_id=params.get("script_id"),
            name=params.get("name"),
        )
        if not script:
            return {"error": "Saved script not found"}

        return await run_saved_script(
            context.db,
            script=script,
            args=params.get("args") or {},
            workspace_root=context.workspace_root,
            timeout_sec=int(params.get("timeout_sec") or 30),
        )


__all__ = [name for name in vars() if not name.startswith("_")]
