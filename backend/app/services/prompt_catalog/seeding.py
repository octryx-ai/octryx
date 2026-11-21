"""Seed the prompt catalog from the code constants, idempotently, never over an admin edit.

For each registered key at global scope:

* no template yet: create it with version 1 = the seed, published;
* the seed text already exists as some version (any state): nothing to do;
* the published version is a seed and the code seed changed: publish the new seed
  (the old seed version is retired);
* otherwise (an admin or imported version is published, or nothing is published
  because an admin retired it): add the new seed as a **draft** only, so an admin can
  diff and decide. A published admin edit is never replaced.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.governed_revision import REVISION_STATE_DRAFT, REVISION_STATE_PUBLISHED
from ...models.runtime.prompt_template import (
    PROMPT_SCOPE_GLOBAL,
    PROMPT_SOURCE_SEED,
    PromptTemplate,
)
from .contract import PromptKeySpec, prompt_digest
from .registry import static_prompt_key_registry
from .store import (
    add_audit,
    add_version,
    published_version,
    stage_template_with_published_version,
    templates_in_scope,
)

logger = logging.getLogger(__name__)

SEED_AUDIT_ACTION = "prompt_catalog.seed"

async def ensure_prompt_catalog_seed(db: AsyncSession, *, admin_user: User) -> dict[str, int]:
    counts = {"created": 0, "seed_updated": 0, "seed_drafted": 0, "unchanged": 0}
    # One read of the global scope and one flush for the new keys: a fresh database seeds ~800 keys, and a write
    # round trip per key made every start (and every test reseed) take seconds.
    existing = await templates_in_scope(db, scope_type=PROMPT_SCOPE_GLOBAL, scope_id=None)
    # Dynamic keys (tool and MCP descriptions) are seeded by code and get rows only when edited.
    for spec in static_prompt_key_registry().values():
        template = existing.get(spec.key)
        if template is None:
            _stage_seeded_template(db, spec, admin_user=admin_user)
            counts["created"] += 1
        else:
            counts[await _reseed_existing(db, template, spec, admin_user=admin_user)] += 1
    await db.flush()
    if counts["created"] or counts["seed_updated"] or counts["seed_drafted"]:
        logger.info("prompt_catalog.seeded", extra={f"prompt_{key}": value for key, value in counts.items()})
    return counts


def _stage_seeded_template(db: AsyncSession, spec: PromptKeySpec, *, admin_user: User) -> None:
    template, version = stage_template_with_published_version(
        db,
        key=spec.key,
        scope_type=PROMPT_SCOPE_GLOBAL,
        scope_id=None,
        body=spec.seed,
        source=PROMPT_SOURCE_SEED,
        created_by=admin_user.id,
        change_note="Seeded from the code constant.",
    )
    add_audit(db, user_id=admin_user.id, action=SEED_AUDIT_ACTION, template=template, details=_facts(version))


async def _reseed_existing(db: AsyncSession, template: PromptTemplate, spec: PromptKeySpec, *, admin_user: User) -> str:
    seed_digest = prompt_digest(spec.seed)
    if any(item.source == PROMPT_SOURCE_SEED and item.digest == seed_digest for item in template.versions):
        return "unchanged"
    current = await published_version(db, template)
    publish = current is not None and current.source == PROMPT_SOURCE_SEED
    version = await add_version(
        db,
        template=template,
        body=spec.seed,
        source=PROMPT_SOURCE_SEED,
        state=REVISION_STATE_PUBLISHED if publish else REVISION_STATE_DRAFT,
        created_by=admin_user.id,
        change_note="New code seed." if publish else "New code seed; an admin version stays published.",
    )
    add_audit(db, user_id=admin_user.id, action=SEED_AUDIT_ACTION, template=template, details=_facts(version))
    return "seed_updated" if publish else "seed_drafted"


def _facts(version: Any) -> dict[str, object]:
    return {"version": version.version, "digest": version.digest, "state": version.state, "source": version.source}


__all__ = [
    "SEED_AUDIT_ACTION",
    "ensure_prompt_catalog_seed",
]
