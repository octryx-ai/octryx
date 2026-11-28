"""One engine session's own files (Claude Code's transcripts, a Codex rollout), sent to the platform after each turn
and restored before a turn resumes a session this device lacks (server ``services/devices/engine_state``)."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import logging
import os
import re
import tarfile
from pathlib import Path
from typing import Any

import httpx

from . import device_state
from .codex_config import THREADS_DIR
from .codex_driver import ENGINE as ENGINE_CODEX
from .codex_driver import runs_codex
from .device_job_offers import LOCAL_PREFIX
from .review_call import runs_review
from .state import LocalState, shared_state
from .transcript_streams import stream_files

logger = logging.getLogger("octryx_claude.device")

ENGINE_CLAUDE = "claude_code"
MAX_STATE_BYTES = 50 * 1024 * 1024
STATE_PATH = "/api/v1/devices/jobs/{job_id}/session-state"
TIMEOUT = 120.0
# Claude Code names a project folder after its working directory, every other character a dash, up to 200.
SLUG_LENGTH = 200
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_AGENT = re.compile(r"^agent-[A-Za-z0-9_-]{1,70}\.jsonl$")


def project_slug(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))[:SLUG_LENGTH]


def _project_dir(config_dir: Path, cwd: str) -> Path:
    slug = project_slug(cwd)
    projects = config_dir / "projects"
    if len(slug) == SLUG_LENGTH and projects.is_dir():
        # A longer path carries Claude Code's own hash after the cut: reuse the folder it already made.
        return next((path for path in sorted(projects.iterdir()) if path.name.startswith(slug)), projects / slug)
    return projects / slug


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def claude_files(config_dir: Path, cwd: str, session_id: str, *, strict: bool = False) -> dict[str, Path]:
    project = _project_dir(config_dir, cwd)
    if not _regular(project / f"{session_id}.jsonl"):
        # Claude Code resumes only from the working directory's folder; a copy elsewhere is still worth sending.
        main = None if strict else stream_files(config_dir, session_id).get("main")
        if main is None:
            return {}
        project = main.parent
    files = {f"claude/{session_id}.jsonl": project / f"{session_id}.jsonl"}
    for path in sorted((project / session_id / "subagents").glob("agent-*.jsonl")):
        if _regular(path) and _AGENT.match(path.name):
            files[f"claude/{session_id}/subagents/{path.name}"] = path
    return files


def codex_files(threads: Path, thread_id: str) -> dict[str, Path]:
    return {f"codex/{path.relative_to(threads).as_posix()}": path
            for path in sorted(threads.glob(f"*/*/*/rollout-*-{thread_id}.jsonl")) if _regular(path)}


def pack(files: dict[str, Path]) -> bytes:
    # Reproducible: same files, same bytes, so a device that holds them skips the download.
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as zipped, \
            tarfile.open(fileobj=zipped, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name in sorted(files):
            data = files[name].read_bytes()
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode, info.uid, info.gid = len(data), 0, 0o600, 0, 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _target(name: str, session_id: str, project: Path | None, threads: Path | None) -> Path | None:
    parts = name.split("/")
    if project is not None and parts[0] == "claude" and (
            parts[1:] == [f"{session_id}.jsonl"]
            or (len(parts) == 4 and parts[1:3] == [session_id, "subagents"] and _AGENT.match(parts[3]))):
        return project.joinpath(*parts[1:])
    rollout = re.compile(rf"^rollout-[A-Za-z0-9_-]+-{re.escape(session_id)}\.jsonl$")
    if threads is not None and parts[0] == "codex" and len(parts) == 5 and all(
            part.isdigit() for part in parts[1:4]) and rollout.match(parts[4]):
        return threads.joinpath(*parts[1:])
    return None


def _write(target: Path, data: bytes) -> bool:
    try:
        if target.read_bytes().startswith(data):
            return False  # the device holds the same session or more of it (these files only grow)
    except OSError:
        pass
    file_mode, dir_mode = (0o660, 0o2770) if shared_state() else (0o600, 0o700)
    target.parent.mkdir(parents=True, exist_ok=True, mode=dir_mode)
    partial = target.with_name(f".{target.name}.restoring")
    partial.write_bytes(data)
    partial.chmod(file_mode)
    partial.replace(target)
    return True


def unpack(data: bytes, session_id: str, *, project: Path | None = None, threads: Path | None = None) -> int:
    written = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            target = _target(member.name, session_id, project, threads) if member.isfile() else None
            source = archive.extractfile(member) if target is not None else None
            if source is not None and _write(target, source.read()):
                written += 1
    return written


def _engine(offer: dict[str, Any]) -> str:
    return ENGINE_CODEX if runs_codex(offer) else ENGINE_CLAUDE


def _places(prepared: Any, offer: dict[str, Any]) -> tuple[Path | None, Path | None]:
    # (Claude Code project folder, Codex threads folder) of this turn; never the person's own ~/.claude.
    env = getattr(prepared, "env", None) or {}
    if runs_codex(offer):
        home = env.get("OCTRYX_CLAUDE_HOME") or ""
        return None, (Path(home) / THREADS_DIR if home else None)
    config = env.get("CLAUDE_CONFIG_DIR") or ""
    return (_project_dir(Path(config), str(offer["folder"])) if config else None), None


def turn_files(prepared: Any, offer: dict[str, Any], session_id: str, *, strict: bool = False) -> dict[str, Path]:
    project, threads = _places(prepared, offer)
    if threads is not None:
        return codex_files(threads, session_id) if threads.is_dir() else {}
    if project is None:
        return {}
    return claude_files(project.parent.parent, str(offer["folder"]), session_id, strict=strict)


def _applies(offer: dict[str, Any], session_id: str) -> bool:
    return bool(_ID.match(session_id or "")) and not str(offer.get("profile") or "").startswith(LOCAL_PREFIX) \
        and not runs_review(offer)


def _client() -> Any:
    return httpx.Client(timeout=TIMEOUT)


def _token(state: LocalState) -> str:
    from .device_channel_auth import channel_token  # noqa: PLC0415

    return channel_token(state, False)


def _url(state: LocalState, job_id: str) -> str:
    base = str(device_state.load_device(state).get("base_url") or "").rstrip("/")
    return base + STATE_PATH.format(job_id=job_id)


def upload(state: LocalState, prepared: Any, offer: dict[str, Any], *, job_id: str, turn_id: str,
           session_id: str) -> str:
    files = turn_files(prepared, offer, session_id)
    if not files:
        return "nothing"
    data = pack(files)
    # Over the cap only the size goes: the platform records it and keeps the previous snapshot.
    params = {"engine": _engine(offer), "engine_session_id": session_id, "turn_id": turn_id,
              "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    with _client() as client:
        response = client.put(_url(state, job_id), params=params,
                              content=data if len(data) <= MAX_STATE_BYTES else b"",
                              headers={"Authorization": f"Bearer {_token(state)}"})
    return "stored" if response.status_code == 200 else f"refused_{response.status_code}"


def restore(state: LocalState, prepared: Any, offer: dict[str, Any], *, job_id: str) -> str:
    snapshot = offer.get("session_state") if isinstance(offer.get("session_state"), dict) else {}
    session_id = str(offer.get("resume") or "")
    if not snapshot or snapshot.get("engine_session_id") != session_id or not _applies(offer, session_id):
        return "none"
    present = turn_files(prepared, offer, session_id, strict=True)
    if present and hashlib.sha256(pack(present)).hexdigest() == snapshot.get("sha256"):
        return "present"
    try:
        with _client() as client:
            response = client.get(_url(state, job_id), headers={"Authorization": f"Bearer {_token(state)}"})
        data = response.content if response.status_code == 200 else b""
    except Exception:  # noqa: BLE001 - an unreachable platform reads like a missing snapshot
        data = b""
    if hashlib.sha256(data).hexdigest() != snapshot.get("sha256"):
        if not present:
            # Resuming a session the engine cannot find fails the turn; it starts fresh, as before snapshots.
            offer["resume"], offer["fork"] = None, False
        return "unavailable"
    project, threads = _places(prepared, offer)
    unpack(data, session_id, project=project, threads=threads)
    return "restored"


async def before_turn(state: LocalState, prepared: Any, offer: dict[str, Any], *, job_id: str) -> None:
    try:
        outcome = await asyncio.to_thread(restore, state, prepared, offer, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 - the turn runs with what the device has
        outcome = type(exc).__name__
    if outcome not in ("none", "present"):
        logger.info("job %s: session state %s", job_id, outcome)


async def after_turn(state: LocalState, prepared: Any, offer: dict[str, Any], result: dict[str, Any], *,
                     job_id: str, turn_id: str) -> None:
    session_id = str(result.get("claude_session_id") or "")
    if not _applies(offer, session_id):
        return
    try:
        outcome = await asyncio.to_thread(upload, state, prepared, offer, job_id=job_id, turn_id=turn_id,
                                          session_id=session_id)
    except Exception as exc:  # noqa: BLE001 - never fails the turn; the platform keeps the previous snapshot
        outcome = type(exc).__name__
    if outcome not in ("stored", "nothing"):
        logger.warning("job %s: session state not stored (%s)", job_id, outcome)


__all__ = ["after_turn", "before_turn", "claude_files", "codex_files", "pack", "project_slug", "restore", "unpack",
           "upload"]
