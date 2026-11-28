"""Where the documentation page goes: the publish & prove Cloud v2 target."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkItemDocument
from ....tools._confluence_instance import confluence_instance
from .page import DocumentationSettings

PROVIDER = "confluence"
MODE_CREATE = "create"


async def _bound_page(db: AsyncSession, run: WorkflowRun, space_key: str, connection_id: str, instance: str
                      ) -> WorkItemDocument | None:
    if not run.work_item_id:
        return None
    return (await db.execute(
        select(WorkItemDocument).where(WorkItemDocument.work_item_id == run.work_item_id,
                                       WorkItemDocument.provider == PROVIDER, WorkItemDocument.space_key == space_key,
                                       WorkItemDocument.connection_id == connection_id,
                                       WorkItemDocument.instance_url == instance)
        .order_by(WorkItemDocument.updated_at.desc()).limit(1))).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class ServedConfluence:
    # Secrets stay in config and are never logged.

    connection_id: str
    name: str
    instance: str
    config: dict[str, Any] = field(repr=False)


class ConnectionUnavailableError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def served_confluence(db: AsyncSession, run: WorkflowRun, space_key: str) -> ServedConfluence:
    from ...named_connections.service_config import ConnectionRefusalError, service_connection_config

    try:
        served = await service_connection_config(db, run.project_id, "confluence", keys=(space_key,))
    except ConnectionRefusalError as error:
        raise ConnectionUnavailableError(error.code or "connection_refused") from None
    instance = confluence_instance(served.config.get("confluence_url"))
    if not instance:
        raise ConnectionUnavailableError("confluence_url_invalid")
    return ServedConfluence(served.connection_id, served.name, instance, dict(served.config))


@dataclass(slots=True)
class V2Target:
    space_key: str
    title: str
    connection_id: str = ""
    connection_name: str = ""
    instance: str = ""
    space_id: str = ""
    operation: str = "create"
    parent_id: str | None = None
    page_id: str | None = None
    base_version: int | None = None
    blockers: list[str] = field(default_factory=list)
    #: ``needs_configuration`` when a blocker is a missing/unsupported configuration, else ``target_blocked``.
    blocker_code: str = ""

    def pinned(self) -> dict[str, Any]:
        return {"connection_id": self.connection_id, "instance": self.instance, "space_id": self.space_id,
                "space_key": self.space_key, "parent_id": self.parent_id, "page_id": self.page_id,
                "title": self.title, "operation": self.operation, "base_version": self.base_version}

    def block(self, code: str, text: str) -> V2Target:
        self.blockers.append(text)
        self.blocker_code = self.blocker_code or code
        return self


def _space_allowed(config: dict[str, Any], space_key: str) -> bool:
    from types import SimpleNamespace

    from ....tools._confluence_access import space_allowed

    return space_allowed(SimpleNamespace(project_config=config), space_key)  # the same allowlist as the v1 tools


async def _bound_page_id(db: AsyncSession, run: WorkflowRun, space_key: str, served: ServedConfluence) -> str:
    from ....models import DocumentationWriteIntent
    from ....models.runtime.documentation_publication import DOCUMENTATION_SLOT, INTENT_SENT_CONFIRMED

    bound = await _bound_page(db, run, space_key, served.connection_id, served.instance)
    if bound is not None:
        return str(bound.page_id)
    done = (await db.execute(
        select(DocumentationWriteIntent).where(
            DocumentationWriteIntent.run_id == run.id, DocumentationWriteIntent.slot == DOCUMENTATION_SLOT,
            DocumentationWriteIntent.state == INTENT_SENT_CONFIRMED,
            DocumentationWriteIntent.connection_id == served.connection_id,
            DocumentationWriteIntent.instance == served.instance)
        .order_by(DocumentationWriteIntent.sent_confirmed_at.desc()).limit(1))).scalar_one_or_none()
    return str(done.result_page_id) if done is not None and done.result_page_id else ""


async def resolve_v2_target(db: AsyncSession, run: WorkflowRun, settings: DocumentationSettings, *, title: str,
                            transport: Any = None) -> V2Target:
    # Blockers never resolve to a guess.
    from .confluence_v2 import STATUS_CURRENT, CloudV2Client
    from .confluence_v2_errors import V2Error, V2ProfileRefusalError

    target = V2Target(space_key=settings.space_key, title=title)
    try:
        served = await served_confluence(db, run, settings.space_key)
    except ConnectionUnavailableError as error:
        return target.block("needs_configuration",
                            f"No usable Confluence connection serves the space {settings.space_key} ({error.code}).")
    target.connection_id, target.connection_name, target.instance = served.connection_id, served.name, served.instance
    if not _space_allowed(served.config, settings.space_key):
        return target.block("needs_configuration",
                            f"The space {settings.space_key} is not allowed on connection {served.name}.")
    from .confluence_v2 import governed_v2_check

    blocked = await governed_v2_check(db, run, instance=served.instance, connection_id=served.connection_id,
                                     space_key=settings.space_key, parent_id=settings.parent_page_id)
    if blocked is not None:
        return target.block("needs_configuration", f"Confluence target read is not allowed: {blocked.reason}")
    bound_id = await _bound_page_id(db, run, settings.space_key, served)
    if not bound_id and not settings.parent_page_id:
        return target.block("needs_configuration", "A new documentation page needs a configured parent page "
                                                   "(feature_documentation.parent_page_id).")
    try:
        client = CloudV2Client(served.instance, served.config, transport=transport)
    except V2ProfileRefusalError as refusal:
        return target.block("needs_configuration", str(refusal))
    try:
        async with client:
            space = await client.find_space(settings.space_key)
            target.space_id = space.id
            if bound_id:
                page = await client.get_page(bound_id, storage=False)
                if page.space_id != space.id or page.status != STATUS_CURRENT:
                    return target.block("target_blocked", f"The Work item's page {bound_id} is not a current page "
                                                          f"in {settings.space_key}.")
                target.operation, target.page_id, target.base_version = "update", page.id, page.version
                target.parent_id = page.parent_id  # an update never moves the page: its parent is pinned
                return target
            parent = await client.get_page(settings.parent_page_id, storage=False)
            if parent.space_id != space.id or parent.status != STATUS_CURRENT:
                return target.block("target_blocked", f"The parent page {settings.parent_page_id} is not a current "
                                                      f"page in {settings.space_key}.")
            target.parent_id = parent.id
            same_title = await client.scan_pages_by_title(space.id, title)
    except V2Error as error:
        return target.block("target_blocked", f"The Confluence target could not be read ({error.kind}: "
                                              f"{str(error)[:160]}); nothing is reserved until it can.")
    if not same_title.complete:
        return target.block("target_blocked", f"The check for an existing page titled '{title}' did not complete "
                                              f"({same_title.reason[:160]}); nothing is created until it does.")
    if same_title.items:
        ids = ", ".join(page.id for page in same_title.items[:5])
        return target.block("target_blocked", f"A page titled '{title}' already exists in {settings.space_key} "
                                              f"(page {ids}) and is not this Work item's page: it is never "
                                              "overwritten.")
    return target
