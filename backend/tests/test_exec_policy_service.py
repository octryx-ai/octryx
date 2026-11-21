"""Exec policy configuration is seeded, layered under scoped overrides, persisted and used by its consumer, and human-readable agent guard rules are normalized and kept across project overrides."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ExecPolicyConfig, Project, User
from app.services.exec_policy import (
    AGENT_GUARD_RULES_KEY,
    get_effective_exec_policy_config,
    upsert_global_exec_policy_config,
)
from app.services.security_analyzer import analyze_security_risk
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_seeded_global_exec_policy_config_is_persisted(db):
    row = (
        await db.execute(
            select(ExecPolicyConfig).where(
                ExecPolicyConfig.project_id.is_(None),
                ExecPolicyConfig.is_active,
            )
        )
    ).scalar_one_or_none()

    assert row is not None
    assert row.name == "Global Exec Policy"
    assert row.config_json["diagnosis_read_only_commands"] == [
        "cat",
        "cd",
        "date",
        "echo",
        "env",
        "find",
        "grep",
        "head",
        "id",
        "ls",
        "pwd",
        "printenv",
        "rg",
        "sed",
        "sort",
        "tail",
        "uniq",
        "wc",
        "whoami",
    ]


@pytest.mark.asyncio
async def test_exec_policy_resolution_layers_scoped_overrides_on_top_of_global_defaults(db):
    project = Project(id=str(uuid.uuid4()), name="exec-policy-project", is_active=True)
    db.add(project)
    db.add(
        ExecPolicyConfig(
            id=str(uuid.uuid4()),
            name="Scoped Exec Policy",
            project_id=project.id,
            priority=50,
            is_active=True,
            config_json={
                "diagnosis_read_only_commands": ["python3"],
            },
        )
    )
    await db.commit()

    effective = await get_effective_exec_policy_config(db, project_id=project.id)

    # A list stored without its removals: the defaults it leaves out count as removed, as every writer stores them.
    assert effective["diagnosis_read_only_commands"] == ["python3"]
    assert effective["diagnosis_git_subcommands"] == [
        "branch",
        "diff",
        "log",
        "remote",
        "rev-parse",
        "show",
        "status",
    ]
    assert effective["always_deny_patterns"][0] == r"\brm\s+-rf\s+/(?:\s|$)"


@pytest.mark.asyncio
async def test_global_exec_policy_updates_persist_and_are_used_by_the_consumer(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    updated = await upsert_global_exec_policy_config(
        db,
        {
            "diagnosis_read_only_commands": ["python3", "cat"],
        },
    )
    await db.commit()

    stored = await db.get(ExecPolicyConfig, updated.id)
    assert stored is not None
    assert stored.config_json["diagnosis_read_only_commands"] == ["python3", "cat"]
    assert stored.config_json["diagnosis_git_subcommands"] == [
        "branch",
        "diff",
        "log",
        "remote",
        "rev-parse",
        "show",
        "status",
    ]

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id="exec-policy-test",
        project_config={},
        run_capability={"enforced": True, "class": "read_only"},
        workspace_root="/tmp",
        db=db,
    )

    # The consumer uses the stored list: ``cat`` (configured, with a closed option binding) is a read,
    # ``ls`` (not configured) is not.
    assert (await analyze_security_risk("bash", "cat README.md", context)).action == "allow"
    assert (await analyze_security_risk("bash", "ls -la", context)).action == "review"
    # A configured command WITHOUT a closed option binding fails closed on read-only paths
    # (``python3 -c ...`` can write or run anything), even though the admin listed it.
    decision = await analyze_security_risk("bash", "python3 --version", context)
    assert decision.action == "review"


@pytest.mark.asyncio
async def test_exec_policy_normalizes_human_readable_agent_guard_rules(db):
    updated = await upsert_global_exec_policy_config(
        db,
        {
            AGENT_GUARD_RULES_KEY: [
                {
                    "id": "coding_prewrite_intelligence_required",
                    "enabled": False,
                    "action": "review",
                    "severity": "low",
                }
            ]
        },
    )
    await db.commit()

    stored = await db.get(ExecPolicyConfig, updated.id)
    assert stored is not None
    guard_rules = stored.config_json[AGENT_GUARD_RULES_KEY]
    repo_guard = next(rule for rule in guard_rules if rule["id"] == "coding_prewrite_intelligence_required")
    source_guard = next(rule for rule in guard_rules if rule["id"] == "technical_source_credibility_required")

    assert repo_guard["label"] == "Require repository intelligence before code writes"
    assert repo_guard["enabled"] is False
    assert repo_guard["action"] == "review"
    assert repo_guard["severity"] == "low"
    assert source_guard["enabled"] is True


@pytest.mark.asyncio
async def test_project_exec_policy_preserves_global_agent_guard_rules(db):
    project = Project(id=str(uuid.uuid4()), name="guard-policy-project", is_active=True)
    db.add(project)
    await upsert_global_exec_policy_config(
        db,
        {
            AGENT_GUARD_RULES_KEY: [
                {
                    "id": "coding_prewrite_intelligence_required",
                    "enabled": False,
                }
            ]
        },
    )
    db.add(
        ExecPolicyConfig(
            id=str(uuid.uuid4()),
            name="Project Read Commands",
            project_id=project.id,
            priority=50,
            is_active=True,
            config_json={"diagnosis_read_only_commands": ["python3"]},
        )
    )
    await db.commit()

    effective = await get_effective_exec_policy_config(db, project_id=project.id)
    repo_guard = next(
        rule for rule in effective[AGENT_GUARD_RULES_KEY] if rule["id"] == "coding_prewrite_intelligence_required"
    )

    # A list stored without its removals: the defaults it leaves out count as removed, as every writer stores them.
    assert effective["diagnosis_read_only_commands"] == ["python3"]
    assert repo_guard["enabled"] is False
