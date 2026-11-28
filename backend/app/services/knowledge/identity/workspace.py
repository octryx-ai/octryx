"""Validated Workspace identity for Knowledge retrieval. Null, wildcard, nil or non-canonical values are rejected, so no
caller can widen visibility."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from ..retrieval.errors import InvalidWorkspaceError, WorkspaceRequiredError

# Canonical RFC 9562 text form only: no braces, no ``urn:uuid:``, no bare hex,
# no surrounding whitespace. Upper-case hex is normalized to lower case.
_CANONICAL_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_RESERVED = frozenset({uuid.UUID(int=0), uuid.UUID(int=(1 << 128) - 1)})


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: uuid.UUID

    def __post_init__(self) -> None:
        # Exact types only: a ``uuid.UUID`` subclass or a non-int ``int`` slot
        # could report one identity while carrying another.
        if type(self.value) is not uuid.UUID or type(self.value.int) is not int:
            raise InvalidWorkspaceError()
        # Keep a private copy so no other holder of the UUID object can alter it.
        value = uuid.UUID(int=self.value.int)
        if value in _RESERVED:
            raise InvalidWorkspaceError()
        object.__setattr__(self, "value", value)

    @classmethod
    def parse(cls, raw: object) -> WorkspaceId:
        # Revalidated into a fresh instance, so a subclass or a later mutation never carries over.
        if isinstance(raw, WorkspaceId):
            if type(raw) is not WorkspaceId:
                raise InvalidWorkspaceError()
            return WorkspaceId(raw.value)
        if raw is None:
            raise WorkspaceRequiredError()
        if isinstance(raw, uuid.UUID):
            return cls(raw)
        if not isinstance(raw, str):
            raise InvalidWorkspaceError()
        if raw == "":
            raise WorkspaceRequiredError()
        if not _CANONICAL_UUID.fullmatch(raw):
            raise InvalidWorkspaceError()
        return cls(uuid.UUID(raw))

    @property
    def canonical(self) -> str:
        return str(self.value)

    def __str__(self) -> str:
        return self.canonical
