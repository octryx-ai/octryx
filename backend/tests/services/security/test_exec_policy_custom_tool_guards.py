"""Custom tool guard rules and Kyverno-style conditions are normalized, invalid conditions are disabled, and project policies keep the global custom tool guard rules."""

from __future__ import annotations

import uuid

import pytest

from app.models import ExecPolicyConfig, Project
from app.services.exec_policy import (
    CUSTOM_TOOL_GUARD_RULES_KEY,
    get_effective_exec_policy_config,
    upsert_global_exec_policy_config,
)


@pytest.mark.asyncio
async def test_exec_policy_normalizes_custom_tool_guard_rules(db):
    updated = await upsert_global_exec_policy_config(
        db,
        {
            CUSTOM_TOOL_GUARD_RULES_KEY: [
                {
                    "id": "no-prod-write",
                    "label": "Block production file writes",
                    "description": "Production paths need a reviewed change path.",
                    "tool_names": ["write_workspace_file"],
                    "capability_types": ["change"],
                    "argument_key": "path",
                    "argument_contains": "production",
                    "action": "review",
                    "severity": "critical",
                },
                {
                    "id": "invalid-empty-matcher",
                    "label": "Invalid",
                },
                {
                    "id": "audit-read",
                    "label": "Audit read",
                    "tool_names": ["todo_read"],
                    "action": "audit",
                    "severity": "info",
                },
            ]
        },
    )
    await db.commit()

    stored = await db.get(ExecPolicyConfig, updated.id)
    assert stored is not None
    custom_rules = stored.config_json[CUSTOM_TOOL_GUARD_RULES_KEY]
    prod_rule = next(rule for rule in custom_rules if rule["id"] == "no-prod-write")
    invalid_rule = next(rule for rule in custom_rules if rule["id"] == "invalid-empty-matcher")
    audit_rule = next(rule for rule in custom_rules if rule["id"] == "audit-read")

    assert prod_rule["enabled"] is True
    assert prod_rule["action"] == "review"
    assert prod_rule["severity"] == "critical"
    assert prod_rule["tool_names"] == ["write_workspace_file"]
    assert prod_rule["capability_types"] == ["change"]
    assert prod_rule["conditions"] is None
    assert invalid_rule["enabled"] is False
    assert invalid_rule["validation_errors"] == ["At least one matcher is required."]
    assert audit_rule["enabled"] is True
    assert audit_rule["action"] == "audit"
    assert audit_rule["severity"] == "info"


@pytest.mark.asyncio
async def test_exec_policy_normalizes_kyverno_style_custom_tool_guard_conditions(db):
    updated = await upsert_global_exec_policy_config(
        db,
        {
            CUSTOM_TOOL_GUARD_RULES_KEY: [
                {
                    "id": "enterprise-write-policy",
                    "label": "Enterprise write policy",
                    "tool_names": ["write_workspace_file"],
                    "conditions": {
                        "all": [
                            {"field": "tool.capability_type", "operator": "equals", "value": "change"},
                            {
                                "any": [
                                    {"field": "args.path", "operator": "matches_pattern", "value": "*production*"},
                                    {"field": "args.metadata.environment", "operator": "in", "values": ["prod", "dr"]},
                                ]
                            },
                            {"not": {"field": "args.approved_change_id", "operator": "exists"}},
                        ]
                    },
                    "action": "review",
                    "severity": "critical",
                }
            ]
        },
    )
    await db.commit()

    stored = await db.get(ExecPolicyConfig, updated.id)
    assert stored is not None
    custom_rule = stored.config_json[CUSTOM_TOOL_GUARD_RULES_KEY][0]

    assert custom_rule["enabled"] is True
    assert custom_rule["conditions"] == {
        "all": [
            {
                "field": "tool.capability_type",
                "operator": "equals",
                "value": "change",
                "values": ["change"],
            },
            {
                "any": [
                    {
                        "field": "args.path",
                        "operator": "matches_pattern",
                        "value": "*production*",
                        "values": ["*production*"],
                    },
                    {
                        "field": "args.metadata.environment",
                        "operator": "in",
                        "value": "prod",
                        "values": ["prod", "dr"],
                    },
                ]
            },
            {
                "not": {
                    "field": "args.approved_change_id",
                    "operator": "exists",
                    "value": None,
                    "values": [],
                }
            },
        ]
    }


@pytest.mark.asyncio
async def test_exec_policy_disables_invalid_custom_tool_guard_conditions(db):
    updated = await upsert_global_exec_policy_config(
        db,
        {
            CUSTOM_TOOL_GUARD_RULES_KEY: [
                {
                    "id": "invalid-operator",
                    "conditions": {"field": "args.path", "operator": "regex", "value": "prod"},
                }
            ]
        },
    )
    await db.commit()

    stored = await db.get(ExecPolicyConfig, updated.id)
    assert stored is not None
    custom_rule = stored.config_json[CUSTOM_TOOL_GUARD_RULES_KEY][0]

    assert custom_rule["enabled"] is False
    assert "Unsupported condition operator 'regex'." in custom_rule["validation_errors"]


@pytest.mark.asyncio
async def test_project_exec_policy_preserves_global_custom_tool_guard_rules(db):
    project = Project(id=str(uuid.uuid4()), name="custom-guard-project", is_active=True)
    db.add(project)
    await upsert_global_exec_policy_config(
        db,
        {
            CUSTOM_TOOL_GUARD_RULES_KEY: [
                {
                    "id": "block-shell",
                    "label": "Block shell",
                    "tool_names": ["bash"],
                    "action": "block",
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
    custom_rule = next(rule for rule in effective[CUSTOM_TOOL_GUARD_RULES_KEY] if rule["id"] == "block-shell")

    # A list stored without its removals: the defaults it leaves out count as removed, as every writer stores them.
    assert effective["diagnosis_read_only_commands"] == ["python3"]
    assert custom_rule["enabled"] is True
