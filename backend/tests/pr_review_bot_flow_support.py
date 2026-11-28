"""Shared helpers for the test_pr_review_bot_flow_* modules."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.models.integration.webhook import Webhook
from app.models.runtime.code_intelligence import CodeRepository
from app.services.pr_review_bot import actions as bot_actions
from app.services.pr_review_bot import webhook as bot_webhook
from app.services.pr_review_bot.settings import BotSettings, store_settings
from app.services.workflow_runs.platform import scm
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import admin_user
from tests.test_workflow_run_platform_actions import FakeTools

FIXTURES = Path(__file__).parent / "fixtures" / "pr_review_bot"


HEADERS = {"X-GitHub-Event": "pull_request"}


def _git(cwd, *args) -> str:
    done = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


def _origin(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "totals.py").write_text("def total(items):\n    subtotal = sum(items)\n    return int(subtotal)\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "-m", "init")
    _git(origin, "checkout", "-q", "-b", "feature/PAY-1-totals")
    (origin / "totals.py").write_text("def total(items):\n    subtotal = sum(items)\n    return round(subtotal)\n")
    _git(origin, "commit", "-qam", "round")
    head = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")
    _git(tmp_path, "clone", "-q", str(origin), str(tmp_path / "pay"))
    return tmp_path / "pay", head


async def _workspace(db, trigger: str = "both") -> tuple[str, CodeRepository, Webhook]:
    project = await make_project(db)
    owner = await admin_user(db)
    record = CodeRepository(project_id=project.id, name="acme/pay", provider="github", repo_root="/tmp/none",
                            config_json={})
    # The review as a required check (``gate``): these flows assert the failing status; ``inform`` is the default.
    store_settings(record, BotSettings(trigger, status_policy="gate"))
    hook = Webhook(name="PRs", project_id=project.id, owner_id=owner.id, source_type="scm_pull_request", is_active=True)
    db.add_all([record, hook])
    await db.flush()
    return project.id, record, hook


def _payload(head: str, **changes) -> dict:
    payload = json.loads((FIXTURES / "github_pull_request_synchronize.json").read_text())
    payload["pull_request"]["head"]["sha"] = head
    payload["pull_request"].update(changes)
    return payload


def _tools(monkeypatch, local_path: Path, **answers) -> FakeTools:
    tools = FakeTools(monkeypatch, {"prepare_github_repository": [{"local_path": str(local_path)}],
                                    "post_github_pull_request_review": [{"status": "posted"}], **answers})
    monkeypatch.setattr(bot_actions, "dispatch_tool", scm.dispatch_tool)
    return tools


REVIEW = {"verdict": "changes", "summary": "Round half away from zero.", "findings": [
    {"severity": "high", "file": "totals.py", "line": 3, "fix": "Use half-away-from-zero rounding.",
     "suggestion": "    return int(subtotal + 0.5)", "start_line": 3},
    {"severity": "medium", "file": "rates.py", "line": 9, "fix": "Rates must round the same way."}],
    "walkthrough": [{"file": "totals.py", "change": "Rounds instead of truncating."}]}


@pytest.fixture(autouse=True)
def _no_background(monkeypatch):
    monkeypatch.setattr(bot_webhook, "_spawn", lambda coroutine: coroutine.close())
