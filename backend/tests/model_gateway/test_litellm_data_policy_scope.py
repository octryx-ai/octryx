"""Auxiliary dispatch owners and multi-workspace scopes carry the strictest database classification, and the admin surface and gateway config keep it in place."""

from __future__ import annotations

import pytest

from app.models import Project
from app.services.model_gateway.data_policy import DENIAL_CLASS_INSUFFICIENT, resolve_workspace_data_classification
from app.services.model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from app.services.model_gateway.litellm import LiteLLMGatewayError
from tests.model_gateway.conftest import ALIAS, MESSAGES, gateway_config, gateway_runtime, verified_admission

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


async def test_an_auxiliary_dispatch_owner_carries_the_database_classification(
    db, gateway, build_gateway_client
) -> None:
    """The owner boundary replaces a caller-forged admission from the row."""

    project = Project(
        id="project-auxiliary-data-policy",
        name="auxiliary-data-policy-project",
        config={
            "model_policy": {"allowed_aliases": [ALIAS]},
            "data_policy": {"classification": "restricted"},
        },
    )
    db.add(project)
    await db.commit()

    admission = await admit_runtimes_for_dispatch(
        db,
        [gateway_runtime(project_model_admission=verified_admission(ALIAS, classification="public"))],
        project_ids=project.id,
        owner="knowledge_graph_runtime",
    )
    carried = admission.first_dispatchable_runtime()["project_model_admission"]
    assert carried.data_classification.classification == "restricted"

    client = build_gateway_client(gateway, project_admission=carried)
    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, ALIAS)

    assert excinfo.value.denial_reason == DENIAL_CLASS_INSUFFICIENT
    assert gateway.requests == []


async def test_a_multi_workspace_scope_carries_its_strictest_classification(db, gateway, build_gateway_client) -> None:
    projects = (
        Project(
            id="project-data-policy-public",
            name="data-policy-public-project",
            config={
                "model_policy": {"allowed_aliases": [ALIAS]},
                "data_policy": {"classification": "public"},
            },
        ),
        Project(
            id="project-data-policy-restricted",
            name="data-policy-restricted-project",
            config={
                "model_policy": {"allowed_aliases": [ALIAS]},
                "data_policy": {"classification": "restricted"},
            },
        ),
    )
    db.add_all(projects)
    await db.commit()

    admission = await admit_runtimes_for_dispatch(
        db,
        [gateway_runtime()],
        project_ids=[project.id for project in projects],
        owner="knowledge_graph_runtime",
    )
    carried = admission.first_dispatchable_runtime()["project_model_admission"]
    assert carried.project_id == projects[0].id
    assert carried.data_classification.classification == "restricted"

    client = build_gateway_client(gateway, project_admission=carried)
    with pytest.raises(LiteLLMGatewayError):
        await client.chat(MESSAGES, ALIAS)
    assert gateway.requests == []


# ---------------------------------------------------------------------------
# The admin write surface owns the closed vocabulary
# ---------------------------------------------------------------------------


async def test_the_admin_surface_persists_and_validates_the_classification(db) -> None:
    from fastapi import HTTPException

    from app.services.admin.project._admin_project_config_owners import list_project_config_key_owners
    from app.services.admin.project.admin_project_config_service import merge_project_config

    project = Project(id="project-admin-write", name="admin-write-project", config={})
    db.add(project)
    await db.commit()

    written = await merge_project_config(
        db,
        project_id=project.id,
        patch={"data_policy": {"classification": "Confidential "}},
        actor_user_id="data-policy-admin",
    )
    assert written["config"]["data_policy"]["classification"] == "confidential"

    with pytest.raises(HTTPException) as excinfo:
        await merge_project_config(
            db,
            project_id=project.id,
            patch={"data_policy": {"classification": "ultra-secret"}},
            actor_user_id="data-policy-admin",
        )
    assert excinfo.value.status_code == 400
    assert "data_policy.classification" in str(excinfo.value.detail)

    # The rejected write left the governed value untouched.
    resolved = await resolve_workspace_data_classification(db, project_id=project.id)
    assert resolved.classification == "confidential"

    owners = {owner["key"]: owner for owner in list_project_config_key_owners()}
    assert owners["data_policy"]["policy_sensitive"] is True
    assert owners["data_policy"]["owner"] == "model_gateway/data_policy"


def test_the_gateway_config_cannot_carry_the_workspace_classification() -> None:
    """The alias catalog declares an allowance, never the workspace's own class."""

    section = gateway_config()["litellm_gateway"]

    assert "classification" not in section
    assert "data_policy" not in section
    assert set(section["aliases"][ALIAS]) == {
        "model_group",
        "context_limit",
        "data_policy_class",
        "capabilities",
        "cost",
    }
