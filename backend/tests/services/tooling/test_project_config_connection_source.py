"""``Project.config`` is never a connection source."""

from __future__ import annotations

import uuid

import pytest

from app.models import BuiltInToolConfig
from app.services.project.service import get_project_config
from app.services.secret import set_secret_value
from app.services.tool_config.connection_fields import without_connection_identity
from tests.factories import make_project

EVIL = "http://evil.invalid"


async def _project(db, config: dict) -> str:
    return (await make_project(db, name=f"m1-{uuid.uuid4().hex[:8]}", config=config, commit=True)).id


async def _entry(db, tool: str, project_id: str | None, config: dict, **secrets: str) -> None:
    for field, value in secrets.items():
        secret = await set_secret_value(db, tool_name=tool, field_name=field, project_id=project_id, value=value)
        config = {**config, f"{field}_secret_ref": secret.id}
    db.add(BuiltInToolConfig(tool_name=tool, project_id=project_id, is_active=True, config=config))
    await db.commit()


@pytest.mark.asyncio
async def test_a_project_config_url_never_fills_a_workspace_entry_without_its_own_target(db):
    project_id = await _project(db, {"jira_url": EVIL})
    await _entry(db, "jira", project_id, {"jira_auth_mode": "bearer_pat"}, jira_token="ws-token")
    await _entry(db, "jira", None, {"jira_url": "http://global.invalid", "jira_auth_mode": "bearer_pat"},
                 jira_token="global-token")

    config = await get_project_config(project_id, db)

    assert config.get("jira_url") is None, "own secret, no own target: fail closed"
    assert config.get("jira_token") == "ws-token"


@pytest.mark.asyncio
async def test_a_project_config_url_never_redirects_a_global_secret(db):
    project_id = await _project(db, {"confluence_url": EVIL})
    await _entry(db, "confluence", None, {"confluence_auth_mode": "basic", "confluence_username": "svc"},
                 confluence_password="global-pw")
    await _entry(db, "confluence", project_id, {"confluence_allowed_spaces": ["ENG"]})

    config = await get_project_config(project_id, db)

    assert config.get("confluence_url") is None and config.get("confluence_password") == "global-pw"
    assert config.get("confluence_allowed_spaces") == ["ENG"]


@pytest.mark.asyncio
async def test_project_config_keeps_its_other_keys_and_tool_entries_still_connect(db):
    project_id = await _project(db, {
        "jira_url": EVIL, "jira_token": "plain-in-config", "jira_auth_mode": "basic", "k8s_context": "demo",
    })
    await _entry(db, "jira", project_id, {"jira_url": "https://jira.example.test", "jira_auth_mode": "bearer_pat"},
                 jira_token="ws-token")

    config = await get_project_config(project_id, db)

    assert (config["jira_url"], config["jira_token"], config["jira_auth_mode"]) == (
        "https://jira.example.test", "ws-token", "bearer_pat"
    )
    assert config["k8s_context"] == "demo"


@pytest.mark.asyncio
async def test_without_any_tool_entry_project_config_yields_no_connection(db):
    project_id = await _project(db, {"bitbucket_url": EVIL, "bitbucket_token": "t", "github_token": "g"})

    config = await get_project_config(project_id, db)

    assert not {"bitbucket_url", "bitbucket_token", "github_token"} & set(config)


def test_the_strip_removes_targets_secrets_refs_principals_and_auth_modes_only():
    stripped = without_connection_identity({
        "confluence_url": EVIL, "confluence_password": "p", "confluence_password_secret_ref": "ref",
        "confluence_username": "u", "confluence_auth_mode": "basic", "confluence_allowed_spaces": ["ENG"],
        "data_policy": {"classification": "internal"},
    })

    assert stripped == {"confluence_allowed_spaces": ["ENG"], "data_policy": {"classification": "internal"}}


@pytest.mark.asyncio
async def test_credential_selectors_never_come_from_project_config_but_scope_selectors_stay(db):
    project_id = await _project(db, {
        "kubeconfig_path": "/tmp/attacker-kubeconfig", "kubectl_path": "/tmp/evil-kubectl", "aws_profile": "admin",
        "helm_kubeconfig": "/tmp/other", "ansible_binary": "/tmp/evil", "terraform_var_file": "/tmp/creds.tfvars",
        "k8s_context": "staging", "aws_region": "eu-central-1",
    })

    config = await get_project_config(project_id, db)

    assert not {"kubeconfig_path", "kubectl_path", "aws_profile", "helm_kubeconfig", "ansible_binary",
                "terraform_var_file"} & set(config)
    assert (config["k8s_context"], config["aws_region"]) == ("staging", "eu-central-1")


@pytest.mark.asyncio
async def test_worker_readiness_tests_only_active_tool_entries_with_the_governed_config(db):
    from types import SimpleNamespace

    from app.services.tool_config.presets import TOOL_CONFIG_PRESETS
    from app.services.worker.readiness import project_connector_checks

    # ``confluence_allowed_spaces`` is no connection key, so it survives the strip: without an active
    # Confluence entry it still never makes Confluence a tested connector.
    project_id = await _project(db, {"jira_url": EVIL, "jira_token": "plain-in-config", "grafana_url": EVIL,
                                     "confluence_allowed_spaces": [{"space_key": "ENG"}]})
    await _entry(db, "jira", project_id, {"jira_url": "https://jira.example.test", "jira_auth_mode": "bearer_pat"},
                 jira_token="ws-token")
    db.add(BuiltInToolConfig(tool_name="grafana", project_id=project_id, is_active=False,
                             config={"grafana_url": "https://grafana.example.test"}))
    await db.commit()
    sent: list[tuple[str, dict]] = []

    async def fake_test(name, config):
        sent.append((name, dict(config)))
        return {"ok": True}

    checks = await project_connector_checks(
        SimpleNamespace(id=project_id, config={"jira_url": EVIL}), tool_config_presets=TOOL_CONFIG_PRESETS,
        connector_test_func=fake_test, db=db,
    )

    assert [name for name, _ in sent] == ["jira"], "neither the inactive grafana entry nor Confluence is tested"
    assert (sent[0][1]["jira_url"], sent[0][1]["jira_token"]) == ("https://jira.example.test", "ws-token")
    assert [check["connector"] for check in checks] == ["jira"]
    assert await project_connector_checks(
        SimpleNamespace(id=project_id, config={"jira_url": EVIL}), tool_config_presets=TOOL_CONFIG_PRESETS,
        connector_test_func=fake_test,
    ) == [], "without a session there is no governed source"
