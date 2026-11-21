"""One verdict of the platform's style check (``check``, ``tool_check``, ``l10n_check``)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    path: str
    message: str
    line: int | None = None
    severity: str = "error"  # error | warning

    def text(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.message} [{self.rule}]"
