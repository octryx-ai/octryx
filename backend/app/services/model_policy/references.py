"""A Model Policy reference: ``name@revision`` (a missing ``@revision`` means unpinned)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
_REVISION = re.compile(r"[1-9][0-9]{0,8}")


@dataclass(frozen=True, slots=True)
class ResourceRef:
    name: str
    revision: int | None

    def render(self) -> str:
        return self.name if self.revision is None else f"{self.name}@{self.revision}"


class ReferenceShapeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_reference(text: str) -> ResourceRef:
    name, separator, revision = text.rpartition("@")
    if not separator:
        name, revision = text, ""
    if not _NAME.fullmatch(name) or (separator and not _REVISION.fullmatch(revision)):
        raise ReferenceShapeError("reference.malformed", f"'{text}' is not of the form name@revision.")
    return ResourceRef(name=name, revision=int(revision) if separator else None)


__all__ = ["ReferenceShapeError", "ResourceRef", "parse_reference"]
