"""Agent output marking (EU AI Act Art. 50(2); anti-slop E): the pure marking helpers and the Confluence write
tools."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.ai_marking import (
    MarkingFacts,
    commit_message_with_trailers,
    facts_from_dict,
    facts_to_dict,
    marker_line,
    marking_facts,
    with_marker,
    with_storage_marker,
)
from app.services.ai_marking_tools import mark_fields
from app.tools.context import ToolContext

FACTS = MarkingFacts(responsible="Run Owner", model="claude-haiku-5-5", run_key="OCX-14")
NO_RUN = MarkingFacts(responsible="Run Owner", model="claude-haiku-5-5")
NO_MODEL = MarkingFacts(responsible="Run Owner")


def test_commit_trailers_follow_the_body_after_one_blank_line():
    assert commit_message_with_trailers("Fix totals\n\nRounding was off.\n", FACTS) == (
        "Fix totals\n\nRounding was off.\n\nAI-Generated-By-octryx: claude-haiku-5-5\nOctryx-Run: OCX-14")
    assert commit_message_with_trailers("Fix totals", NO_RUN) == "Fix totals\n\nAI-Generated-By-octryx: claude-haiku-5-5"


def test_commit_trailers_join_an_existing_trailer_block():
    message = "Fix totals\n\nBody.\n\nCo-Authored-By: Dev <dev@example.com>\nRefs: OCX-14"
    assert commit_message_with_trailers(message, NO_RUN) == message + "\nAI-Generated-By-octryx: claude-haiku-5-5"


def test_commit_trailers_are_idempotent_and_need_a_model():
    once = commit_message_with_trailers("Fix totals", FACTS)
    assert commit_message_with_trailers(once, FACTS) == once
    assert commit_message_with_trailers("Fix totals", None) == "Fix totals"
    assert commit_message_with_trailers("Fix totals", NO_MODEL) == "Fix totals"


def test_marker_line_names_model_run_and_responsible_only_when_known():
    assert marker_line(FACTS) == (
        "— Written by an agent (octryx · claude-haiku-5-5, run OCX-14) — responsible: Run Owner.")
    assert marker_line(NO_RUN) == "— Written by an agent (octryx · claude-haiku-5-5) — responsible: Run Owner."
    assert marker_line(MarkingFacts(responsible="Run Owner", run_key="OCX-14")) == (
        "— Written by an agent (octryx, run OCX-14) — responsible: Run Owner.")
    assert marker_line(NO_MODEL) == "— Written by an agent (octryx) — responsible: Run Owner."


def test_text_marker_is_appended_once():
    marked = with_marker("Summary\n", FACTS)
    assert marked == "Summary\n\n" + marker_line(FACTS)
    assert with_marker(marked, FACTS) == marked
    assert with_marker("", NO_MODEL) == marker_line(NO_MODEL)
    assert with_marker("Summary", None) == "Summary"


def test_storage_marker_escapes_and_is_appended_once():
    facts = MarkingFacts(responsible="Run <Owner>", model="m<x>&y", run_key='OCX-"1"')
    marked = with_storage_marker("<p>Doc</p>", facts)
    assert marked == ("<p>Doc</p><p><em>— Written by an agent (octryx · m&lt;x&gt;&amp;y, run OCX-&quot;1&quot;) — "
                      "responsible: Run &lt;Owner&gt;.</em></p>")
    assert with_storage_marker(marked, facts) == marked
    assert with_storage_marker("<p>Doc</p>", None) == "<p>Doc</p>"


def test_facts_round_trip_and_need_a_responsible():
    assert facts_from_dict(facts_to_dict(FACTS)) == FACTS
    assert facts_from_dict(facts_to_dict(NO_MODEL)) == NO_MODEL
    assert facts_to_dict(None) is None
    assert facts_from_dict({"model": "claude-haiku-5-5", "run_key": "OCX-14"}) is None
    assert facts_from_dict("not a dict") is None


@pytest.mark.asyncio
async def test_marking_facts_need_a_db_and_never_raise():
    class BrokenDb:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db down")

        async def get(self, *_args, **_kwargs):
            raise RuntimeError("db down")

    base = {"user_id": "u", "project_ids": [], "roles": [], "session_id": "s", "project_config": {}}
    assert await marking_facts(None) is None
    assert await marking_facts(ToolContext(**base)) is None
    assert await marking_facts(ToolContext(**base, turn_model="claude-haiku-5-5", db=BrokenDb())) is None


@pytest.mark.asyncio
async def test_marking_facts_name_the_calling_user_and_the_turn_model(db):
    from tests.phased_workflow_fixtures import admin_user

    admin = await admin_user(db)
    context = ToolContext(user_id=admin.id, project_ids=[], roles=[], session_id="no-run", project_config={}, db=db,
                          turn_model="claude-haiku-5-5")
    assert await marking_facts(context) == MarkingFacts(responsible=admin.display_name, model="claude-haiku-5-5")
    context.turn_model = None
    assert await marking_facts(context) == MarkingFacts(responsible=admin.display_name)


# --- Confluence write tools ------------------------------------------------------------------------------------


@pytest.fixture
def confluence(monkeypatch):
    import app.tools._confluence_access as access

    sent: list[httpx.Request] = []
    label_status = {"code": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("/label"):
            return httpx.Response(label_status["code"], json={"results": []})
        return httpx.Response(200, json={"id": "777", "title": "T", "version": {"number": 1}})

    monkeypatch.setattr(access, "egress_transport", lambda _connection: httpx.MockTransport(handler))
    return sent, label_status


def _context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=[], session_id="s",
                       project_config={"confluence_url": "https://wiki.test", "confluence_allowed_spaces": ["DOC"]})


# The registry marks the arguments before dispatch (ai_marking_tools); the tool gets them already marked.
@pytest.mark.asyncio
@pytest.mark.parametrize("label_code", [200, 500])
async def test_a_marked_page_is_sent_with_its_line_and_labelled_best_effort(confluence, label_code):
    from app.tools.confluence import CreateConfluencePage

    sent, label_status = confluence
    label_status["code"] = label_code
    params = mark_fields("create_confluence_page", {"space_key": "DOC", "title": "T", "content": "Plain text"},
                         NO_RUN)
    result = await CreateConfluencePage().execute(params, _context())

    assert result["status"] == "created"  # a refused label never fails the write
    create, label = sent
    body = json.loads(create.content)["body"]["storage"]["value"]
    assert body.startswith("<p>Plain text") and marker_line(NO_RUN) in body
    assert (label.method, label.url.path) == ("POST", "/rest/api/content/777/label")
    assert json.loads(label.content) == [{"prefix": "global", "name": "ai-generated"}]


@pytest.mark.asyncio
async def test_an_unmarked_page_is_written_without_a_label(confluence):
    from app.tools.confluence import CreateConfluencePage

    sent, _status = confluence
    await CreateConfluencePage().execute({"space_key": "DOC", "title": "T", "content": "Plain text"}, _context())

    [create] = sent
    assert json.loads(create.content)["body"]["storage"]["value"] == "<p>Plain text</p>"
