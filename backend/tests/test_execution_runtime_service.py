import pytest

from app.models import SystemConfig
from app.services.execution_runtime import (
    ExecutionRuntimeResult,
    execute_with_runtime,
    resolve_execution_runtime_config,
    workspace_mount_for_path,
)


@pytest.mark.asyncio
async def test_resolve_execution_runtime_config_uses_system_and_project_overrides(db):
    db.add_all(
        [
            SystemConfig(key="agent.execution_runtime_provider", value="docker"),
            SystemConfig(key="agent.execution_runtime_docker_image", value="python:3.12-slim"),
            SystemConfig(key="agent.execution_runtime_docker_network_mode", value="bridge"),
            SystemConfig(key="agent.execution_runtime_allow_host_fallback", value="true"),
            SystemConfig(key="agent.execution_runtime_sandbox_mode", value="compat"),
            SystemConfig(key="agent.execution_runtime_docker_memory_mb", value="768"),
            SystemConfig(key="agent.execution_runtime_docker_pids_limit", value="512"),
        ]
    )
    await db.commit()

    config = await resolve_execution_runtime_config(
        db,
        project_config={
            "execution_runtime_docker_image": "ghcr.io/example/octryx-runtime:1",
            "execution_runtime_allow_host_fallback": False,
            "execution_runtime_sandbox_mode": "hard",
            "execution_runtime_docker_memory_mb": 1024,
        },
    )

    assert config.provider == "docker"
    assert config.docker_image == "ghcr.io/example/octryx-runtime:1"
    assert config.docker_network_mode == "bridge"
    assert config.allow_host_fallback is False
    assert config.sandbox_mode == "hard"
    assert config.docker_memory_mb == 1024
    assert config.docker_pids_limit == 512


@pytest.mark.asyncio
async def test_execute_with_runtime_builds_docker_command(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    cwd = workspace_root / "repo"
    extra_mount = tmp_path / "kubeconfig"
    cwd.mkdir(parents=True)
    extra_mount.write_text("apiVersion: v1\n", encoding="utf-8")
    observed: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"ok", b"")

    async def fake_exec(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("app.services.execution_runtime.docker.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("app.services.execution_runtime.docker.asyncio.create_subprocess_exec", fake_exec)

    result = await execute_with_runtime(
        db=None,
        project_config={
            "execution_runtime_provider": "docker",
            "execution_runtime_docker_image": "ghcr.io/example/octryx-runtime:1",
            "execution_runtime_docker_network_mode": "bridge",
            "execution_runtime_allow_host_fallback": False,
            "execution_runtime_sandbox_mode": "hard",
            "execution_runtime_docker_memory_mb": 640,
            "execution_runtime_docker_pids_limit": 300,
        },
        command=["python3", "-V"],
        cwd=cwd,
        workspace_root=workspace_root,
        timeout_sec=30,
        mounts=[workspace_mount_for_path(host_path=extra_mount, container_path="/runtime-mounts/kubeconfig")],
    )

    argv = list(observed["args"])
    assert argv[:5] == ["/usr/bin/docker", "run", "--rm", "--init", "--network"]
    assert "bridge" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert "--read-only" in argv
    assert "--memory" in argv
    assert "640m" in argv
    assert "--pids-limit" in argv
    assert "300" in argv
    assert f"{workspace_root.resolve()}:/workspace" in argv
    assert "/workspace/repo" in argv
    assert f"{extra_mount.resolve()}:/runtime-mounts/kubeconfig:ro" in argv
    assert "ghcr.io/example/octryx-runtime:1" in argv
    assert argv[-2:] == ["python3", "-V"]
    assert result.exit_code == 0
    assert result.metadata["provider"] == "docker"
    assert result.metadata["containerized"] is True
    assert result.metadata["sandbox_mode"] == "hard"


@pytest.mark.asyncio
async def test_execute_with_runtime_falls_back_to_host_when_docker_missing(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    async def fake_host_command(**kwargs):
        return ExecutionRuntimeResult(
            exit_code=0,
            stdout="hello",
            stderr="",
            timed_out=False,
            metadata={"provider": "host", "containerized": False},
        )

    monkeypatch.setattr("app.services.execution_runtime.docker.shutil.which", lambda _: None)
    monkeypatch.setattr("app.services.execution_runtime.service._run_host_command_impl", fake_host_command)

    result = await execute_with_runtime(
        db=None,
        project_config={
            "execution_runtime_provider": "docker",
            "execution_runtime_allow_host_fallback": True,
        },
        command=["printf", "hello"],
        cwd=workspace_root,
        workspace_root=workspace_root,
        timeout_sec=30,
    )

    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.metadata["provider"] == "host"
    assert result.metadata["host_fallback"] is True
    assert result.metadata["fallback_reason"] == "execution_runtime_unavailable"


@pytest.mark.asyncio
async def test_execute_with_runtime_does_not_fall_back_to_host_by_default(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    monkeypatch.setattr("app.services.execution_runtime.docker.shutil.which", lambda _: None)

    result = await execute_with_runtime(
        db=None,
        project_config={
            "execution_runtime_provider": "docker",
        },
        command=["printf", "hello"],
        cwd=workspace_root,
        workspace_root=workspace_root,
        timeout_sec=30,
    )

    assert result.exit_code is None
    assert result.stdout == ""
    assert result.stderr == "execution_runtime_unavailable error_type=ExecutionRuntimeUnavailableError"
    assert result.metadata["host_fallback"] is False
    assert result.metadata["requested_provider"] == "docker"


@pytest.mark.asyncio
async def test_execute_with_runtime_hard_sandbox_disables_host_fallback(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    monkeypatch.setattr("app.services.execution_runtime.docker.shutil.which", lambda _: None)

    result = await execute_with_runtime(
        db=None,
        project_config={
            "execution_runtime_provider": "docker",
            "execution_runtime_allow_host_fallback": True,
            "execution_runtime_sandbox_mode": "hard",
        },
        command=["printf", "hello"],
        cwd=workspace_root,
        workspace_root=workspace_root,
        timeout_sec=30,
    )

    assert result.exit_code is None
    assert result.stdout == ""
    assert result.stderr == "execution_runtime_unavailable error_type=ExecutionRuntimeUnavailableError"
    assert result.metadata["requested_provider"] == "docker"
    assert result.metadata["host_fallback"] is False
    assert result.metadata["sandbox_mode"] == "hard"


def test_shell_children_do_not_inherit_the_aws_container_credentials_opt_in():
    """With AWS_CONTAINER_* set, botocore in a child would silently assume the process's AWS role."""
    from app.services.execution_runtime.host import _sanitize_env

    env = {
        "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://127.0.0.1:9911/v1/credentials",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/example",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN": "example",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE": "/run/secrets/aws_container_credentials_token",
        "AWS_REGION": "eu-central-1",
    }
    assert _sanitize_env(env) == {"AWS_REGION": "eu-central-1"}
