"""Codex seat: Codex on the person's own ChatGPT login, through the platform (variant A).

The login is the person's own and is made with Codex's official login, never by the launcher:

- the **seat home** ``<state>/codex-seat`` is a ``CODEX_HOME`` only for that login. ``octryx codex login`` runs
  ``codex login`` (browser, or ``--device-auth``) with it and ``cli_auth_credentials_store = "file"``, so Codex
  writes ``<seat home>/auth.json`` itself. The launcher never reads, copies, prints or sends that file;
- a seat **session's** ``CODEX_HOME`` holds ``auth.json`` as a symlink to the seat home's. Codex follows a linked
  credential file and writes a refreshed token through it (codex-rs ``login/src/auth/storage_file.rs``
  ``resolve_auth_file``), so every session uses the one login without a copy;
- ``octryx codex status`` asks ``codex login status`` and shows only logged in or not; the device service reports the
  same yes/no to the platform (``codex_seat_login`` in ``hello``/``state``, :func:`reported_login`), as it reports
  the Claude seat's ``seat_login``.

Where the seat's model calls leave is the platform's switch (``seat_traffic`` in ``/client-policy``'s ``codex_seat``,
:func:`seat_traffic`):

- ``device`` (the platform's default): the session's provider is the job's loopback seat proxy
  (``codex_seat_proxy``): the platform admits each call, the proxy sends it to ChatGPT from this device and reports
  the answer;
- ``gateway`` (and any platform that does not name it): the platform's seat route
  (``/api/v1/model-gateway/openai/seat``, ``requires_openai_auth``) receives the ChatGPT token and forwards it
  unchanged to ChatGPT's Codex backend.

Either way the Workspace's seat policy, the hooks, the transcript and the evidence apply, and there is never a
fallback from one way to the other. The session-bound seat credential travels from the process environment
(:data:`SEAT_CREDENTIAL_ENV`), never through a file.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

SEAT_HOME = "codex-seat"
SEAT_ROUTE = "/api/v1/model-gateway/openai/seat"
SEAT_PROVIDER_ID = "octryx_seat"
# Not an ``OCTRYX_*`` name: the hook wrapper exports those into a file; this one lives only in the process env.
SEAT_CREDENTIAL_ENV = "OCTRYX_CODEX_SEAT_CREDENTIAL"
SEAT_CREDENTIAL_HEADER = "X-Octryx-Seat-Credential"
_CONFIG = 'cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n'
TRAFFIC_DEVICE = "device"
TRAFFIC_GATEWAY = "gateway"
EXTRA_TRAFFIC = "codex_seat_traffic"


def seat_traffic(policy: object) -> str:
    """``device`` when the platform's ``/client-policy`` says so; else ``gateway`` (a platform without the switch has
    no admit/report pair)."""
    seat = policy.get("codex_seat") if isinstance(policy, dict) else None
    return TRAFFIC_DEVICE if isinstance(seat, dict) and seat.get("seat_traffic") == TRAFFIC_DEVICE else TRAFFIC_GATEWAY


def sends_from_device(extra: dict) -> bool:
    return bool(extra.get("codex_seat")) and extra.get(EXTRA_TRAFFIC) == TRAFFIC_DEVICE


def seat_home(state_root: str | Path) -> Path:
    return Path(state_root) / SEAT_HOME


def ensure_seat_home(state_root: str | Path) -> Path:
    home = seat_home(state_root)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = home / "config.toml"
    if not config.exists():
        config.write_text(_CONFIG, encoding="utf-8")
    return home


def _env(state_root: str | Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key not in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN")}
    env["CODEX_HOME"] = str(ensure_seat_home(state_root))
    return env


def logged_in(codex: str, state_root: str | Path) -> bool:
    """Whether the seat home has a ChatGPT login (``codex login status``'s exit code; its output is discarded)."""
    try:
        done = subprocess.run([codex, "login", "status"], env=_env(state_root), stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


REPORT_CACHE_SECONDS = 300.0
# ``(seat home, auth.json mtime) -> (checked at, logged in)``: the device service asks every few seconds; ``codex login
# status`` runs again only after :data:`REPORT_CACHE_SECONDS` or when the login file changed (a login or a logout).
_reported: dict[tuple[str, int], tuple[float, bool]] = {}


def _resolved_codex() -> str:
    from .codex_driver import CodexUnavailableError, resolve_codex  # noqa: PLC0415

    try:
        return resolve_codex()
    except CodexUnavailableError:
        return ""


def reported_login(state_root: str | Path, *, codex: Callable[[], str] = _resolved_codex,
                   clock: Callable[[], float] = time.monotonic) -> bool:
    """Logged in yes/no for the device report: ``codex login status``'s exit code only, never the file's contents.

    No login file in the seat home (or no usable ``codex``) is ``False`` without running Codex."""
    auth = seat_home(state_root) / "auth.json"
    try:
        stamp = auth.stat().st_mtime_ns
    except OSError:
        return False
    key = (str(auth.parent), stamp)
    now = clock()
    cached = _reported.get(key)
    if cached is not None and now - cached[0] < REPORT_CACHE_SECONDS:
        return cached[1]
    binary = codex()
    answer = bool(binary) and logged_in(binary, state_root)
    _reported.clear()
    _reported[key] = (now, answer)
    return answer


def login(codex: str, state_root: str | Path, *, device_auth: bool = False) -> int:
    """The person's own ``codex login`` into the seat home (interactive; the launcher sees none of it)."""
    argv = [codex, "login", *(["--device-auth"] if device_auth else [])]
    return subprocess.call(argv, env=_env(state_root))


def link_login(session_home: Path, state_root: str | Path) -> None:
    """``<session home>/auth.json`` -> the seat home's, a link (never a copy)."""
    target = seat_home(state_root) / "auth.json"
    link = session_home / "auth.json"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


__all__ = ["EXTRA_TRAFFIC", "REPORT_CACHE_SECONDS", "SEAT_CREDENTIAL_ENV", "SEAT_CREDENTIAL_HEADER", "SEAT_PROVIDER_ID",
           "SEAT_ROUTE", "TRAFFIC_DEVICE", "TRAFFIC_GATEWAY", "ensure_seat_home", "link_login", "logged_in", "login",
           "reported_login", "seat_home", "seat_traffic", "sends_from_device"]
