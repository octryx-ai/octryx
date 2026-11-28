"""What one turn produced, read for the check library: :class:`TurnEvidence` from tool history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .library import ToolUse, TurnEvidence

# Closed: the tools whose successful call creates an artifact, and the artifact type it creates.
ARTIFACT_PRODUCERS = {
    "create_diagram": "diagram",
    "append_diagram": "diagram",
    "edit_diagram": "diagram",
    "create_document": "document",
    "create_presentation": "presentation",
}
_FAILED_STATUSES = frozenset({"error", "failed", "denied", "blocked", "refused", "timeout"})
# The turn's tool history keeps the model-facing (compacted) result under ``result``. A test run's evidence is its full
# structured result (output, fresh report, runtime): the loop keeps that too, under this key, for the evidence tools.
FULL_RESULT_KEY = "full_result"
EVIDENCE_TOOLS = frozenset({"run_test_suite", "bash"})
MISSING_FULL_RESULT = "full_result_missing"
# Markers of a model-facing copy of a result (a stored artifact summary, a capped copy), not the full result.
_COMPACTED_MARKERS = ("_prompt_result_source", "_hard_capped", "_artifact_kind")


def _evidence_result(name: str, entry: Mapping[str, Any]) -> Any:
    full = entry.get(FULL_RESULT_KEY)
    if isinstance(full, Mapping):
        return full
    result = entry.get("result")
    if name in EVIDENCE_TOOLS and isinstance(result, Mapping) and any(key in result for key in _COMPACTED_MARKERS):
        # Only the model's shortened copy is here: it proves nothing, the call is not verified (never invented).
        return {"error": MISSING_FULL_RESULT, "reason": "only the compacted result of this call was kept"}
    return result


def _succeeded(entry: Mapping[str, Any], result: Any) -> bool:
    if str(entry.get("status") or "success").strip().lower() in _FAILED_STATUSES:
        return False
    return not (isinstance(result, Mapping) and result.get("error"))


def tool_uses(entries: Iterable[Any]) -> list[ToolUse]:
    uses = []
    for entry in entries or []:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("tool_name") or entry.get("name") or "").strip()
        if name:
            result = _evidence_result(name, entry)
            uses.append(ToolUse(name=name, succeeded=_succeeded(entry, result), result=result,
                                params=entry.get("params"), call_id=str(entry.get("persisted_call_id") or "")))
    return uses


def turn_evidence(
    tool_history: Iterable[Any],
    *,
    answer: str = "",
    answer_evidence: Mapping[str, Any] | None = None,
    verification_state: str | None = None,
    test_command_prefixes: Iterable[Iterable[str]] | None = None,
) -> TurnEvidence:
    from .test_command_outcome import reclassify
    from .test_results import DEFAULT_TEST_PREFIXES, chat_verification_state, test_run_from_use
    from .urls import tool_written_texts

    prefixes = tuple(tuple(item) for item in (test_command_prefixes or DEFAULT_TEST_PREFIXES))
    # A test command whose runner ran no test is no test run; one that could not start is the environment's.
    uses, environment_failure = reclassify(tool_uses(tool_history), prefixes)
    if verification_state is None:
        # In chat the last test run after the last change decides, like octryx-claude's Stop gate; a turn
        # that changed nothing stays without a test gate state (nothing to prove). A test command run through the
        # shell counts as a test run (the Workspace's test command prefixes); any other shell call as a change.
        derived = chat_verification_state(uses, prefixes)
        verification_state = None if derived == "not_applicable" else derived
    runs = [run for use in uses if (run := test_run_from_use(use, source="chat", prefixes=prefixes)) is not None]
    record = answer_evidence if isinstance(answer_evidence, Mapping) else {}
    cited = record.get("cited_count")
    sources = record.get("evidence_url_count")
    return TurnEvidence(
        tools=uses,
        artifacts=[{"type": ARTIFACT_PRODUCERS[use.name], "tool": use.name}
                   for use in uses if use.succeeded and use.name in ARTIFACT_PRODUCERS],
        answer=str(answer or ""),
        cited_count=cited if type(cited) is int else None,
        source_count=sources if type(sources) is int else None,
        verification_state=verification_state,
        test_runs=runs,
        environment_failure=environment_failure,
        written_files=tool_written_texts(uses),  # ``urls_cited``: what the platform write tools wrote
    )


__all__ = ["ARTIFACT_PRODUCERS", "tool_uses", "turn_evidence"]
