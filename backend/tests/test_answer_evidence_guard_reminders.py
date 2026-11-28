"""The guard reminds an uncited or invented-link answer once, then delivers it with a sources note or marker."""

from __future__ import annotations

from app.services.answer_evidence.record import ANSWER_EVIDENCE_KEY, read_answer_evidence

# --- the runtime boundary --------------------------------------------------------------------------


class _Db:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
















def test_the_trace_record_reader_keeps_only_closed_values() -> None:
    assert read_answer_evidence({ANSWER_EVIDENCE_KEY: {"evidence_guard": "maybe"}}) is None
    read = read_answer_evidence({ANSWER_EVIDENCE_KEY: {"evidence_guard": "passed", "cited_count": "3", "uncited_count": 0}})
    assert read["evidence_guard"] == "passed" and read["cited_count"] is None and read["uncited_count"] == 0
