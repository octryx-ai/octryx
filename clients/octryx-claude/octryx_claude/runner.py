"""``octryx-claude device run --runner``: a platform server runner that joins the pool with the join secret;
Codex runs under the agent's account, which reaches tokens only through the launcher's broker."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import socket
import subprocess
import uuid
from pathlib import Path

import httpx

from . import __version__, device_state, token_broker
from .state import CREDENTIAL_SET_DEVICE, LocalState

logger = logging.getLogger(__name__)

JOIN_SECRET_FILE = Path("/run/secrets/octryx/runner-join")
ENROLL_PATH = "/api/v1/devices/runner/enroll"
AGENT_UID_ENV = "OCTRYX_AGENT_UID"
RUNTIME_ENV = "OCTRYX_RUNNER_RUNTIME"
WORKSPACE_ROOT = "/workspace"
HTTP_TIMEOUT = 30.0
BROKER_SOCKET = "broker/token.sock"
PARALLEL_JOBS = 1
AGENT_HOME = "/tmp/agent-home"
TENANT_FILE = "runner-tenant"
# What one person's turns leave behind: their files, Codex's threads and homes, the launcher's session folders.
TENANT_STATE = ("sessions", "codex-homes", "codex-threads", "claude-config")
WIPE_TIMEOUT = 300


def agent_command() -> list[str]:
    # Empty outside a server runner; inside, the agent's account with no capability left.
    uid = agent_uid()
    if uid is None:
        return []
    return ["setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups", "--inh-caps=-all",
            "--ambient-caps=-all", "--bounding-set=-all", "--no-new-privs", "--"]


class RunnerError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def agent_uid() -> int | None:
    raw = os.environ.get(AGENT_UID_ENV, "")
    return int(raw) if raw.isdigit() else None


def agent_git_env(folder: str, base: dict[str, str] | None = None) -> dict[str, str]:
    # The launcher owns the folder, so the agent's git (and its hooks) would refuse it as "dubious ownership".
    if agent_uid() is None or not folder:
        return {}
    source = os.environ if base is None else base
    raw = str(source.get("GIT_CONFIG_COUNT") or "").strip()
    index = int(raw) if raw.isdigit() else 0
    return {**{key: value for key, value in source.items() if key.startswith("GIT_CONFIG_")},
            "GIT_CONFIG_COUNT": str(index + 1), f"GIT_CONFIG_KEY_{index}": "safe.directory",
            f"GIT_CONFIG_VALUE_{index}": os.path.realpath(folder)}


def enroll(state: LocalState, base_url: str, *, http: httpx.Client, secret_file: Path = JOIN_SECRET_FILE) -> str:
    from .oauth import register_client  # noqa: PLC0415

    try:
        secret = secret_file.read_text(encoding="utf-8").strip()
    except OSError:
        secret = ""
    if not secret:
        raise RunnerError("runner_join_secret_missing")
    client_id = register_client(http, base_url, "http://127.0.0.1/runner")
    name = f"runner-{socket.gethostname()[:24]}-{uuid.uuid4().hex[:6]}"
    body = {"join_secret": secret, "client_id": client_id, "name": name,
            "public_key": device_state.generate_key(state), "client_version": __version__,
            "max_parallel_jobs": PARALLEL_JOBS, "runtime": os.environ.get(RUNTIME_ENV, "")}
    try:
        response = http.post(f"{base_url}{ENROLL_PATH}", json=body, timeout=HTTP_TIMEOUT)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RunnerError("platform_unreachable") from exc
    payload = payload if isinstance(payload, dict) else {}
    credential, device = payload.get("credential"), payload.get("device")
    if response.status_code != 201 or not isinstance(credential, dict) or not isinstance(device, dict) \
            or not credential.get("refresh_token"):
        raise RunnerError(str(payload.get("reason") or f"enroll_refused_{response.status_code}")[:80])
    state.with_credential_set(CREDENTIAL_SET_DEVICE).write_credentials({
        "base_url": base_url, "client_id": client_id, "refresh_token": str(credential["refresh_token"]),
        "scopes": list(credential.get("scopes") or []), "tokens": {}})
    device_state.save_device(state, {
        "device_id": str(device["id"]), "name": name, "os": "linux", "base_url": base_url,
        "folders": [WORKSPACE_ROOT], "max_parallel_jobs": PARALLEL_JOBS, "paused": False, "service_kind": "runner",
        "runner": True})
    return str(device["id"])


def ensure_job_folder(folder: str) -> None:
    # The platform names a fresh folder under the runner's workspace for a thread; the agent's group writes in it.
    path = Path(folder)
    if str(path.parent) == WORKSPACE_ROOT and not path.exists():
        path.mkdir(mode=0o2770)
        os.chmod(path, 0o2770)


def tenant_roots(state: LocalState) -> list[Path]:
    return [Path(WORKSPACE_ROOT), Path(AGENT_HOME), *(state.root / name for name in TENANT_STATE)]


def admit_tenant(state: LocalState, body: dict, *, busy: bool, roots: list[Path] | None = None) -> bool:
    # A runner serves one person in one Workspace at a time; the next one starts on an empty runner.
    tenant = f"{body.get('owner_user_id') or ''}/{body.get('workspace_id') or ''}"
    marker = state.root / TENANT_FILE
    try:
        if marker.read_text(encoding="utf-8") == tenant:
            return True
    except OSError:
        pass
    if busy or not _wipe(roots if roots is not None else tenant_roots(state)):
        return False
    carried = body.get("session_state") if isinstance(body.get("session_state"), dict) else {}
    if not body.get("resume_session_id") or carried.get("engine_session_id") != body.get("resume_session_id"):
        # Only a session whose files the platform holds goes on here; the earlier tenant's are gone.
        body.pop("resume_session_id", None)
        body.pop("fork_session", None)
    marker.write_text(tenant, encoding="utf-8")
    return True


def _wipe(roots: list[Path]) -> bool:
    present = [root for root in roots if root.is_dir()]
    if (command := agent_command()) and present:
        # The agent's own files first, as the agent: the launcher may not enter folders the agent made private.
        _as_agent([*command, "find", *map(str, present), "-mindepth", "1", "-delete"])
    for root in present:
        with contextlib.suppress(OSError):
            for entry in list(root.iterdir()):
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    with contextlib.suppress(OSError):
                        entry.unlink()
    return all(_empty(root) for root in present)


def _empty(root: Path) -> bool:
    try:
        return not any(root.iterdir())
    except PermissionError:
        command = agent_command()
        found = _as_agent([*command, "find", str(root), "-mindepth", "1", "-print", "-quit"]) if command else None
        return found is not None and found.returncode == 0 and not found.stdout.strip()


def _as_agent(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=WIPE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None


def broker_socket(state: LocalState) -> Path:
    return state.root / BROKER_SOCKET


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    base_url = os.environ.get("OCTRYX_BASE_URL", "").rstrip("/")
    if not base_url:
        logger.error("runner did not start: OCTRYX_BASE_URL is not set")
        return 2
    state = LocalState().ensure()
    if state.root.stat().st_uid == os.getuid():
        os.chmod(state.root, 0o3770)  # the agent's group may add files here but not replace the launcher's
    if not device_state.load_device(state):
        try:
            with httpx.Client(follow_redirects=False) as http:
                logger.info("enrolled as %s", enroll(state, base_url, http=http))
        except RunnerError as error:
            logger.error("runner did not start: %s", error.code)
            return 2

    async def run() -> None:
        from .device_runtime import serve  # noqa: PLC0415

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, stop.set)
        broker = asyncio.create_task(token_broker.serve(state.with_credential_set(CREDENTIAL_SET_DEVICE),
                                                        broker_socket(state), stop))
        try:
            await serve(state, stop)
        finally:
            stop.set()
            await broker

    asyncio.run(run())
    return 0


__all__ = [
    "AGENT_HOME",
    "AGENT_UID_ENV",
    "RUNTIME_ENV",
    "RunnerError",
    "admit_tenant",
    "agent_command",
    "agent_uid",
    "broker_socket",
    "enroll",
    "ensure_job_folder",
    "main",
    "tenant_roots",
]
