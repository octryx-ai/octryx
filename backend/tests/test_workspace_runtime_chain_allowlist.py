"""The Workspace runtime allowlist bounds the fallback chain, not only the start runtime."""

from types import SimpleNamespace
from typing import Any

import pytest

import app.services.session.turn_runtime_selection as selection_module
from app.services.model_selection.snapshot import SelectionSnapshot, scope_from_view
from app.services.session.turn_refusals import TurnRefusalState, TurnRefusedError
from app.services.session.turn_runtime_selection import RuntimeChoice, resolve_turn_runtime


def _view(mode: str, *runtime_target_ids: str) -> dict[str, Any]:
    return {
        "workspace_id": "ws-1",
        "bindings_by_kind": {
            "runtime": [
                {"binding_key": f"runtime-target:{target_id}", "source_entity_id": target_id}
                for target_id in runtime_target_ids
            ]
        },
        "runtime_policy": {"runtime_assignment_mode": mode},
    }


SELECTED_T2 = _view("selected_only", "t2")












def _target(target_id: str):
    return SimpleNamespace(id=target_id, model_id=target_id, priority=1, is_active=True, use_case_tags=[])


async def _resolve(monkeypatch, view: dict[str, Any], active: list[str]) -> RuntimeChoice:
    async def fake_targets(_db, *_args, **_kwargs):
        return [_target(target_id) for target_id in active]

    monkeypatch.setattr(selection_module, "get_runtime_targets", fake_targets)

    async def fake_selection(_db, workspace_view, _session):
        return SelectionSnapshot(), scope_from_view(workspace_view)

    monkeypatch.setattr(selection_module, "load_turn_selection", fake_selection)
    choice = RuntimeChoice(runtime_target_id="", runtime_label="", labels={"": "Auto", **{t: t for t in active}})
    await resolve_turn_runtime(
        None,
        choice,
        runtime_target_id_explicit=False,
        session=None,
        workspace_execution_view=view,
        agent_runtime_target_id="",
        workflow_contract=None,
    )
    return choice


@pytest.mark.asyncio
async def test_a_workspace_without_an_active_allowed_runtime_is_refused_with_a_code(monkeypatch) -> None:
    # The only selected runtime (t2) is inactive: the automatic chain (t1) must not answer.
    with pytest.raises(TurnRefusedError) as refused:
        await _resolve(monkeypatch, SELECTED_T2, active=["t1"])
    assert refused.value.refusal.state == TurnRefusalState.RUNTIME_NOT_ALLOWED


@pytest.mark.asyncio
async def test_an_active_allowed_runtime_is_not_an_implicit_default(monkeypatch) -> None:
    # Intended: the Workspace's first runtime binding is no longer a silent default. The turn
    # runs automatically; the chain admission keeps only the Workspace's allowed runtime (t2, tests above).
    choice = await _resolve(monkeypatch, SELECTED_T2, active=["t1", "t2"])
    assert (choice.runtime_target_id, choice.source) == ("", "global_default")
    choice = await _resolve(monkeypatch, _view("all_installed"), active=["t1"])
    assert choice.runtime_target_id == ""
