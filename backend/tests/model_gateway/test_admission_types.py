from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agent.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIAL_KEY
from app.services.model_gateway.litellm.admission_types import AdmissionDenial, StoredModelPolicy
from app.services.model_gateway.litellm.runtime_admission import apply_model_policy_to_runtimes
from tests.model_gateway.conftest import ALIAS, PROJECT_ID, gateway_config, gateway_runtime, workspace_classification
from tests.policy_engine_support import bearer, make_user
from tests.services.workspace.test_workspace_models import ROUTE, _setup
from tests.typed_dict_support import shape_problems

SECRET_ALIAS_CONFIG = gateway_config()
SECRET_ALIAS_CONFIG["litellm_gateway"]["aliases"][ALIAS]["data_policy_class"] = "public"


@pytest.mark.parametrize(("project_config", "runtime", "classification"), [
    ({"model_policy": {"allowed_aliases": []}}, gateway_runtime(), "internal"),
    ({"model_policy": {"denied_aliases": [ALIAS]}}, gateway_runtime(), "internal"),
    ({"model_policy": {"allowed_aliases": [ALIAS]}}, gateway_runtime(model="octryx-unlisted"), "internal"),
    ({"model_policy": {"allowed_aliases": [ALIAS]}}, gateway_runtime(config_json=SECRET_ALIAS_CONFIG), "confidential"),
])
def test_every_admission_denial_is_an_admission_denial(project_config, runtime, classification):
    [admitted] = apply_model_policy_to_runtimes([runtime], project_config=project_config, project_id=PROJECT_ID,
                                                data_classification=workspace_classification(classification))
    assert shape_problems(admitted[RUNTIME_ADMISSION_DENIAL_KEY], AdmissionDenial, "denial") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["selected", "all_cleared"])
async def test_a_saved_model_list_stores_a_stored_model_policy(client, db, mode):
    from app.models import Project

    admin = await make_user(db, admin=True)
    project, _target_id = await _setup(db, "internal", model_policy={"denied_aliases": ["octryx-legacy"]})
    view = (await client.get(ROUTE.format(project.id), headers=bearer(admin))).json()
    body = {"mode": mode, "selected": ["octryx-general"] if mode == "selected" else [], "default": None,
            "task_overrides": {}, "seat": dict(view["contract"]["seat"])}
    saved = await client.put(ROUTE.format(project.id), json=body, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    stored = (await db.execute(select(Project).where(Project.id == project.id))).scalar_one()
    await db.refresh(stored)
    assert shape_problems(stored.config["model_policy"], StoredModelPolicy, "model_policy") == []
