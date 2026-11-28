"""What a workflow run writes becomes Workspace knowledge at once: knowledge first, web search second, so a later spec
builds on a spec of the same Workspace that is already published instead of researching the web from scratch."""

from __future__ import annotations

import html
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, User, WorkflowRun

logger = logging.getLogger(__name__)

MEDIA_TYPE = "text/markdown"
MAX_BYTES = 2 * 1024 * 1024
EVENT_INGESTED = "knowledge_ingested"
EVENT_SKIPPED = "knowledge_ingest_skipped"
_KEY_CLEAN = re.compile(r"[^a-z0-9._-]+")


def auto_ingest(project: Project | None) -> bool:
    knowledge = dict(project.config or {}).get("knowledge") if project is not None and isinstance(
        project.config, dict) else None
    return not (isinstance(knowledge, dict) and knowledge.get("auto_ingest") is False)


def source_key(kind: str, *parts: str) -> str:
    key = _KEY_CLEAN.sub("-", ".".join([kind, *parts]).lower()).strip("-.")
    return key[:200] or kind


def storage_to_markdown(storage: str) -> str:
    text = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2) + "\n",
                  storage, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|tr|li|pre|blockquote)>|<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.rstrip() for line in html.unescape(text).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


async def ingest_run_document(db: AsyncSession, run: WorkflowRun, *, key: str, title: str, text: str,
                              source_url: str | None, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..records import record_event

    project = await db.get(Project, run.project_id) if run.project_id else None
    requester = await db.get(User, run.requested_by) if run.requested_by else None
    note = {"source_key": key, "title": title[:200], **(detail or {})}
    if project is None or requester is None or not auto_ingest(project) or not text.strip():
        reason = "switched_off" if project is not None and not auto_ingest(project) else "nothing_to_ingest"
        record_event(db, run, EVENT_SKIPPED, node_id=run.current_node_id, detail={**note, "reason": reason})
        return {"state": "skipped", "reason": reason}
    data = text.encode("utf-8")[:MAX_BYTES]
    try:
        # The ledger commits (and on a race rolls back) the session it is given: its own session, never the run's
        # transaction (the documentation step still holds uncommitted state).
        ingested = await _ingest_isolated(project_id=project.id, user_id=requester.id, key=key, title=title,
                                          data=data, source_url=source_url)
    except Exception as error:  # noqa: BLE001 - knowledge is a side effect; the documentation step stands
        logger.warning("run_document_ingest_failed run=%s key=%s", run.id, key, exc_info=True)
        record_event(db, run, EVENT_SKIPPED, node_id=run.current_node_id,
                     detail={**note, "reason": type(error).__name__})
        return {"state": "failed", "reason": type(error).__name__}
    state = "recorded" if ingested.created else "unchanged"
    record_event(db, run, EVENT_INGESTED, node_id=run.current_node_id, detail={
        **note, "state": state, "revision": ingested.revision_ordinal, "spans": ingested.span_count,
        "source_url": source_url})
    return {"state": state, "revision": ingested.revision_ordinal}


async def _ingest_isolated(*, project_id: str, user_id: str, key: str, title: str, data: bytes,
                           source_url: str | None) -> Any:
    from ....db import core as db_core
    from ...knowledge.access.authorization import authorize_workspace
    from ...knowledge.ingestion.text_ingest import ingest_text_source
    from ...knowledge.runtime import get_evidence_runtime

    async with db_core.async_session_factory() as own:
        user = await own.get(User, user_id)
        authorized = await authorize_workspace(own, current_user=user, workspace_id=project_id, require_author=True)
        ingested = await ingest_text_source(
            own, runtime=get_evidence_runtime(), authorized=authorized, source_key=key, display_title=title[:200],
            declared_media_type=MEDIA_TYPE, data=data, created_by=user_id, source_url=source_url or None)
        await own.commit()
        return ingested


def spec_url(run: WorkflowRun, path: str, head: str) -> str | None:
    repository = str(run.repository or "")
    if repository.startswith("github:") and head:
        return f"https://github.com/{repository.removeprefix('github:')}/blob/{head}/{path}"
    return None


__all__ = ["EVENT_INGESTED", "auto_ingest", "ingest_run_document", "source_key", "spec_url", "storage_to_markdown"]
