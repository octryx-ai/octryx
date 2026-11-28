"""Read-only git smart HTTP for one run from its working copy: only the run's branch is advertised, and protocol
v0 keeps a request to commits reachable from it. A push never goes this way (``scm.push``)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from ...models import WorkflowRun
from ..workflow_runs.safe_git import SAFE_CONFIG, git_env

SERVICE = "git-upload-pack"
ADVERTISEMENT_TYPE = "application/x-git-upload-pack-advertisement"
RESULT_TYPE = "application/x-git-upload-pack-result"
REASON_NO_WORKING_COPY = "run_has_no_working_copy"
REASON_NO_BRANCH = "run_has_no_branch"
CHUNK = 64 * 1024
TIMEOUT_SECONDS = 600


def git_path(run_id: str) -> str:
    return f"/api/v1/agent-gateway/git/{run_id}"


def working_copy(run: WorkflowRun) -> tuple[Path | None, str]:
    local = str(dict(run.context or {}).get("local_path") or "")
    root = Path(local) if local else None
    if root is None or not (root / ".git").exists():
        return None, REASON_NO_WORKING_COPY
    branch = str(run.branch or "")
    return (root, branch) if branch else (None, REASON_NO_BRANCH)


def _command(root: Path, branch: str, *, advertise: bool) -> list[str]:
    return ["git", *SAFE_CONFIG, "-c", "uploadpack.hideRefs=refs/", "-c", f"uploadpack.hideRefs=!refs/heads/{branch}",
            "-c", "uploadpack.allowTipSHA1InWant=false", "-c", "uploadpack.allowReachableSHA1InWant=false",
            "-c", "uploadpack.allowAnySHA1InWant=false", "upload-pack", "--stateless-rpc",
            *(["--advertise-refs"] if advertise else []), str(root)]


def _pkt(line: str) -> bytes:
    data = line.encode()
    return f"{len(data) + 4:04x}".encode() + data


async def _run(root: Path, branch: str, *, advertise: bool, body: bytes) -> AsyncIterator[bytes]:
    env = {key: value for key, value in git_env().items() if key != "GIT_PROTOCOL"}
    process = await asyncio.create_subprocess_exec(
        *_command(root, branch, advertise=advertise), env=env,
        stdin=asyncio.subprocess.PIPE if body else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    assert process.stdout is not None
    try:
        if process.stdin is not None:
            # upload-pack may stop reading early (an invalid request); uvloop then raises RuntimeError on the
            # closed pipe instead of BrokenPipeError.
            with contextlib.suppress(BrokenPipeError, ConnectionResetError, RuntimeError):
                process.stdin.write(body)
                await process.stdin.drain()
                process.stdin.close()
        while chunk := await asyncio.wait_for(process.stdout.read(CHUNK), TIMEOUT_SECONDS):
            yield chunk
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.wait()


async def advertisement(root: Path, branch: str) -> AsyncIterator[bytes]:
    yield _pkt(f"# service={SERVICE}\n") + b"0000"
    async for chunk in _run(root, branch, advertise=True, body=b""):
        yield chunk


def upload_pack(root: Path, branch: str, body: bytes) -> AsyncIterator[bytes]:
    return _run(root, branch, advertise=False, body=body)


__all__ = ["ADVERTISEMENT_TYPE", "REASON_NO_BRANCH", "REASON_NO_WORKING_COPY", "RESULT_TYPE", "SERVICE",
           "advertisement", "git_path", "upload_pack", "working_copy"]
