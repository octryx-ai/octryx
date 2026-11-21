"""Spec Studio on a real run: the draft phase records it, the product owner changes, comments and approves through the
API, and the approval freezes the review baseline and writes the decisions into SPEC.md (Coffee fixture).

A spec must not claim "no product owner answers" and drop accepted proposals; every decision lands in SPEC.md,
written by the platform.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace

FIXTURES = Path(__file__).parent / "fixtures/spec_studio/caf44"
SPEC = "coffee/flutter/claude/SPEC.md"


def _definition() -> dict:
    phase = copy.deepcopy(PHASE)
    phase["output"] = "spec_studio"
    phase["tool_policy"]["allowlist"].append("submit_spec_studio")
    phase["workflow_contract"]["checks"] = [{"type": "tool_called", "params": {"tools": ["submit_spec_studio"]},
                                             "blocking": True, "description": "Spec Studio recorded"}]
    return {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "draft", "type": "phase", "label": "Draft", "config": phase},
        {"id": "decisions", "type": "user_confirmation", "label": "Approve the spec", "config": {"subject": "decisions"}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
        {"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}},
    ], "edges": [
        {"id": "a", "source_node_id": "start", "target_node_id": "draft"},
        {"id": "b", "source_node_id": "draft", "target_node_id": "decisions"},
        {"id": "c", "source_node_id": "decisions", "target_node_id": "done", "when": "confirmed"},
        {"id": "d", "source_node_id": "decisions", "target_node_id": "draft", "when": "changed", "kind": "loop",
         "max_iterations": 3},
        {"id": "e", "source_node_id": "decisions", "target_node_id": "stopped", "when": "stopped"},
    ]}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _working_copy(tmp_path: Path) -> Path:
    (tmp_path / "coffee/flutter/claude").mkdir(parents=True)
    shutil.copy(FIXTURES / "SPEC.md", tmp_path / SPEC)
    _git(tmp_path, "init", "-q")
    return tmp_path


async def _waiting_run(db, tmp_path: Path):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition()), session=session,
                          project_id=workspace_id)
    run.context = {**dict(run.context or {}), "local_path": str(_working_copy(tmp_path))}
    raw = json.loads((FIXTURES / "studio.json").read_text(encoding="utf-8"))
    answer = await submit_output(db, run, "submit_spec_studio", raw, principal=admin, session_id=session.id)
    assert (answer["state"], answer["version"], answer["open_points"]) == ("recorded", 1, [])
    resolution = await run_turn_resolution(db, session, user_message="Write the spec.")
    await phase_turn(db, session.id, resolution, ["submit_spec_studio"])
    assert run.node_state["waiting"]["subject"] == "decisions"
    # The independent review reviewed this tree; the push sends exactly it (platform/scm.push).
    _git(tmp_path, "add", "-A")
    run.context = {**dict(run.context or {}), "review": {"tree": _git(tmp_path, "write-tree"), "verdict": "pass"}}
    await db.commit()
    return run


@pytest.mark.asyncio
async def test_the_product_owner_decides_comments_and_approves_and_spec_md_carries_every_decision(
        client, auth_headers, db, tmp_path):
    from app.services.observability import agent_metrics

    agent_metrics.reset()
    run = await _waiting_run(db, tmp_path)
    url = f"/api/v1/workflow-runs/{run.id}/spec-studio"
    studio = (await client.get(url, headers=auth_headers)).json()
    assert studio["awaiting_approval"] is True and studio["open_points"] == []
    # The run card offers the Studio (desktop run bar and phone run page).
    card = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    assert card["spec_studio"] == {"version": 1, "open_points": 0, "frozen": False, "approved": 0}
    assert [s["id"] for s in studio["artefact"]["screens"]] == ["today", "beans", "brew", "filter", "gear"]

    for change in ({"op": "answer", "question": "purge", "value": "24"},
                   {"op": "design", "theme": "light", "key": "accent", "value": "#7A3F20"},
                   {"op": "comment.add", "screen": "today", "device": "phone", "x": 120, "y": 812,
                    "element": "Bohnen", "path": "nav.beans", "text": "nicht Namen sondern Icons"}):
        response = await client.patch(url, headers=auth_headers, json=change)
        assert response.status_code == 200, response.text
    refused = await client.patch(url, headers=auth_headers, json={"op": "answer", "question": "x", "value": "y"})
    assert refused.status_code == 422

    approved = await client.post(f"{url}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["frozen"] is True and body["status"] != "waiting"
    spec = (tmp_path / SPEC).read_text(encoding="utf-8")
    assert "### Spec Studio decisions (v1, approved by" in spec
    assert "`purgeIdleHours` – Ab wie langer Pause" in spec and "Nach 24 Stunden (proposal was Nach 2 Stunden)" in spec
    assert "`hardnessUnit` – Einheit für die Wasserhärte? → °fH (proposal accepted)." in spec
    assert "`accent` (light): #7A3F20" in spec and "| `accent` | #7A3F20 | #E0A06A |" in spec
    assert "Comment on Heute, 390 px at “Bohnen” (`nav.beans`): nicht Namen sondern Icons" in spec
    # Inside the spec's own Decisions section, after its 15 decisions, before the open questions.
    assert spec.index("15. Annahmen") < spec.index("Spec Studio decisions") < spec.index("## 9 Offene Fragen")
    approved_app = json.loads((tmp_path / "coffee/flutter/claude/spec-studio.json").read_text(encoding="utf-8"))
    assert approved_app["design"]["directions"][0]["light"]["accent"] == "#7A3F20"

    await db.refresh(run)
    review = run.context["review"]
    assert review["studio_writeback"]["files"] == [SPEC, "coffee/flutter/claude/spec-studio.json"]
    _git(tmp_path, "add", "-A")
    assert review["tree"] == _git(tmp_path, "write-tree") != review["studio_writeback"]["reviewed_tree"]
    baseline = (await client.get(f"{url}/baseline", headers=auth_headers)).json()
    assert len(baseline["baseline"]) == 5 * 2 * 2
    assert baseline["baseline"][0] == {
        "name": "today-390-light", "screen": "today", "viewport": {"width": 390, "height": 844}, "theme": "light",
        "data": "filled", "url": f"/chat?area=work&work_view=spec_studio&run_id={run.id}&render=today&device=phone"
                                 "&theme=light&data=filled&version=1", "path": "/"}
    assert baseline["approved"]["who"] and baseline["approved"]["how"] == "product_owner"
    events = (await client.get(f"/api/v1/workflow-runs/{run.id}/events", headers=auth_headers)).json()
    kinds = [event["kind"] for event in events["events"]]
    assert kinds.count("spec_studio_changed") == 3 and "spec_studio_approved" in kinds
    # Counted in-process at the event, never from the database.
    metrics = [line for line in agent_metrics.render() if line.startswith("octryx_spec_studio_events_total{")]
    assert any('event="changed"' in line and 'kind="comment.add"' in line and float(line.rsplit(" ", 1)[1]) == 1
               for line in metrics)
    assert any('event="approved"' in line and 'kind="product_owner"' in line for line in metrics)


@pytest.mark.asyncio
async def test_open_points_block_approval_and_a_revision_carries_every_change_to_the_draft(
        client, auth_headers, db, tmp_path):
    run = await _waiting_run(db, tmp_path)
    url = f"/api/v1/workflow-runs/{run.id}/spec-studio"
    await client.patch(url, headers=auth_headers, json={"op": "rule", "rule": "R10", "param": "ratio", "value": "15"})
    await client.patch(url, headers=auth_headers, json={"op": "acceptance", "id": "AC-3", "verdict": "change",
                                                         "note": "Mein V60 läuft mit 1:15"})
    blocked = await client.post(f"{url}/approve", headers=auth_headers)
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "spec_open_points"
    assert "## Decisions" not in (tmp_path / SPEC).read_text(encoding="utf-8")

    revised = await client.post(f"{url}/revise", headers=auth_headers)
    assert revised.status_code == 200, revised.text
    await db.refresh(run)
    assert run.current_node_id == "draft"
    answer = run.context["po_answers"][-1]["text"]
    assert "Rule R10: set `ratio` to 15 and recompute its worked examples." in answer
    assert "AC-3 must change: Mein V60 läuft mit 1:15." in answer
    assert "`purgeIdleHours`" in answer and "Nach 2 Stunden (proposal accepted)" in answer


@pytest.mark.asyncio
async def test_a_spec_confirmed_without_a_person_still_writes_its_decisions_before_the_push(db, tmp_path):
    from app.services.workflow_runs.spec_studio.hooks import agent_open_points, before_push, note_open_points

    run = await _waiting_run(db, tmp_path)
    assert agent_open_points(run) == []
    await before_push(db, run)
    await before_push(db, run)  # once per artefact version: a retried push writes nothing twice
    spec = (tmp_path / SPEC).read_text(encoding="utf-8")
    assert spec.count("approved by the platform (auto-accepted)") == 1
    assert "`purgeIdleHours` – Ab wie langer Pause soll die App das Vorab-Mahlen (Totraum) empfehlen? → Nach 2 " \
           "Stunden (proposal accepted)." in spec
    entry = run.context["spec_studio"]["approved"][-1]
    assert (entry["how"], entry["approved_by"], entry["open_points"]) == ("auto_accepted", None, [])

    # Open points the agent can fix reach it as an answer (the auto-accept sends the spec back with them).
    note_open_points(run, [{"section": "rules", "target": "R1", "text": "R1: add one realistic example."}])
    assert run.context["po_answers"][-1]["text"].endswith("- R1: add one realistic example.")
