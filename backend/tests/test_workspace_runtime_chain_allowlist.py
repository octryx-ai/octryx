"""The Workspace runtime allowlist bounds the fallback chain, not only the start runtime."""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import app.services.session.turn_runtime_selection as selection_module
from app.agent.core.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIED_STATUS
from app.agent.core.runtime.runtime_errors import RUNTIME_ERROR_RUNTIME_NOT_ALLOWED
from app.agent.engine.runtime._engine_runtime_fallback import _chat_with_runtime_fallback
from app.services.model_selection.snapshot import SelectionSnapshot, scope_from_view
from app.services.session.turn_refusals import TurnRefusalState, TurnRefusedError
from app.services.session.turn_runtime_selection import RuntimeChoice, resolve_turn_runtime
from app.services.workspace_composition.runtime_chain_admission import apply_workspace_runtime_allowlist
from tests.model_gateway.conftest import MESSAGES, RecordingRuntimeFactory, backup_runtime


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


def _runtime(name: str, target_id: str, priority: int) -> dict[str, Any]:
    return backup_runtime(provider_name=name, model=f"{name}-model", target_id=target_id, priority=priority)


async def _run_chain(runtimes: list[dict[str, Any]], factory: RecordingRuntimeFactory):
    return await _chat_with_runtime_fallback(
        runtimes,
        messages=MESSAGES,
        tools=None,
        get_provider_func=factory,
        retry_policy={"max_retries": 0, "pause_seconds": 0, "fallback_mode": "all_runtimes"},
    )


@pytest.mark.asyncio
async def test_a_disallowed_first_runtime_is_skipped_and_the_allowed_one_answers() -> None:
    chain = apply_workspace_runtime_allowlist([_runtime("other", "t1", 1), _runtime("backup", "t2", 2)], SELECTED_T2)
    factory = RecordingRuntimeFactory(forbidden=("other",))

    _response, used_runtime, attempts = await _run_chain(chain, factory)

    assert factory.constructed == ["backup"]
    assert used_runtime["target_id"] == "t2"
    denied = [item for item in attempts if item.get("status") == RUNTIME_ADMISSION_DENIED_STATUS]
    assert [item["target_id"] for item in denied] == ["t1"]
    assert denied[0]["error_class"] == RUNTIME_ERROR_RUNTIME_NOT_ALLOWED
    assert denied[0]["dispatched"] is False


@pytest.mark.asyncio
async def test_fallback_never_reaches_a_runtime_the_workspace_does_not_allow() -> None:
    # The allowed start runtime times out; the next target in the platform order is not allowed.
    chain = apply_workspace_runtime_allowlist([_runtime("backup", "t2", 1), _runtime("other", "t3", 2)], SELECTED_T2)
    factory = RecordingRuntimeFactory(
        failures={"backup": httpx.ReadTimeout("timed out")}, forbidden=("other",)
    )

    with pytest.raises(RuntimeError) as excinfo:
        await _run_chain(chain, factory)

    assert "other" not in factory.constructed
    classes = {item.get("target_id"): item.get("error_class") for item in excinfo.value.runtime_attempts}
    assert classes["t3"] == RUNTIME_ERROR_RUNTIME_NOT_ALLOWED


def test_all_installed_and_environment_runtimes() -> None:
    chain = [_runtime("other", "t1", 1), _runtime("env", "", 2)]
    # all_installed (and no view at all) leaves the chain untouched.
    assert apply_workspace_runtime_allowlist(chain, _view("all_installed")) == chain
    assert apply_workspace_runtime_allowlist(chain, None) == chain
    # selected_only refuses the environment runtime too: it is on no Workspace list.
    refused = apply_workspace_runtime_allowlist(chain, _view("selected_only", "t1"))
    assert "admission_denial" not in refused[0]
    assert refused[1]["admission_denial"]["error_class"] == RUNTIME_ERROR_RUNTIME_NOT_ALLOWED


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
