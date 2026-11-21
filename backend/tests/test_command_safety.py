"""Command safety — one contract for the command risk gate, Workspace Inherit/Override, a
threshold of 0 honoured, dead exec-policy fields cut, an e-mail address in a command is not sent to review."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ExecPolicyConfig, Project
from app.services.exec_policy.policy_config import DEFAULT_EXEC_POLICY_CONFIG
from app.services.exec_policy.service import get_effective_exec_policy_config
from app.services.security_analyzer.content_command import content_command_analyzer
from app.services.security_analyzer.llm_risk import _first_set
from app.tools.context import ToolContext
from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/command-safety"


def _body(view: dict, **changes) -> dict:
    body = {
        "checks": {item["key"]: item["enabled"] for item in view["checks"]},
        "llm_risk": {key: view["llm_risk"][key] for key in ("timeout_seconds", "review_threshold", "deny_threshold")},
        "lists": dict(view["lists"]),
    }
    for key, value in changes.items():
        body[key] = {**body[key], **value} if isinstance(value, dict) else value
    return body


@pytest.mark.asyncio
async def test_one_payload_writes_the_checks_thresholds_and_command_lists(client, db):
    admin = await make_user(db, admin=True)
    view = (await client.get(ROUTE, headers=bearer(admin))).json()
    assert [item["key"] for item in view["checks"] if item["enabled"]] == ["exec_policy", "secret_access",
                                                                          "command_guardrail"]
    assert view["llm_risk"]["review_threshold"] == 40 and view["llm_risk"]["deny_threshold"] == 80
    assert "rm" in " ".join(view["lists"]["always_deny_patterns"]) and "ls" in view["lists"]["commands"]

    body = _body(view, checks={"llm_risk": True}, llm_risk={"review_threshold": 0, "deny_threshold": 0},
                 lists={"always_deny_patterns": [*view["lists"]["always_deny_patterns"], "terraform destroy"]})
    body["guard_rules"] = {view["guard_rules"][0]["id"]: False}
    saved = await client.put(ROUTE, json=body, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert after["llm_risk"]["review_threshold"] == 0 and after["llm_risk"]["deny_threshold"] == 0
    assert next(item for item in after["checks"] if item["key"] == "llm_risk")["enabled"] is True
    assert "terraform destroy" in after["lists"]["always_deny_patterns"]
    assert after["guard_rules"][0]["enabled"] is False
    effective = await get_effective_exec_policy_config(db)
    assert "terraform destroy" in effective["always_deny_patterns"]


@pytest.mark.asyncio
async def test_invalid_payloads_are_refused_with_a_code(client, db):
    admin = await make_user(db, admin=True)
    view = (await client.get(ROUTE, headers=bearer(admin))).json()
    none = _body(view, checks={key: False for key in ("exec_policy", "secret_access", "command_guardrail", "llm_risk")})
    inverted = _body(view, llm_risk={"review_threshold": 70, "deny_threshold": 60})
    out_of_range = _body(view, llm_risk={"timeout_seconds": 0})
    for body, code in [(none, "command_safety_no_check"), (inverted, "command_safety_deny_below_review"),
                       (out_of_range, "command_safety_invalid")]:
        refused = await client.put(ROUTE, json=body, headers=bearer(admin))
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == code
    member = await make_user(db, admin=False)
    assert (await client.get(ROUTE, headers=bearer(member))).status_code == 403


def test_a_threshold_of_zero_is_a_value_not_a_fallback():
    assert _first_set({"k": 0}, {"k": 40}, "k", 80) == 0
    assert _first_set({}, {"k": 0}, "k", 80) == 0
    assert _first_set({"k": None}, {"k": ""}, "k", 80) == 80


@pytest.mark.asyncio
async def test_a_workspace_override_stores_only_what_differs_and_inherit_clears_it(client, db):
    admin = await make_user(db, admin=True)
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, config={})
    db.add(project)
    await db.commit()
    platform = (await client.get(ROUTE, headers=bearer(admin))).json()
    settings = _body(platform, llm_risk={"deny_threshold": 60},
                     lists={"commands": [*platform["lists"]["commands"], "kubectl-neat"]})
    saved = await client.put(f"{ROUTE}/workspaces/{project.id}", json={"mode": "override", "settings": settings},
                             headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    assert saved.json()["mode"] == "override"
    assert saved.json()["differences"] == ["Block from score 60", "Commands list differs"]
    await db.refresh(project)
    assert project.config["runtime_policy"]["default_bundle"] == {"llm_security_analyzer_deny_threshold": 60}
    row = (await db.execute(select(ExecPolicyConfig).where(ExecPolicyConfig.project_id == project.id))).scalar_one()
    assert set(row.config_json) == {"diagnosis_read_only_commands", "diagnosis_read_only_commands_removed_defaults"}, \
        "only the overriding key (and the defaults it removes), no full copy"

    # A later platform edit still reaches the Workspace's other keys.
    body = _body(platform, lists={"always_deny_patterns": [*platform["lists"]["always_deny_patterns"], "halt"]})
    assert (await client.put(ROUTE, json=body, headers=bearer(admin))).status_code == 200
    effective = await get_effective_exec_policy_config(db, project_id=project.id)
    assert "halt" in effective["always_deny_patterns"] and "kubectl-neat" in effective["diagnosis_read_only_commands"]
    overview = (await client.get(ROUTE, headers=bearer(admin))).json()["workspaces"]
    assert next(item for item in overview if item["id"] == project.id)["mode"] == "override"

    inherited = await client.put(f"{ROUTE}/workspaces/{project.id}", json={"mode": "inherit"}, headers=bearer(admin))
    assert inherited.status_code == 200 and inherited.json()["mode"] == "inherit"
    assert (await db.execute(select(ExecPolicyConfig).where(ExecPolicyConfig.project_id == project.id))).first() is None


def test_the_fields_nothing_enforced_are_cut():
    for key in ("allowed_models", "blocked_models", "max_output_tokens_per_turn", "audit_level",
                "allowed_external_domains", "blocked_external_domains", "applies_to_agent_types",
                "blocked_output_patterns", "active_schedule", "allowed_tools", "blocked_tools",
                "audit_required_actions", "max_tool_calls_per_session", "max_session_duration_seconds"):
        assert key not in DEFAULT_EXEC_POLICY_CONFIG


@pytest.mark.asyncio
async def test_an_address_in_a_command_is_no_longer_sent_to_review(db):
    context = ToolContext(user_id="u", project_ids=[], roles=[], session_id="s", project_config={}, db=db)
    finding = await content_command_analyzer("run_cli_command", "git config user.email dev@example.com", context)
    assert finding.action == "allow", finding.reason
    key = await content_command_analyzer("run_cli_command", ("echo AKIAAB" + "CDEFGHIJKLMNOP"), context)
    assert key.action == "review", "credentials still reach commands"
    assert key.details["policies"] == ["platform:credentials-masked"]
