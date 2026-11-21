"""Team-rule proposals from ``@octryx ignore``.

An ignored finding proposes a rule (``propose``): the file, the finding's text and the reason given. Nothing changes
until a Workspace admin or owner decides (``decide``, ``api/routes/pr_review_bot.py``):

- **accept**: the rule text (as proposed, or as the admin edited it) is appended to the repository's code style
  ``rules`` (``code_style.store.set_repository_profile``, validated and audited). Every later review of the
  repository reads it in its code style checklist as a team rule, the bot's too;
- **reject**: the proposal is closed; the ignored finding stays ignored on its pull request.

Proposals live in the Workspace's ``config["pr_review_bot"]["rule_proposals"]`` (the section the bot owns), the newest
``MAX_PROPOSALS``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import Project
from ...models.runtime.code_intelligence import CodeRepository
from ...time_utils import utc_now
from .seat_choice import CONFIG_KEY

PROPOSALS_KEY = "rule_proposals"
MAX_PROPOSALS = 200
OPEN, ACCEPTED, REJECTED = "open", "accepted", "rejected"
MAX_RULE = 500


def proposals(project: Project | None) -> list[dict[str, Any]]:
    section = dict((project.config or {}).get(CONFIG_KEY) or {}) if project is not None else {}
    return [dict(item) for item in section.get(PROPOSALS_KEY) or [] if isinstance(item, dict)]


def _store(project: Project, rows: list[dict[str, Any]]) -> None:
    section = dict((project.config or {}).get(CONFIG_KEY) or {})
    project.config = {**dict(project.config or {}), CONFIG_KEY: {**section, PROPOSALS_KEY: rows[-MAX_PROPOSALS:]}}
    flag_modified(project, "config")


def rule_text(finding: dict[str, Any], reason: str) -> str:
    """``Do not report in pay/bulk.py: <the finding> (reason: <why>)``, at most ``MAX_RULE`` characters."""
    text = " ".join(str(finding.get("fix") or "").split())
    why = " ".join(reason.split())
    return (f"Do not report in {finding.get('file')}: {text}" + (f" (reason: {why})" if why else ""))[:MAX_RULE]


def propose(project: Project, *, repository_id: str, finding: dict[str, Any], reason: str, proposed_by: str,
            pr_url: str) -> dict[str, Any]:
    row = {"id": uuid.uuid4().hex[:12], "state": OPEN, "repository_id": repository_id,
           "file": str(finding.get("file") or ""), "rule": rule_text(finding, reason), "reason": reason[:MAX_RULE],
           "finding": {key: finding.get(key) for key in ("id", "severity", "file", "line", "fix")},
           "proposed_by": proposed_by, "pr_url": pr_url, "created_at": utc_now().isoformat()}
    _store(project, [*proposals(project), row])
    return row


async def decide(db: AsyncSession, project: Project, proposal_id: str, *, accept: bool, actor_id: str,
                 rule: str = "") -> dict[str, Any] | str:
    """The decided proposal, or a refusal reason (``proposal_not_found``, ``proposal_decided``,
    ``repository_not_found``, or the code style's own validation reason)."""
    from app.services.code_style.schema_values import CodeStyleError

    from ..code_style.store import repository_profile, set_repository_profile

    rows = proposals(project)
    row = next((item for item in rows if item.get("id") == proposal_id), None)
    if row is None:
        return "proposal_not_found"
    if row.get("state") != OPEN:
        return "proposal_decided"
    if accept:
        record = await db.get(CodeRepository, str(row.get("repository_id") or ""))
        if record is None or record.project_id != project.id:
            return "repository_not_found"
        text = " ".join((rule or row["rule"]).split())[:MAX_RULE]
        profile = repository_profile(record)
        rules = "\n".join(part for part in (str(profile.get("rules") or "").strip(), f"- {text}") if part)
        try:
            await set_repository_profile(db, record, {**profile, "rules": rules}, actor_id=actor_id)
        except CodeStyleError as error:
            return error.reason
        row["rule"] = text
    row.update(state=ACCEPTED if accept else REJECTED, decided_by=actor_id, decided_at=utc_now().isoformat())
    _store(project, [row if item.get("id") == proposal_id else item for item in rows])
    return row


__all__ = ["ACCEPTED", "OPEN", "PROPOSALS_KEY", "REJECTED", "decide", "proposals", "propose", "rule_text"]
