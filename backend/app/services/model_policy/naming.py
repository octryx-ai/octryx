"""Registry names and revision numbering of model policies.

A registry name is referenced as ``name@revision``, so it must never contain
``@`` or whitespace. The accepted shape is a closed charset (lower-case letters,
digits, ``.``, ``_``, ``-``), checked as input validation only.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import NAME_INVALID, RegistryRefusalError

NAME_MAX_LENGTH = 120
_NAME_SHAPE = re.compile(r"[a-z0-9][a-z0-9._-]*")


def normalize_name(raw: object) -> str:
    name = str(raw or "").strip()
    if not name or len(name) > NAME_MAX_LENGTH or _NAME_SHAPE.fullmatch(name) is None:
        raise RegistryRefusalError(NAME_INVALID, max_length=NAME_MAX_LENGTH)
    return name


async def next_revision_number(db: AsyncSession, revision_column, parent_column, parent_id: str) -> int:
    current = (await db.execute(select(func.max(revision_column)).where(parent_column == parent_id))).scalar()
    return int(current or 0) + 1


__all__ = ["NAME_MAX_LENGTH", "next_revision_number", "normalize_name"]
