"""The instance default classification: admin-only, audited, stored value over env and fail-closed on invalid values."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, Project, SystemConfig
from app.services.knowledge.projection.workspace_classification_default import set_instance_default
from app.services.knowledge.projection.workspace_classification_values import ClassificationValueError
from tests.data_classification_settings_support import (  # noqa: F401
    _actions,
    _admin_id,
    _bearer,
    _config,
    _route,
    _workspace,
    env,
)
from tests.knowledge_evidence_seed_support import seed_member

DEFAULT_ROUTE = "/api/v1/admin/data-classification/default"


@pytest.mark.asyncio
async def test_the_instance_default_is_admin_only_audited_and_never_overwrites(client, db, env):  # noqa: F811
    unclassified = await _workspace(db)
    own = await _workspace(db, {"data_policy": {"classification": "confidential"}})
    cleared = await _workspace(db, {"data_policy": {"classification_cleared": True}})
    unreadable = await _workspace(db, {"data_policy": "secret"})
    member = await seed_member(db, workspace_id=unclassified, role="owner")
    await db.commit()
    admin = await _bearer(await _admin_id(db))

    forbidden = await client.post(f"{DEFAULT_ROUTE}/apply", headers=await _bearer(member))
    before = (await client.get(DEFAULT_ROUTE, headers=admin)).json()
    missing = await client.post(f"{DEFAULT_ROUTE}/apply", headers=admin)
    # The default itself changes only through a governed classification version.
    await set_instance_default(db, classification="internal", actor_id=await _admin_id(db), apply_to_unclassified=False)
    await db.commit()
    applied = await client.post(f"{DEFAULT_ROUTE}/apply", headers=admin)

    assert forbidden.status_code == 403 and missing.status_code == 422
    assert (before["classification"], before["source"], before["env_in_effect"]) == (None, "unset", False)
    assert before["unclassified_count"] >= 1
    assert applied.status_code == 200 and applied.json()["source"] == "admin"
    assert applied.json()["applied_count"] == before["unclassified_count"]
    assert (await _config(db, unclassified))["data_policy"] == {"classification": "internal"}
    assert (await _config(db, own))["data_policy"] == {"classification": "confidential"}
    assert (await _config(db, cleared))["data_policy"] == {"classification_cleared": True}
    assert (await _config(db, unreadable))["data_policy"] == "secret"
    assert "knowledge.workspace.data_classification_default" in await _actions(db, unclassified)
    audits = (await db.execute(select(AuditLog).where(
        AuditLog.action == "admin.data_classification.default_updated").order_by(AuditLog.created_at))).scalars().all()
    assert [audit.details["after"] for audit in audits] == ["internal", "internal"]
    assert audits[-1].details["applied_count"] == applied.json()["applied_count"]

    # The classification later disappears without the governed path (no cleared marker): the Workspace
    # was defaulted once already, so the default never comes back.
    project = await db.get(Project, unclassified)
    project.config = {}
    await db.commit()
    again = await client.post(f"{DEFAULT_ROUTE}/apply", headers=admin)
    assert again.json()["applied_count"] == 0, "a defaulted Workspace is never defaulted again"
    assert (await _config(db, unclassified)) == {}


@pytest.mark.asyncio
async def test_the_stored_default_wins_over_the_env_bootstrap_value(client, db, env):  # noqa: F811
    env.setattr(get_settings(), "knowledge_default_data_classification", "public")
    admin = await _bearer(await _admin_id(db))

    bootstrap = (await client.get(DEFAULT_ROUTE, headers=admin)).json()
    await set_instance_default(db, classification=None, actor_id=await _admin_id(db), apply_to_unclassified=False)
    await db.commit()
    explicit_none = (await client.get(DEFAULT_ROUTE, headers=admin)).json()
    with pytest.raises(ClassificationValueError):
        await set_instance_default(db, classification="classified", actor_id=await _admin_id(db),
                                   apply_to_unclassified=False)
    stored = (await db.execute(select(SystemConfig.value).where(
        SystemConfig.key == "knowledge.default_data_classification"))).scalar_one()

    assert (bootstrap["classification"], bootstrap["source"], bootstrap["env_in_effect"]) == ("public", "env", True)
    assert (explicit_none["classification"], explicit_none["state"], explicit_none["source"],
            explicit_none["env_in_effect"]) == (None, "unset", "admin", False)
    assert stored == "none"


@pytest.mark.asyncio
async def test_an_invalid_stored_default_fails_closed_and_never_falls_back_to_env(client, db, env):  # noqa: F811
    """A stored value that is no level is ``invalid``; the env bootstrap value never stands in for it."""
    from app.services.knowledge.projection.workspace_classification_default import apply_instance_default_classification
    from app.services.knowledge.projection.workspace_classification_values import instance_default_for

    env.setattr(get_settings(), "knowledge_default_data_classification", "public")
    db.add(SystemConfig(key="knowledge.default_data_classification", value="classified"))
    unclassified = await _workspace(db)
    owner = await seed_member(db, workspace_id=unclassified, role="owner")
    await db.commit()
    admin_id = await _admin_id(db)

    resolved = await instance_default_for(db)
    admin_view = (await client.get(DEFAULT_ROUTE, headers=await _bearer(admin_id))).json()
    workspace_view = (await client.get(_route(unclassified), headers=await _bearer(owner))).json()
    applied = await apply_instance_default_classification(db, project_id=unclassified, actor_id=admin_id)
    await db.commit()

    assert resolved == (None, "invalid", "admin")
    assert (admin_view["classification"], admin_view["state"], admin_view["source"], admin_view["env_in_effect"]) \
        == (None, "invalid", "admin", False)
    assert workspace_view["instance_default"] == {"classification": None, "state": "invalid"}
    assert (workspace_view["effective"], workspace_view["source"]) == (None, "unset")
    assert applied is None and "data_policy" not in await _config(db, unclassified)
