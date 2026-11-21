"""The deck embeds the full diagram, not the turn-history preview.

A ``create_diagram`` result is hard-capped before it enters the turn history:
the model never needs the full draw.io document in context, so the
``diagram_xml`` string is truncated. Rendering the deck's diagram image from
that preview embeds a diagram cut off after its first cells — containers keep
their size while their interior is empty (live finding: a 232-node AWS topology
embedded as one subnet with two nodes).

These tests pin the fix: ``create_presentation`` loads the full diagram XML
back from the persisted tool call and renders that, using the history preview
only for the id/title and as a last-resort fallback.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Session, ToolCall, User
from app.tools.presentation_impl import _presentation_evidence as evidence

# A wrapped draw.io document whose interior would be lost to a mid-string cut.
FULL_XML = (
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="vpc" value="vpc" style="grIcon=mxgraph.aws4.group_vpc;" vertex="1" parent="1">'
    '<mxGeometry x="0" y="0" width="800" height="900" as="geometry"/></mxCell>'
    '<mxCell id="lb0" value="alb0" style="resIcon=mxgraph.aws4.application_load_balancer;" vertex="1" parent="vpc">'
    '<mxGeometry x="20" y="30" width="64" height="64" as="geometry"/></mxCell>'
    '<mxCell id="rds0" value="rds0" style="resIcon=mxgraph.aws4.rds;" vertex="1" parent="vpc">'
    '<mxGeometry x="20" y="400" width="64" height="64" as="geometry"/></mxCell>'
    '<mxCell id="sqs0" value="sqs0" style="resIcon=mxgraph.aws4.sqs;" vertex="1" parent="1">'
    '<mxGeometry x="900" y="30" width="64" height="64" as="geometry"/></mxCell>'
    "</root></mxGraphModel>"
)
# The history keeps only the opening of that document — the rds/sqs cells are gone.
CAPPED_PREVIEW_XML = FULL_XML[:180]


async def _seed_diagram_tool_call(db, *, diagram_id: str, xml: str) -> str:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        tool_name="create_diagram",
        status="success",
        result={"status": "created", "diagram_id": diagram_id, "diagram_xml": xml, "title": "AWS Topology"},
    )
    db.add_all([session, tool_call])
    await db.flush()
    return session.id


@pytest.mark.asyncio
async def test_load_full_diagram_xml_reads_persisted_tool_call(db):
    session_id = await _seed_diagram_tool_call(db, diagram_id="diagram-9", xml=FULL_XML)

    loaded = await evidence.load_full_diagram_xml(db, session_id=session_id, diagram_id="diagram-9")

    assert loaded == FULL_XML
    assert "mxgraph.aws4.rds" in loaded
    assert "mxgraph.aws4.sqs" in loaded


@pytest.mark.asyncio
async def test_load_full_diagram_xml_missing_returns_empty(db):
    session_id = await _seed_diagram_tool_call(db, diagram_id="diagram-9", xml=FULL_XML)

    assert await evidence.load_full_diagram_xml(db, session_id=session_id, diagram_id="absent") == ""
    assert await evidence.load_full_diagram_xml(None, session_id=session_id, diagram_id="diagram-9") == ""


@pytest.mark.asyncio
async def test_diagram_images_render_from_full_xml_not_preview(db, tmp_path, monkeypatch):
    session_id = await _seed_diagram_tool_call(db, diagram_id="diagram-9", xml=FULL_XML)
    # History carries only the capped preview, which must not be what is rendered.
    history = [
        {
            "tool_name": "create_diagram",
            "params": {},
            "result": {"status": "created", "diagram_id": "diagram-9", "diagram_xml": CAPPED_PREVIEW_XML,
                       "title": "AWS Topology", "_hard_capped": True},
        }
    ]

    rendered_xml: dict[str, str] = {}

    def _fake_render(*, diagram_id: str, diagram_xml: str, scale: int) -> bytes:
        rendered_xml["xml"] = diagram_xml
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr("app.services.diagram_export_service.render_diagram_png", _fake_render)

    images, warnings = await evidence.diagram_images_from_history(
        history, output_dir=Path(tmp_path), db=db, session_id=session_id
    )

    assert len(images) == 1
    # The renderer saw the FULL document, not the capped preview.
    assert rendered_xml["xml"] == FULL_XML
    assert "mxgraph.aws4.rds" in rendered_xml["xml"]
    # A successfully loaded full XML raises no capped-preview warning.
    assert not any("capped preview" in w for w in warnings)
    assert Path(images[0]["path"]).exists()


@pytest.mark.asyncio
async def test_diagram_images_warn_when_full_xml_unavailable(db, tmp_path, monkeypatch):
    # No persisted tool call for this diagram id -> fallback to preview + warning.
    history = [
        {
            "tool_name": "create_diagram",
            "params": {},
            "result": {"status": "created", "diagram_id": "orphan", "diagram_xml": CAPPED_PREVIEW_XML,
                       "title": "AWS Topology", "_hard_capped": True},
        }
    ]

    def _fake_render(*, diagram_id: str, diagram_xml: str, scale: int) -> bytes:
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr("app.services.diagram_export_service.render_diagram_png", _fake_render)

    images, warnings = await evidence.diagram_images_from_history(
        history, output_dir=Path(tmp_path), db=db, session_id="no-such-session"
    )

    assert len(images) == 1
    assert any("capped preview" in w for w in warnings)
