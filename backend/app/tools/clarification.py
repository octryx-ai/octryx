"""Tool implementation for ask_clarification."""

from __future__ import annotations

from typing import Any

from ..services.clarification_service import (
    create_clarification_question,
    get_open_clarification_for_session,
)
from .context import ToolContext


class AskClarificationTool:
    name = "ask_clarification"
    description = "Pause the run and surface a clarification question to the user."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        question_text = str(params.get("question", ""))
        question_id = str(params.get("question_id", ""))
        priority = str(params.get("priority", "medium"))
        context_snapshot = params.get("context_snapshot") or {}

        if not question_text or not question_id:
            return {"error": "question and question_id are required"}

        session_id = None
        if context and hasattr(context, "session_id"):
            session_id = context.session_id
        if not session_id:
            session_id = context_snapshot.get("session_id") if context_snapshot else None
        if not session_id:
            return {"error": "session_id is required in tool context"}

        # Resolve project_id and run_id from context if available
        project_id = None
        run_id = None

        # Resolve requested_by from context
        requested_by = context.user_id if context and context.user_id else "system"

        db = context.db if context and context.db is not None else None
        owns_db_session = db is None
        if owns_db_session:
            from ..db import async_session_factory

            db = async_session_factory()
            await db.__aenter__()

        try:
            # Check for existing clarification with same question_id + session_id (idempotency)
            existing = await get_open_clarification_for_session(db, session_id=session_id)
            if existing is not None and existing.question_id == question_id:
                if existing.status == "answered":
                    return {
                        "status": "already_answered",
                        "answer": existing.answer_text,
                        "resumed": True,
                        "question_id": existing.id,
                    }
                if existing.status == "skipped":
                    return {
                        "status": "skipped",
                        "resumed": False,
                        "question_id": existing.id,
                    }
                if existing.status == "open":
                    return {
                        "status": "open",
                        "question_id": existing.id,
                        "question": existing.question_text,
                        "paused": True,
                    }

            # Build context snapshot from context if not provided
            snapshot = dict(context_snapshot) if context_snapshot else {}
            if not snapshot and context:
                snapshot = {
                    "session_id": session_id,
                    "project_id": project_id,
                    "run_id": run_id,
                }

            # Create clarification question
            question = await create_clarification_question(
                db,
                session_id=session_id,
                project_id=project_id,
                run_id=run_id,
                question_id=question_id,
                question_text=question_text,
                context_json=snapshot,
                requested_by=requested_by,
                priority=priority,
            )
            if owns_db_session:
                await db.commit()
            else:
                await db.flush()

            return {
                "status": "paused",
                "question_id": question.id,
                "question": question_text,
                "paused": True,
            }
        except Exception:
            if owns_db_session:
                await db.rollback()
            raise
        finally:
            if owns_db_session:
                await db.__aexit__(None, None, None)
