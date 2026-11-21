"""A device job without an agent (server ``services/devices/tool_jobs``): the platform sends
``tool_job {job_id, archives, steps, timeout}``; the launcher fetches each archive into one temporary folder
(``tree_archive.fetch``: sha256 checked, unpacked safely), runs the steps in order with :func:`tool_run.run_tool`
(pinned tools only, no shell, minimal environment) and answers ``tool_job_result {job_id, steps}`` raw: the status,
exit code, output and the files each step wrote. A file the step cut at ``max_output`` goes up whole as an upload
(``tree_archive.upload``) and is answered by its id. The folder is removed afterwards, whatever happened.

In a step's ``args`` ``{archive:<name>}`` is that archive's folder and ``{out:<file>}`` a file in ``out/``; every
step starts in the job's folder. The launcher judges nothing: the platform reads the result.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import tool_run, tree_archive

MESSAGE_OFFER, MESSAGE_RESULT, MESSAGE_FAILED = "tool_job", "tool_job_result", "tool_job_failed"
_ID = re.compile(r"^tj_[0-9a-f]{20}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_TOKEN = re.compile(r"\{(archive|out):([^{}]*)\}")
OUT = "out"


def _argument(arg: str, folders: dict[str, str]) -> str:
    def value(match: re.Match[str]) -> str:
        kind, name = match.groups()
        return folders[name] if kind == "archive" else f"{OUT}/{name}"

    return _TOKEN.sub(value, arg)


def _upload_cut(state: Any, root: Path, name: str, upload: Callable[..., Any]) -> dict[str, Any] | str:
    answer = upload(state, (root / OUT / name).read_bytes(), name=name)
    return {"upload": answer["id"]} if isinstance(answer, dict) and answer.get("id") else str(answer)


def run_job(state: Any, body: dict[str, Any], *, fetch: Callable[..., Any] = tree_archive.fetch,
            upload: Callable[..., Any] = tree_archive.upload,
            run: Callable[..., dict[str, Any]] = tool_run.run_tool) -> tuple[str, dict[str, Any]]:
    """``(message type, body)`` of the answer; blocking, run it off the event loop."""
    job_id = str(body.get("job_id") or "")
    root = Path(tempfile.mkdtemp(prefix="octryx-tool-job-"))
    try:
        (root / OUT).mkdir()
        folders: dict[str, str] = {}
        for item in body.get("archives") or []:
            name = str(dict(item or {}).get("name") or "")
            if not _NAME.match(name):
                return MESSAGE_FAILED, {"job_id": job_id, "reason": "an archive has no plain name"}
            unpacked, why = fetch(state, dict(item), root / name)
            if unpacked is None:
                return MESSAGE_FAILED, {"job_id": job_id, "reason": f"archive {name}: {why}"[:300]}
            folders[name] = name
        steps = []
        for step in body.get("steps") or []:
            step = dict(step or {})
            outputs = [f"{OUT}/{name}" for name in step.get("outputs") or [] if _NAME.match(str(name))]
            try:
                args = [_argument(str(arg), folders) for arg in step.get("args") or []]
            except KeyError:
                steps.append({"id": step.get("id"), "status": "error", "exit": None, "stdout": "",
                              "stderr": "an argument names an archive this job did not send", "files": {}})
                continue
            done = run(str(step.get("tool") or ""), args, cwd=root, timeout=float(step.get("timeout") or 60),
                       outputs=outputs)
            files: dict[str, Any] = {}
            for path, text in dict(done.get("files") or {}).items():
                name = path.removeprefix(f"{OUT}/")
                whole = (root / OUT / name).stat().st_size if (root / OUT / name).is_file() else 0
                files[name] = _upload_cut(state, root, name, upload) if whole > len(text.encode()) else text
            steps.append({"id": step.get("id"), **{key: done.get(key) for key in (
                "status", "exit", "stdout", "stderr", "truncated")}, "files": files})
        return MESSAGE_RESULT, {"job_id": job_id, "steps": steps}
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def serve(state: Any, body: dict[str, Any], send: Callable[[str, dict[str, Any]], Awaitable[bool]]) -> None:
    """Run one offered job off the receive loop and answer it."""
    if not _ID.match(str(body.get("job_id") or "")):
        return
    try:
        message_type, answer = await asyncio.to_thread(run_job, state, body)
    except Exception as error:  # noqa: BLE001 - the platform learns that the job failed, never silence
        message_type, answer = MESSAGE_FAILED, {"job_id": body["job_id"],
                                                "reason": f"{type(error).__name__}: {error}"[:300]}
    await send(message_type, answer)


__all__ = ["MESSAGE_FAILED", "MESSAGE_OFFER", "MESSAGE_RESULT", "run_job", "serve"]
