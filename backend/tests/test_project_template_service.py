import pytest
from sqlalchemy import select

from app.models import Project, User, UserProject
from app.services.project_template_service import ProjectTemplateSpec, import_project_template


@pytest.mark.asyncio
async def test_import_project_template_creates_project_with_source_metadata(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    template = ProjectTemplateSpec(
        template_key="example-template",
        display_name="Example Template",
        version="1.0.0",
        project_name="example",
        project_description="Example imported project",
        project_config={"repo_root": "var/repos/example"},
        metadata={"origin": "test"},
    )

    project = await import_project_template(db, template=template, admin_user=admin)
    await db.flush()

    assert project.name == "example"
    assert project.source_type == "template"
    assert project.template_key == "example-template"
    assert project.template_version == "1.0.0"
    assert project.template_metadata == {"origin": "test", "template_display_name": "Example Template"}
    user_config = {k: v for k, v in project.config.items() if k != "trace_capture"}
    assert user_config == {"repo_root": "var/repos/example"}

    assignment = (
        await db.execute(
            select(UserProject).where(
                UserProject.user_id == admin.id,
                UserProject.project_id == project.id,
            )
        )
    ).scalar_one()
    assert assignment.role == "owner"


@pytest.mark.asyncio
async def test_import_project_template_updates_metadata_without_overwriting_config(db):
    project = Project(
        name="template-existing",
        description="Admin edited",
        config={"admin": "kept"},
    )
    db.add(project)
    await db.flush()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    template = ProjectTemplateSpec(
        template_key="template-existing",
        display_name="Template Existing",
        version="2.0.0",
        project_name="template-existing",
        project_config={"admin": "overwritten"},
    )

    updated = await import_project_template(db, template=template, admin_user=admin)
    await db.flush()

    assert updated.id == project.id
    user_config = {k: v for k, v in updated.config.items() if k != "trace_capture"}
    assert user_config == {"admin": "kept"}
    assert updated.source_type == "template"
    assert updated.template_version == "2.0.0"
