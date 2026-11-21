"""Shared helpers for the test_review_convergence_* modules."""

from __future__ import annotations

from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _finding(severity, file="benchmark/src/profile.js", fix="x", ident=""):
    return {"severity": severity, "file": file, "line": 3, "fix": fix, **({"id": ident} if ident else {})}


def _delivery(tmp_path, decisions: dict, review: dict | None = None):
    from tests.test_ticket_delivery import _definition as delivery

    definition = delivery()
    definition["nodes"].insert(2, {"id": "review", "type": "review", "label": "Review",
                                   "config": {"phase": "work", **(review or {})}})
    definition["nodes"][3]["config"].update({"shows": "review_verdict", "auto_accept": "review_passed",
                                             "auto_revise": 2, **decisions})
    definition["edges"][1] = {"id": "b", "source_node_id": "work", "target_node_id": "review"}
    definition["edges"].append({"id": "f", "source_node_id": "review", "target_node_id": "decisions"})
    return definition


async def _started(db, tmp_path, definition, committed: dict | None = None):
    import subprocess

    from tests.workflow_run_review_support import changed_repo

    root = tmp_path / "w"
    for name, text in (committed or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    if committed:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "apps"], cwd=root,
                       check=True)
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id, session=session)
    await db.commit()
    return run, session
