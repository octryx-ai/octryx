from __future__ import annotations

from typing import get_args

import pytest
from sqlalchemy import select

from app.models import WorkspaceCapabilityBinding
from app.services.mcp_governance.resource_identity import MCP_RESOURCE_LIFECYCLE_STATES, MCP_RESOURCE_RISKS
from app.services.mcp_governance.resource_types import (
    LifecycleState,
    McpResourceRisk,
    MirroredBindingConfig,
    MirroredPolicyConfig,
    MirrorMarkerConfig,
    MirrorMarkerPolicy,
)
from tests.support.mcp_resource_support import (
    DOC_URI,
    OTHER_URI,
    PROMPT,
    create_mcp_workspace,
    mcp_prompt,
    mcp_resource,
    mirror_catalog,
)
from tests.typed_dict_support import shape_problems


async def _bindings(db, workspace) -> list[WorkspaceCapabilityBinding]:
    return list((await db.execute(select(WorkspaceCapabilityBinding).where(
        WorkspaceCapabilityBinding.workspace_id == workspace.project.id))).scalars())


def _problems(binding: WorkspaceCapabilityBinding) -> list[str]:
    if binding.binding_status == "hidden":
        return (shape_problems(binding.binding_config, MirrorMarkerConfig, "marker")
                + shape_problems(binding.policy_config, MirrorMarkerPolicy, "marker policy"))
    return (shape_problems(binding.binding_config, MirroredBindingConfig, binding.binding_key)
            + shape_problems(binding.policy_config, MirroredPolicyConfig, f"{binding.binding_key} policy"))


@pytest.mark.asyncio
async def test_every_mirror_run_stores_the_typed_binding_configs(db) -> None:
    workspace = await create_mcp_workspace(db)
    runs = [
        {"resources": [DOC_URI, OTHER_URI], "prompts": [PROMPT]},
        {"resources": [mcp_resource(DOC_URI, mime_type="application/json")], "prompts": []},
        {"resources": [DOC_URI, mcp_resource(OTHER_URI, description="Password: hunter2-secret-value")],
         "prompts": [mcp_prompt(PROMPT, arguments=[{"name": "topic", "required": True}])]},
    ]
    seen: set[str] = set()
    for run in runs:
        await mirror_catalog(db, workspace, **run)
        bindings = await _bindings(db, workspace)
        assert [line for binding in bindings for line in _problems(binding)] == []
        seen |= {key for binding in bindings for key in binding.binding_config}
    assert {"reviewState", "previousContractDigest", "missingDetectedAt", "reappearedAt", "mirrorRejection"} <= seen


def test_the_mcp_resource_vocabularies_are_the_constants_the_code_uses():
    assert get_args(McpResourceRisk) == MCP_RESOURCE_RISKS
    assert get_args(LifecycleState) == MCP_RESOURCE_LIFECYCLE_STATES
