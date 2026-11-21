"""AI output marking (EU AI Act Art. 50(2)): the pure marking helpers and the Confluence write tools."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.ai_marking import (
    MarkingFacts,
    commit_message_with_trailers,
    marker_line,
    marking_facts,
    with_marker,
    with_storage_marker,
)
from app.tools.context import ToolContext

FACTS = MarkingFacts(model="claude-haiku-5-5", run_key="OCX-14")
NO_RUN = MarkingFacts(model="claude-haiku-5-5", run_key=None)


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


def test_marker_line_with_and_without_run():
    assert marker_line(FACTS) == "— Written by AI (octryx · claude-haiku-5-5) in run OCX-14."
    assert marker_line(NO_RUN) == "— Written by AI (octryx · claude-haiku-5-5)."


def test_text_marker_is_appended_once():
    marked = with_marker("Summary\n", FACTS)
    assert marked == "Summary\n\n— Written by AI (octryx · claude-haiku-5-5) in run OCX-14."
    assert with_marker(marked, FACTS) == marked
    assert with_marker("Summary", None) == "Summary"


def test_storage_marker_escapes_and_is_appended_once():
    facts = MarkingFacts(model="m<x>&y", run_key='OCX-"1"')
    marked = with_storage_marker("<p>Doc</p>", facts)
    assert marked == ("<p>Doc</p><p><em>— Written by AI (octryx · m&lt;x&gt;&amp;y) in run OCX-&quot;1&quot;.</em>"
                      "</p>")
    assert with_storage_marker(marked, facts) == marked
    assert with_storage_marker("<p>Doc</p>", None) == "<p>Doc</p>"


@pytest.mark.asyncio
async def test_marking_facts_never_invent_a_model_and_never_raise():
    class BrokenDb:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db down")

    base = {"user_id": "u", "project_ids": [], "roles": [], "session_id": "s", "project_config": {}}
    assert await marking_facts(ToolContext(**base)) is None
    assert await marking_facts(ToolContext(**base, turn_model="claude-haiku-5-5", db=BrokenDb())) == NO_RUN


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


def _context(turn_model: str | None) -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=[], session_id="s", turn_model=turn_model,
                       project_config={"confluence_url": "https://wiki.test", "confluence_allowed_spaces": ["DOC"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("label_code", [200, 500])
async def test_an_agent_page_is_marked_and_labelled_best_effort(confluence, label_code):
    from app.tools.confluence import CreateConfluencePage

    sent, label_status = confluence
    label_status["code"] = label_code
    result = await CreateConfluencePage().execute({"space_key": "DOC", "title": "T", "content": "Plain text"},
                                                  _context("claude-haiku-5-5"))

    assert result["status"] == "created"  # a refused label never fails the write
    create, label = sent
    body = json.loads(create.content)["body"]["storage"]["value"]
    assert body == "<p>Plain text</p><p><em>— Written by AI (octryx · claude-haiku-5-5).</em></p>"
    assert (label.method, label.url.path) == ("POST", "/rest/api/content/777/label")
    assert json.loads(label.content) == [{"prefix": "global", "name": "ai-generated"}]


@pytest.mark.asyncio
async def test_without_a_turn_model_the_page_is_written_as_before(confluence):
    from app.tools.confluence import CreateConfluencePage

    sent, _status = confluence
    await CreateConfluencePage().execute({"space_key": "DOC", "title": "T", "content": "Plain text"}, _context(None))

    [create] = sent
    assert json.loads(create.content)["body"]["storage"]["value"] == "<p>Plain text</p>"
