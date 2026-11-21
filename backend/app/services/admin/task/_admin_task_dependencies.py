"""Task dependency operations for admin task service."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, TaskDependency
from ._admin_task_serialization import serialize_task_dependency


async def list_task_dependencies(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    tasks = (await db.execute(select(Task))).scalars().all()
    task_lookup = {task.id: task for task in tasks}
    dependencies = (
        (
            await db.execute(
                select(TaskDependency)
                .where(TaskDependency.task_id == task_id)
                .order_by(TaskDependency.depends_on_task_id)
            )
        )
        .scalars()
        .all()
    )
    dependents = (
        (
            await db.execute(
                select(TaskDependency)
                .where(TaskDependency.depends_on_task_id == task_id)
                .order_by(TaskDependency.task_id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "dependencies": [serialize_task_dependency(entry, task_lookup=task_lookup) for entry in dependencies],
        "dependents": [serialize_task_dependency(entry, task_lookup=task_lookup) for entry in dependents],
        "available_tasks": [
            {"id": task.id, "name": task.name}
            for task in sorted(tasks, key=lambda row: (row.name.lower(), row.id))
            if task.id != task_id
        ],
    }


async def upsert_task_dependency(
    db: AsyncSession,
    *,
    task_id: str,
    depends_on_task_id: str,
    condition: str,
) -> dict[str, Any]:
    if task_id == depends_on_task_id:
        raise HTTPException(status_code=400, detail="A task cannot depend on itself")
    task = await db.get(Task, task_id)
    depends_on = await db.get(Task, depends_on_task_id)
    if not task or not depends_on:
        raise HTTPException(status_code=404, detail="Task not found")
    existing = (
        await db.execute(
            select(TaskDependency).where(
                TaskDependency.task_id == task_id,
                TaskDependency.depends_on_task_id == depends_on_task_id,
            )
        )
    ).scalar_one_or_none()
    entry = existing or TaskDependency(task_id=task_id, depends_on_task_id=depends_on_task_id)
    entry.condition = condition
    if existing is None:
        db.add(entry)
        await db.flush()
    if await creates_task_dependency_cycle(db, task_id=task_id):
        raise HTTPException(status_code=400, detail="Task dependency would create a cycle")
    await db.commit()
    return await list_task_dependencies(db, task_id=task_id)


async def delete_task_dependency(db: AsyncSession, *, task_id: str, dependency_id: str) -> dict[str, Any]:
    entry = (
        await db.execute(
            select(TaskDependency).where(
                TaskDependency.id == dependency_id,
                TaskDependency.task_id == task_id,
            )
        )
    ).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Dependency not found")
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted", "id": dependency_id}


async def creates_task_dependency_cycle(db: AsyncSession, *, task_id: str) -> bool:
    rows = (await db.execute(select(TaskDependency.task_id, TaskDependency.depends_on_task_id))).all()
    graph: dict[str, set[str]] = {}
    for source, target in rows:
        graph.setdefault(str(source), set()).add(str(target))

    visited: set[str] = set()
    stack: set[str] = set()

    def walk(node: str) -> bool:
        if node in stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        stack.add(node)
        for neighbor in graph.get(node, set()):
            if walk(neighbor):
                return True
        stack.remove(node)
        return False

    return walk(task_id)
