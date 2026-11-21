"""Ansible tools and playbook approvals and the execution runtime health adapters for Terraform and Ansible."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.models import (
    AnsibleJobRun,
    Session,
    User,
)
from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _write_fake_ansible_binaries(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    inventory_path = tmp_path / "hosts.ini"
    inventory_path.write_text("[web]\\nweb01\\n", encoding="utf-8")

    inventory_binary = tmp_path / "ansible-inventory"
    inventory_binary.write_text(
        """#!/usr/bin/env python3
import json
print(json.dumps({"web": {"hosts": ["web01"]}, "_meta": {"hostvars": {"web01": {"ansible_host": "10.0.0.1"}}}}))
""",
        encoding="utf-8",
    )
    inventory_binary.chmod(0o755)

    ansible_binary = tmp_path / "ansible"
    ansible_binary.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
tree_dir = pathlib.Path(args[args.index("--tree") + 1])
tree_dir.mkdir(parents=True, exist_ok=True)
(tree_dir / "web01").write_text(json.dumps({"ansible_facts": {"ansible_hostname": "web01", "ansible_os_family": "Debian"}}))
print("web01 | SUCCESS => gathered")
""",
        encoding="utf-8",
    )
    ansible_binary.chmod(0o755)

    playbook_binary = tmp_path / "ansible-playbook"
    playbook_binary.write_text(
        """#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if "--check" in args:
    print("PLAY RECAP: web01 changed=0 unreachable=0 failed=0")
else:
    print("PLAY RECAP: web01 changed=2 unreachable=0 failed=0")
""",
        encoding="utf-8",
    )
    playbook_binary.chmod(0o755)

    playbook_root = tmp_path / "playbooks"
    playbook_root.mkdir()
    (playbook_root / "deploy.yml").write_text("- hosts: all\\n  tasks: []\\n", encoding="utf-8")
    return inventory_path, inventory_binary, ansible_binary, playbook_binary


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ansible_tools_cover_inventory_facts_run_check_and_job_output(tmp_path: Path, db):
    inventory_path, inventory_binary, ansible_binary, playbook_binary = _write_fake_ansible_binaries(tmp_path)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.commit()

    async def allow_grant(*args, **kwargs):
        return True

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.tools.connectors.ansible_runtime.consume_change_preview_grant", allow_grant)

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["viewer"],
        session_id=session.id,
        db=db,
        workspace_root=str(tmp_path),
        project_config={
            "tool_policy": {"high_risk_grants": ["run_playbook"]},
            "ansible_inventory_path": str(inventory_path.relative_to(tmp_path)),
            "ansible_inventory_binary": str(inventory_binary),
            "ansible_binary": str(ansible_binary),
            "ansible_playbook_binary": str(playbook_binary),
            "ansible_playbook_root": "playbooks",
            "ansible_allowed_playbooks": ["deploy.yml"],
            "ansible_allowed_hosts": ["web01"],
        },
    )

    inventory = await execute_tool("list_inventory", {}, context)
    assert inventory["host_count"] == 1
    assert "web01" in inventory["hosts"]

    facts = await execute_tool("get_facts", {"host_pattern": "web01"}, context)
    assert facts["count"] == 1
    assert facts["facts"]["web01"]["ansible_facts"]["ansible_hostname"] == "web01"

    check_mode = await execute_tool("check_mode", {"playbook": "deploy.yml", "host_pattern": "web01"}, context)
    assert check_mode["status"] == "completed"
    assert "changed=0" in check_mode["stdout"]

    run = await execute_tool("run_playbook", {"playbook": "deploy.yml", "host_pattern": "web01"}, context)
    assert run["status"] == "completed"
    assert "changed=2" in run["stdout"]

    output = await execute_tool("get_job_output", {"job_id": run["job_id"]}, context)
    assert output["command_type"] == "run_playbook"
    assert "changed=2" in output["stdout"]

    job = await db.get(AnsibleJobRun, run["job_id"])
    assert job is not None
    assert job.status == "completed"
    monkeypatch.undo()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ansible_run_playbook_blocks_with_approval_and_connector_health_supports_native_test(
    tmp_path: Path, db, monkeypatch
):
    inventory_path, inventory_binary, ansible_binary, playbook_binary = _write_fake_ansible_binaries(tmp_path)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.commit()

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["viewer"],
        session_id=session.id,
        db=db,
        workspace_root=str(tmp_path),
        project_config={
            "tool_policy": {"high_risk_grants": ["run_playbook"]},
            "ansible_inventory_path": str(inventory_path.relative_to(tmp_path)),
            "ansible_inventory_binary": str(inventory_binary),
            "ansible_binary": str(ansible_binary),
            "ansible_playbook_binary": str(playbook_binary),
            "ansible_playbook_root": "playbooks",
            "ansible_allowed_playbooks": ["deploy.yml"],
            "ansible_allowed_hosts": ["web01"],
        },
    )

    blocked = await execute_tool("run_playbook", {"playbook": "deploy.yml", "host_pattern": "web01"}, context)
    assert blocked["approval_required"] is True
    assert blocked["change_preview"]["kind"] == "ansible"

    monkeypatch.setattr(connector_test_service_module.Path, "cwd", staticmethod(lambda: tmp_path))
    health = await run_connector_connection_test(
        "ansible",
        {
            "ansible_inventory_path": str(inventory_path.relative_to(tmp_path)),
            "ansible_inventory_binary": str(inventory_binary),
        },
    )
    assert health["ok"] is True
    assert health["summary"] == "Connected to Ansible inventory."
    assert health["execution_runtime"]["provider"] == "host"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_connector_health_terraform_uses_execution_runtime_adapter(monkeypatch, tmp_path: Path):
    observed: dict[str, Any] = {}

    async def fake_execute_with_runtime(**kwargs):
        observed["command"] = kwargs["command"]
        observed["cwd"] = kwargs["cwd"]
        return type(
            "FakeRuntimeResult",
            (),
            {
                "exit_code": 0,
                "stdout": json.dumps({"terraform_version": "1.9.9"}),
                "stderr": "",
                "timed_out": False,
                "metadata": {"provider": "docker", "containerized": True},
            },
        )()

    async def fake_resolve_execution_runtime_config(db, *, project_config=None):
        return type(
            "FakeRuntimeConfig",
            (),
            {
                "provider": "docker",
                "docker_image": "ghcr.io/example/runtime:1",
                "docker_network_mode": "none",
                "allow_host_fallback": False,
            },
        )()

    root = tmp_path / "terraform"
    root.mkdir()
    monkeypatch.setattr(connector_test_service_module, "execute_with_runtime", fake_execute_with_runtime)
    monkeypatch.setattr(
        connector_test_service_module, "resolve_execution_runtime_config", fake_resolve_execution_runtime_config
    )
    monkeypatch.setattr(connector_test_service_module.shutil, "which", lambda command: None)
    monkeypatch.setattr(connector_test_service_module.Path, "cwd", staticmethod(lambda: tmp_path))

    health = await run_connector_connection_test(
        "terraform",
        {
            "execution_runtime_provider": "docker",
            "execution_runtime_allow_host_fallback": False,
            "terraform_binary": "terraform",
            "terraform_root": "terraform",
        },
    )

    assert health["ok"] is True
    assert health["execution_runtime"]["provider"] == "docker"
    assert observed["command"] == ["terraform", "version", "-json"]
    assert observed["cwd"] == root.resolve()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_connector_health_ansible_uses_execution_runtime_adapter(monkeypatch, tmp_path: Path):
    inventory = tmp_path / "inventory.ini"
    inventory.write_text("[all]\nweb01\n", encoding="utf-8")
    observed: dict[str, Any] = {}

    async def fake_execute_with_runtime(**kwargs):
        observed["command"] = kwargs["command"]
        return type(
            "FakeRuntimeResult",
            (),
            {
                "exit_code": 0,
                "stdout": json.dumps({"all": {"hosts": ["web01"]}, "_meta": {}}),
                "stderr": "",
                "timed_out": False,
                "metadata": {"provider": "docker", "containerized": True},
            },
        )()

    async def fake_resolve_execution_runtime_config(db, *, project_config=None):
        return type(
            "FakeRuntimeConfig",
            (),
            {
                "provider": "docker",
                "docker_image": "ghcr.io/example/runtime:1",
                "docker_network_mode": "none",
                "allow_host_fallback": False,
            },
        )()

    monkeypatch.setattr(connector_test_service_module, "execute_with_runtime", fake_execute_with_runtime)
    monkeypatch.setattr(
        connector_test_service_module, "resolve_execution_runtime_config", fake_resolve_execution_runtime_config
    )
    monkeypatch.setattr(connector_test_service_module.shutil, "which", lambda command: None)
    monkeypatch.setattr(connector_test_service_module.Path, "cwd", staticmethod(lambda: tmp_path))

    health = await run_connector_connection_test(
        "ansible",
        {
            "execution_runtime_provider": "docker",
            "execution_runtime_allow_host_fallback": False,
            "ansible_inventory_binary": "ansible-inventory",
            "ansible_inventory_path": "inventory.ini",
        },
    )

    assert health["ok"] is True
    assert health["execution_runtime"]["provider"] == "docker"
    assert observed["command"] == ["ansible-inventory", "-i", str(inventory.resolve()), "--list", "--json"]
