"""The system tests' screenshots on the decision card: a run reader lists the current
pass's screenshots and reads one by its name; nobody else sees them, and a name never reaches outside the folder."""

from __future__ import annotations

import os
import time

import pytest

from app.models import User
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_member, seed_outsider, seed_workspace
from tests.phased_workflow_fixtures import publish_phased
from tests.policy_engine_support import bearer
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]

DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Ship?", "config": {"subject": "decisions"}},
              {"id": "review", "type": "review", "label": "Review", "config": {"phase": "implement", "screens": True}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "r0", "source_node_id": "go", "target_node_id": "review", "when": "confirmed"},
              {"id": "r3", "source_node_id": "review", "target_node_id": "done"},
              {"id": "r1", "source_node_id": "go", "target_node_id": "blocked", "when": "changed"},
              {"id": "r2", "source_node_id": "go", "target_node_id": "blocked", "when": "stopped"}],
}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff" + b"\x00" * 16


async def _run(db, tmp_path):
    workspace_id = await seed_workspace(db)
    requester = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="member"))
    outsider = await db.get(User, await seed_outsider(db))
    run = await start_run(db, user=requester, workflow_key=await publish_phased(db, DEFINITION),
                          project_id=workspace_id, session=await new_chat_session(db, requester, workspace_id))
    (tmp_path / ".git").mkdir()
    run.context = {**dict(run.context or {}), "local_path": str(tmp_path)}
    await db.commit()
    return run, requester, outsider


def _pass(tmp_path, node_id: str, files: dict[str, bytes], *, age: float = 0) -> None:
    folder = tmp_path / ".git" / "octryx-screens" / node_id
    folder.mkdir(parents=True)
    (folder / ".entry").write_text("1")
    for name, data in files.items():
        (folder / name).write_bytes(data)
    stamp = time.time() - age
    os.utime(folder, (stamp, stamp))


async def test_a_reader_lists_the_last_pass_and_reads_one_screenshot(client, db, tmp_path):
    run, requester, _ = await _run(db, tmp_path)
    _pass(tmp_path, "review", {"old.png": PNG})
    _pass(tmp_path, "build", {"other.png": PNG}, age=600)
    _pass(tmp_path, "implement", {"recipe-list.png": PNG, "cart.jpg": JPEG, "notes.txt": b"not an image"})
    listed = await client.get(f"/api/v1/workflow-runs/{run.id}/screens", headers=bearer(requester.id))
    assert listed.status_code == 200, listed.text
    assert listed.json()["screens"] == [
        {"name": "cart.jpg", "media_type": "image/jpeg", "size": len(JPEG), "node_id": "implement"},
        {"name": "recipe-list.png", "media_type": "image/png", "size": len(PNG), "node_id": "implement"}]
    one = await client.get(f"/api/v1/workflow-runs/{run.id}/screens/recipe-list.png", headers=bearer(requester.id))
    assert one.status_code == 200 and one.content == PNG
    assert one.headers["content-type"] == "image/png" and one.headers["x-content-type-options"] == "nosniff"
    missing = await client.get(f"/api/v1/workflow-runs/{run.id}/screens/old.png", headers=bearer(requester.id))
    assert missing.status_code == 404
    other = await client.get(f"/api/v1/workflow-runs/{run.id}/screens/other.png", headers=bearer(requester.id))
    assert other.status_code == 404


async def test_a_server_run_lists_the_working_copy_folder(client, db, tmp_path):
    run, requester, _ = await _run(db, tmp_path)
    folder = tmp_path / "test-reports" / "screenshots"
    folder.mkdir(parents=True)
    (folder / "home.png").write_bytes(PNG)
    listed = (await client.get(f"/api/v1/workflow-runs/{run.id}/screens", headers=bearer(requester.id))).json()
    assert listed["screens"] == [{"name": "home.png", "media_type": "image/png", "size": len(PNG),
                                  "node_id": "implement"}]


async def test_a_run_without_screenshots_lists_none(client, db, tmp_path):
    run, requester, _ = await _run(db, tmp_path)
    listed = await client.get(f"/api/v1/workflow-runs/{run.id}/screens", headers=bearer(requester.id))
    assert listed.status_code == 200 and listed.json() == {"screens": []}


async def test_someone_outside_the_workspace_sees_no_screenshot(client, db, tmp_path):
    run, _, outsider = await _run(db, tmp_path)
    _pass(tmp_path, "implement", {"recipe-list.png": PNG})
    listed = await client.get(f"/api/v1/workflow-runs/{run.id}/screens", headers=bearer(outsider.id))
    one = await client.get(f"/api/v1/workflow-runs/{run.id}/screens/recipe-list.png", headers=bearer(outsider.id))
    assert listed.status_code == 404 and one.status_code == 404
    assert listed.json()["detail"]["code"] == "unknown_run"


@pytest.mark.parametrize("name", ["..", ".entry", "..%2F..%2Fsecret.png", "%2E%2E", "..%5Csecret.png",
                                  "a%5C..%5Csecret.png"])
async def test_a_name_never_leaves_the_screenshot_folder(client, db, tmp_path, name):
    run, requester, _ = await _run(db, tmp_path)
    _pass(tmp_path, "implement", {"recipe-list.png": PNG})
    (tmp_path / "secret.png").write_bytes(PNG)
    (tmp_path / ".git" / "secret.png").write_bytes(PNG)
    refused = await client.get(f"/api/v1/workflow-runs/{run.id}/screens/{name}", headers=bearer(requester.id))
    assert refused.content != PNG and not refused.headers.get("content-type", "").startswith("image/")
    if name != "..":
        assert refused.status_code in (400, 404)


async def test_a_dotted_or_backslashed_name_is_refused_before_any_lookup(client, db, tmp_path):
    run, requester, _ = await _run(db, tmp_path)
    for name in (".entry", "a%5Cb.png"):
        refused = await client.get(f"/api/v1/workflow-runs/{run.id}/screens/{name}", headers=bearer(requester.id))
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "invalid_name"


async def test_a_new_entry_of_the_phase_shows_only_its_own_screenshots(client, db, tmp_path):
    from app.services.workflow_runs.review.screens import store

    run, requester, _ = await _run(db, tmp_path)
    assert store(run, node_id="implement", entry=1, name="round-1.png", data=PNG) == ""
    assert store(run, node_id="implement", entry=2, name="round-2.png", data=PNG) == ""
    listed = (await client.get(f"/api/v1/workflow-runs/{run.id}/screens", headers=bearer(requester.id))).json()
    assert [item["name"] for item in listed["screens"]] == ["round-2.png"]


def test_a_device_run_without_a_server_copy_keeps_its_screens_in_the_data_folder(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.config import get_settings
    from app.services.workflow_runs.review.screens import collect, store

    monkeypatch.setattr(get_settings(), "artifact_store_dir", str(tmp_path / "data" / "artifacts"))
    run = SimpleNamespace(id="run-1", context={"local_path": "/Volumes/data/bench/coffee-claude-demo"})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    assert store(run, node_id="hands_on", entry=3, name="hands-on-s1-failed.png", data=png) == ""
    assert (tmp_path / "data" / "run-screens" / "run-1" / "hands_on" / "hands-on-s1-failed.png").is_file()
    assert [screen.name for screen in collect(run, "hands_on")] == ["hands-on-s1-failed.png"]
