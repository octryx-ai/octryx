import json

import pytest

from app.models import SystemConfig
from app.services.office import documents as office_documents
from app.services.office.documents import get_office_template_library


@pytest.mark.asyncio
async def test_office_template_library_prefers_project_over_runtime_and_builtin(db, tmp_path, monkeypatch):
    builtin_template = tmp_path / "builtin.potx"
    runtime_template = tmp_path / "runtime.potx"
    project_template = tmp_path / "project.potx"
    for candidate in (builtin_template, runtime_template, project_template):
        candidate.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(
        office_documents,
        "built_in_office_template_library",
        lambda: [
            {
                "key": "shared-template",
                "name": "Builtin Template",
                "doc_type": "pptx",
                "path": str(builtin_template),
                "description": "Builtin default",
                "is_default": True,
            }
        ],
    )
    db.add(
        SystemConfig(
            key="agent.office_template_library",
            value=json.dumps(
                [
                    {
                        "key": "shared-template",
                        "name": "Runtime Template",
                        "doc_type": "pptx",
                        "path": str(runtime_template),
                        "description": "Runtime override",
                        "is_default": True,
                    }
                ]
            ),
        )
    )
    await db.commit()

    library = await get_office_template_library(
        db=db,
        project_config={
            "office_template_library": [
                {
                    "key": "shared-template",
                    "name": "Project Template",
                    "doc_type": "pptx",
                    "path": str(project_template),
                    "description": "Project override",
                    "is_default": True,
                }
            ]
        },
    )

    entry = next(item for item in library if item["key"] == "shared-template")
    assert entry["path"] == str(project_template)
    assert entry["name"] == "Project Template"
