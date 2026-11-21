"""Run an Ansible command as a recorded job: the job row, the subprocess with its timeout, the redacted result."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from ...models import AnsibleJobRun
from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext


async def _record_ansible_job_start(
    context: ToolContext,
    *,
    command_type: str,
    command: list[str],
    playbook: str | None = None,
    inventory_path: str | None = None,
    host_pattern: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> AnsibleJobRun | None:
    if context.db is None:
        return None
    job = AnsibleJobRun(
        session_id=context.session_id,
        user_id=context.user_id,
        command_type=command_type,
        status="running",
        playbook=playbook,
        inventory_path=inventory_path,
        host_pattern=host_pattern,
        command=redact_process_output(" ".join(command)),
        metadata_json=metadata_json or {},
    )
    context.db.add(job)
    await context.db.flush()
    await context.db.commit()
    return job


async def _record_ansible_job_finish(
    context: ToolContext,
    job: AnsibleJobRun | None,
    *,
    status: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    facts_json: dict[str, Any] | None = None,
) -> None:
    if context.db is None or job is None:
        return
    job.status = status
    job.exit_code = exit_code
    job.stdout = stdout[:50000]
    job.stderr = stderr[:50000]
    job.facts_json = facts_json
    await context.db.commit()


async def _finish_timed_out(context: ToolContext, proc: Any, job: AnsibleJobRun | None, binary: str) -> dict[str, Any]:
    proc.kill()
    await proc.communicate()
    if job is not None:
        await _record_ansible_job_finish(
            context, job, status="failed", exit_code=None, stdout="", stderr="timed out"
        )
    return {"error": f"{binary} timed out", "job_id": job.id if job else None}


def _command_result(
    job: AnsibleJobRun | None,
    *,
    exit_code: int | None,
    succeeded: bool,
    stdout: str,
    stderr: str,
    shown_command: str,
    cwd: Path,
    status: str,
    facts_json: dict[str, Any] | None,
) -> dict[str, Any]:
    if not succeeded:
        return {
            "error": f"ansible_command_failed exit_code={exit_code}",
            "error_code": "ansible_command_failed",
            "job_id": job.id if job else None,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "command": shown_command,
            "cwd": str(cwd),
        }
    result = {
        "job_id": job.id if job else None,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "command": shown_command,
        "cwd": str(cwd),
        "status": status,
    }
    if facts_json is not None:
        result["facts"] = facts_json
    return result


async def _run_ansible_command(
    context: ToolContext,
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 180,
    allow_exit_codes: tuple[int, ...] = (0,),
    command_type: str,
    playbook: str | None = None,
    inventory_path: str | None = None,
    host_pattern: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    facts_loader: Any | None = None,
) -> dict[str, Any]:
    binary = command[0]
    if shutil.which(binary) is None and not Path(binary).exists():
        return {"error": f"{binary} is not available on PATH"}
    job = await _record_ansible_job_start(
        context,
        command_type=command_type,
        command=command,
        playbook=playbook,
        inventory_path=inventory_path,
        host_pattern=host_pattern,
        metadata_json=metadata_json,
    )
    proc = await asyncio.create_subprocess_exec(
        *command, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        return await _finish_timed_out(context, proc, job, binary)
    # The playbook/inventory output is the product the agent reads (also after a failed task), and it
    # is stored on the job row: it is kept, but only through the redactor, before storing or returning.
    stdout_text = redact_process_output(stdout)
    stderr_text = redact_process_output(stderr)
    shown_command = redact_process_output(" ".join(command))
    facts_json = await facts_loader() if facts_loader else None
    succeeded = proc.returncode in allow_exit_codes
    status = "completed" if succeeded else "failed"
    # A job row exists only with a database session; the recorder skips the update without one.
    await _record_ansible_job_finish(
        context, job, status=status, exit_code=proc.returncode, stdout=stdout_text, stderr=stderr_text,
        facts_json=facts_json,
    )
    return _command_result(
        job,
        exit_code=proc.returncode,
        succeeded=succeeded,
        stdout=stdout_text,
        stderr=stderr_text,
        shown_command=shown_command,
        cwd=cwd,
        status=status,
        facts_json=facts_json,
    )
