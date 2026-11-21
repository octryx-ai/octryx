"""The headless runner inside a platform sandbox.

Rule: a sandbox is a device the platform owns. It takes only the jobs of the run it was started for, holds no
repository credential and reaches git only through the platform's run-bound gateway.

A sandbox talks to the platform like a device: a short-lived container per run, in which ``octryx-claude device run
--sandbox`` takes the run's device jobs exactly as a Mac does (events, approvals, files, live progress). Here:

Git goes only through the platform's git gateway: the sandbox never sees a repository token. The runner mints a
short-lived, run-bound gateway token with its sandbox device credential (``POST /api/v1/devices/sandbox/git-token
{run_id}`` → ``{token, expires_at, url}``) whenever git asks for one, through the credential helper ``octryx-claude
git-credential`` (username ``x-run``). origin is the gateway URL; nothing secret is ever written to ``.git/config``.
The gateway enforces read/read_write, pushes only to ``octryx-run/<run_id>``, no force, no tags; the platform opens
the pull request.

1. **Inputs:**
   - env: ``OCTRYX_BASE_URL``, ``OCTRYX_SANDBOX_RUN_ID``, ``OCTRYX_SANDBOX_BRANCH`` (the base branch, optional),
     ``OCTRYX_WORKSPACE`` (default ``/workspace``), ``OCTRYX_TOOLCHAIN``;
   - one secret file: ``/run/secrets/octryx/enroll`` (one-time, run-bound, TTL ≤ 10 min, worthless once used).
2. **Enrollment** (:func:`enroll`): a fresh Ed25519 key in the state dir (tmpfs), then ``POST
   /api/v1/devices/sandbox/enroll {token, public_key, …}``. The answer has the device registration's shape
   ``{credential: {refresh_token, client_id, scopes}, device: {id}}``, so the normal token and renewal code works
   unchanged. The device is ``linux``, ``service_kind: sandbox``, folders ``[/workspace]``, profile ``governed``,
   one job at a time.
3. **Checkout** (:func:`checkout`): ``git clone`` from the gateway URL into the workspace, the repository's
   credential helper set to ``octryx-claude git-credential`` (the agent's own fetch and push work the same way), and
   the run branch ``octryx-run/<run_id>`` checked out.
4. **Serve** (:func:`serve`): the normal channel and job manager, without the person-level parts (no live sessions,
   no update check, no local model, no folder watcher, no notifications, no pet).
5. **End:** after :data:`IDLE_EXIT_SECONDS` without a running turn once a turn finished, after
   :data:`FIRST_JOB_SECONDS` without any job, on revoke or SIGTERM. Exit 0; log lines as JSON on stdout.

Model calls go only through the platform gateway with the device credential (the governed profile): there is no
model key in the container.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__, device_state
from .sandbox_serve import serve
from .state import CREDENTIAL_SET_DEVICE, CREDENTIAL_SET_ENV, HOME_ENV, LocalState

ENROLL_PATH = "/api/v1/devices/sandbox/enroll"
GIT_TOKEN_PATH = "/api/v1/devices/sandbox/git-token"
ENROLL_FILE = Path("/run/secrets/octryx/enroll")
GIT_USER = "x-run"
HELPER = "!octryx-claude git-credential"
DEFAULT_WORKSPACE = "/workspace"
HTTP_TIMEOUT = 30.0
CLONE_TIMEOUT = 600.0
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")

logger = logging.getLogger("octryx_claude.sandbox")


class SandboxError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": round(record.created, 3), "level": record.levelname.lower(), "logger": record.name,
                           "message": record.getMessage()})


def settings(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The sandbox's inputs from the environment, checked; raises :class:`SandboxError` with a fixed code."""
    source = os.environ if env is None else env
    base_url = source.get("OCTRYX_BASE_URL", "").strip().rstrip("/")
    run_id = source.get("OCTRYX_SANDBOX_RUN_ID", "").strip()
    branch = source.get("OCTRYX_SANDBOX_BRANCH", "").strip()
    if not base_url.startswith("https://"):
        raise SandboxError("base_url_not_https")
    if not _RUN_ID.match(run_id):
        raise SandboxError("run_id_invalid")
    if branch and (not _BRANCH.match(branch) or branch.startswith("-") or ".." in branch):
        raise SandboxError("branch_invalid")
    return {"base_url": base_url, "run_id": run_id, "branch": branch,
            "workspace": source.get("OCTRYX_WORKSPACE", "").strip() or DEFAULT_WORKSPACE,
            "toolchain": source.get("OCTRYX_TOOLCHAIN", "").strip()}


def _secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return value if 16 <= len(value) <= 8192 and not any(ch.isspace() for ch in value) else ""


def enroll(state: LocalState, config: Mapping[str, str], *, http: httpx.Client, token_file: Path = ENROLL_FILE) -> str:
    """Registers this sandbox as the run's device; returns the device id. Raises :class:`SandboxError`."""
    token = _secret(token_file)
    if not token:
        raise SandboxError("enroll_token_missing")
    workspace = config["workspace"]
    body = {"token": token, "run_id": config["run_id"], "public_key": device_state.generate_key(state),
            "os": "linux", "folders": [workspace], "profiles_available": ["governed"], "max_parallel_jobs": 1,
            "client_version": __version__, "service_kind": "sandbox", "toolchain": config.get("toolchain", "")}
    try:
        response = http.post(f"{config['base_url']}{ENROLL_PATH}", json=body, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise SandboxError("platform_unreachable") from exc
    if response.status_code not in (200, 201):
        raise SandboxError(f"enroll_refused_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SandboxError("enroll_answer_invalid") from exc
    credential = payload.get("credential") if isinstance(payload, dict) else None
    device = payload.get("device") if isinstance(payload, dict) else None
    if not isinstance(credential, dict) or not isinstance(device, dict) or not credential.get("refresh_token") \
            or not device.get("id"):
        raise SandboxError("enroll_answer_invalid")
    state.with_credential_set(CREDENTIAL_SET_DEVICE).write_credentials({
        "base_url": config["base_url"], "client_id": str(credential.get("client_id") or ""),
        "refresh_token": str(credential["refresh_token"]), "scopes": list(credential.get("scopes") or []),
        "tokens": {},
    })
    device_state.save_device(state, {
        "device_id": str(device["id"]), "name": f"sandbox-{config['run_id']}"[:60], "os": "linux",
        "base_url": config["base_url"], "folders": [workspace], "max_parallel_jobs": 1, "paused": False,
        "service_kind": "sandbox", "sandbox_run_id": config["run_id"],
    })
    return str(device["id"])


def git_token(state: LocalState, *, http: httpx.Client) -> dict[str, str]:
    """A fresh gateway token for this sandbox's run, minted with the device credential; raises SandboxError."""
    from .tokens import DEVICE_AUDIENCE, TokenUnavailableError, get_access_token  # noqa: PLC0415

    device = device_state.load_device(state)
    run_id, base_url = str(device.get("sandbox_run_id") or ""), str(device.get("base_url") or "")
    if not _RUN_ID.match(run_id) or not base_url.startswith("https://"):
        raise SandboxError("not_enrolled")
    try:
        access = get_access_token(state.with_credential_set(CREDENTIAL_SET_DEVICE), DEVICE_AUDIENCE, http=http)
        response = http.post(f"{base_url}{GIT_TOKEN_PATH}", json={"run_id": run_id},
                             headers={"Authorization": f"Bearer {access}"}, timeout=HTTP_TIMEOUT)
    except (TokenUnavailableError, httpx.HTTPError) as exc:
        raise SandboxError("git_token_unavailable") from exc
    if response.status_code not in (200, 201):
        raise SandboxError(f"git_token_refused_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SandboxError("git_token_invalid") from exc
    token, url = (payload.get(key) if isinstance(payload, dict) else None for key in ("token", "url"))
    if not isinstance(token, str) or not token or any(ch.isspace() for ch in token) or not isinstance(url, str) \
            or not url.startswith(("https://", "http://")) or "@" in url.split("/", 3)[2]:
        raise SandboxError("git_token_invalid")
    return {"token": token, "url": url, "expires_at": str(payload.get("expires_at") or "")}


# What git (and the credential helper it starts) inherits from the container (like the server's
# server_env.ALLOWED_INHERITED): the basics, TLS trust, proxies, and where the device state lives. Nothing else.
GIT_ENV_ALLOWED = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
                   "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                   "http_proxy", "https_proxy", "no_proxy", HOME_ENV, CREDENTIAL_SET_ENV)


def git_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment git runs with in the sandbox: the allowlist above plus no prompts and no system config."""
    environ = os.environ if source is None else source
    env = {key: environ[key] for key in GIT_ENV_ALLOWED if key in environ}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def credential_helper(action: str, stdin: Any, stdout: Any, *, state: LocalState | None = None,
                      http_factory: Callable[[], httpx.Client] = httpx.Client) -> int:
    """``octryx-claude git-credential <get|store|erase>``: git's credential helper protocol. ``get`` answers with a
    fresh gateway token, and only when git names exactly the gateway's protocol and host; nothing is
    ever stored."""
    request: dict[str, str] = {}
    for line in stdin.read().splitlines():
        key, _, value = line.partition("=")
        if key:
            request[key] = value
    if action != "get":
        return 0  # store/erase: the token lives only for this one git call
    if not request.get("protocol") or not request.get("host"):
        return 0  # git always names both for an http(s) remote; a request without them gets nothing
    state = state or LocalState()
    try:
        with http_factory(follow_redirects=False) as http:
            minted = git_token(state, http=http)
    except SandboxError as error:
        logger.warning("no gateway token for git: %s", error.code)
        return 1
    gateway = urlsplit(minted["url"])
    if request["protocol"] != gateway.scheme or request["host"] != gateway.netloc:
        return 0  # another protocol or host asks: it gets nothing
    stdout.write(f"username={GIT_USER}\npassword={minted['token']}\n")
    return 0


def checkout(state: LocalState, config: Mapping[str, str], *, http: httpx.Client,
             run: Callable[..., Any] = subprocess.run) -> str:
    """Clones the run's repository from the gateway into the (empty) workspace and checks out the run branch."""
    workspace = Path(config["workspace"])
    if workspace.exists() and any(workspace.iterdir()):
        raise SandboxError("workspace_not_empty")
    url = git_token(state, http=http)["url"]
    env = git_env()
    branch = f"octryx-run/{config['run_id']}"
    clone = ["git", "-c", "credential.helper=", "-c", f"credential.helper={HELPER}", "clone", "--no-tags",
             "--single-branch"] + (["--branch", config["branch"]] if config.get("branch") else []) + \
            ["--", url, str(workspace)]
    steps = [clone,
             ["git", "-C", str(workspace), "config", "--replace-all", "credential.helper", ""],
             ["git", "-C", str(workspace), "config", "--add", "credential.helper", HELPER],
             ["git", "-C", str(workspace), "config", "push.default", "current"],
             ["git", "-C", str(workspace), "checkout", "-b", branch]]
    for argv in steps:
        try:
            done = run(argv, env=env, capture_output=True, text=True, timeout=CLONE_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxError("clone_failed") from exc
        if getattr(done, "returncode", 1) != 0:
            raise SandboxError("clone_failed")
    return branch


def maven_mirror(env: Mapping[str, str], home: Path) -> Path | None:
    """With ``MAVEN_MIRROR`` set (a later Nexus/Artifactory), a ``settings.xml`` that sends every request there."""
    mirror = env.get("MAVEN_MIRROR", "").strip()
    if not mirror.startswith("https://"):
        return None
    from xml.sax.saxutils import escape  # noqa: PLC0415

    path = home / ".m2" / "settings.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""<settings><mirrors><mirror><id>platform</id><mirrorOf>*</mirrorOf>
<url>{escape(mirror)}</url></mirror></mirrors></settings>
""", encoding="utf-8")
    return path


def main(env: Mapping[str, str] | None = None) -> int:
    """``octryx-claude device run --sandbox``."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLines())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    source = dict(os.environ if env is None else env)
    try:
        config = settings(source)
        state = LocalState()
        maven_mirror(source, Path(source.get("HOME") or "/tmp/home"))
        with httpx.Client(follow_redirects=False) as http:
            device_id = enroll(state, config, http=http)
            logger.info("enrolled as %s for run %s", device_id, config["run_id"])
            branch = checkout(state, config, http=http)
        logger.info("workspace cloned through the git gateway; branch %s", branch)
    except SandboxError as error:
        logger.error("sandbox did not start: %s", error.code)
        return 2

    async def run() -> str:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, stop.set)
        return await serve(state, stop)

    reason = asyncio.run(run())
    logger.info("sandbox ends (%s)", reason)
    return 0


__all__ = [
    "SandboxError",
    "checkout",
    "credential_helper",
    "enroll",
    "git_token",
    "main",
    "settings",
]
