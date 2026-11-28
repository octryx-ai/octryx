"""``knowledge_changes`` over a Knowledge scope. Facts come from exactly one Workspace, never merged across graphs."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.bindings import KnowledgeScope
from ..ledger.errors import EvidenceLedgerError, EvidenceLedgerState
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products
from .changes import STATE_OK, knowledge_changes
from .changes_facts import ChangesResult
from .errors import GraphStoreError


async def scoped_changes(
    db: AsyncSession, *, runtime: EvidenceRuntime, scope: KnowledgeScope, product: object, **options
) -> tuple[str, ChangesResult]:
    requested = tuple(normalize_products(product)) if product else ()
    targets = [scope.primary, *(s.authorized for s in scope.sources if s.products_for(requested) is not None)]
    own: ChangesResult | Exception | None = None
    for authorized in targets:
        try:
            result = await knowledge_changes(db, runtime=runtime, authorized=authorized, product=product, **options)
        except EvidenceLedgerError as error:
            if error.state is EvidenceLedgerState.INVALID_REQUEST:
                raise
            result = error
        except GraphStoreError as error:
            result = error
        if authorized is scope.primary:
            own = result
        if isinstance(result, ChangesResult) and result.state == STATE_OK:
            return authorized.project_id, result
    if isinstance(own, Exception):
        raise own
    return scope.primary.project_id, own


__all__ = ["scoped_changes"]
