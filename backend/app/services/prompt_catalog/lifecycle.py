"""Admin lifecycle of the System prompt texts: draft, submit, publish, retire, revert to shipped.

Every operation refuses with a closed :class:`PromptCatalogRefusal` code instead of
guessing. A draft is validated against its key's placeholder contract when it is
written and again when it is published, so an unknown placeholder never reaches a
turn. Every key, whatever its risk,
goes through ``in_review`` and a four-eyes approval (``services/prompt_catalog/governance``).
An override may be global or scoped to a workflow or a Workspace (the workflow owner defines the flow; four eyes
still apply): a ``workflow:<flow key>`` text by the workflow's owner, a
``workspace:<id>`` text by the Workspace's owners and admins (``scope_rights``), each through the same draft →
review → approval by another person → publish; agent guidance stays in the agent's own instructions. "Revert to
shipped" publishes the code seed again without review (it is the
reviewed product text). Every change writes an audit row with ids, versions and digests only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_RETIRED,
)
from ...models.runtime.prompt_template import (
    PROMPT_SCOPE_GLOBAL,
    PROMPT_SCOPE_WORKFLOW,
    PROMPT_SOURCE_ADMIN,
    PROMPT_SOURCE_SEED,
    PromptTemplate,
    PromptTemplateVersion,
)
from ...time_utils import utc_now
from ..governance.four_eyes import SelfApprovalRefusedError, self_approve_review
from .contract import REASON_UNKNOWN_KEY, PromptTemplateUnavailableError, prompt_digest, validate_body
from .governance import check_publish_approval, create_review_approval
from .registry import is_known_prompt_key, prompt_key_spec
from .scope_rights import may_write, workflow_exists
from .scopes import PromptScopeError, normalized_scope
from .store import (
    add_audit,
    add_version,
    create_template,
    find_template,
    publish_existing,
    published_version,
    retire_version,
)


class PromptCatalogRefusal(Exception):  # noqa: N818 - a closed refusal, not an error condition
    def __init__(self, code: str, status: int = 409, **facts: object) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.facts = facts

    def as_detail(self) -> dict[str, object]:
        return {"code": self.code, **self.facts}


REFUSAL_SCOPE_FORBIDDEN = "prompt_scope_forbidden"
REFUSAL_ALREADY_SHIPPED = "prompt_already_shipped"


def _validated(key: str, body: str) -> None:
    try:
        validate_body(prompt_key_spec(key), body)
    except PromptTemplateUnavailableError as refusal:
        if refusal.reason == REASON_UNKNOWN_KEY:
            raise PromptCatalogRefusal("prompt_key_not_found", 404, key=key) from None
        raise PromptCatalogRefusal(
            refusal.code, 422, key=key, reason=refusal.reason, names=list(refusal.names)
        ) from None


async def create_draft(
    db: AsyncSession,
    *,
    key: str,
    scope_type: str | None,
    scope_id: str | None,
    body: str,
    change_note: str,
    user: User,
) -> tuple[PromptTemplate, PromptTemplateVersion]:
    try:
        kind, ident = normalized_scope(scope_type, scope_id)
    except PromptScopeError as refusal:
        raise PromptCatalogRefusal(refusal.code, 422) from None
    if kind == PROMPT_SCOPE_WORKFLOW and not await workflow_exists(db, str(ident)):
        raise PromptCatalogRefusal("prompt_workflow_not_found", 404, workflow=ident)
    await require_rights(db, user, kind, ident)
    _validated(key, body)
    template = await find_template(db, key=key, scope_type=kind, scope_id=ident)
    if template is None:
        template = await create_template(db, key=key, scope_type=kind, scope_id=ident, created_by=user.id)
    version = await add_version(
        db,
        template=template,
        body=body,
        source=PROMPT_SOURCE_ADMIN,
        state=REVISION_STATE_DRAFT,
        created_by=user.id,
        change_note=change_note,
    )
    add_audit(db, user_id=user.id, action="prompt_catalog.draft", template=template, details=_facts(version))
    return template, version


async def require_rights(db: AsyncSession, user: User, scope_type: str, scope_id: str | None) -> None:
    """The user may write at this scope (``scope_rights``); else ``prompt_scope_forbidden``."""
    if not await may_write(db, user.id, scope_type, scope_id):
        raise PromptCatalogRefusal(REFUSAL_SCOPE_FORBIDDEN, 403, scope_type=scope_type)


async def load_version(db: AsyncSession, version_id: str) -> tuple[PromptTemplate, PromptTemplateVersion]:
    version = await db.get(PromptTemplateVersion, version_id)
    if version is None:
        raise PromptCatalogRefusal("prompt_version_not_found", 404)
    template = await db.get(PromptTemplate, version.template_id)
    if template is None:
        raise PromptCatalogRefusal("prompt_version_not_found", 404)
    return template, version


async def submit_for_review(db: AsyncSession, *, version_id: str, user: User) -> PromptTemplateVersion:
    template, version = await load_version(db, version_id)
    await require_rights(db, user, template.scope_type, template.scope_id)
    if version.state != REVISION_STATE_DRAFT:
        raise PromptCatalogRefusal("prompt_version_not_draft", state=version.state)
    _validated(template.key, version.body)
    approval = await create_review_approval(db, template=template, version=version, requested_by=user.id)
    now = utc_now()
    version.state = REVISION_STATE_IN_REVIEW
    version.submitted_by = user.id
    version.submitted_at = now
    version.approval_id = approval.id
    version.updated_at = now
    await db.flush()
    add_audit(db, user_id=user.id, action="prompt_catalog.submit", template=template, details=_facts(version))
    return version


async def publish(
    db: AsyncSession, *, version_id: str, user: User, approval_id: str | None, self_approve: bool = False
) -> tuple[PromptTemplateVersion, dict[str, object] | None]:
    template, version = await load_version(db, version_id)
    await require_rights(db, user, template.scope_type, template.scope_id)
    _validated(template.key, version.body)
    # Every key needs the four-eyes review, standard risk included.
    if version.state != REVISION_STATE_IN_REVIEW:
        raise PromptCatalogRefusal("prompt_review_required", state=version.state)
    if self_approve and not approval_id:
        try:
            approval_id = await self_approve_review(db, version.approval_id, actor_id=user.id)
        except SelfApprovalRefusedError as error:
            raise PromptCatalogRefusal(error.code) from None
    gate = await check_publish_approval(
        db, template=template, version=version, approval_id=approval_id or version.approval_id
    )
    gate_payload: dict[str, object] = gate.as_dict()
    if not gate.passed:
        raise PromptCatalogRefusal("governance_approval_required", approval_gate=gate_payload)
    await publish_existing(db, template=template, version=version, published_by=user.id, approval_id=gate.approval_id)
    details = _facts(version)
    if gate_payload and gate_payload.get("approval_mode"):
        details["approval_mode"] = gate_payload["approval_mode"]
    add_audit(db, user_id=user.id, action="prompt_catalog.publish", template=template, details=details)
    return version, gate_payload


async def retire(db: AsyncSession, *, version_id: str, user: User) -> PromptTemplateVersion:
    template, version = await load_version(db, version_id)
    await require_rights(db, user, template.scope_type, template.scope_id)
    if version.state == REVISION_STATE_RETIRED:
        raise PromptCatalogRefusal("prompt_version_retired")
    retire_version(version, retired_by=user.id)
    await db.flush()
    add_audit(db, user_id=user.id, action="prompt_catalog.retire", template=template, details=_facts(version))
    return version


async def revert_to_shipped(db: AsyncSession, *, key: str, user: User) -> PromptTemplateVersion:
    """Publish the shipped code text of ``key`` again (global); no review, it is the product's reviewed text."""
    if not is_known_prompt_key(key):
        raise PromptCatalogRefusal("prompt_key_not_found", 404, key=key)
    spec = prompt_key_spec(key)
    template = await find_template(db, key=key, scope_type=PROMPT_SCOPE_GLOBAL, scope_id=None)
    current = await published_version(db, template) if template is not None else None
    if current is None or (current.source == PROMPT_SOURCE_SEED and current.digest == prompt_digest(spec.seed)):
        raise PromptCatalogRefusal(REFUSAL_ALREADY_SHIPPED, key=key)
    version = await add_version(
        db, template=template, body=spec.seed, source=PROMPT_SOURCE_SEED, state=REVISION_STATE_DRAFT,
        created_by=user.id, change_note="Reverted to the shipped text.",
    )
    await publish_existing(db, template=template, version=version, published_by=user.id, approval_id=None)
    add_audit(db, user_id=user.id, action="prompt_catalog.revert", template=template, details=_facts(version))
    return version


async def versions_of(db: AsyncSession, template_ids: list[str]) -> list[PromptTemplateVersion]:
    if not template_ids:
        return []
    return list(
        (
            await db.execute(
                select(PromptTemplateVersion)
                .where(PromptTemplateVersion.template_id.in_(template_ids))
                .order_by(PromptTemplateVersion.version.asc())
            )
        )
        .scalars()
        .all()
    )


def _facts(version: PromptTemplateVersion) -> dict[str, object]:
    return {"version": version.version, "digest": version.digest, "state": version.state}


__all__ = [
    "PromptCatalogRefusal",
    "create_draft",
    "load_version",
    "publish",
    "retire",
    "revert_to_shipped",
    "submit_for_review",
    "versions_of",
]
