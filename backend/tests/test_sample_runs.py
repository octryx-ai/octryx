"""Sample runs: one real run, shaped like one from the shared stack, exported to a bundle and imported into
the demo with a "Sample run" badge."""

from __future__ import annotations

import json
import shutil
import sys
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import (
    DeviceJob,
    DeviceJobEvent,
    FlowDefinition,
    FlowDefinitionVersion,
    Message,
    Project,
    Session,
    ToolCall,
    TurnTrace,
    TurnTraceSummary,
    UsageEvent,
    User,
    UserDevice,
    WorkflowHandoff,
    WorkflowRun,
    WorkflowRunDecision,
    WorkflowRunEvent,
    WorkflowRunSession,
    WorkItem,
)
from app.time_utils import utc_now

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
import run_bundle  # noqa: E402

pytestmark = pytest.mark.asyncio

PERSON = {"username": "jane.roe", "email": "jane.roe@corp.example", "display_name": "Jane Roe"}


def _id() -> str:
    return str(uuid.uuid4())


async def _user(db, username: str, **extra) -> User:
    user = User(id=_id(), username=username, email=extra.pop("email", f"{username}@example.invalid"),
                password_hash="x", **extra)
    db.add(user)
    await db.flush()
    return user


async def _workspace(db, name: str, owner: User, key: str = "OCX-1") -> tuple[Project, WorkItem]:
    project = Project(id=_id(), name=name)
    db.add(project)
    await db.flush()
    item = WorkItem(id=_id(), project_id=project.id, source_key=key, source_instance=name,
                    title="Discount is subtracted as an amount")
    db.add(item)
    await db.flush()
    return project, item


async def _source_run(db) -> dict:
    person = await _user(db, PERSON["username"], email=PERSON["email"], display_name=PERSON["display_name"])
    bot = await _user(db, "pr-review-bot", account_type="bot")
    project, item = await _workspace(db, "Source Workspace", person)
    flow = FlowDefinition(id=_id(), key="team-delivery", name="Team delivery", created_by=person.id)
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(id=_id(), flow_id=flow.id, version=3, created_by=person.id)
    db.add(version)
    await db.flush()
    start = utc_now() - timedelta(days=3)
    run = WorkflowRun(id=_id(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                      title="OCX-1 Discount is subtracted as an amount", flow_definition_version_id=version.id,
                      work_item_id=item.id, ticket_key="OCX-1", repository="github:demo/demo-shop",
                      branch="octryx/ocx-1", status="completed", outcome="delivered", requested_by=person.id,
                      responsible_user_id=person.id, created_at=start, completed_at=start + timedelta(minutes=40),
                      pull_request={"number": 7, "url": "http://127.0.0.1:24264/demo/demo-shop/pull/7"},
                      context={"folder": f"/Users/{PERSON['username']}/work/demo-shop", "note": "by Jane Roe",
                               "target": {"device_name": "lab-mac-07", "folder": "/srv/agents/lab/demo-shop",
                                          "device_id": "dev_" + "a" * 16}})
    child = WorkflowRun(id=_id(), project_id=project.id, workflow_kind="steps", workflow_key="implement",
                        title="Implement", parent_run_id=run.id, status="completed", requested_by=person.id,
                        created_at=start + timedelta(minutes=5))
    review = WorkflowRun(id=_id(), project_id=project.id, workflow_kind="steps", workflow_key="pr-review-bot",
                         title="Review PR #7", repository=run.repository, branch=run.branch, status="completed",
                         requested_by=bot.id, created_at=start + timedelta(minutes=35))
    other = WorkflowRun(id=_id(), project_id=project.id, workflow_kind="steps", workflow_key="team-delivery",
                        title="Someone else's run", status="completed", requested_by=person.id, created_at=start)
    db.add_all([run, child, review, other])
    await db.flush()
    main = Session(id=_id(), user_id=person.id, project_id=project.id, started_at=start,
                   metadata_={"gateway_profile": "seat", "gateway_session_key": "gsk-1", "oauth_grant_id": "grant-1",
                              "hook_key_enc": "fernet:not-for-the-demo", "launcher_state_root": "/opt/launch/x"})
    db.add(main)
    await db.flush()
    sub = Session(id=_id(), user_id=person.id, project_id=project.id, parent_session_id=main.id, started_at=start)
    db.add(sub)
    await db.flush()
    db.add_all([WorkflowRunSession(run_id=run.id, session_id=main.id, role="main", runtime="octryx_claude"),
                WorkflowRunSession(run_id=child.id, session_id=sub.id, role="child")])
    message = Message(id=_id(), session_id=main.id, role="assistant", content="Fixed the discount, Jane.")
    db.add(message)
    await db.flush()
    trace = TurnTrace(id=_id(), session_id=main.id, message_id=message.id, model="sonnet",
                      input_messages_json=[{"role": "system", "content": "the whole prompt"}],
                      context_snapshot_json={"prompt": "context"}, raw_output={"text": "done"})
    db.add(trace)
    await db.flush()
    device = UserDevice(id="dev_" + "a" * 16, owner_user_id=person.id, name="jane-laptop", name_key="jane-laptop",
                        os="macos", public_key="pk", folders=[], profiles=[])
    db.add(device)
    await db.flush()
    job = DeviceJob(id="dj_" + "b" * 16, device_id=device.id, owner_user_id=person.id, session_id=main.id,
                    workspace_id=project.id, folder=f"/Users/{PERSON['username']}/work/demo-shop", profile="edit",
                    status="closed", cost_usd=Decimal("0.42"))
    db.add(job)
    await db.flush()
    db.add_all([
        ToolCall(id=_id(), session_id=main.id, message_id=message.id, tool_name="Edit", status="success"),
        TurnTraceSummary(trace_id=trace.id, session_id=main.id, run_key=f"run:{run.id}", outcome="ok",
                         created_at=start),
        UsageEvent(id=_id(), session_id=main.id, user_id=person.id, provider="anthropic", model="sonnet",
                   tokens_in=1000, tokens_out=200, cost=Decimal("0"), list_cost=Decimal("0.42"),
                   cost_source="seat", created_at=start),
        DeviceJobEvent(job_id=job.id, seq=1, type="turn", body={"text": "editing shop/pricing.py"}),
        DeviceJobEvent(job_id=job.id, seq=2, type="done", body={}),
        WorkflowRunEvent(run_id=run.id, kind="phase_done", node_id="implement", detail={"run": child.id},
                         actor_id=person.id),
        WorkflowRunEvent(run_id=run.id, kind="note", detail={"link": f"http://localhost:24260/work/runs/{run.id}"}),
        WorkflowRunDecision(run_id=run.id, kind="confirmation", action="approve", decided_by=person.id),
        WorkflowHandoff(id=_id(), parent_run_id=run.id, child_run_id=child.id, receiver_session_id=sub.id,
                        parent_node_id="implement", parent_entry=1, parent_state_version=1,
                        parent_version_id=version.id, child_descriptor={}, workspace_id=project.id,
                        requested_by=person.id, target_kind="role",
                        target_key="implement", contract={}, envelopes={}, acceptance="all", payload_hash="h",
                        expires_at=start + timedelta(days=1)),
    ])
    await db.flush()
    return {"run": run, "child": child, "review": review, "other": other, "person": person, "bot": bot}


async def _demo(db, auth_user) -> tuple[Project, WorkItem]:
    project, item = await _workspace(db, "Demo Shop", auth_user)
    return project, item


def _factory(db):
    class Shared:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_exc):
            return False

    return Shared


@pytest.fixture
def demo_switch(monkeypatch):
    monkeypatch.setenv("OCTRYX_DEMO", "1")


async def _bundle(db) -> tuple[dict, dict]:
    source = await _source_run(db)
    collected = await run_bundle.collect(db, source["run"].id)
    bundle = {"format": run_bundle.FORMAT, "version": run_bundle.VERSION, "sample": True, "id": _id(),
              **collected, "pull": None}
    return source, run_bundle.sanitize(bundle, github="http://127.0.0.1:24264", app_base="http://localhost:24260")


# ---- export ----------------------------------------------------------------------------------------------------------

async def test_the_export_takes_the_run_its_children_its_review_and_what_hangs_off_them(db):
    source, bundle = await _bundle(db)
    tables = bundle["tables"]
    assert {row["id"] for row in tables["workflow_runs"]} == {source[k].id for k in ("run", "child", "review")}
    counts = {table: len(rows) for table, rows in tables.items() if rows}
    assert counts == {"sessions": 2, "workflow_runs": 3, "workflow_run_sessions": 2, "workflow_run_events": 2,
                      "workflow_run_decisions": 1, "workflow_handoffs": 1, "messages": 1, "tool_calls": 1,
                      "turn_traces": 1, "turn_trace_summaries": 1, "usage_events": 1, "device_jobs": 1,
                      "device_job_events": 2}


async def test_the_export_carries_no_person_no_home_folder_no_prompt_and_no_stack_url(db):
    _source, bundle = await _bundle(db)
    text = run_bundle.dumps(bundle)
    for word in ("jane", "Jane", "Roe", "corp.example", "/Users/", "127.0.0.1:24264", "localhost:24260", "the whole prompt",
                 "lab-mac-07", "/srv/agents", "/work/demo-shop", "gsk-1", "grant-1", "fernet:", "/opt/launch",
                 "hook_key_enc", "gateway_session_key", "oauth_grant_id", "launcher_state_root"):
        assert word not in text, word
    assert run_bundle.GIT_BASE in text and run_bundle.APP_BASE in text and "/home/demo/demo-shop" in text
    assert bundle["tables"]["workflow_runs"][0]["context"]["target"] == {
        "device_name": run_bundle.DEVICE_NAME, "folder": "/home/demo/demo-shop",
        "device_id": run_bundle.DEVICE_PLACEHOLDER}
    assert "dev_" + "a" * 16 not in text  # the recording machine's id, in a column or inside JSON
    trace = bundle["tables"]["turn_traces"][0]
    assert trace["input_messages_json"] == [] and trace["context_snapshot_json"] == {}
    assert trace["raw_output"] == {"text": "done"}  # the answer stays
    assert any(user["account_type"] == "bot" and user["username"] == "pr-review-bot"
               for user in bundle["references"]["users"].values())


def test_a_names_replacement_is_word_bound():
    change = run_bundle.replacer({"ann": "demo"}, words=True)
    assert change("ann wrote to ann.lee and planned an annex; Ann agreed") == \
        "demo wrote to ann.lee and planned an annex; demo agreed"


def test_the_check_refuses_a_secret_and_a_too_big_bundle():
    assert run_bundle.check('{"ok": "nothing"}') == []
    assert any("secret" in problem for problem in run_bundle.check('{"key": "ghp_' + "a" * 36 + '"}'))
    assert any("bytes" in problem for problem in run_bundle.check("x" * (run_bundle.MAX_BYTES + 1)))
    assert any("hook_key_enc" in problem for problem in run_bundle.check('{"hook_key_enc": "fernet:x"}'))
    assert any("oauth_grant_id" in problem for problem in run_bundle.check('{"oauth_grant_id": "g"}'))
    assert any("device" in problem for problem in run_bundle.check('{"device_id": "dev_0123456789abcdef"}'))
    assert run_bundle.check('{"device_id": "' + run_bundle.DEVICE_PLACEHOLDER + '"}') == []


# ---- import: only in the demo ----------------------------------------------------------------------------------------

def test_the_import_refuses_outside_the_demo(monkeypatch):
    monkeypatch.delenv("OCTRYX_DEMO", raising=False)
    with pytest.raises(SystemExit, match="outside the demo"):
        run_bundle.require_demo("import")
    monkeypatch.setenv("OCTRYX_DEMO", "yes")
    with pytest.raises(SystemExit, match="outside the demo"):
        run_bundle.require_demo("import")


def test_the_import_refuses_a_production_runtime(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("OCTRYX_DEMO", "1")
    monkeypatch.setattr(get_settings(), "runtime_profile", "production")
    with pytest.raises(SystemExit, match="runtime profile 'production'"):
        run_bundle.require_demo("import")
    monkeypatch.setattr(get_settings(), "runtime_profile", "staging")
    run_bundle.require_demo("import")


async def test_the_cli_import_refuses_before_reading_anything(monkeypatch, tmp_path):
    monkeypatch.delenv("OCTRYX_DEMO", raising=False)
    with pytest.raises(SystemExit, match="outside the demo"):
        run_bundle.main(["import", str(tmp_path / "missing.json")])


async def test_the_export_refuses_outside_the_demo_before_opening_its_maintenance_session(monkeypatch):
    from app.config import get_settings
    from app.services.data_access import viewer as viewer_module

    def opened(*_args, **_kwargs):
        raise AssertionError("no platform_maintenance session outside the demo")

    monkeypatch.setattr(viewer_module, "platform_maintenance", opened)
    monkeypatch.setattr("app.services.data_access.platform_maintenance", opened)
    monkeypatch.delenv("OCTRYX_DEMO", raising=False)
    with pytest.raises(SystemExit, match="refusing to export a sample run outside the demo"):
        await run_bundle.export(_id())
    monkeypatch.setenv("OCTRYX_DEMO", "1")
    monkeypatch.setattr(get_settings(), "runtime_profile", "production")
    with pytest.raises(SystemExit, match="refusing to export a sample run in the runtime profile 'production'"):
        await run_bundle.export(_id())


# ---- import ----------------------------------------------------------------------------------------------------------

async def _imported(db, auth_user) -> tuple[dict, dict, str]:
    source, bundle = await _bundle(db)
    await _demo(db, auth_user)
    new = await run_bundle.import_bundle(json.loads(run_bundle.dumps(bundle)), workspace="Demo Shop",
                                         github="http://127.0.0.1:8434", session_factory=_factory(db))
    return source, bundle, new


async def test_the_import_writes_the_run_as_a_sample_with_new_ids_and_its_references_remapped(
        db, auth_user, demo_switch):
    source, bundle, new = await _imported(db, auth_user)
    from app.services.workflow_runs.views import is_sample

    run = await db.get(WorkflowRun, new)
    runs = [item for item in (await db.execute(select(WorkflowRun))).scalars()
            if dict(item.context or {}).get("sample_bundle") == bundle["id"]]
    imported_sessions = [link.session_id for link in (await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.run_id.in_([item.id for item in runs])))).scalars()]
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.session_id.in_(imported_sessions)))).scalars().all()
    summaries = (await db.execute(select(TurnTraceSummary).where(
        TurnTraceSummary.session_id.in_(imported_sessions)))).scalars().all()
    project = (await db.execute(select(Project).where(Project.name == "Demo Shop"))).scalar_one()
    item = (await db.execute(select(WorkItem).where(WorkItem.project_id == project.id))).scalar_one()
    assert run is not None and run.id != source["run"].id and is_sample(run)
    assert not is_sample(source["run"])
    assert run.title == "Sample run: OCX-1 Discount is subtracted as an amount"
    assert (run.project_id, run.work_item_id, run.requested_by) == (project.id, item.id, auth_user.id)
    assert run.status == "completed" and run.ticket_key == "OCX-1"
    assert run.flow_definition_version_id is not None  # the same flow, found by its key
    assert run.context["folder"] == "/home/demo/demo-shop" and run.context["note"] == "by demo"
    assert run.pull_request["url"] == "http://127.0.0.1:8434/demo/demo-shop/pull/7"
    assert abs((run.completed_at - utc_now()).total_seconds()) < 120  # moved so it ends now
    assert len(runs) == 3 and all(is_sample(item) for item in runs)
    assert sum(1 for item in runs if item.title.startswith("Sample run: ")) == 1
    review = next(item for item in runs if item.workflow_key == "pr-review-bot")
    assert review.requested_by == source["bot"].id  # a bot keeps its own account
    child = next(item for item in runs if item.workflow_key == "implement")
    assert child.parent_run_id == run.id
    assert len(usage) == 1 and usage[0].list_cost == Decimal("0.42") and usage[0].user_id == auth_user.id
    assert len(summaries) == 1 and summaries[0].run_key == f"run:{run.id}"
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars().all()
    details = sorted((event.detail for event in events), key=json.dumps)
    assert details == sorted([{"run": child.id}, {"link": f"http://127.0.0.1:8000/work/runs/{run.id}"}],
                             key=json.dumps)  # an id inside JSON follows its row; the stack's URL becomes this one
    sessions = (await db.execute(select(WorkflowRunSession).where(WorkflowRunSession.run_id == run.id))).scalars()
    main_session = await db.get(Session, next(iter(sessions)).session_id)
    assert main_session.user_id == auth_user.id and main_session.project_id == project.id
    message = (await db.execute(select(Message).where(Message.session_id == main_session.id))).scalar_one()
    assert message.content == "Fixed the discount, demo."
    assert (await db.execute(select(func.count()).select_from(ToolCall).where(
        ToolCall.session_id == main_session.id))).scalar() == 1


async def test_the_seat_job_runs_on_a_revoked_placeholder_device(db, auth_user, demo_switch):
    _source, _bundle_, _new = await _imported(db, auth_user)
    device = (await db.execute(select(UserDevice).where(UserDevice.name == run_bundle.DEVICE_NAME))).scalar_one()
    assert device.owner_user_id == auth_user.id and device.status == "revoked" and device.revoked_at is not None
    job = (await db.execute(select(DeviceJob).where(DeviceJob.device_id == device.id))).scalar_one()
    assert job.folder == "/home/demo/demo-shop" and job.owner_user_id == auth_user.id
    events = (await db.execute(select(DeviceJobEvent).where(DeviceJobEvent.job_id == job.id)
                               .order_by(DeviceJobEvent.seq))).scalars().all()
    assert [event.seq for event in events] == [1, 2]
    run = await db.get(WorkflowRun, _new)
    assert run.context["target"]["device_id"] == device.id  # a device inside JSON points at the same placeholder


async def test_a_bundle_is_imported_once(db, auth_user, demo_switch):
    _source, bundle, first = await _imported(db, auth_user)
    again = await run_bundle.import_bundle(json.loads(run_bundle.dumps(bundle)), workspace="Demo Shop",
                                           github="http://127.0.0.1:8434", session_factory=_factory(db))
    assert first and again is None


# ---- the run views ---------------------------------------------------------------------------------------------------











async def test_the_run_views_show_the_sample_with_its_flag(client, auth_headers, db, auth_user, demo_switch):
    _source, _bundle_, new = await _imported(db, auth_user)
    listed = (await client.get("/api/v1/workflow-runs?view=work", headers=auth_headers)).json()["runs"]
    row = next(item for item in listed if item["id"] == new)
    assert row["sample"] is True and row["title"].startswith("Sample run: ")
    samples = {item["id"] for item in listed if item["sample"]}
    assert len(samples) == 3 and new in samples  # the run, its child and its review run
    assert {item["title"] for item in listed if not item["sample"]} >= {"Someone else's run", "Implement"}
    detail = (await client.get(f"/api/v1/workflow-runs/{new}", headers=auth_headers)).json()["run"]
    assert detail["sample"] is True
    events = await client.get(f"/api/v1/workflow-runs/{new}/events", headers=auth_headers)
    assert events.status_code == 200


# ---- the pull request on the fake GitHub -----------------------------------------------------------------------------

def _serve(root: Path):
    from http.server import ThreadingHTTPServer

    fake = run_bundle._load_module(BACKEND.parent / "deployment" / "demo" / "fake_github.py", "bundle_fake_github")
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.make_handler(fake.Store(root, "http://unset/api/v3")))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    server.RequestHandlerClass = fake.make_handler(fake.Store(root, f"{url}/api/v3"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, url


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_pull_request_is_replayed_with_its_commits_review_and_status(tmp_path):
    source, source_url = _serve(tmp_path / "source")
    target, target_url = _serve(tmp_path / "target")
    try:
        files = {"README.md": "# Demo Shop\n", "shop/pricing.py": "def total(x):\n    return x - 5\n"}
        for url in (source_url, target_url):
            run_bundle._http("POST", f"{url}/_fake/repos", {"owner": "demo", "repo": "demo-shop", "files": files})
        work = tmp_path / "work"
        run_bundle._git("clone", "-q", f"{source_url}/demo/demo-shop.git", str(work))
        run_bundle._git("checkout", "-q", "-b", "octryx/ocx-1", cwd=work)
        (work / "shop" / "pricing.py").write_text("def total(x):\n    return x * 0.95\n")
        run_bundle._git("commit", "-qam", "Fix the discount", cwd=work,
                        env={"GIT_AUTHOR_NAME": "Jane Roe", "GIT_AUTHOR_EMAIL": PERSON["email"],
                             "GIT_COMMITTER_NAME": "Jane Roe", "GIT_COMMITTER_EMAIL": PERSON["email"]})
        run_bundle._git("push", "-q", "origin", "octryx/ocx-1", cwd=work)
        api = f"{source_url}/api/v3/repos/demo/demo-shop"
        pull = run_bundle._http("POST", f"{api}/pulls", {"title": "OCX-1 Fix the discount", "head": "octryx/ocx-1",
                                                         "base": "main", "body": "Fixes OCX-1"})
        sha = pull["head"]["sha"]
        review = run_bundle._http("POST", f"{api}/pulls/{pull['number']}/reviews", {
            "body": f"Looks right at {sha[:7]}", "commit_id": sha,
            "comments": [{"path": "shop/pricing.py", "line": 2, "body": "Percent, good."}]})
        inline = run_bundle._http("GET", f"{api}/pulls/{pull['number']}/reviews/{review['id']}/comments")[0]
        run_bundle._http("POST", f"{api}/pulls/{pull['number']}/comments/{inline['id']}/replies", {"body": "Thanks"})
        run_bundle._http("POST", f"{api}/issues/{pull['number']}/comments", {"body": "Summary: fixed"})
        run_bundle._http("POST", f"{api}/statuses/{sha}", {"state": "success", "context": "octryx/review",
                                                          "description": "No findings",
                                                          "target_url": f"{source_url}/x"})

        recorded = run_bundle.export_pull(source_url, "demo/demo-shop", "octryx/ocx-1")
        bundle = run_bundle.sanitize({"references": {"users": {}, "projects": {}}, "pull": recorded},
                                     github=source_url)
        assert "Jane" not in json.dumps(bundle) and source_url not in json.dumps(bundle)
        replayed = run_bundle._walk(bundle["pull"], run_bundle.replacer({run_bundle.GIT_BASE: target_url}))
        pairs = run_bundle.replay_pull(target_url, replayed)

        pulls = run_bundle._http("GET", f"{target_url}/_fake/pulls")
        assert len(pulls) == 1
        made = pulls[0]
        new_sha = made["head"]["sha"]
        assert made["number"] == 1 and made["title"] == "OCX-1 Fix the discount" and new_sha != sha
        assert pairs[sha] == new_sha and pairs[f"demo/demo-shop/pull/{pull['number']}"] == "demo/demo-shop/pull/1"
        assert [status["context"] for status in made["statuses"]] == ["octryx/review"]
        assert made["statuses"][0]["target_url"] == f"{target_url}/x"
        assert made["reviews"][0]["body"] == f"Looks right at {new_sha[:7]}"
        assert [row["body"] for row in made["review_comments"]] == ["Percent, good.", "Thanks"]
        assert made["review_comments"][1]["in_reply_to_id"] == made["review_comments"][0]["id"]
        assert [row["body"] for row in made["comments"]] == ["Summary: fixed"]
        clone = tmp_path / "check"
        run_bundle._git("clone", "-q", "-b", "octryx/ocx-1", f"{target_url}/demo/demo-shop.git", str(clone))
        assert "0.95" in (clone / "shop" / "pricing.py").read_text()
        author = run_bundle._git("log", "-1", "--format=%an <%ae>", cwd=clone).strip()
        assert author == "demo <demo@localhost.invalid>"
        run_bundle.replay_pull(target_url, replayed)  # again: the branch is there, nothing is added
        assert len(run_bundle._http("GET", f"{target_url}/_fake/pulls")) == 1
    finally:
        source.shutdown()
        target.shutdown()


# ---- the bundle the demo ships ----------------------------------------------------------------------------------------

SHIPPED = BACKEND.parent / "deployment" / "demo" / "sample-run" / "run.json"


def test_the_shipped_bundle_passes_the_check():
    assert run_bundle.check(SHIPPED.read_text(encoding="utf-8")) == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
async def test_the_shipped_bundle_imports_onto_the_demo_shop_with_its_pull_request(db, auth_user, demo_switch,
                                                                                  tmp_path):
    seed = run_bundle._load_module(BACKEND.parent / "deployment" / "demo" / "seed_demo.py", "shipped_seed_demo")
    server, url = _serve(tmp_path / "git")
    try:
        run_bundle._http("POST", f"{url}/_fake/repos", {"owner": "demo", "repo": "demo-shop", "files": seed.files()})
        project, _ = await _workspace(db, "Demo Shop", auth_user, key="OCX-2")
        new = await run_bundle.import_bundle(json.loads(SHIPPED.read_text(encoding="utf-8")), workspace="Demo Shop",
                                             github=url, session_factory=_factory(db))
        run = await db.get(WorkflowRun, new)
        item = (await db.execute(select(WorkItem).where(WorkItem.project_id == project.id))).scalar_one()
        assert run.workflow_key == "epic-delivery" and run.status == "completed"
        device = (await db.execute(select(UserDevice).where(UserDevice.name == run_bundle.DEVICE_NAME))).scalar_one()
        assert device.status == "revoked" and run_bundle.DEVICE_PLACEHOLDER not in json.dumps(run.context)
        assert dict(run.context["runtime_target"])["device_id"] == device.id  # what the UI asks the models of
        assert run.work_item_id == item.id and run.title.startswith("Sample run: ")
        pulls = run_bundle._http("GET", f"{url}/_fake/pulls")
        assert [(pull["number"], pull["state"]) for pull in pulls] == [(1, "open")]
        assert run.pull_request["url"] == f"{url}/demo/demo-shop/pull/1" and run.pull_request["id"] == "1"
        review = (await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_key == "pr-review-bot"))).scalar_one()
        assert review.title.startswith("Pull request #1: ") and review.pull_request["id"] == "1"
        assert review.context["pr_review"]["pr_id"] == "1"  # the bot's own record of the pull request it reviewed
        from app.models.runtime.secure_work import WorkPullRequest

        recorded = (await db.execute(select(WorkPullRequest))).scalars().all()
        assert [(row.pr_id, row.status, row.work_item_id, row.pr_url) for row in recorded] == [
            ("1", "open", item.id, f"{url}/demo/demo-shop/pull/1")]  # the run and its work item show it
        assert recorded[0].title == "OCX-2: Free shipping from 50.00" and recorded[0].reviewers_json == [{"name": "demo-admin"}]
        assert pulls[0]["comments"] and pulls[0]["reviews"]  # the review bot's summary and its review came along
        clone = tmp_path / "check"
        run_bundle._git("clone", "-q", "-b", pulls[0]["head"]["ref"], f"{url}/demo/demo-shop.git", str(clone))
        assert "FREE_SHIPPING_FROM" in (clone / "shop" / "pricing.py").read_text()
        page = _page(f"{url}/demo/demo-shop/pull/1")  # where the run's "Open the pull request" leads
        assert page.startswith("<!doctype html>") and "OCX-2: Free shipping from 50.00 <span>#1</span>" in page
        assert "shop/pricing.py" in page and "FREE_SHIPPING_FROM" in page  # diff stat and the folded diff
        assert "Octryx review" in page and "octryx/review" in page  # the bot's summary comment and its status
        assert "reviewed" in page and "<script" not in page
        recorded = {row["id"] for row in json.loads(SHIPPED.read_text(encoding="utf-8"))["tables"]["workflow_runs"]}
        assert not any(old in page for old in recorded) and new in page  # the PR text names the demo's runs
    finally:
        server.shutdown()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
async def test_the_seeded_sample_leaves_no_open_pull_request_on_its_work_item(db, auth_user, demo_switch, tmp_path):
    from app.models.runtime.secure_work import WorkPullRequest

    seed = run_bundle._load_module(BACKEND.parent / "deployment" / "demo" / "seed_demo.py", "closed_seed_demo")
    server, url = _serve(tmp_path / "git")
    try:
        run_bundle._http("POST", f"{url}/_fake/repos", {"owner": "demo", "repo": "demo-shop", "files": seed.files()})
        await _workspace(db, "Demo Shop", auth_user, key="OCX-2")
        bundle = seed.closed_sample(json.loads(SHIPPED.read_text(encoding="utf-8")))
        new = await run_bundle.import_bundle(bundle, workspace="Demo Shop", github=url, session_factory=_factory(db))
        pulls = run_bundle._http("GET", f"{url}/_fake/pulls")
        assert [(pull["number"], pull["state"]) for pull in pulls] == [(1, "closed")]
        assert (await db.get(WorkflowRun, new)).pull_request["state"] == "closed"
        assert [row.status for row in (await db.execute(select(WorkPullRequest))).scalars()] == ["closed"]
    finally:
        server.shutdown()


def _page(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=10) as answer:  # noqa: S310 - the test's own local fake
        assert answer.headers.get_content_type() == "text/html"
        return answer.read().decode()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_pull_request_page_escapes_what_it_shows_and_404s_an_unknown_one(tmp_path):
    import urllib.error

    server, url = _serve(tmp_path / "git")
    try:
        run_bundle._http("POST", f"{url}/_fake/repos", {"owner": "demo", "repo": "demo-shop",
                                                       "files": {"README.md": "# x\n"}})
        work = tmp_path / "work"
        run_bundle._git("clone", "-q", f"{url}/demo/demo-shop.git", str(work))
        run_bundle._git("checkout", "-q", "-b", "topic", cwd=work)
        (work / "README.md").write_text("# x <b>\n")
        run_bundle._git("commit", "-qam", "change", cwd=work, env={"GIT_AUTHOR_NAME": "demo",
                        "GIT_AUTHOR_EMAIL": "demo@localhost.invalid", "GIT_COMMITTER_NAME": "demo",
                        "GIT_COMMITTER_EMAIL": "demo@localhost.invalid"})
        run_bundle._git("push", "-q", "origin", "topic", cwd=work)
        api = f"{url}/api/v3/repos/demo/demo-shop"
        run_bundle._http("POST", f"{api}/pulls", {"title": "<script>alert(1)</script>", "head": "topic",
                                                  "base": "main", "body": "a <img src=x onerror=1> body"})
        page = _page(f"{url}/demo/demo-shop/pull/1")
        assert "<script>" not in page and "<img" not in page and "&lt;script&gt;" in page
        assert '<span class="add">+# x &lt;b&gt;</span>' in page
        with pytest.raises(urllib.error.HTTPError) as missing:
            _page(f"{url}/demo/demo-shop/pull/9")
        assert missing.value.code == 404
    finally:
        server.shutdown()


def test_renumber_follows_the_replayed_pull_request_and_leaves_other_numbers_alone():
    tables = {"workflow_runs": [
        {"title": "Pull request #2: OCX-2 shipping", "pull_request": {"id": "2", "url": "x/pull/2"},
         "context": {"pr_review": {"pr_id": "2"}, "attempt": "2"}},
        {"title": "Story / epic delivery", "pull_request": {"id": "2"}, "context": {}}],
        "workflow_run_events": [{"detail": {"pr_id": "2", "round": 2}}]}
    recorded = {"repository": "demo/demo-shop", "pull": {"number": 2}}
    rows = run_bundle.renumber(tables, recorded, {"demo/demo-shop/pull/2": "demo/demo-shop/pull/1"})
    review, main = rows["workflow_runs"]
    assert review["title"] == "Pull request #1: OCX-2 shipping" and review["pull_request"]["id"] == "1"
    assert review["context"] == {"pr_review": {"pr_id": "1"}, "attempt": "2"}
    assert main["pull_request"]["id"] == "1" and main["title"] == "Story / epic delivery"
    assert rows["workflow_run_events"][0]["detail"] == {"pr_id": "1", "round": 2}
    assert run_bundle.renumber(tables, recorded, {}) is tables  # no replay, nothing to follow
