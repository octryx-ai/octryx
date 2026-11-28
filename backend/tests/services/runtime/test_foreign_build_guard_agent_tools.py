"""The execution runtime backstop, the agent tools (bash, run_cli_command, start_runtime_process, run_validation_commands, check_file_syntax) and the code-quality runner refuse a build before anything starts and still run read-only commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.execution_runtime import ExecutionRuntimeResult, execute_with_runtime
from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE, SERVER_BUILD_NOT_ALLOWED
from app.services.execution_runtime.foreign_build_guard import runtime_refusal
from app.tools.context import ToolContext


def _runtime_fakes():
    calls: list = []

    async def config(db, project_config=None):
        from app.services.execution_runtime import ExecutionRuntimeConfig

        return ExecutionRuntimeConfig(provider="host")

    async def host(**kwargs):
        calls.append(kwargs["command"])
        return ExecutionRuntimeResult(exit_code=0, stdout="ok", stderr="", timed_out=False, metadata={})

    return calls, {"resolve_config_fn": config, "host_command_fn": host}


def _context(tmp_path, **extra) -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=["admin"], session_id="s", project_config={},
                       workspace_root=str(tmp_path), **extra)


def _fake_runtime(monkeypatch):
    from app.tools.runtime_impl import _runtime_workspace_cli

    calls: list = []

    async def execute(**kwargs):
        calls.append(kwargs["command"])
        return ExecutionRuntimeResult(exit_code=0, stdout="", stderr="", timed_out=False, metadata={})

    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", execute)
    monkeypatch.setattr(_runtime_workspace_cli, "execute_with_runtime", execute)
    return calls


@pytest.mark.asyncio
async def test_the_execution_runtime_refuses_a_build_before_anything_starts(tmp_path):
    calls, fakes = _runtime_fakes()
    result = await execute_with_runtime(db=None, project_config={}, command="npm ci && npm test", cwd=tmp_path,
                                        workspace_root=tmp_path, timeout_sec=5, shell=True, **fakes)
    assert calls == [] and result.exit_code is None and result.stderr == SERVER_BUILD_MESSAGE
    assert result.metadata["refused"] == SERVER_BUILD_NOT_ALLOWED
    assert runtime_refusal(result, command="npm ci")["foreign_build_guard"]["program"] == "npm"
    ran = await execute_with_runtime(db=None, project_config={}, command=["git", "status"], cwd=tmp_path,
                                     workspace_root=tmp_path, timeout_sec=5, **fakes)
    assert calls == [["git", "status"]] and ran.exit_code == 0 and runtime_refusal(ran) is None


@pytest.mark.asyncio
async def test_only_a_fixed_platform_binary_opts_out_of_the_backstop(tmp_path):
    calls, fakes = _runtime_fakes()
    await execute_with_runtime(db=None, project_config={}, command=["/opt/kube/kubectl", "get", "pods"], cwd=tmp_path,
                               workspace_root=tmp_path, timeout_sec=5, guard_foreign_build=False, **fakes)
    assert calls == [["/opt/kube/kubectl", "get", "pods"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["mvn -q test", "./gradlew test", "npm ci", "pytest", "bash -c 'make'"])
async def test_the_bash_tool_refuses_a_build_and_no_approval_can_lift_it(monkeypatch, tmp_path, command):
    from app.tools.runtime_impl import _runtime_command_policy
    from app.tools.runtime_impl._runtime_bash_web import BashTool

    calls = _fake_runtime(monkeypatch)
    granted: list = []

    async def grant(*args, **kwargs):
        granted.append(args)
        return True

    monkeypatch.setattr(_runtime_command_policy, "_consume_approval_grant", grant)
    result = await BashTool().execute({"command": command}, _context(tmp_path))
    assert calls == [] and granted == [], result
    assert (result["error_code"], result["error"]) == (SERVER_BUILD_NOT_ALLOWED, SERVER_BUILD_MESSAGE)


@pytest.mark.asyncio
async def test_the_bash_tool_still_runs_a_read_only_command(monkeypatch, tmp_path):
    from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
    from app.services.security_analyzer import builtins
    from app.tools.runtime_impl._runtime_bash_web import BashTool

    async def exec_config(db, project_id=None):
        return DEFAULT_EXEC_POLICY_CONFIG

    monkeypatch.setattr(builtins, "get_effective_exec_policy_config", exec_config)
    calls = _fake_runtime(monkeypatch)
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s", capability_type="diagnosis",
                          project_config={}, workspace_root=str(tmp_path))
    result = await BashTool().execute({"command": "git status"}, context)
    assert calls == ["git status"] and "error" not in result, result


@pytest.mark.asyncio
async def test_the_bash_backstop_refuses_a_resolved_script(monkeypatch, tmp_path):
    from app.tools.runtime_impl import _runtime_bash_web

    async def allow(*args, **kwargs):
        return None

    async def config(db, project_config=None):
        from app.services.execution_runtime import ExecutionRuntimeConfig

        return ExecutionRuntimeConfig(provider="host")

    async def host(**kwargs):  # must never run
        raise AssertionError("the host ran a refused command")

    async def runtime(**kwargs):
        return await execute_with_runtime(**kwargs, resolve_config_fn=config, host_command_fn=host)

    monkeypatch.setattr(_runtime_bash_web, "_policy_block_result", allow)
    monkeypatch.setattr(_runtime_bash_web, "_maybe_resolve_script_command",
                        lambda command, **kwargs: ("./scripts/test.sh", None, kwargs["cwd"]))
    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", runtime)
    result = await _runtime_bash_web.BashTool().execute({"command": "run the tests"}, _context(tmp_path))
    assert result["error_code"] == SERVER_BUILD_NOT_ALLOWED
    assert result["foreign_build_guard"]["command_class"] == "repository_script"


@pytest.mark.asyncio
async def test_run_cli_command_and_start_runtime_process_refuse_a_build(monkeypatch, tmp_path):
    from app.tools.runtime_impl._runtime_workspace_cli import RunCLICommandTool
    from app.tools.runtime_impl._runtime_workspace_processes import StartRuntimeProcessTool

    calls = _fake_runtime(monkeypatch)
    cli = await RunCLICommandTool().execute({"command": "mvn -q test"}, _context(tmp_path))
    process = await StartRuntimeProcessTool().execute({"command": "npm run dev"},
                                                      _context(tmp_path, db=SimpleNamespace()))
    assert calls == []
    assert cli["error_code"] == process["error_code"] == SERVER_BUILD_NOT_ALLOWED


@pytest.mark.asyncio
async def test_run_validation_commands_refuses_the_whole_contract_before_the_first_command(monkeypatch, tmp_path):
    from app.tools.runtime_impl import _runtime_validation_commands as module

    ran: list = []

    async def contract(context):
        return ["git diff --stat", "mvn -q verify"]

    async def run(command, *, cwd):  # must never run
        ran.append(command)
        return {"command": command, "ok": True, "exit_code": 0}

    monkeypatch.setattr(module, "_contract_commands", contract)
    monkeypatch.setattr(module, "_run_command", run)
    result = await module.RunValidationCommandsTool().execute({}, _context(tmp_path))
    assert ran == [] and result["all_green"] is False and result["error_code"] == SERVER_BUILD_NOT_ALLOWED


@pytest.mark.asyncio
async def test_the_code_quality_runner_refuses_tests_and_builds_but_runs_ruff(monkeypatch, tmp_path):
    from app.services import code_quality_service

    calls: list = []

    async def execute(**kwargs):
        calls.append(kwargs["command"])
        return ExecutionRuntimeResult(exit_code=0, stdout="", stderr="", timed_out=False, metadata={})

    monkeypatch.setattr(code_quality_service, "execute_with_runtime", execute)
    for command in (["mvn", "-q", "test"], ["./gradlew", "test"], ["npm", "test", "--", "--runInBand"],
                    ["/usr/bin/python3", "-m", "pytest", ".", "-q"], ["eslint", "."]):
        refused = await code_quality_service._run_exec(command, cwd=tmp_path)
        assert refused["error_code"] == SERVER_BUILD_NOT_ALLOWED and refused["status"] == "refused", command
    assert calls == []
    assert (await code_quality_service._run_exec(["ruff", "check", "."], cwd=tmp_path))["exit_code"] == 0
    assert calls == [["ruff", "check", "."]]


@pytest.mark.asyncio
async def test_check_file_syntax_refuses_go_vet_and_still_parses_python(tmp_path):
    from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "ok.py").write_text("x = 1\n")
    go = await CheckFileSyntaxTool().execute({"path": "main.go"}, _context(tmp_path))
    assert go["error_code"] == SERVER_BUILD_NOT_ALLOWED and go["valid"] is None
    assert (await CheckFileSyntaxTool().execute({"path": "ok.py"}, _context(tmp_path)))["valid"] is True
