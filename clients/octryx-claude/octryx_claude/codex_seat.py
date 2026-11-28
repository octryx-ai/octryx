"""Codex seat: Codex on the person's own ChatGPT login, made with Codex's official login, never by the launcher.
Sessions link the seat home's ``auth.json``, so Codex writes refreshed tokens through to the one login."""

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
    argv = [codex, "login", *(["--device-auth"] if device_auth else [])]
    return subprocess.call(argv, env=_env(state_root))


def link_login(session_home: Path, state_root: str | Path) -> None:
    target = seat_home(state_root) / "auth.json"
    link = session_home / "auth.json"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


__all__ = ["REPORT_CACHE_SECONDS", "SEAT_CREDENTIAL_ENV", "SEAT_CREDENTIAL_HEADER", "SEAT_PROVIDER_ID", "SEAT_ROUTE",
           "ensure_seat_home", "link_login", "logged_in", "login", "reported_login", "seat_home"]
