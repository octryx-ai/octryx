"""The ACL step of one synced item: store the source's restriction before anything is ingested (5b).

Runs first for every listed item, before the version marker and the content hash, because an ACL
can change while the content does not. The step writes the ledger's ACL for the item's
``source_key`` (``access/source_acl.py``) and, when that changed for a source already served, owes
its re-projection so the spans carry the new marker. It decides one of three outcomes:

- **ingest**: the item is readable by the whole configured audience (any earlier restriction is
  lifted), or it is restricted, the Workspace enforces source ACLs, and the connector expanded the
  restriction to member addresses within bounds. The restriction is stored first, so the revision
  that follows is never served as public, not even for one projection.
- **withhold** (``restricted_acl``): restricted, and either the Workspace does not enforce source
  ACLs (the default) or the connector cannot expand this mechanism (a Jira security level).
- **withhold** (``acl_unresolved``): restricted, but the expansion failed or exceeded its bounds.

A withheld item is stored as restricted to nobody before the runner retires what it served, so its
revision history is not readable by evidence key either. An item whose audience could not be
determined at all is the runner's failure, and is never ingested.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...access.acl_keys import MAX_SOURCE_PRINCIPALS
from ...access.source_acl import reproject_source, restrict_source, unrestrict_source
from ...ledger.errors import EvidenceLedgerContractError
from .contract import (
    ACL_AUDIENCE_RESTRICTED,
    ACL_AUDIENCE_SCOPE,
    REASON_ACL_UNRESOLVED,
    REASON_RESTRICTED_ACL,
    AclExpansion,
    ConnectorError,
    SourceConnector,
    SourceItem,
)


@dataclass(frozen=True, slots=True)
class AclDecision:
    """``withhold`` is the fixed reason the item is not ingested; ``None`` means ingest it."""

    audience: str
    withhold: str | None = None
    reprojected: bool = False

    @property
    def restricted(self) -> bool:
        """Its title must not reach the run report, which every Workspace member can read."""
        return self.audience != ACL_AUDIENCE_SCOPE


async def _expansion(connector: SourceConnector, item: SourceItem) -> AclExpansion | str:
    """The expanded restriction, or the fixed reason it cannot be used."""
    if not item.acl.complete:
        return REASON_ACL_UNRESOLVED
    # A connector predating 5b has no expansion: it can never ingest restricted items. A connector
    # reading items with several connections expands each with the one that listed it.
    expand_item = getattr(connector, "expand_item_acl", None)
    expand = getattr(connector, "expand_acl", None)
    if expand_item is None and expand is None:
        return REASON_RESTRICTED_ACL
    try:
        expansion = await (expand_item(item) if expand_item is not None else expand(item.acl))
    except ConnectorError:
        return REASON_ACL_UNRESOLVED
    if expansion is None:
        return REASON_RESTRICTED_ACL
    if type(expansion) is not AclExpansion or len(expansion.member_emails) > MAX_SOURCE_PRINCIPALS:
        return REASON_ACL_UNRESOLVED
    return expansion


async def apply_item_acl(
    db: AsyncSession,
    *,
    connector: SourceConnector,
    project_id: str,
    source_key: str,
    item: SourceItem,
    serves_source: bool,
    enforce: bool,
) -> AclDecision:
    """Store the item's ACL and decide whether it is ingested. Never commits."""
    audience = item.acl.audience
    if audience == ACL_AUDIENCE_SCOPE:
        lifted = await unrestrict_source(db, project_id=project_id, source_key=source_key)
        reprojected = (
            lifted and serves_source and await reproject_source(db, project_id=project_id, source_key=source_key)
        )
        return AclDecision(audience, reprojected=reprojected)
    if audience != ACL_AUDIENCE_RESTRICTED:
        # An undetermined audience is the runner's failure and never reaches this step.
        raise EvidenceLedgerContractError()
    restriction = item.acl.restriction or "restricted"
    expansion: AclExpansion | str = await _expansion(connector, item) if enforce else REASON_RESTRICTED_ACL
    if not isinstance(expansion, AclExpansion):
        # Restricted to nobody until a sync can store who may read it.
        await restrict_source(
            db,
            project_id=project_id,
            source_key=source_key,
            restriction=restriction,
            source_principals=item.acl.principals,
        )
        return AclDecision(audience, withhold=expansion)
    changed = await restrict_source(
        db,
        project_id=project_id,
        source_key=source_key,
        restriction=restriction,
        source_principals=item.acl.principals,
        member_emails=expansion.member_emails,
    )
    reprojected = changed and serves_source and await reproject_source(db, project_id=project_id, source_key=source_key)
    return AclDecision(audience, reprojected=reprojected)


__all__ = ["AclDecision", "apply_item_acl"]
