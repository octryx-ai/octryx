"""The texts a platform action writes, taken only from the run's own record."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem

MAX_TEXT = 20_000  # a phase answer (an interview) is posted whole; a cut is marked (see confirmation_payloads)


def _last_answer(run: WorkflowRun) -> str:
    context = dict(run.context or {})
    answers = dict(context.get("answers") or {})
    return str(answers.get(str(context.get("last_phase") or "")) or "")


def findings_text(run: WorkflowRun) -> str:
    """The failed checks of the newest gate, one per line."""
    gates = [item for item in dict(run.gate_results or {}).values() if isinstance(item, dict)]
    latest = max(gates, key=lambda item: str(item.get("at") or ""), default={})
    failed = [": ".join(part for part in (str(item.get("description") or item.get("type") or ""),
                                          str(item.get("detail") or "")) if part)
              for item in latest.get("results") or []
              if isinstance(item, dict) and item.get("outcome") in ("failed", "not_applicable")]
    return "\n".join(f"- {line}" for line in failed if line)


async def run_text(db: AsyncSession, run: WorkflowRun, source: str) -> str:
    if source == "work_item":
        item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
        return (f"{item.title}\n\n{item.description or ''}".strip() if item is not None else run.title)[:MAX_TEXT]
    if source == "phase_answer":
        from ..confirmation_payloads import capped

        return capped(_last_answer(run), MAX_TEXT)
    if source == "findings":
        findings = findings_text(run)
        return (f"Workflow run '{run.title}': a round did not pass.\n{findings}" if findings
                else f"Workflow run '{run.title}': a round did not pass.")[:MAX_TEXT]
    if source == "dor_questions":
        # What keeps the Work item from being ready (triage): the Definition of Ready's missing parts.
        missing = list(dict(dict(run.context or {}).get("definition_of_ready") or {}).get("missing") or [])
        return ("Before work can start, please clarify:\n" + "\n".join(f"- {item}" for item in missing))[:MAX_TEXT] \
            if missing else ""
    if source == "review":
        # The independent reviewer's verdict as a comment: summary and one line per finding.
        from ..review.verdict import verdict_from_record

        verdict = verdict_from_record(dict(run.context or {}).get("review"))
        if verdict is None:
            return ""
        lines = [f"Independent review of '{run.title}': {verdict.verdict}. {verdict.summary}".strip()]
        lines += [f"- {finding.render()}" for finding in verdict.findings]
        return "\n".join(lines)[:MAX_TEXT]
    if source == "hypothesis":
        # E's incident hypothesis as the phase submitted it (``phase_outputs``), never the chat answer.
        from ..phase_outputs import recorded_output

        record = dict((recorded_output(run, "incident_hypothesis") or {}).get("record") or {})
        if not record:
            return ""
        lines = [record.get("summary") or "", "", f"Cause: {record.get('cause')}", f"Impact: {record.get('impact')}",
                 f"Next step: {record.get('next_step')}",
                 f"Code fix needed: {'yes' if record.get('code_fix_needed') else 'no'}", "Sources:",
                 *[f"- {source}" for source in record.get("sources") or []]]
        return "\n".join(lines)[:MAX_TEXT]
    if source == "pull_request":
        url = str(dict(run.pull_request or {}).get("url") or "")
        return f"Pull request: {url}" if url else ""
    return ""


def first_line(text: str, limit: int = 240) -> str:
    return (text.strip().splitlines() or [""])[0][:limit]


__all__ = ["findings_text", "first_line", "run_text"]
