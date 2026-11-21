"""A Bearer token for Git over HTTPS, without putting it into argv, a URL or a file.

Git reads ``http.<url>.extraHeader`` from its configuration; ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_<n>`` /
``GIT_CONFIG_VALUE_<n>`` (Git 2.31+) add configuration through the process environment only, the same way the
other credentials reach Git today (the askpass script reads them from the environment). The header is scoped to
the remote's origin (``http.https://host[:port]/.extraHeader``), so a redirect to, or a submodule on, another host
never receives it. A refused token fails instead of asking for other credentials: ``GIT_TERMINAL_PROMPT=0``, no
inherited ``GIT_ASKPASS``/``SSH_ASKPASS``, and the credential helpers are cleared (``credential.helper`` empty).
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit


def _origin(remote_url: str) -> str:
    split = urlsplit(str(remote_url or "").strip())
    host = (split.hostname or "").lower()
    scheme = split.scheme.lower()
    if scheme not in ("http", "https") or not host:
        raise ValueError("A Git remote over HTTP(S) is required for a Bearer token.")
    if ":" in host:  # an IPv6 literal keeps its brackets
        host = f"[{host}]"
    return f"{scheme}://{host}{f':{split.port}' if split.port else ''}/"


def _config_count(env: Mapping[str, str]) -> int:
    raw = str(env.get("GIT_CONFIG_COUNT") or "").strip()
    return int(raw) if raw.isdigit() else 0


def bearer_header_env(remote_url: str, token: str, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """``base`` (default: this process's environment) plus the remote origin's ``Authorization: Bearer`` header."""
    if not token or any(ch in token for ch in "\r\n"):
        raise ValueError("A Bearer token for Git is required.")
    env = dict(os.environ if base is None else base)
    for name in ("GIT_ASKPASS", "SSH_ASKPASS"):
        env.pop(name, None)
    index = _config_count(env)
    config = (("credential.helper", ""), (f"http.{_origin(remote_url)}.extraHeader", f"Authorization: Bearer {token}"))
    for offset, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index + offset}"], env[f"GIT_CONFIG_VALUE_{index + offset}"] = key, value
    env["GIT_CONFIG_COUNT"] = str(index + len(config))
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def basic_header_env(remote_url: str, username: str, secret: str,
                     base: Mapping[str, str] | None = None) -> dict[str, str]:
    """``base`` plus the remote origin's ``Authorization: Basic`` header (GitHub's ``x-access-token`` + token, a
    Bitbucket username + password), the same way as :func:`bearer_header_env`: environment only, no script."""
    if not username or not secret or any(ch in username + secret for ch in "\r\n"):
        raise ValueError("A username and a password for Git are required.")
    pair = base64.b64encode(f"{username}:{secret}".encode()).decode()
    env = dict(os.environ if base is None else base)
    for name in ("GIT_ASKPASS", "SSH_ASKPASS"):
        env.pop(name, None)
    index = _config_count(env)
    config = (("credential.helper", ""), (f"http.{_origin(remote_url)}.extraHeader", f"Authorization: Basic {pair}"))
    for offset, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index + offset}"], env[f"GIT_CONFIG_VALUE_{index + offset}"] = key, value
    env["GIT_CONFIG_COUNT"] = str(index + len(config))
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def has_credentials(url: str) -> bool:
    """True when an HTTP(S) URL carries a user or password (``https://user:secret@host/...``)."""
    split = urlsplit(str(url or "").strip())
    return split.scheme.lower() in ("http", "https") and "@" in split.netloc


def without_credentials(url: str) -> str:
    """The URL without its user and password; any other URL as it is."""
    text = str(url or "").strip()
    if not has_credentials(text):
        return text
    split = urlsplit(text)
    return urlunsplit((split.scheme, split.netloc.rsplit("@", 1)[1], split.path, split.query, split.fragment))


_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    "case \"$1\" in\n"
    "  *Username*|*username*) printf '%s\\n' \"$OCTRYX_GIT_USERNAME\" ;;\n"
    "  *Password*|*password*) printf '%s\\n' \"$OCTRYX_GIT_SECRET\" ;;\n"
    "  *) printf '\\n' ;;\n"
    "esac\n"
)


def basic_askpass_env(
    remote_url: str, username: str, secret: str, *, script_dir: str, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """``base`` plus an askpass answering Git's Basic prompts from the environment (a username and password sign-in).

    The script written to ``script_dir`` holds no value: it prints ``OCTRYX_GIT_USERNAME`` /
    ``OCTRYX_GIT_SECRET`` from Git's environment. Credential helpers are cleared, so nothing is stored.
    """
    _origin(remote_url)  # an HTTP(S) remote only
    if not username or not secret or any(ch in username + secret for ch in "\r\n"):
        raise ValueError("A username and a password for Git are required.")
    script = os.path.join(script_dir, "askpass.sh")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(_ASKPASS_SCRIPT)
    os.chmod(script, 0o700)
    env = dict(os.environ if base is None else base)
    env.pop("SSH_ASKPASS", None)
    index = _config_count(env)
    env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = "credential.helper", ""
    env["GIT_CONFIG_COUNT"] = str(index + 1)
    env.update({"GIT_ASKPASS": script, "GIT_TERMINAL_PROMPT": "0", "OCTRYX_GIT_USERNAME": username,
                "OCTRYX_GIT_SECRET": secret})
    return env


__all__ = ["basic_askpass_env", "basic_header_env", "bearer_header_env", "has_credentials", "without_credentials"]
