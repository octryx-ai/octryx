"""The sandboxed document parser port (``Parser``).

The API process never parses a PDF or an Office document. It hands the bytes to a parser that
runs in its own container without any network, and reads back a structured document. The port
is asynchronous on purpose: a 400-page specification takes minutes, far longer than one bounded
outbox run, so a run *submits* once and later runs *poll* the same task.

Failures are a closed taxonomy with fixed reasons, like the embedding port. Nothing the sandbox
answers — an error body, a stack trace, a file name — is carried out of the adapter.
"""

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
    """A parser failure with a fixed state and a fixed reason token; never server text."""

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
    """Who parsed a revision: recorded on the revision at registration, verified at parse time."""

    name: str
    version: str
    sandbox: str

    def __post_init__(self) -> None:
        for value in (self.name, self.version, self.sandbox):
            if type(value) is not str or not 0 < len(value) <= MAX_PARSER_FIELD_CHARS:
                raise ParserError(ParserState.CONTRACT_VIOLATION, "identity")


class DocumentParser(Protocol):
    """A sandboxed parser. Implementations own their transport and map every failure."""

    @property
    def identity(self) -> ParserIdentity: ...

    async def submit(
        self, data: bytes, media_type: str, *, do_ocr: bool = True, page_range: tuple[int, int] | None = None
    ) -> str:
        """Start parsing; returns the sandbox's opaque task reference.

        ``do_ocr`` and ``page_range`` are per-request options (the OCR choice, ``ocr_choice.py``): OCR off for
        a born-digital PDF, and a page range for the cheap text-layer probe.
        """

    async def poll(self, task_ref: str) -> TaskStatus:
        """Where the task is now."""

    async def result(self, task_ref: str) -> dict[str, Any]:
        """The parsed document of a successful task (a DoclingDocument as JSON)."""


__all__ = ["DocumentParser", "ParserError", "ParserIdentity", "ParserState", "TaskStatus"]
