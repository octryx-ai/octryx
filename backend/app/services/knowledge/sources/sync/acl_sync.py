"""The ACL step of one synced item: store the source's restriction before anything is ingested. It runs before the
version check: an ACL can change alone."""

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
    audience: str
    withhold: str | None = None
    reprojected: bool = False

    @property
    def restricted(self) -> bool:
        # The title must not reach the run report, which every Workspace member can read.
        return self.audience != ACL_AUDIENCE_SCOPE


async def _expansion(connector: SourceConnector, item: SourceItem) -> AclExpansion | str:
    if not item.acl.complete:
        return REASON_ACL_UNRESOLVED
    # A connector without expansion can never ingest restricted items. A connector reading items with several
    # connections expands each with the one that listed it.
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
