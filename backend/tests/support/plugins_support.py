"""Shared helpers for the test_plugins_* modules."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.models import Project, User, UserProject
from app.services.skill_catalog.effective import candidates
from app.services.skill_catalog.extension import SURFACE_PLATFORM_CHAT
from app.services.work_role_model.seeds import ensure_seed_catalog
from tests.policy_engine_support import bearer

SHIPPED = Path(__file__).resolve().parents[3] / "plugins" / "release-notes"


def uid() -> str:
    return str(uuid.uuid4())


async def _workspace_admin(db) -> tuple[User, Project, Project]:
    await ensure_seed_catalog(db)  # the built-in functions (read, delivery, ...) the shipped role builds on
    user = User(id=uid(), username=f"lead_{uid()[:6]}", email=f"{uid()[:6]}@test.local", password_hash="x",
                auth_source="local")
    ours, other = (Project(id=uid(), name=f"ws-{uid()[:6]}", is_active=True, config={}) for _ in range(2))
    db.add_all([user, ours, other])
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id=ours.id, role="admin", granted_by=user.id))
    await db.commit()
    return user, ours, other


async def _delivered(db, project_id: str) -> dict[str, str]:
    return {c.skill.name: c.reason for c in await candidates(db, project_id=project_id, surface=SURFACE_PLATFORM_CHAT)
            if c.skill.name in ("release-notes", "release-readiness")}


def _write(folder: Path, files: dict[str, bytes]) -> None:
    import shutil

    shutil.rmtree(folder, ignore_errors=True)
    for path, data in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(data)


async def _in_image(db, folder: Path, plugins: dict[str, dict[str, bytes]]) -> dict[str, dict]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.plugins.image import sync_image_plugins

    for entry, files in plugins.items():
        _write(folder / entry, files)
    report = await sync_image_plugins(async_sessionmaker(db.bind, expire_on_commit=False), folder)
    db.expire_all()
    return {item["entry"]: item for item in report.entries}


def _switch(client, who: str, plugin: str, workspace_id: str, on: bool = True):
    return client.post(f"/api/v1/plugins/available/{plugin}/{'activate' if on else 'deactivate'}",
                       json={"workspace_id": workspace_id}, headers=bearer(who))
