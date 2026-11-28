import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project


async def make_project(db: AsyncSession, *, name: str | None = None, commit: bool = False, **fields) -> Project:
    project = Project(id=str(uuid.uuid4()), name=name or f"ws-{uuid.uuid4().hex[:8]}", **fields)
    db.add(project)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return project
