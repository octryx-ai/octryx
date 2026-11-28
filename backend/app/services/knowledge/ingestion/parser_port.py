"""The sandboxed document parser port (``Parser``). The API process never parses a PDF or Office document; nothing the
sandbox answers leaves the adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

MAX_PARSER_FIELD_CHARS = 60


class ParserState(StrEnum):
    NEEDS_CONFIGURATION = "needs_configuration"
    UNAVAILABLE = "unavailable"
    # The sandbox could not parse this document; retrying the same bytes will not help.
    REFUSED = "refused"
    CONTRACT_VIOLATION = "contract_violation"


class ParserError(Exception):
    def __init__(self, state: ParserState, reason: str) -> None:
        super().__init__(f"parser {state.value}: {reason}")
        self.state = state
        self.reason = reason


class TaskStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    # The sandbox does not know the task (it restarted, or dropped the result): submit again.
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class ParserIdentity:
    name: str
    version: str
    sandbox: str

    def __post_init__(self) -> None:
        for value in (self.name, self.version, self.sandbox):
            if type(value) is not str or not 0 < len(value) <= MAX_PARSER_FIELD_CHARS:
                raise ParserError(ParserState.CONTRACT_VIOLATION, "identity")


class DocumentParser(Protocol):
    @property
    def identity(self) -> ParserIdentity: ...

    async def submit(
        self, data: bytes, media_type: str, *, do_ocr: bool = True, page_range: tuple[int, int] | None = None
    ) -> str:
        pass

    async def poll(self, task_ref: str) -> TaskStatus:
        pass

    async def result(self, task_ref: str) -> dict[str, Any]:
        pass


__all__ = ["DocumentParser", "ParserError", "ParserIdentity", "ParserState", "TaskStatus"]
