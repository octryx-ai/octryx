"""An original is displayed by its type: markdown as text, HTML sanitized with its source change date, a PDF not at all and an oversized original refused, and the sanitizer drops unsafe links."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.project.knowledge_evidence import KnowledgeSourceRevisionOrigin
from app.services.knowledge.access.authorization import parse_workspace_id
from app.services.knowledge.display import original_view
from app.services.knowledge.display.html_view import render_html_view
from tests.knowledge_evidence_seed_support import fetch_user, seed_member
from tests.knowledge_original_view_diff_support import (  # noqa: F401
    FIRST,
    _code,
    _owner_and_source,
    _path,
    _set_revision,
    as_user,
    evidence_runtime,
)

HOSTILE_HTML = (
    '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Page title</title>'
    "<style>body{display:none}</style><script>alert('head')</script></head>"
    '<body><h1 onclick="steal()">Release notes</h1>'
    '<p style="color:red" class="x" id="y">Version <strong>4.0</strong> &amp; more.</p>'
    "<script>document.cookie</script><iframe src=\"https://evil.example\">frame text</iframe>"
    '<img src="https://tracker.example/p.gif" onerror="steal()">'
    '<a href="javascript:alert(1)">bad link</a> <a href="https://docs.example/x?a=1&b=2">good link</a>'
    '<table><tr><td colspan="2" onmouseover="x()">cell</td></tr></table>'
    "<svg><script>svg()</script><text>vector</text></svg>"
    "<custom-macro>macro text</custom-macro></body></html>"
)


async def _replace_bytes(db, runtime, workspace_id, revision_id, data: bytes, media_type: str) -> None:
    """Make one revision hold ``data`` (e.g. an HTML page) exactly as ingestion would have stored it."""
    stored = await runtime.object_store.put_if_absent(parse_workspace_id(workspace_id), data)
    await _set_revision(
        db,
        revision_id,
        object_key=stored.ref.key,
        content_sha256=stored.ref.content_sha256,
        byte_size=len(data),
        media_type=media_type,
    )


# --- display view -------------------------------------------------------------------------------


async def test_a_markdown_original_is_displayed_as_text(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    as_user(reader)

    response = await client.get(_path(workspace_id, created["source_id"], created["revision_id"], "view"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["content_type"] == "text/markdown"
    assert body["text"] == FIRST.decode()
    assert body["html"] is None
    assert (body["state"], body["revision_id"], body["revision_ordinal"]) == ("ok", created["revision_id"], 1)
    assert body["source_changed_at"] is None


async def test_an_html_original_is_sanitized_and_carries_its_source_change_date(client, db, as_user, evidence_runtime):  # noqa: F811
    runtime, _, _ = evidence_runtime
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    await _replace_bytes(db, runtime, workspace_id, created["revision_id"], HOSTILE_HTML.encode(), "text/html")
    db.add(
        KnowledgeSourceRevisionOrigin(
            revision_id=created["revision_id"],
            project_id=workspace_id,
            source_url="https://wiki.example/pages/1",
            source_changed_at=datetime(2026, 10, 1, 8, 30),
        )
    )
    await db.commit()

    response = await client.get(_path(workspace_id, created["source_id"], created["revision_id"], "view"))

    assert response.status_code == 200
    body = response.json()
    html, text = body["html"], body["text"]
    for forbidden in ("<script", "<style", "<iframe", "<svg", "<img", "onclick", "onerror", "onmouseover",
                      "javascript:", "style=", "class=", "id=", "alert", "steal", "frame text", "Page title"):
        assert forbidden not in html
        assert forbidden not in text
    assert "<h1>Release notes</h1>" in html
    assert '<a href="https://docs.example/x?a=1&amp;b=2" rel="noopener noreferrer nofollow" target="_blank">' in html
    assert '<td colspan="2">cell</td>' in html
    assert "<a>bad link</a>" in html
    assert "macro text" in html and "<custom-macro" not in html
    assert "Version 4.0 & more." in text and "Release notes" in text
    assert body["source_changed_at"] == "2026-10-01T08:30:00+00:00"
    assert body["source_url"] == "https://wiki.example/pages/1"


async def test_a_pdf_original_is_not_displayable(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    await _set_revision(db, created["revision_id"], media_type="application/pdf")

    response = await client.get(_path(workspace_id, created["source_id"], created["revision_id"], "view"))

    assert (response.status_code, _code(response)) == (415, "original_not_displayable")


async def test_an_oversized_original_view_is_too_large_not_truncated(
    client, db, as_user, evidence_runtime, monkeypatch  # noqa: F811
):
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    monkeypatch.setattr(original_view, "MAX_VIEW_BYTES", 10)

    body = (await client.get(_path(workspace_id, created["source_id"], created["revision_id"], "view"))).json()

    assert (body["state"], body["text"], body["html"], body["limit_bytes"]) == ("too_large", None, None, 10)


# --- sanitizer ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        " JaVaScRiPt:alert(1)",
        "jav&#x09;ascript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "vbscript:x",
        "/relative/path",
        "//evil.example/x",
        "https:no-host",
    ],
)
def test_unsafe_link_targets_are_dropped(href):
    view = render_html_view(f'<a href="{href}">x</a>')

    assert view.html == "<a>x</a>"


def test_the_sanitizer_keeps_safe_structure_and_closes_what_it_opens():
    view = render_html_view(
        '<div><p title="a&quot;b">one<em>two<ul><li>three</ul><a href="mailto:ops@example.com" title=\'q"t\'>m</a>'
        "<!-- secret comment --><scr<script>x</script>ipt>"
    )

    assert "secret comment" not in view.html and "<script" not in view.html
    assert '<a href="mailto:ops@example.com" title="q&quot;t" rel="noopener noreferrer nofollow" target="_blank">' in (
        view.html
    )
    assert view.html.count("<div>") == view.html.count("</div>") == 1
    assert view.html.count("<p>") == view.html.count("</p>")
    assert "title" not in view.html.split("<a")[0]
    assert [line for line in view.text.splitlines() if line][:2] == ["onetwo", "three"]
