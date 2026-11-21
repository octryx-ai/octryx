from __future__ import annotations

import pytest

from app.services.persistent_process_runtime import (
    configure_persistent_process_runtime,
    spawn_persistent_pty_process,
    spawn_persistent_stdio_process,
)


@pytest.mark.asyncio
async def test_spawn_persistent_stdio_process_builds_docker_command(monkeypatch, tmp_path):
    configure_persistent_process_runtime(None)

    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = None
        stdin = object()
        stdout = object()

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(
        "app.services.persistent_process_runtime.service.resolve_execution_runtime_config",
        lambda db, project_config=None: _async_return(
            type(
                "Cfg",
                (),
                {
                    "provider": "docker",
                    "docker_image": "python:3.12-slim",
                    "docker_network_mode": "bridge",
                    "allow_host_fallback": True,
                    "sandbox_mode": "hard",
                    "docker_memory_mb": 768,
                    "docker_pids_limit": 128,
                },
            )()
        ),
    )
    monkeypatch.setattr(
        "app.services.persistent_process_runtime.service.asyncio.create_subprocess_exec",
        fake_exec,
    )
    monkeypatch.setattr(
        "app.services.persistent_process_runtime.docker_command.shutil.which",
        lambda binary: "/usr/bin/docker" if binary == "docker" else None,
    )

    handle = await spawn_persistent_stdio_process(
        db=None,
        project_config={},
        command=["pylsp"],
        cwd=tmp_path,
        workspace_root=tmp_path,
        stderr_mode="devnull",
    )

    assert handle.runtime_kind == "stdio"
    assert handle.metadata["provider"] == "docker"
    assert handle.metadata["sandbox_mode"] == "hard"
    args = list(captured["args"])
    assert args[:6] == ["/usr/bin/docker", "run", "--rm", "--init", "-i", "--network"]
    assert "--cap-drop=ALL" in args
    assert "--memory" in args
    assert "768m" in args
    assert "--pids-limit" in args
    assert "128" in args
    assert "python:3.12-slim" in args
    assert "pylsp" in args


@pytest.mark.asyncio
async def test_spawn_persistent_pty_process_falls_back_to_host(monkeypatch, tmp_path):
    configure_persistent_process_runtime(None)

    class FakePopen:
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.pid = 4321

    monkeypatch.setattr(
        "app.services.persistent_process_runtime.service.resolve_execution_runtime_config",
        lambda db, project_config=None: _async_return(
            type(
                "Cfg",
                (),
                {
                    "provider": "docker",
                    "docker_image": "python:3.11-slim",
                    "docker_network_mode": "none",
                    "allow_host_fallback": True,
                    "sandbox_mode": "compat",
                    "docker_memory_mb": 512,
                    "docker_pids_limit": 256,
                },
            )()
        ),
    )
    monkeypatch.setattr(
        "app.services.persistent_process_runtime.docker_command.shutil.which",
        lambda binary: None if binary == "docker" else None,
    )
    monkeypatch.setattr(
        "app.services.persistent_process_runtime.service.subprocess.Popen",
        FakePopen,
    )

    handle = await spawn_persistent_pty_process(
        db=None,
        project_config={},
        shell_command="/bin/bash",
        cwd=tmp_path,
        workspace_root=tmp_path,
        master_fd=10,
        slave_fd=11,
        env={"TERM": "xterm-256color"},
    )

    assert handle.runtime_kind == "pty"
    assert handle.metadata["provider"] == "host"
    assert handle.metadata["host_fallback"] is True
    assert handle.process.pid == 4321
    assert handle.process.argv == ["/bin/bash"]


async def _async_return(value):
    return value
