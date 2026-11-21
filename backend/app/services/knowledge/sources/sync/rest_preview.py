"""What the admin API says about a Custom REST Knowledge source: its ACL state and a dry-run sample.

**ACL state** (in every answer that describes the source). A restricted source (the default) is ingested only when
the Workspace enforces source ACLs (``access/source_acl.acl_enforcement_enabled``); otherwise every restricted item
is withheld (``restricted_acl``), the existing behaviour for every source. An admin would otherwise see a source that
"runs" and yields nothing, so the answer says it outright (``restricted_items_withheld``).

**Sample** (the setup drawer's dry run before saving). One page of the draft's list operation through the same
connector a run uses, mapped to item headers with their ACL facet, and the first item's content rendered (bounded for
the answer). Nothing is ingested and no sync state is written; the REST calls are audited like any call
(``rest_api_call_runs``), so the session commits them.

The sample reads as the source's role, which the configuring author need not hold. So a restricted item's title,
link and content are shown only when the author holds one of the roles it admits (else ``hidden: true``), the same
rule a knowledge search applies after the sync: configuring a source never shows more than searching it would.

**Excerpt**: every visible item carries the first ``EXCERPT_CHARS`` characters of its
content (``excerpt``), so the author sees what will be ingested, not only titles. A source with a
``detail_operation`` reads each visible sample item through it (at most ``SAMPLE_ITEMS`` calls, audited like the
run's). The sample goes to people, never to a model, so by the rule "fence only at a model's input" it carries no
fence markers (``unfence_text``, should the API's text contain any); it is masked with the secret rule set
(``secret_masking.masked_text``) like every text shown back, and cut with an ellipsis. The first item's longer
``text`` is masked the same way.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....content_security.knowledge_fence import unfence_text
from ....secret_masking import masked_text
from ...access.authorization import AuthorizedWorkspace
from ...access.source_acl import acl_enforcement_enabled
from ...ledger.errors import EvidenceLedgerContractError
from .config import ConnectorConfig
from .contract import ACL_AUDIENCE_RESTRICTED, ACL_AUDIENCE_SCOPE, ConnectorError
from .owner_rules import enforce_source_rules
from .rest_acl import roles_of, roles_of_user
from .rest_config import VISIBILITY_RESTRICTED
from .rest_connection import resolve_rest_connection
from .rest_source import RestKnowledgeConnector
from .runner import PAGE_SIZE

SAMPLE_ITEMS = 10
SAMPLE_CONTENT_CHARS = 2000
EXCERPT_CHARS = 300
ELLIPSIS = "\u2026"


async def acl_state(db: AsyncSession, project_id: str, scope: dict[str, Any]) -> dict[str, Any]:
    visibility = scope.get("visibility") or VISIBILITY_RESTRICTED
    enforced = await acl_enforcement_enabled(db, project_id)
    withheld = visibility == VISIBILITY_RESTRICTED and not enforced
    return {
        "visibility": visibility,
        "acl_enforced": enforced,
        "restricted_items_withheld": withheld,
        "note": ("This Workspace does not enforce source ACLs, so restricted items are withheld until it does "
                 "(Knowledge settings), or set visibility to 'workspace'.") if withheld else None,
    }


async def describe_rest_source(db: AsyncSession, row: Any) -> dict[str, Any]:
    return {"acl": await acl_state(db, row.project_id, dict(row.scope or {}))}


def _visible(item: Any, own_roles: frozenset[str]) -> bool:
    roles = roles_of(item.acl)
    return item.acl.audience == ACL_AUDIENCE_SCOPE or bool(roles and roles & own_roles)


def shown_text(text: str) -> str:
    """Text of a source shown to people: no fence markers, secrets masked."""
    return masked_text(unfence_text(text)) or ""


def excerpt(text: str, title: str | None = None) -> str:
    """At most ``EXCERPT_CHARS`` characters of ``text`` on one line, masked, cut with an ellipsis.

    A rendered JSON record starts with its title as a heading (``rest_render.render_json``); the title is shown
    next to the excerpt already, so the heading is left out."""
    body = text.replace("\r\n", "\n").strip()
    if title and body.startswith(f"# {title}"):
        body = body[len(f"# {title}"):]
    flat = " ".join(shown_text(body).split())
    return flat if len(flat) <= EXCERPT_CHARS else flat[:EXCERPT_CHARS - len(ELLIPSIS)].rstrip() + ELLIPSIS


def _text(content: Any) -> str | None:
    return content.data.decode("utf-8", "replace") if content.media_type.startswith("text/") else None


def _header(item: Any, visible: bool, content: Any = None) -> dict[str, Any]:
    if not visible:
        return {"external_id": item.external_id, "hidden": True, "version_marker": item.version_marker,
                "acl": item.acl.as_dict()}
    text = _text(content) if content is not None and not isinstance(content, str) else None
    return {"external_id": item.external_id, "title": item.title, "source_url": item.source_url,
            "version_marker": item.version_marker,
            "source_changed_at": item.source_changed_at.isoformat() if item.source_changed_at else None,
            "acl": item.acl.as_dict(),
            "excerpt": excerpt(text, item.title) if text is not None else None,
            **({"excerpt_reason": content} if isinstance(content, str) else {})}


async def _contents(connector: RestKnowledgeConnector, items: tuple, visible: list[bool]) -> dict[str, Any]:
    """Each visible sample item's content, or the fixed reason it could not be read (by external id)."""
    contents: dict[str, Any] = {}
    for item, shown in zip(items, visible, strict=True):
        if not shown:
            continue
        try:
            contents[item.external_id] = await connector.fetch(item)
        except ConnectorError as error:
            contents[item.external_id] = error.reason
    return contents


def _first_content(items: tuple, visible: list[bool], contents: dict[str, Any]) -> dict[str, Any] | None:
    if not items:
        return None
    if not visible[0]:
        return {"external_id": items[0].external_id, "hidden": True}
    content = contents[items[0].external_id]
    if isinstance(content, str):
        return {"external_id": items[0].external_id, "reason": content}
    text = _text(content)
    return {"external_id": items[0].external_id, "media_type": content.media_type, "bytes": len(content.data),
            "text": shown_text(text)[:SAMPLE_CONTENT_CHARS] if text is not None else None}


async def sample_rest_source(db: AsyncSession, *, authorized: AuthorizedWorkspace, config: ConnectorConfig,
                             actor_id: str) -> dict[str, Any]:
    """Map one page of a draft ``custom_rest`` source without ingesting; raises ``ConnectorError`` when refused."""
    if type(authorized) is not AuthorizedWorkspace or not authorized.may_author:
        raise EvidenceLedgerContractError()
    await enforce_source_rules(db, project_id=authorized.project_id, config=config, actor_id=actor_id)
    scope = dict(config.scope)
    connection = await resolve_rest_connection(db, authorized.project_id, scope)
    connector = RestKnowledgeConnector(connection, scope=scope, db=db, project_id=authorized.project_id,
                                       actor_id=actor_id)
    own_roles = await roles_of_user(db, authorized.project_id, actor_id)
    try:
        page = await connector.list_items(None, limit=PAGE_SIZE)
        first = page.items[0] if page.items else None
        shown = page.items[:SAMPLE_ITEMS]
        visible = [_visible(item, own_roles) for item in shown]
        contents = await _contents(connector, shown, visible)
        members = None
        if first is not None and first.acl.audience == ACL_AUDIENCE_RESTRICTED:
            expansion = await connector.expand_acl(first.acl)
            members = None if expansion is None else {"admitted": len(expansion.member_emails),
                                                      "unmapped": expansion.unmapped}
    finally:
        await db.commit()  # the executor's audit rows of the sample's calls
    return {
        "items": [_header(item, seen, contents.get(item.external_id)) for item, seen in zip(shown, visible,
                                                                                               strict=True)],
        "listed": len(page.items),
        "skipped": [{"record": record, "reason": reason} for record, reason in page.skipped[:SAMPLE_ITEMS]],
        "last_page": page.next_token is None,
        "listing": dict(connector.listing_facts),
        "first_item_content": _first_content(shown, visible, contents),
        "first_item_members": members,
        "acl": await acl_state(db, authorized.project_id, scope),
    }


__all__ = ["EXCERPT_CHARS", "acl_state", "describe_rest_source", "excerpt", "sample_rest_source", "shown_text"]
