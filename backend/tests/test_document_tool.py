"""create_document: template selection, description persistence, composition.

A profile may hold several Word templates for different purposes, each with a
purpose description. Selection is explicit; with several and no name the tool
returns the catalog rather than guessing. Descriptions persist across a registry rebuild.
"""

import uuid
from pathlib import Path

import pytest
from docx import Document

from app.services import corp_identity_service as svc
from app.services.corp_identity import profile_edits
from app.tools.context import ToolContext
from app.tools.document import CreateDocumentTool
from app.tools.document_impl._document_template import resolve_document_template


def _docx(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Document().save(str(path))
    return path


def _snapshot() -> dict:
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {
            "resource_node_count": 232,
            "edge_count": 444,
            "node_counts_by_type": {"subnet": 9, "load_balancer": 5, "rds_instance": 2},
        },
        "scope": {"regions": ["eu-central-1"]},
    }


async def _seed_profile_with_docx(db, tmp_path, *, files: list[str]) -> str:
    root = tmp_path / "profile-root"
    source = root / "source"
    for name in files:
        _docx(source / name)
    record = {
        "id": "doc-profile",
        "name": "Brand",
        "source_path": str((source / files[0]).resolve()),
        "profile_root": str(root.resolve()),
        "summary": {"name": "Brand"},
    }
    await svc._save_registry(db, [record])
    return "doc-profile"


def _ctx(db, tmp_path, snapshot: dict, *, profile_id: str = "", template_path: str = "", template: str = "") -> tuple:
    history = [{"tool_name": "aws_topology_snapshot", "params": {}, "result": snapshot}]
    ctx = ToolContext(
        user_id="u",
        project_ids=[],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
        workspace_root=str(tmp_path / "ws"),
        turn_tool_history=history,
    )
    params = {"topic": "AWS-Architektur"}
    if profile_id:
        params["profile_id"] = profile_id
    if template_path:
        params["template_path"] = template_path
    if template:
        params["template"] = template
    return ctx, params


@pytest.mark.asyncio
async def test_create_document_composes_from_explicit_template(db, tmp_path):
    template = _docx(tmp_path / "brand.docx")
    ctx, params = _ctx(db, tmp_path, _snapshot(), template_path=str(template))

    result = await CreateDocumentTool().execute(params, ctx)

    assert result["status"] == "created"
    assert result["block_count"] > 5
    assert Path(result["file_path"]).is_file()
    assert Path(result["file_path"]).suffix == ".docx"


@pytest.mark.asyncio
async def test_create_document_requires_snapshot(db, tmp_path):
    template = _docx(tmp_path / "brand.docx")
    ctx = ToolContext(
        user_id="u", project_ids=[], roles=["admin"], session_id=str(uuid.uuid4()),
        project_config={}, db=db, workspace_root=str(tmp_path / "ws"), turn_tool_history=[],
    )
    result = await CreateDocumentTool().execute({"topic": "X", "template_path": str(template)}, ctx)
    assert "error" in result
    assert result["required_tool"] == "aws_topology_snapshot"


@pytest.mark.asyncio
async def test_multiple_templates_without_name_returns_catalog(db, tmp_path):
    profile_id = await _seed_profile_with_docx(db, tmp_path, files=["design-doc.docx", "one-pager.docx"])
    ctx, params = _ctx(db, tmp_path, _snapshot(), profile_id=profile_id)

    result = await CreateDocumentTool().execute(params, ctx)

    assert result["status"] == "needs_template_selection"
    names = {t["source_file_name"] for t in result["templates"]}
    assert names == {"design-doc.docx", "one-pager.docx"}


@pytest.mark.asyncio
async def test_named_template_is_selected(db, tmp_path):
    profile_id = await _seed_profile_with_docx(db, tmp_path, files=["design-doc.docx", "one-pager.docx"])
    ctx, params = _ctx(db, tmp_path, _snapshot(), profile_id=profile_id, template="one-pager")

    result = await CreateDocumentTool().execute(params, ctx)

    assert result["status"] == "created"
    assert result["template"]["template_name"] or result["template"]["template_id"]
    assert "one-pager" in Path(result["template"]["path"]).name


@pytest.mark.asyncio
async def test_template_description_persists_across_reload(db, tmp_path):
    profile_id = await _seed_profile_with_docx(db, tmp_path, files=["design-doc.docx", "one-pager.docx"])
    detail = await svc.get_corp_identity_profile_detail(db, profile_id)
    target = next(t for t in detail["templates"]["docx"] if t["source_file_name"] == "one-pager.docx")

    await profile_edits.update_corp_identity_template(
        db, profile_id, target["template_id"], {"description": "Management one-pager", "display_name": "One-Pager"}
    )

    # A fresh detail load (rebuilds the template map from disk) still has it.
    reloaded = await svc.get_corp_identity_profile_detail(db, profile_id)
    again = next(t for t in reloaded["templates"]["docx"] if t["source_file_name"] == "one-pager.docx")
    assert again["description"] == "Management one-pager"
    assert again["display_name"] == "One-Pager"
    # The id is stable across the reload — metadata never orphans.
    assert again["template_id"] == target["template_id"]


@pytest.mark.asyncio
async def test_resolve_document_template_explicit_and_catalog(db, tmp_path):
    profile_id = await _seed_profile_with_docx(db, tmp_path, files=["a.docx", "b.docx"])
    ctx, _ = _ctx(db, tmp_path, _snapshot(), profile_id=profile_id)

    ambiguous = await resolve_document_template(ctx, profile_id=profile_id)
    assert ambiguous.needs_selection and ambiguous.path is None
    assert len(ambiguous.catalog) == 2

    picked = await resolve_document_template(ctx, profile_id=profile_id, template="a")
    assert not picked.needs_selection
    assert picked.path is not None and picked.path.name == "a.docx"
