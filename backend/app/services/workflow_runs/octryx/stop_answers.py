"""The phase agent's answers at Stop: its last answer, the answers over a question round's passes, the task list."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

MAX_ANSWER = 100_000


async def _keep_task_list(db: AsyncSession, run: WorkflowRun, node: Any, answer: str, *, change: Any = None,
                          passed: bool = False) -> None:
    from .. import task_status
    from ..task_list import for_roles, parse, phase_roles, run_task_list, sets_task_list

    config = dict(getattr(node, "config", None) or {})
    capability = str(dict(config.get("workflow_contract") or {}).get("capability_class") or "")
    if capability.startswith("read") or sets_task_list(config):
        items = parse(answer)
        if items:
            await task_status.store(db, run, task_status.seed(items, await task_status.previous(db, run), run.id))
        return
    items = run_task_list(run)
    if items and change is not None:
        from ..task_list import passed_tests

        own = for_roles(items, phase_roles(config))
        moved_own = {item["id"]: item for item in task_status.after_build(own, change, passed=passed, run_id=run.id,
                                                                         green=passed_tests(run))}
        moved = [moved_own.get(item.get("id"), item) for item in items]
        if moved != items:
            await task_status.store(db, run, moved)


async def _last_answer(db: AsyncSession, session_id: str, since: datetime | None,
                       hook_input: dict[str, Any]) -> str:
    said = hook_input.get("last_assistant_message")
    if isinstance(said, str) and said.strip():
        return said.strip()[:MAX_ANSWER]
    from sqlalchemy import select

    from ....models import Message

    query = select(Message.content).where(Message.session_id == session_id, Message.role == "assistant")
    if since is not None:
        query = query.where(Message.created_at >= since)
    content = (await db.execute(query.order_by(Message.created_at.desc()).limit(1))).scalar()
    return str(content or "").strip()[:MAX_ANSWER]


PASS_ANSWERS_KEY = "stop_pass_answers"
QUESTION_ROUND_CLASSES = frozenset({"spec_interview", "bug_intake"})


def question_round_phase(node: Any) -> bool:
    # Other phases keep the last answer: a shorter corrected task list must not get its old list back first.
    contract = dict(dict(getattr(node, "config", None) or {}).get("workflow_contract") or {})
    return str(contract.get("workflow_class") or "") in QUESTION_ROUND_CLASSES


def phase_answer(run: WorkflowRun, node_id: str, item_id: str | None, answer: str) -> str:
    # No marker is asked of the model, so a weak model's back reference to an earlier answer works as well.
    context = dict(run.context or {})
    key = f"{node_id}/{item_id or ''}"
    entry = dict(run.node_state or {}).get("entry")
    kept = dict(dict(context.get(PASS_ANSWERS_KEY) or {}).get(key) or {})
    earlier = [str(text) for text in kept.get("answers") or []] if kept.get("entry") == entry else []
    answer = str(answer or "").strip()
    if not answer:
        return "\n\n".join(earlier)[:MAX_ANSWER]
    if answer not in earlier:
        earlier = [text for text in earlier if len(text) > len(answer) and text not in answer]
        earlier.append(answer)
    context[PASS_ANSWERS_KEY] = {**dict(context.get(PASS_ANSWERS_KEY) or {}),
                                 key: {"entry": entry, "answers": earlier}}
    run.context = context
    return "\n\n".join(earlier)[:MAX_ANSWER]


async def _answers_since(db: AsyncSession, session_id: str, since: datetime | None) -> int:
    from sqlalchemy import func, select

    from ....models import Message

    query = select(func.count()).select_from(Message).where(Message.session_id == session_id,
                                                            Message.role == "assistant")
    if since is not None:
        query = query.where(Message.created_at >= since)
    return int((await db.execute(query)).scalar() or 0)
