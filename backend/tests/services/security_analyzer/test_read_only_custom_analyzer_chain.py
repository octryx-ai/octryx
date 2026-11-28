"""The read-only capability does not weaken with a custom analyzer chain."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services.exec_policy import DEFAULT_EXEC_POLICY_CONFIG
from app.services.run_capability.escalation import CAPABILITY_REFUSAL_KEY
from app.services.security_analyzer.service import analyze_security_risk
from app.tools.context import ToolContext
from tests.shell_expansion_support import _granted_session, _runtime, exec_config  # noqa: F401

CUSTOM_CHAIN = ["secret_access"]


async def _context(db, monkeypatch, tmp_path, *, key: str, command: str, approved: bool, source: str):
    user_id = await _granted_session(db, key, command)
    if not approved:
        from app.models import Session

        session = (await db.execute(select(Session).where(Session.id == f"r7-{key}"))).scalar_one()
        session.metadata_ = {}
        await db.flush()

    async def runtime_settings(db):
        return {"security_analyzer_chain": CUSTOM_CHAIN}

    if source == "system":
        monkeypatch.setattr("app.services.system_config.get_agent_runtime_settings", runtime_settings)
    return ToolContext(
        user_id=user_id, project_ids=[], roles=["viewer"], session_id=f"r7-{key}", db=db,
        capability_type="diagnosis", workspace_root=str(tmp_path),
        project_config={"security_analyzer_chain": CUSTOM_CHAIN} if source == "workspace" else {},
        run_capability={"enforced": True, "class": "read_only"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["uniq glob-*", "cat <(printf canary)"])
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("source", ["workspace", "system"])
async def test_optional_analyzer_chain_cannot_disable_enforced_expansion_refusal(
    db, monkeypatch, tmp_path, exec_config, command, approved, source  # noqa: F811
):
    module, calls = _runtime(monkeypatch)
    key = f"chain-{source}-{approved}-{command.startswith('uniq')}"
    context = await _context(db, monkeypatch, tmp_path, key=key, command=command, approved=approved, source=source)

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], (calls, result)
    assert CAPABILITY_REFUSAL_KEY in result, result
    assert "approval_id" not in result


@pytest.mark.asyncio
async def test_an_earlier_exec_policy_finding_cannot_hide_the_expansion(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    module, calls = _runtime(monkeypatch)
    command = "uniq glob-* # shutdown"
    user_id = await _granted_session(db, "earlier-finding", command)
    context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"], session_id="r7-earlier-finding", db=db,
                          capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability={"enforced": True, "class": "read_only"})

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], (calls, result)
    assert CAPABILITY_REFUSAL_KEY in result


@pytest.mark.asyncio
async def test_default_chain_keeps_the_hard_boundary(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    module, calls = _runtime(monkeypatch)
    user_id = await _granted_session(db, "default-chain", "uniq glob-*")
    context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"], session_id="r7-default-chain", db=db,
                          capability_type="diagnosis", workspace_root=str(tmp_path), project_config={},
                          run_capability={"enforced": True, "class": "read_only"})

    result = await module.BashTool().execute({"command": "uniq glob-*"}, context)

    assert calls == [] and CAPABILITY_REFUSAL_KEY in result


OTHER_READ_ONLY_REFUSALS = [
    "sort -o out input",
    "uniq in out",
    "find . -delete",
    "HOME=/tmp/x cat a",
    "env PATH=/tmp/x cat a",
    "/tmp/x/cat a",
    "cat a > /tmp/x",
    "cat a; touch /tmp/x",
    "kubectl get pods -o go-template-file=/tmp/canary",
    "python3 -c 'open(\"x\",\"w\")'",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["workspace", "system"])
@pytest.mark.parametrize("command", OTHER_READ_ONLY_REFUSALS)
async def test_a_custom_chain_keeps_every_read_only_rule_without_a_grant(
    db, monkeypatch, tmp_path, exec_config, command, source  # noqa: F811
):
    module, calls = _runtime(monkeypatch)
    key = f"other-{source}-{OTHER_READ_ONLY_REFUSALS.index(command)}"
    context = await _context(db, monkeypatch, tmp_path, key=key, command=command, approved=False, source=source)

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [], (command, result)
    # The same outcome as under the default chain: a capability refusal, or, where another analyzer objects
    # as well (``env`` is also a secret-access finding), the existing approval request; never an execution.
    default_module, default_calls = _runtime(monkeypatch)
    default_context = ToolContext(user_id=context.user_id, project_ids=[], roles=["viewer"],
                                  session_id=context.session_id, db=db, capability_type="diagnosis",
                                  workspace_root=str(tmp_path), project_config={},
                                  run_capability={"enforced": True, "class": "read_only"})
    if source == "system":
        monkeypatch.undo()
        default_module, default_calls = _runtime(monkeypatch)
        from app.services.security_analyzer import builtins

        async def config(db, project_id=None):
            return DEFAULT_EXEC_POLICY_CONFIG

        monkeypatch.setattr(builtins, "get_effective_exec_policy_config", config)
    default = await default_module.BashTool().execute({"command": command}, default_context)
    assert default_calls == []
    assert (CAPABILITY_REFUSAL_KEY in result) == (CAPABILITY_REFUSAL_KEY in default), (result, default)
    assert CAPABILITY_REFUSAL_KEY in result or result.get("approval_required") or result.get("approval_id"), result


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["default", "workspace"])
async def test_a_verbatim_grant_is_refused_the_same_under_any_chain(
    db, monkeypatch, tmp_path, exec_config, source  # noqa: F811
):
    module, calls = _runtime(monkeypatch)
    command = "sort -o out input"
    user_id = await _granted_session(db, f"verbatim-{source}", command)
    context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"], session_id=f"r7-verbatim-{source}",
                          db=db, capability_type="diagnosis", workspace_root=str(tmp_path),
                          project_config={"security_analyzer_chain": CUSTOM_CHAIN} if source == "workspace" else {},
                          run_capability={"enforced": True, "class": "read_only"})

    result = await module.BashTool().execute({"command": command}, context)

    assert calls == [] and result["capability_refusal"]["run_capability"] == "read_only"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["default", "workspace", "system"])
@pytest.mark.parametrize("command", ["find . -name '*.py'", "cat '<(x)'", "sort -u input", "rg --glob '*.py' pattern src"])
async def test_quoted_literals_and_plain_reads_run_under_any_chain(
    db, monkeypatch, tmp_path, exec_config, command, source  # noqa: F811
):
    module, calls = _runtime(monkeypatch)
    if source == "default":
        user_id = await _granted_session(db, f"pos-default-{hash(command) % 1000}", "unrelated")
        context = ToolContext(user_id=user_id, project_ids=[], roles=["viewer"],
                              session_id=f"r7-pos-default-{hash(command) % 1000}", db=db, capability_type="diagnosis",
                              workspace_root=str(tmp_path), project_config={},
                              run_capability={"enforced": True, "class": "read_only"})
    else:
        context = await _context(db, monkeypatch, tmp_path, key=f"pos-{source}-{hash(command) % 1000}",
                                 command="unrelated", approved=False, source=source)

    await module.BashTool().execute({"command": command}, context)

    assert calls == [(command, True)], command


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [["cat", "glob-*"], ["cat", "<(printf canary)"], ["sort", "-u", "$x"]], ids=" ".join)
async def test_literal_argv_stays_literal_under_a_custom_chain(exec_config, argv):  # noqa: F811
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s",
                          project_config={"security_analyzer_chain": CUSTOM_CHAIN},
                          run_capability={"enforced": True, "class": "read_only"})

    report = await analyze_security_risk("run_cli_command", list(argv), context)

    assert report.action == "allow", (argv, report.reason)


def test_the_default_exec_config_is_used_in_these_tests():
    assert "uniq" in DEFAULT_EXEC_POLICY_CONFIG["diagnosis_read_only_commands"]
