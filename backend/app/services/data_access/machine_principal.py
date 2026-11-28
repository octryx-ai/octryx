"""The viewer of a machine-authenticated request: the person who owns the integration it authenticated against. The
integration's credential is checked before that person becomes the request's viewer (:func:`authenticating_owner`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import select

from .read_filter import PRIVATE_ACCESS_MODE
from .viewer import as_viewer, bind_request_viewer


@dataclass(frozen=True)
class IntegrationOwner:
    user_id: str | None
    # In a private Workspace: a failed credential must then answer like an unknown integration.
    private: bool


async def integration_owner(db, model: type, row_id: object, *, owner_column: str | None,
                            key_column: str = "id") -> IntegrationOwner:
    # The owner is owner_column, else the owner of the private Workspace the row lies in. Like an API key lookup this
    # runs before anyone is known: three columns of one row, never returned.
    from ...models import Project  # noqa: PLC0415

    table, projects = model.__table__, Project.__table__
    workspace = table.c[getattr(model, model.__workspace_column__).property.columns[0].name]
    columns = [workspace] + ([table.c[owner_column]] if owner_column else [])
    connection = await db.connection()
    row = (await connection.execute(select(*columns).where(table.c[key_column] == row_id))).first()
    if row is None:
        return IntegrationOwner(None, private=False)
    private_owner = (await connection.execute(select(projects.c.owner_user_id).where(
        projects.c.id == row[0], projects.c.access_mode == PRIVATE_ACCESS_MODE))).first() if row[0] else None
    owner = row[1] if owner_column else (private_owner[0] if private_owner else None)
    return IntegrationOwner(str(owner) if owner else None, private=private_owner is not None)


@asynccontextmanager
async def authenticating_owner(db, model: type, row_id: object, *, owner_column: str | None,
                               key_column: str = "id") -> AsyncIterator[IntegrationOwner]:
    # Reads as the integration's owner while the block checks the credential; the owner becomes the request's
    # viewer only when the block ends without raising.
    owner = await integration_owner(db, model, row_id, owner_column=owner_column, key_column=key_column)
    with as_viewer(owner.user_id):
        yield owner
    bind_request_viewer(owner.user_id)


async def bind_authenticated_owner(db, model: type, row_id: object, *, owner_column: str | None) -> None:
    # For a route that has checked the integration's credential already.
    bind_request_viewer((await integration_owner(db, model, row_id, owner_column=owner_column)).user_id)


__all__ = ["IntegrationOwner", "authenticating_owner", "bind_authenticated_owner", "integration_owner"]
