"""A turn's runtime comes from one explicit source and stays stable for every iteration."""

from types import SimpleNamespace

import pytest

import app.services.session.turn_runtime_selection as selection_module
from app.services.model_selection.gates import CatalogModel, WorkspaceScope
from app.services.model_selection.snapshot import SelectionSnapshot
from app.services.session.turn_refusals import TurnRefusalState, TurnRefusedError
from app.services.session.turn_runtime_selection import (
    RuntimeChoice,
    RuntimeSelectionSource,
    resolve_turn_runtime,
)
from app.services.workflow_routing.platform_selection import (
    SECURE_WORK_CODING_EXECUTION,
    platform_workflow_selection_resolution,
)
from app.services.workflow_runs.seeding import phased_seeds

SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"
NOVA = "amazon.nova-2-lite-v1:0"
CODING = {"workflow_id": "coding_change_tdd", "required_model_capability": "coding"}


def _target(target_id: str, model_id: str, priority: int, tags: tuple[str, ...] = ()):
    return SimpleNamespace(id=target_id, model_id=model_id, priority=priority, is_active=True, use_case_tags=list(tags))


TARGETS = [_target("nova", NOVA, 1), _target("sonnet", SONNET, 2, ("edit",)), _target("haiku", "claude-haiku-4.5", 3)]
# The coding capability is the Model catalog's explicit checkbox, not a name heuristic.
# The catalog states it: only Sonnet is coding-capable.
CODING_CAPABLE = {"sonnet"}


def _model(target, *, cleared: str | None = "internal", enabled: bool = True) -> CatalogModel:
    return CatalogModel(
        key=target.id, provider_id="bedrock", model_id=target.model_id, display_name=target.id,
        provider_name="Bedrock", driver="bedrock_api", enabled=enabled, provider_active=True, cleared_up_to=cleared,
        capabilities={"tools": True, "vision": False, "coding": target.id in CODING_CAPABLE, "long_context": False},
        target_ids=(target.id,),
    )


def _selection(targets=TARGETS, *, default: str = "", data_class: str = "", **overrides):
    models = {target.id: overrides.get(target.id) or _model(target) for target in targets}
    snapshot = SelectionSnapshot(
        models=models, by_target={target.id: target.id for target in targets},
        order=tuple(target.id for target in targets),
    )
    return snapshot, WorkspaceScope(data_class=data_class, default_target_id=default)


def _choice(runtime_target_id: str = "", *, explicit: bool = False) -> RuntimeChoice:
    labels = {"": "Auto", **{target.id: target.id for target in TARGETS}}
    source = RuntimeSelectionSource.EXPLICIT if explicit else RuntimeSelectionSource.GLOBAL_DEFAULT
    return RuntimeChoice(runtime_target_id=runtime_target_id, runtime_label="", labels=labels, source=source)


def _use(monkeypatch, selection) -> None:
    async def fake_selection(_db, _view, _session):
        return selection

    monkeypatch.setattr(selection_module, "load_turn_selection", fake_selection)


@pytest.fixture
def targets(monkeypatch):
    async def fake_targets(_db, *args, **kwargs):
        return TARGETS

    monkeypatch.setattr(selection_module, "get_runtime_targets", fake_targets)
    _use(monkeypatch, _selection())


async def _resolve(choice, *, explicit=False, session=None, agent="", contract=None):
    await resolve_turn_runtime(
        None,
        choice,
        runtime_target_id_explicit=explicit,
        session=session,
        workspace_execution_view=None,
        agent_runtime_target_id=agent,
        workflow_contract=contract,
    )
    return choice.runtime_target_id, choice.source


def _session(runtime_target_id: str, source: str | None):
    metadata = {"runtime_target_id": runtime_target_id}
    if source is not None:
        metadata["runtime_selection_source"] = source
    return SimpleNamespace(metadata_=metadata)


@pytest.mark.asyncio
async def test_each_source_in_precedence_order(targets, monkeypatch):
    assert await _resolve(_choice("haiku", explicit=True), explicit=True, agent="sonnet") == ("haiku", "explicit")
    assert await _resolve(_choice(), session=_session("haiku", "explicit"), agent="sonnet") == ("haiku", "session")
    assert await _resolve(_choice(), agent="sonnet") == ("sonnet", "agent")
    assert await _resolve(_choice(), contract=CODING) == ("sonnet", "workflow")
    _use(monkeypatch, _selection(default="haiku"))
    assert await _resolve(_choice()) == ("haiku", "workspace_default")
    _use(monkeypatch, _selection())
    assert await _resolve(_choice()) == ("", "global_default")


@pytest.mark.asyncio
async def test_only_a_chosen_runtime_sticks_to_the_thread(targets):
    # A runtime an earlier turn derived (default, workflow, agent) is derived again, not inherited.
    assert await _resolve(_choice(), session=_session("haiku", "workflow")) == ("", "global_default")
    assert await _resolve(_choice(), session=_session("haiku", "explicit")) == ("haiku", "session")
    # A runtime without a recorded source is no choice either.
    assert await _resolve(_choice(), session=_session("haiku", None)) == ("", "global_default")


@pytest.mark.asyncio
async def test_a_coding_workflow_never_lands_on_a_model_without_the_coding_capability(targets, monkeypatch):
    # The non-coding runtime has priority 1 and is the Workspace default: both are skipped.
    _use(monkeypatch, _selection(default="nova"))
    assert await _resolve(_choice(), session=_session("nova", "explicit"), agent="nova", contract=CODING) == (
        "sonnet",
        "workflow",
    )
    with pytest.raises(TurnRefusedError) as refused:
        await _resolve(_choice("nova", explicit=True), explicit=True, contract=CODING)
    assert refused.value.refusal.state == TurnRefusalState.RUNTIME_REQUIREMENT_UNMET


@pytest.mark.asyncio
async def test_no_capable_runtime_is_a_closed_refusal(monkeypatch):
    async def weak_only(_db, *args, **kwargs):
        return [TARGETS[0]]

    monkeypatch.setattr(selection_module, "get_runtime_targets", weak_only)
    _use(monkeypatch, _selection([TARGETS[0]]))
    with pytest.raises(TurnRefusedError) as refused:
        await _resolve(_choice(), contract=CODING)
    assert refused.value.refusal.state == TurnRefusalState.RUNTIME_REQUIREMENT_UNMET


@pytest.mark.asyncio
async def test_an_explicit_model_not_cleared_for_the_workspace_is_refused_with_the_reason(targets, monkeypatch):
    # The data clearance gates a direct-provider model too: a Confidential Workspace cannot pick a direct model
    # cleared only for Internal data.
    _use(monkeypatch, _selection(data_class="confidential"))
    with pytest.raises(TurnRefusedError) as refused:
        await _resolve(_choice("haiku", explicit=True), explicit=True)
    assert refused.value.refusal.state == TurnRefusalState.RUNTIME_NOT_ALLOWED
    assert "not cleared" in refused.value.refusal.detail


@pytest.mark.asyncio
async def test_an_implicit_pin_that_may_not_answer_is_skipped_never_used(targets, monkeypatch):
    disabled = _model(TARGETS[1], enabled=False)
    _use(monkeypatch, _selection(default="sonnet", sonnet=disabled))
    assert await _resolve(_choice(), agent="sonnet") == ("", "global_default")


def test_the_coding_workflows_declare_their_model_capability():
    coding_phases = [
        node["config"]["workflow_contract"]
        for seed in phased_seeds()
        for node in seed["definition"]["nodes"]
        if node.get("type") == "phase" and (node.get("config") or {}).get("workflow_id") == "coding_change_tdd"
    ]
    assert coding_phases
    assert all(contract["required_model_capability"] == "coding" for contract in coding_phases)
    platform = platform_workflow_selection_resolution(SECURE_WORK_CODING_EXECUTION)
    assert platform["workflow_contract"]["required_model_capability"] == "coding"




