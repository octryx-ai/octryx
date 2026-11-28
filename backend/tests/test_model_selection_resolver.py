"""The one model resolver: the same gates for every driver, every path, every fallback."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider, Project
from app.services.model_selection.gates import AliasGrant, CatalogModel, WorkspaceScope, gate
from app.services.model_selection.platform_order import active_config
from app.services.model_selection.resolver import ModelRequest, resolve_model
from app.services.model_selection.snapshot import SelectionSnapshot, load_scope, load_snapshot
from app.services.runtime_options import list_chat_runtime_options
from app.services.workspace_composition.execution_view import get_workspace_execution_view


def _model(key: str, *, cleared: str | None = "internal", enabled: bool = True, coding: bool = False,
           driver: str = "bedrock_api") -> CatalogModel:
    return CatalogModel(
        key=key, provider_id="p", model_id=key, display_name=key.title(), provider_name="P", driver=driver,
        enabled=enabled, provider_active=True, cleared_up_to=cleared,
        capabilities={"tools": True, "vision": False, "coding": coding, "long_context": False}, target_ids=(f"t-{key}",),
    )


def _snapshot(*models: CatalogModel, fallback: str = "next", tasks: dict | None = None) -> SelectionSnapshot:
    return SelectionSnapshot(
        models={model.key: model for model in models},
        by_ref={(model.provider_id, model.model_id): model.key for model in models},
        by_target={f"t-{model.key}": model.key for model in models},
        order=tuple(model.key for model in models), fallback=fallback, task_models=tasks or {},
    )


LARGE = _model("large", cleared="confidential", coding=True)
FAST = _model("fast", cleared="internal")
UNCLEARED = _model("raw", cleared=None)
SNAPSHOT = _snapshot(FAST, LARGE, UNCLEARED)
CONFIDENTIAL = WorkspaceScope(data_class="confidential")
INTERNAL = WorkspaceScope(data_class="internal")
SELECTED_FAST = WorkspaceScope(data_class="internal", assignment_mode="selected_only",
                               selected_target_ids=frozenset({"t-fast"}))


@pytest.mark.parametrize(
    ("scope", "request_", "start", "source", "chain", "refusal"),
    [
        # Automatic: the first candidate of the platform order; fallback = the rest of the candidates.
        (INTERNAL, ModelRequest(), "fast", "platform_order", ["fast", "large"], ""),
        # Confidential: the order's #1 is not cleared, so the first cleared model starts; nothing else may answer.
        (CONFIDENTIAL, ModelRequest(), "large", "platform_order", ["large"], ""),
        # A person's choice is used only if it may answer, else refused with the reason, never swapped.
        (INTERNAL, ModelRequest(person_choice="large"), "large", "person", ["large", "fast"], ""),
        (CONFIDENTIAL, ModelRequest(person_choice="fast"), "", "", [], "chosen_model_not_allowed"),
        # An implicit pin that may not answer is skipped; the next source decides.
        (CONFIDENTIAL, ModelRequest(agent_pin="fast"), "large", "platform_order", ["large"], ""),
        (INTERNAL, ModelRequest(agent_pin="large", step_pin="fast"), "large", "agent", ["large", "fast"], ""),
        (INTERNAL, ModelRequest(step_pin="large"), "large", "workflow_step", ["large", "fast"], ""),
        # A selected-only Workspace: fallback never leaves its list.
        (SELECTED_FAST, ModelRequest(), "fast", "platform_order", ["fast"], ""),
        (SELECTED_FAST, ModelRequest(person_choice="large"), "", "", [], "chosen_model_not_allowed"),
        # A capability requirement reads the catalog checkbox.
        (INTERNAL, ModelRequest(capability="coding"), "large", "platform_order", ["large"], ""),
        # An unclassified Workspace still needs a model cleared for some data.
        (WorkspaceScope(), ModelRequest(person_choice="raw"), "", "", [], "chosen_model_not_allowed"),
    ],
)
def test_the_resolver_matrix(scope, request_, start, source, chain, refusal):
    result = resolve_model(SNAPSHOT, scope, request_)
    assert (result.start, result.source, result.chain, result.refusal) == (start, source, chain, refusal)
    assert result.trace, "every decision carries its explanation"


def test_stop_mode_has_no_fallback_and_no_candidate_is_needs_configuration():
    assert resolve_model(_snapshot(FAST, LARGE, fallback="stop"), INTERNAL, ModelRequest()).chain == ["fast"]
    empty = resolve_model(_snapshot(UNCLEARED), INTERNAL, ModelRequest())
    assert empty.refusal == "needs_configuration" and not empty.chain


def test_a_task_model_starts_its_task_and_a_workspace_default_is_explicit_only():
    snapshot = _snapshot(FAST, LARGE, tasks={"summarize": "large"})
    assert resolve_model(snapshot, INTERNAL, ModelRequest(task="summarize")).start == "large"
    assert resolve_model(snapshot, WorkspaceScope(data_class="internal", default_target_id="t-large"),
                         ModelRequest()).source == "workspace_default"


def test_the_gates_hold_for_every_driver():
    gateway = _model("alias", cleared="internal", driver="litellm_gateway")
    assert gate(gateway, CONFIDENTIAL) == gate(FAST, CONFIDENTIAL) == "not_cleared_for_data"
    assert gate(_model("off", enabled=False), INTERNAL) == "model_not_enabled"


def test_a_gateway_alias_the_workspace_model_policy_does_not_grant_is_never_chosen():
    # The label never says "Automatic · Sonnet" while the gateway refuses Sonnet
    # (model_alias_not_granted_for_project).
    sonnet = _model("sonnet", driver="litellm_gateway")
    opus = _model("opus", driver="litellm_gateway")
    direct = _model("direct")
    snapshot = _snapshot(sonnet, opus, direct)
    only_opus = WorkspaceScope(data_class="internal", alias_grant=AliasGrant.from_policy({"allowed_aliases": ["opus"]}))

    assert gate(sonnet, only_opus) == "alias_not_granted_in_workspace"
    assert gate(opus, only_opus) == gate(direct, only_opus) == "", "a direct model has no alias grant"
    assert gate(sonnet, INTERNAL) == "", "a scope without the Workspace config leaves the grant to the gateway"
    result = resolve_model(snapshot, only_opus, ModelRequest())
    assert (result.start, result.chain) == ("opus", ["opus", "direct"])
    denied = AliasGrant.from_policy({"allow_all_admitted_aliases": True, "denied_aliases": ["opus"]})
    assert resolve_model(snapshot, WorkspaceScope(data_class="internal", alias_grant=denied),
                         ModelRequest()).chain == ["sonnet", "direct"]
    nothing = WorkspaceScope(data_class="internal", alias_grant=AliasGrant.from_policy(None))
    assert resolve_model(snapshot, nothing, ModelRequest()).start == "direct", "no model_policy grants no alias"






@pytest.mark.asyncio
async def test_a_model_entering_the_order_without_a_catalog_row_gets_one_cleared_for_internal(db):
    provider = LLMProvider(name=f"p-{uuid.uuid4().hex[:6]}", driver="bedrock_api", display_name="P", is_active=True)
    db.add(provider)
    await db.flush()
    config = await active_config(db, create=True)
    db.add(ControlPlaneRuntimeTarget(config_id=config.id, provider_id=provider.id, model_id="new-model", priority=9))
    await db.commit()

    row = (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id))).scalar_one()
    assert (row.catalog_key, row.is_active, row.cleared_up_to, row.supports_tools) == ("new-model", True, "internal", None)


async def _gateway_order(db, *aliases: str) -> tuple[LLMProvider, dict[str, str]]:
    from tests.model_gateway.conftest import gateway_config, gateway_provider

    config = gateway_config()
    template = config["litellm_gateway"]["aliases"]["octryx-general"]
    for alias in aliases:
        config["litellm_gateway"]["aliases"][alias] = {**template, "display_name": alias.title()}
    provider = gateway_provider(name=f"gw-{uuid.uuid4().hex[:6]}", config_json=config)
    db.add(provider)
    await db.flush()
    for target in (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all():
        target.is_active = False  # only this order counts
    control = await active_config(db, create=True)
    db.add_all([LLMModel(provider_id=provider.id, model_id=alias, display_name=alias.title(), is_active=True,
                         cleared_up_to="confidential") for alias in aliases])
    await db.flush()  # the catalog rows first: a target without one gets a default row (order listener)
    targets = {}
    for priority, alias in enumerate(aliases, start=1):
        target = ControlPlaneRuntimeTarget(id=str(uuid.uuid4()), config_id=control.id, provider_id=provider.id,
                                           model_id=alias, priority=priority, is_active=True)
        db.add(target)
        targets[alias] = target.id
    await db.commit()
    return provider, targets


@pytest.mark.asyncio
async def test_the_automatic_label_names_the_model_the_gates_admit(db):
    provider, targets = await _gateway_order(db, "sonnet", "haiku", "opus")
    workspace = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                        config={"data_policy": {"classification": "internal"},
                                "model_policy": {"allowed_aliases": ["haiku", "opus"]}})
    db.add(workspace)
    await db.commit()
    view = await get_workspace_execution_view(db, workspace_id=workspace.id)

    scope = await load_scope(db, workspace_id=workspace.id, view=view)
    assert scope.alias_grant is not None and scope.alias_grant.allowed == {"haiku", "opus"}
    options = {option["value"]: option for option in await list_chat_runtime_options(db, workspace_execution_view=view)}
    assert options[""]["label"] == "Automatic · Haiku", "Sonnet is not granted to the Workspace"
    assert options[targets["sonnet"]]["disabled"] is True
    assert "model policy" in options[targets["sonnet"]]["disabled_reason"]

    haiku = (await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id,
                                                     LLMModel.model_id == "haiku"))).scalar_one()
    haiku.is_active = False  # disabled in the Model catalog: the chain builder drops it
    await db.commit()
    options = {option["value"]: option for option in await list_chat_runtime_options(db, workspace_execution_view=view)}
    assert options[""]["label"] == "Automatic · Opus"
    assert options[targets["haiku"]]["disabled"] is True


@pytest.mark.asyncio
async def test_a_row_without_capabilities_json_keeps_its_supports_flags_in_the_snapshot(db):
    provider = LLMProvider(name=f"p-{uuid.uuid4().hex[:6]}", driver="bedrock_api", display_name="P", is_active=True)
    db.add(provider)
    await db.flush()
    db.add(LLMModel(provider_id=provider.id, model_id="legacy", is_active=True, cleared_up_to="internal",
                    capabilities_json=None, supports_tools=True, supports_vision=True))
    await db.commit()

    capabilities = (await load_snapshot(db)).for_ref(provider.id, "legacy").capabilities
    assert capabilities["tools"] is True and capabilities["vision"] is True
