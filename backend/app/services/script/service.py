"""Persistence and execution helpers for reusable Python scripts."""

import json
import mimetypes
import re
import shutil
import textwrap
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SavedPythonScript
from ...runtime_limits import DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS
from ...time_utils import utc_now
from ..execution_runtime import execute_with_runtime
from ..system_config import get_agent_runtime_settings

# Saved scripts execute user-supplied code — Docker with hard sandbox is required.
# Host execution would allow arbitrary code on the host. Fail if Docker is unavailable.
_SAVED_SCRIPT_REQUIRED_PROVIDER = "docker"
_SAVED_SCRIPT_REQUIRED_SANDBOX_MODE = "hard"


def _enforce_docker_for_saved_script(project_config: dict[str, Any] | None) -> dict[str, Any]:
    """Force Docker provider for saved script execution to prevent host-code injection."""
    config = dict(project_config or {})
    config.setdefault("execution_runtime_provider", _SAVED_SCRIPT_REQUIRED_PROVIDER)
    config.setdefault("execution_runtime_sandbox_mode", _SAVED_SCRIPT_REQUIRED_SANDBOX_MODE)
    config["execution_runtime_allow_host_fallback"] = False
    return config

ARTIFACT_LINE_PATTERN = re.compile(r"(?i)(?:saved\s+(?:as|to)|written\s+to)\s*:\s*(.+)")
ALLOWED_SCRIPT_RUNTIMES = {"python", "python3"}


def _truncate(text: str, *, max_output_chars: int = DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS) -> str:
    if len(text) <= max_output_chars:
        return text
    return text[:max_output_chars] + "\n...[truncated]"


def _resolve_script_artifacts(stdout_text: str, cwd: Path) -> list[dict]:
    artifacts: list[dict] = []
    seen_paths: set[str] = set()
    for line in stdout_text.splitlines():
        match = ARTIFACT_LINE_PATTERN.search(line.strip())
        if not match:
            continue
        raw_path = match.group(1).strip().strip("'\"")
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
        if str(resolved) in seen_paths or not resolved.exists() or not resolved.is_file():
            continue
        media_type, _ = mimetypes.guess_type(str(resolved))
        artifacts.append(
            {
                "name": resolved.name,
                "path": str(resolved),
                "media_type": media_type or "application/octet-stream",
                "size_bytes": resolved.stat().st_size,
            }
        )
        seen_paths.add(str(resolved))
    return artifacts


def _default_runner_code() -> str:
    return textwrap.dedent(
        """
        import asyncio
        import importlib.util
        import json
        import pathlib
        import sys

        script_path = pathlib.Path(sys.argv[1])
        raw_args = sys.argv[2] if len(sys.argv) > 2 else "{}"
        args = json.loads(raw_args)

        spec = importlib.util.spec_from_file_location("saved_script_impl", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        async def run():
            if not hasattr(module, "main"):
                raise RuntimeError("Saved script must define a main(args) function")

            result = module.main(args)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, (dict, list)):
                print(json.dumps(result))
            elif result is None:
                print("")
            else:
                print(str(result))

        asyncio.run(run())
        """
    ).strip()


def _resolve_script_runtime(runtime_value: str | None) -> str:
    runtime = str(runtime_value or "python3").strip()
    if not runtime:
        runtime = "python3"
    if Path(runtime).name not in ALLOWED_SCRIPT_RUNTIMES:
        raise ValueError("Saved script runtime must be one of: " + ", ".join(sorted(ALLOWED_SCRIPT_RUNTIMES)))
    return runtime


async def list_saved_scripts(db: AsyncSession, *, active_only: bool = True) -> list[SavedPythonScript]:
    stmt = select(SavedPythonScript).order_by(SavedPythonScript.name.asc())
    if active_only:
        stmt = stmt.where(SavedPythonScript.is_active)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_saved_script(
    db: AsyncSession,
    *,
    script_id: str | None = None,
    name: str | None = None,
) -> SavedPythonScript | None:
    if script_id:
        return await db.get(SavedPythonScript, script_id)
    if name:
        result = await db.execute(select(SavedPythonScript).where(SavedPythonScript.name == name))
        return result.scalar_one_or_none()
    return None


async def save_python_script(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    purpose: str,
    code: str,
    description: str = "",
    arguments_schema: dict | None = None,
    tags: list[str] | None = None,
    is_active: bool = True,
) -> SavedPythonScript:
    result = await db.execute(select(SavedPythonScript).where(SavedPythonScript.name == name.strip()))
    script = result.scalar_one_or_none()

    if not script:
        script = SavedPythonScript(
            name=name.strip(),
            created_by_user_id=user_id,
        )
        db.add(script)

    script.purpose = purpose.strip()
    script.description = description.strip() or None
    script.code = code
    script.arguments_schema = arguments_schema or {}
    script.tags = tags or []
    script.is_active = is_active
    await db.flush()
    return script


async def delete_saved_script(db: AsyncSession, script_id: str) -> bool:
    script = await db.get(SavedPythonScript, script_id)
    if not script:
        return False
    await db.delete(script)
    await db.flush()
    return True


async def run_saved_script(
    db: AsyncSession,
    *,
    script: SavedPythonScript,
    args: dict | None = None,
    workspace_root: str | None = None,
    timeout_sec: int = 30,
) -> dict:
    args = args or {}
    cwd = Path(workspace_root).resolve() if workspace_root else Path.cwd()
    workspace_root_path = cwd

    try:
        runtime = _resolve_script_runtime(script.runtime)
    except ValueError as exc:
        return {
            "error": str(exc),
            "script_id": script.id,
            "name": script.name,
        }

    # VULN-8 mitigation: enforce Docker + hard sandbox for saved script execution
    enforced_project_config = _enforce_docker_for_saved_script({})
    if shutil.which("docker") is None:
        return {
            "error": (
                "Saved script execution requires Docker to run user code securely. "
                "Docker is not available on this host."
            ),
            "script_id": script.id,
            "name": script.name,
        }

    runner_code = _default_runner_code()
    runtime_settings = await get_agent_runtime_settings(db)
    max_output_chars = int(
        runtime_settings.get("saved_script_max_output_chars") or DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS
    )

    temp_root = workspace_root_path / ".octryx" / "runtime-scripts"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{script.name}-{uuid.uuid4().hex}"
    temp_path.mkdir(parents=True, exist_ok=True)
    try:
        script_path = temp_path / "saved_script.py"
        runner_path = temp_path / "runner.py"
        script_path.write_text(script.code, encoding="utf-8")
        runner_path.write_text(runner_code, encoding="utf-8")

        runtime_result = await execute_with_runtime(
            db=db,
            project_config=enforced_project_config,
            command=[
                runtime,
                str(runner_path.relative_to(workspace_root_path)),
                str(script_path.relative_to(workspace_root_path)),
                json.dumps(args),
            ],
            cwd=workspace_root_path,
            workspace_root=workspace_root_path,
            timeout_sec=timeout_sec,
            # A saved platform script, not repository content, in the docker sandbox (no host fallback); a project
            # that set another provider runs it on the host, where the server-build guard holds.
            guard_foreign_build=enforced_project_config.get("execution_runtime_provider") != "docker",
        )
        if runtime_result.timed_out:
            return {
                "error": runtime_result.stderr or f"Saved script timed out after {timeout_sec}s",
                "script_id": script.id,
                "name": script.name,
                "execution_runtime": runtime_result.metadata,
            }
        if runtime_result.exit_code is None:
            return {
                "error": runtime_result.stderr or "Saved script could not be executed",
                "script_id": script.id,
                "name": script.name,
                "execution_runtime": runtime_result.metadata,
            }
    finally:
        shutil.rmtree(temp_path, ignore_errors=True)

    script.usage_count = (script.usage_count or 0) + 1
    script.last_used_at = utc_now()
    await db.flush()

    stdout_text = _truncate(runtime_result.stdout, max_output_chars=max_output_chars)
    stderr_text = _truncate(runtime_result.stderr, max_output_chars=max_output_chars)
    parsed_output = None
    if stdout_text.strip():
        try:
            parsed_output = json.loads(stdout_text)
        except json.JSONDecodeError:
            parsed_output = None

    result = {
        "script_id": script.id,
        "name": script.name,
        "purpose": script.purpose,
        "exit_code": runtime_result.exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "parsed_output": parsed_output,
        "artifacts": _resolve_script_artifacts(stdout_text, cwd),
        "execution_runtime": runtime_result.metadata,
    }
    if runtime_result.exit_code != 0:
        result["error"] = stderr_text or stdout_text or f"Saved script exited with code {runtime_result.exit_code}"
    return result
