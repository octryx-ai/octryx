"""Host command execution with a sanitized environment."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from .contracts import ExecutionRuntimeResult
from .process_tree import communicate_within_deadline, process_group_spawn_kwargs

# Environment variables that are dangerous if passed through to shell execution
_DANGEROUS_ENV_VARS: frozenset[str] = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_PROFILE",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    # The container-credentials opt-in: a child with these gets the process's AWS role implicitly.
    "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "GCP_SERVICE_ACCOUNT_KEY", "KUBECONFIG",
    "GONOGOSSH", "PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "GIT_SSH_COMMAND", "GIT_TEMPLATE_DIR", "GIT_CONFIG_PARAMETERS",
})


def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
    """Remove dangerous environment variables from env dict."""
    return {k: v for k, v in env.items() if k not in _DANGEROUS_ENV_VARS}


def _host_env(
    *, shell: bool, env: Mapping[str, str] | None, process_env: Mapping[str, str] | None
) -> dict[str, str]:
    # When shell=True, build a minimal environment — do not blindly inherit
    # the host environment, which enables variable expansion and injection attacks.
    if shell:
        safe_vars = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/root"),
            "USER": os.environ.get("USER", "root"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        host_env = dict(safe_vars)
        # None means "inherit the host environment" (sanitized).
        inherited_env = process_env if process_env is not None else os.environ
        if inherited_env:
            host_env.update(_sanitize_env(dict(inherited_env)))
        if env:
            host_env.update(_sanitize_env(dict(env)))
    else:
        host_env = dict(process_env or os.environ)
        if env:
            host_env.update(env)
    return host_env


async def _run_host_command_impl(
    *,
    command: list[str] | str,
    cwd: Path,
    timeout_sec: int,
    shell: bool,
    env: Mapping[str, str] | None = None,
    process_env: Mapping[str, str] | None = None,
    subprocess_shell_factory: Callable[..., Awaitable[Any]] | None = None,
    subprocess_exec_factory: Callable[..., Awaitable[Any]] | None = None,
) -> ExecutionRuntimeResult:
    # Resolve at call time so monkeypatched module attributes take effect.
    subprocess_shell_factory = subprocess_shell_factory or asyncio.create_subprocess_shell
    subprocess_exec_factory = subprocess_exec_factory or asyncio.create_subprocess_exec
    host_env = _host_env(shell=shell, env=env, process_env=process_env)
    if shell:
        process = await subprocess_shell_factory(
            str(command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=host_env,
            **process_group_spawn_kwargs(),
        )
    else:
        argv = [str(arg) for arg in (command if isinstance(command, list) else [command])]
        process = await subprocess_exec_factory(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=host_env,
            **process_group_spawn_kwargs(),
        )
    # The deadline (and a cancellation) kills the whole process group, not only the direct child.
    output = await communicate_within_deadline(process, timeout_sec=timeout_sec)
    if output.timed_out:
        return ExecutionRuntimeResult(
            exit_code=None,
            stdout="",
            stderr=f"Command timed out after {timeout_sec}s",
            timed_out=True,
            metadata={"provider": "host", "containerized": False},
        )
    return ExecutionRuntimeResult(
        exit_code=process.returncode,
        stdout=output.stdout.decode("utf-8", errors="replace"),
        stderr=output.stderr.decode("utf-8", errors="replace"),
        timed_out=False,
        metadata={"provider": "host", "containerized": False},
    )
