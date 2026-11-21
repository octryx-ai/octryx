"""Shared helpers for the test_hands_on_* modules."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace


def _scenario(part="regression", covers=(), width=1280, **extra):
    return {"part": part, "title": f"{part} {'/'.join(covers)}", "viewport": {"width": width, "height": 800},
            "covers": list(covers), "steps": [{"do": "goto", "path": "/"}, {"do": "reload"},
                                              {"do": "expect_text", "text": "Bohne 1"}], **extra}


def _answer():
    return {"scenarios": [
        _scenario("feature", fresh_profile=True),
        _scenario(covers=("app_loads", "persistence_reload", "empty_state", "invalid_input")),
        _scenario(covers=("mobile_390",), width=390),
        _scenario(covers=("desktop_1280",), fresh_profile=False, seed=[{"do": "click", "text": "Skip"}]),
    ]}


def _definition() -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
            {"id": "hands_on", "type": "platform_action", "label": "Hands-on", "config": {"action": "hands_on.run"}},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}},
        ],
        "edges": [
            {"id": "a", "source_node_id": "start", "target_node_id": "work"},
            {"id": "b", "source_node_id": "work", "target_node_id": "hands_on"},
            {"id": "c", "source_node_id": "hands_on", "target_node_id": "done", "when": "succeeded"},
            {"id": "d", "source_node_id": "hands_on", "target_node_id": "work", "when": "failed", "kind": "loop",
             "max_iterations": 3},
        ],
    }


class _Model:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    async def answer(self, *, system, user, images=None):
        self.asked.append(user)
        return SimpleNamespace(answer=self.answers.pop(0), usage=None)


async def _at_hands_on(db, monkeypatch, *, runtime="device", pointer=True, model=None, definition=None):
    offered = []

    async def device(_db, _run):
        return runtime

    async def file(_db, _run):
        return {"file": "web/.octryx/environment.json", "app_folder": "web"} if pointer else None

    async def turn(_db, _run, node):
        offered.append(node.id)

    async def setup(_db, _run):
        return SimpleNamespace(instructions="", definition_id="reviewer")

    async def choice(_db, _run, _config):
        return SimpleNamespace(model="m")

    async def factory(_db, **_kwargs):
        return model

    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", device)
    monkeypatch.setattr("app.services.workflow_runs.pipeline.environment_file_for", file)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", turn)
    monkeypatch.setattr("app.services.workflow_runs.review.reviewer_agent.reviewer_setup", setup)
    monkeypatch.setattr("app.services.workflow_runs.review.choice.review_choice", choice)
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition or _definition()),
                          project_id=workspace_id,
                          session=session)
    resolution = await run_turn_resolution(db, session, user_message="Build it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    return run, session, offered, factory


def _reproduce_definition(confirm: bool = False) -> dict:
    definition = _definition()
    node = next(item for item in definition["nodes"] if item["id"] == "hands_on")
    node["config"] = {"action": "hands_on.run", "mode": "reproduce", **({"confirm": True} if confirm else {})}
    definition["nodes"] += [{"id": name, "type": "outcome", "config": {"outcome": "done"}}
                            for name in ("reproduced", "person", "cannot")]
    definition["edges"] = [edge for edge in definition["edges"] if edge["source_node_id"] != "hands_on"] + [
        {"id": "r1", "source_node_id": "hands_on", "target_node_id": "reproduced", "when": "succeeded"},
        {"id": "r2", "source_node_id": "hands_on", "target_node_id": "person", "when": "skipped"},
        {"id": "r3", "source_node_id": "hands_on", "target_node_id": "work", "when": "failed", "kind": "loop",
         "max_iterations": 2},
        {"id": "r4", "source_node_id": "hands_on", "target_node_id": "cannot", "when": "cannot_reproduce"}]
    return definition
