"""The device of the B device rehearsal: launcher hooks against the real gateway endpoints, and run helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from app.models import WorkflowRun
from app.services.mcp_parity_dispatch import run_parity_mcp_tool
from app.services.model_gateway.inbound.transcript_tools import upsert_gateway_tool_calls
from app.services.model_gateway.inbound.turn_delta import newest_turn
from app.services.workflow_runs.octryx.contract import run_contract
from tests.device_job_session_parity_support import GATEWAY, _gateway
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_run_runtime_evidence_support import DEVICE_SCOPES, PREFIX

CLIENT_DIR = Path(__file__).resolve().parents[2] / "clients" / "octryx-claude"
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from octryx_claude import run_contract as launcher_contract  # noqa: E402 - the launcher's own package
from octryx_claude import test_report as launcher_report  # noqa: E402
from octryx_claude.state import LocalState  # noqa: E402


def _clean_environment(working_copy: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST", "PYTHONPATH"))}
    return {**environment, "PATH": f"{working_copy / '.tools'}{os.pathsep}{environment.get('PATH', '')}"}


class Device:
    def __init__(self, client, db, headers: dict, root: Path, state_dir: Path, run_id: str) -> None:
        self.client, self.db, self.headers, self.root, self.run_id = client, db, headers, root, run_id
        self.key = headers["X-Octryx-Session"]
        self.state = LocalState(state_dir).ensure()
        self.gateway = None

    async def contract(self) -> dict:
        run = await self.db.get(WorkflowRun, self.run_id)
        await self.db.refresh(run)
        contract = await run_contract(self.db, run)
        launcher_contract.remember(self.state, self.key, {"workflow_run": contract})
        return contract

    def _hook(self, event: str, tool: str, tool_use_id: str, **tool_input) -> dict:
        return {"hook_event_name": event, "tool_name": tool, "tool_use_id": tool_use_id, "cwd": str(self.root),
                "tool_input": tool_input}

    async def pre(self, tool: str, tool_use_id: str = "", **tool_input) -> dict:
        hook = self._hook("PreToolUse", tool, tool_use_id or f"toolu_{uuid.uuid4().hex[:12]}", **tool_input)
        facts = launcher_contract.facts(await self.contract(), root=self.root, with_diff=False, hook_input=hook)
        answer = await self.client.post(f"{GATEWAY}/tool-check", headers=self.headers,
                                        json={**hook, launcher_contract.FACTS_KEY: facts})
        assert answer.status_code == 200, answer.text
        return answer.json()

    async def _executed(self, hook: dict, output: str, *, failed: bool) -> None:
        answer = await self.client.post(f"{GATEWAY}/tool-executed", headers=self.headers, json=hook)
        assert answer.status_code == 200, answer.text
        messages = [{"role": "user", "content": "go"},
                    {"role": "assistant", "content": [{"type": "tool_use", "id": hook["tool_use_id"],
                                                       "name": hook["tool_name"], "input": hook["tool_input"]}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": hook["tool_use_id"],
                                                  "content": output, "is_error": failed}]}]
        self.gateway = self.gateway or await _gateway(self.db, self.headers)
        await upsert_gateway_tool_calls(self.db, self.gateway.id, newest_turn(messages))
        await self.db.commit()

    async def read(self, relative: str) -> None:
        tool_use_id = f"toolu_{uuid.uuid4().hex[:12]}"
        await self._executed(self._hook("PostToolUse", "Read", tool_use_id, file_path=str(self.root / relative)),
                             (self.root / relative).read_text(), failed=False)

    async def write(self, relative: str, content: str, *, tool: str = "Write") -> dict:
        tool_use_id = f"toolu_{uuid.uuid4().hex[:12]}"
        decided = await self.pre(tool, tool_use_id, file_path=str(self.root / relative), content=content)
        if decided["decision"] == "allow":
            (self.root / relative).write_text(content)
            await self._executed(self._hook("PostToolUse", tool, tool_use_id, file_path=str(self.root / relative),
                                            content=content), "ok", failed=False)
        return decided

    async def bash(self, command: str) -> subprocess.CompletedProcess:
        tool_use_id = f"toolu_{uuid.uuid4().hex[:12]}"
        decided = await self.pre("Bash", tool_use_id, command=command)
        assert decided["decision"] == "allow", decided
        pre_hook = self._hook("PreToolUse", "Bash", tool_use_id, command=command)
        contract = launcher_contract.current(self.state, self.key)
        launcher_report.before(self.state, self.key, contract, pre_hook, self.root)
        done = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True, timeout=180,
                              env=_clean_environment(self.root))
        post = {**pre_hook, "hook_event_name": "PostToolUse" if done.returncode == 0 else "PostToolUseFailure"}
        report = launcher_report.attach(self.state, self.key, contract, post, self.root)
        body = {**post, launcher_contract.FACTS_KEY: {"test_report": report}} if report else post
        output = done.stdout + done.stderr
        await self._executed(body, output if done.returncode == 0 else f"Exit code {done.returncode}\n{output}",
                             failed=done.returncode != 0)
        return done

    async def mcp(self, tool: str, arguments: dict) -> dict:
        from app.services.mcp_governed_knowledge import McpCaller

        admin = await admin_user(self.db)
        caller = McpCaller(user_id=admin.id, grant_id="device-grant", scopes=DEVICE_SCOPES,
                           workspace_header=self.headers["X-Octryx-Workspace"], session_key=self.key)
        answer = await run_parity_mcp_tool(self.db, caller=caller, tool_name=tool, arguments=arguments)
        tool_use_id = f"toolu_{uuid.uuid4().hex[:12]}"
        await self._executed(self._hook("PostToolUse", PREFIX + tool, tool_use_id, **arguments), str(answer),
                             failed=answer.get("state") != "recorded")
        return answer

    async def stop(self) -> dict:
        facts = launcher_contract.facts(await self.contract(), root=self.root, with_diff=True)
        answer = await self.client.post(f"{GATEWAY}/verification", headers=self.headers,
                                        json={"hook_event_name": "Stop", launcher_contract.FACTS_KEY: facts})
        assert answer.status_code == 200, answer.text
        await self.db.commit()
        return answer.json()


async def _run(db, run_id: str) -> WorkflowRun:
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    return run


def _last_test_run(run: WorkflowRun) -> dict:
    return run.context["tests"]["runs"][-1]


def _outcomes(test_run: dict) -> dict[str, str]:
    return {test_id: value["outcome"] for test_id, value in test_run["results"].items()}


def _pipeline_junit(bare: Path, head: str, tmp: Path) -> str:
    checkout = tmp / "pipeline"
    subprocess.run(["git", "clone", "-q", str(bare), str(checkout)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-q", head], cwd=checkout, check=True, capture_output=True)
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST", "PYTHONPATH"))}
    done = subprocess.run([sys.executable, "-m", "pytest", "-v", "tests/", "--junitxml=test-reports/report.xml",
                           "-p", "no:cacheprovider"], cwd=checkout, capture_output=True, text=True, timeout=180,
                          env=environment)
    assert done.returncode == 0, done.stdout
    return (checkout / "test-reports" / "report.xml").read_text()
