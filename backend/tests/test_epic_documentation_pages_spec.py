"""The spec page is published only from a pushed spec of the story's own folder, a story publishes the spec page its spec run could not, and what the runs write becomes workspace knowledge a backfill finds again."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services.workflow_runs.documentation import auto_grant
from app.services.workflow_runs.documentation.auto_pages import publish_feature, publish_spec
from tests.documentation_acceptance_support import PARENT
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.epic_documentation_pages_support import _events, _git, _run, _workspace

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("public_source_dns")]


@pytest.fixture
def evidence_runtime(monkeypatch):
    from app.config import get_settings
    from app.services.knowledge.runtime import set_evidence_runtime
    from tests.knowledge_evidence_runtime_support import build_runtime

    monkeypatch.setattr(get_settings(), "platform_public_origin", "https://octryx.example.test")
    runtime, _, _index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime
    finally:
        set_evidence_runtime(None)


async def test_the_spec_page_is_skipped_without_a_pushed_spec(db, monkeypatch):
    admin, project, stub, epic, _stories = await _workspace(db, monkeypatch)
    run = _run(admin, project, epic, "spec-writing", pr="7")
    db.add(run)
    await db.flush()
    outcome, route = await publish_spec(db, run, {})
    assert (route, outcome.result["reason"]) == ("skipped", "spec_unavailable")
    assert set(stub.pages) == {PARENT}
    assert auto_grant.GRANT_KEY in run.context  # the grant stands; the next step may still write under it


async def test_a_story_publishes_the_spec_page_the_spec_run_could_not(db, monkeypatch, tmp_path):
    """When spec-writing's ``publish_spec`` skips (no usable Confluence connection), nothing else publishes the spec.
    The first story with a grant lacking the spec page writes it from its branch (the spec three folders deep),
    before its feature page, which then links it."""
    admin, project, stub, epic, (s1, _s2) = await _workspace(db, monkeypatch)
    _git(tmp_path, "init", "-q")
    folder = tmp_path / "coffee" / "web" / "claude"
    folder.mkdir(parents=True)
    (folder / "SPEC.md").write_text("# Coffee\n\n## 1 Goal\n\nBeans.\n")
    (folder / "app.py").write_text("print('x')\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "story 1")
    story = _run(admin, project, s1, "epic-delivery", pr="8", context={
        "local_path": str(tmp_path), "head_sha": _git(tmp_path, "rev-parse", "HEAD")})
    db.add(story)
    await db.flush()
    _outcome, route = await publish_feature(db, story, {})
    assert route == "succeeded"
    pages = story.context["documentation_grant"]["pages"]
    spec = stub.pages[pages["spec"]["page_id"]]
    assert spec["title"].endswith("- Specification") and "Beans." in spec["body"]
    assert "coffee/web/claude/SPEC.md" in spec["body"] and "pr/8" not in spec["body"]  # not the story's PR
    assert pages["spec"]["url"] in stub.pages[pages[f"feature:{s1.source_key}"]["page_id"]]["body"]

    again = _run(admin, project, s1, "epic-delivery", after=story, pr="9", context={
        "local_path": str(tmp_path), "head_sha": _git(tmp_path, "rev-parse", "HEAD")})
    db.add(again)
    await db.flush()
    await publish_feature(db, again, {})
    assert stub.pages[pages["spec"]["page_id"]]["version"] == 1  # written once; later stories leave it


async def test_the_spec_of_the_storys_own_folder_is_the_one_published(tmp_path):
    """A repository can keep app/web/claude/SPEC.md and app/web/codex/SPEC.md side by side; a Codex story's commit
    changes no SPEC.md, so the first by name (claude) must not be published for it."""
    from types import SimpleNamespace

    from app.services.workflow_runs.documentation.spec_source import pushed_spec

    _git(tmp_path, "init", "-q")
    for engine in ("claude", "codex"):
        folder = tmp_path / "coffee" / "web" / engine
        folder.mkdir(parents=True)
        (folder / "SPEC.md").write_text(f"# {engine} spec\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "specs")
    (tmp_path / "coffee" / "web" / "codex" / "app.js").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "codex story")
    run = SimpleNamespace(context={"local_path": str(tmp_path), "head_sha": _git(tmp_path, "rev-parse", "HEAD")},
                          id="r", project_id="p", repository="", runtime_target=None)
    path, text = await pushed_spec(run)
    assert (path, text.strip()) == ("coffee/web/codex/SPEC.md", "# codex spec")


async def test_what_the_runs_write_becomes_workspace_knowledge(
        client, db, monkeypatch, tmp_path, evidence_runtime):  # client: its own sessions reach the test database
    """Knowledge first: the spec and every page a run writes are Workspace knowledge
    at once (source link, a new revision per change); a Workspace switches it off."""
    from app.models.project.knowledge_evidence import KnowledgeEvidenceSource

    admin, project, _stub, epic, (s1, _s2) = await _workspace(db, monkeypatch)
    _git(tmp_path, "init", "-q")
    (tmp_path / "coffee").mkdir()
    (tmp_path / "coffee" / "SPEC.md").write_text("# Coffee\n\n## 1 Goal\n\nBrew at 93 degrees.\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "spec")
    head = _git(tmp_path, "rev-parse", "HEAD")
    spec_run = _run(admin, project, epic, "spec-writing", pr="7", context={
        "local_path": str(tmp_path), "head_sha": head, "stories": [s1.source_key]})
    spec_run.repository = "github:octryx-ai/coffee"
    db.add(spec_run)
    await db.flush()
    assert (await publish_spec(db, spec_run, {}))[1] == "succeeded"
    story = _run(admin, project, s1, "epic-delivery", after=spec_run, pr="8")
    db.add(story)
    await db.flush()
    assert (await publish_feature(db, story, {}))[1] == "succeeded"

    sources = {row.source_key: row for row in (await db.execute(select(KnowledgeEvidenceSource).where(
        KnowledgeEvidenceSource.project_id == project.id))).scalars().all()}
    spec_key = "spec.github-octryx-ai-coffee.coffee-spec.md"
    from app.models.project.knowledge_evidence import KnowledgeSourceRevisionOrigin

    urls = set((await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars().all())
    assert spec_key in sources and f"https://github.com/octryx-ai/coffee/blob/{head}/coffee/SPEC.md" in urls
    pages = [key for key in sources if key.startswith("confluence.")]
    assert len(pages) == 2  # the feature page and the overview (the spec page is the spec file)
    assert [event["state"] for event in await _events(db, story, "knowledge_ingested")] == ["recorded", "recorded"]

    project.config = {**project.config, "knowledge": {"auto_ingest": False}}
    await db.flush()
    again = _run(admin, project, s1, "epic-delivery", after=story, pr="9")
    db.add(again)
    await db.flush()
    await publish_feature(db, again, {})
    assert {event["reason"] for event in await _events(db, again, "knowledge_ingest_skipped")} == {"switched_off"}
