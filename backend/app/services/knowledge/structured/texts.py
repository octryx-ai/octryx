"""The stored text of one revision and where each offset or line is cited."""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from ..objects import KnowledgeObjectError
from ..objects.source_object import SourceObjectRef
from ..retrieval.errors import KnowledgeRetrievalError
from .facts import SpanInput, SpanRef
from .sources import Candidate


async def read_revision_text(context, candidate: Candidate) -> str:
    from app.services.knowledge.structured.build_states import StructuredSourceError

    runtime = context.runtime
    if runtime is None or getattr(runtime, "object_store", None) is None:
        raise StructuredSourceError("object_store_not_configured")
    try:
        ref = SourceObjectRef(bucket=candidate.object_bucket, key=candidate.object_key,
                              version_id=candidate.object_version_id, content_sha256=candidate.content_sha256)
        data = await runtime.object_store.get_verified(context.workspace, ref)
    except (KnowledgeObjectError, KnowledgeRetrievalError):
        raise StructuredSourceError("source_unreadable") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise StructuredSourceError("not_utf8") from None


@dataclass(frozen=True)
class SpanIndex:
    char_starts: list[tuple[int, int]]
    line_starts: list[tuple[int, int]]

    @classmethod
    def of(cls, spans: list[SpanInput]) -> SpanIndex:
        chars = sorted(((span.char_start or 0), span.ordinal) for span in spans)
        lines = sorted(((span.line_start or 1), span.ordinal) for span in spans)
        return cls(chars, lines)

    def _at(self, items: list[tuple[int, int]], position: int) -> int:
        index = max(bisect.bisect_right(items, (position, 1 << 30)) - 1, 0)
        return items[index][1] if items else 1

    def at_offset(self, offset: int) -> SpanRef:
        return SpanRef(self._at(self.char_starts, offset))

    def at_line(self, line: int) -> SpanRef:
        return SpanRef(self._at(self.line_starts, line), line)


__all__ = ["SpanIndex", "read_revision_text"]
