"""A turn's runtime comes from one explicit source and stays stable for every iteration."""

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.agent.core.context.run_context as run_context_module
import app.agent.engine as engine_module
import app.services.session.turn_runtime_selection as selection_module
from app.agent.engine import run_agent
from app.agent.loops.request._loop_request_routing import prepare_runtime_routing
from app.models import Project, Session, User
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
from tests.run_capability_support import DECLARED_CHANGE_RUN

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


def test_iteration_routing_never_reorders_the_turns_runtimes(monkeypatch):
    from app.agent.loops.request import _loop_request_routing

    monkeypatch.setattr(_loop_request_routing, "coding_discipline_for_role", lambda **kwargs: "edit")
    monkeypatch.setattr(_loop_request_routing, "reasoning_task_type_for_turn", lambda **kwargs: "code_generation")
    monkeypatch.setattr(_loop_request_routing, "reasoning_stage_for_turn", lambda **kwargs: "execute")
    runtimes = [{"model": SONNET}, {"model": NOVA}]
    routing = prepare_runtime_routing(
        runtimes=runtimes,
        capability_type="change",
        context_plan=None,
        request_analysis={},
        current_step=None,
        current_step_for_runtime=None,
        step_tool_history=[{"tool_name": "write_workspace_file", "success": True}],
        _model_role_for_current_subtask=lambda **kwargs: "code_generation",
    )
    assert routing["current_runtimes"] == runtimes
    assert routing["current_coding_discipline"] == "edit"


@pytest.mark.asyncio
async def test_a_follow_up_iteration_after_a_tool_result_keeps_the_turns_runtime(db, monkeypatch, tmp_path):
    # After a tool result the "edit" discipline must not reroute the turn
    # from its priority-1 runtime to a configured/benchmarked weak model.
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    (tmp_path / "calculator.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        status="running",
        metadata_={**DECLARED_CHANGE_RUN, "workspace_root": str(tmp_path)},
    )
    db.add(session)
    await db.commit()

    runtimes = [
        {"provider_name": "bedrock", "model": SONNET, "priority": 1},
        {"provider_name": "bedrock", "model": NOVA, "priority": 2},
    ]
    responses = [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "write",
                    "function": {
                        "name": "write_workspace_file",
                        "arguments": json.dumps({"path": "calculator.py", "content": "def divide(a, b):\n    return a / b\n"}),
                    },
                }
            ],
            "model": SONNET,
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        },
        {"content": "Done.", "tool_calls": None, "model": SONNET, "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
    ]
    first_models: list[str] = []

    async def fake_runtimes(_db, runtime_target_id=None):
        return runtimes

    async def fake_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        first_models.append(runtimes[0]["model"])
        return (responses.pop(0) if responses else responses_done()), runtimes[0]

    def responses_done():
        return {"content": "Done.", "tool_calls": None, "model": SONNET, "usage": {}}

    async def settings_with_discipline_models(_db):
        # An admin-configured weak edit model must not reroute any "edit" iteration.
        return {"edit_model": NOVA, "test_fix_model": NOVA, "discipline_routing_mode": "manual_first"}

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)
    monkeypatch.setattr(run_context_module, "get_agent_runtime_settings", settings_with_discipline_models)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Change divide in calculator.py.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="coding",
        db=db,
    ):
        pass

    assert len(first_models) >= 2, "the turn must iterate after the tool result"
    assert set(first_models) == {SONNET}
