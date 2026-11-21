"""One refusal type for the skill catalog: a fixed ``code``, an HTTP status and structured details."""

from __future__ import annotations

from typing import Any


class SkillCatalogError(Exception):
    def __init__(self, code: str, status: int = 409, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, **self.details}


__all__ = ["SkillCatalogError"]
