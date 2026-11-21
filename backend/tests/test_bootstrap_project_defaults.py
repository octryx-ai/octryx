import pytest
from sqlalchemy import select

from app.bootstrap import seed_database
from app.models import Project

pytestmark = pytest.mark.without_legacy_project_templates


@pytest.mark.asyncio
async def test_bootstrap_seeds_only_generic_default_project_by_default(db):
    projects = (await db.execute(select(Project))).scalars().all()
    project_names = {project.name for project in projects}

    assert "default" in project_names
    assert "demo" not in project_names
    assert "acme-orders" not in project_names

    default_project = next(project for project in projects if project.name == "default")
    assert default_project.is_system is True
    assert default_project.source_type == "system"
    assert default_project.template_key == "system-default-project"


@pytest.mark.asyncio
async def test_bootstrap_preserves_existing_user_projects(db):
    user_project = Project(
        name="acme-orders",
        description="Existing user-owned project",
        config={"existing": True},
        source_type="manual",
    )
    db.add(user_project)
    await db.flush()

    await seed_database(db)

    preserved = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    assert preserved.id == user_project.id
    assert preserved.config == {"existing": True}
