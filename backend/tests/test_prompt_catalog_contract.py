"""Contract of the governed prompt catalog (``services/prompt_catalog``).

Precedence (Workspace > global published > seed), explicit refusal
(``prompt_template_unavailable``, never an empty string or a silent fallback), the
closed placeholder set enforced on write, the idempotent seed that never replaces a
published admin edit, four-eyes publication of high-risk keys, and the end-to-end
path: a published edit changes the next turn's prompt and the turn trace records
``key@version`` with its digest.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, AuditLog, Project, Role, User, UserRole
from app.models.runtime.prompt_template import PromptTemplate, PromptTemplateVersion
from app.services.prompt_catalog import (
    PromptTemplateUnavailableError,
    lifecycle,
    prompt_set_scope,
    render_prompt,
    resolve_prompt_set,
    seed_prompt_set,
)
from app.services.prompt_catalog.registry import prompt_key_spec
from app.services.prompt_catalog.seeding import ensure_prompt_catalog_seed
from app.services.prompt_catalog.store import add_version, create_template
from tests.prompt_catalog_contract_support import KEY, _admin, _publish

HIGH_RISK_KEY = "system.base.full"


async def _workspace(db) -> Project:
    project = Project(name=f"prompt-ws-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    return project


@pytest.mark.asyncio
async def test_precedence_is_workspace_then_global_then_seed(db) -> None:
    admin = await _admin(db)
    workspace = await _workspace(db)

    async def body(workspace_id: str | None) -> tuple[str, str]:
        prompt_set = await resolve_prompt_set(db, workspace_id=workspace_id)
        with prompt_set_scope(prompt_set):
            return render_prompt(KEY), prompt_set.usage()[KEY]["source"]

    assert await body(workspace.id) == (prompt_key_spec(KEY).seed, "global")
    await _publish(db, KEY, "Global edit.")
    await _publish(db, KEY, "Workspace edit.", scope_type="workspace", scope_id=workspace.id)

    assert await body(workspace.id) == ("Workspace edit.", "workspace")
    assert await body(None) == ("Global edit.", "global")

    global_template = (
        await db.execute(select(PromptTemplate).where(PromptTemplate.key == KEY, PromptTemplate.scope_key == "global"))
    ).scalar_one()
    published = (
        await db.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == global_template.id, PromptTemplateVersion.state == "published"
            )
        )
    ).scalar_one()
    await lifecycle.retire(db, version_id=published.id, user=admin)
    # Nothing published at global any more: the code seed is the last level, recorded as such.
    assert await body(None) == (prompt_key_spec(KEY).seed, "seed")


@pytest.mark.asyncio
async def test_missing_unbound_and_invalid_templates_are_explicit_refusals(db) -> None:
    with pytest.raises(PromptTemplateUnavailableError) as unknown:
        seed_prompt_set().render("system.no_such_key")
    assert (unknown.value.code, unknown.value.reason) == ("prompt_template_unavailable", "unknown_key")

    with prompt_set_scope(None), pytest.raises(PromptTemplateUnavailableError) as unbound:
        render_prompt(KEY)
    assert unbound.value.reason == "prompt_set_unbound"

    with pytest.raises(PromptTemplateUnavailableError) as unbound_placeholder:
        seed_prompt_set().render("system.mode_instructions_line")
    assert unbound_placeholder.value.reason == "placeholder_unbound"

    # A published Workspace body that no longer fits the key's contract is refused, not skipped for global.
    admin = await _admin(db)
    workspace = await _workspace(db)
    template = await create_template(db, key=KEY, scope_type="workspace", scope_id=workspace.id, created_by=admin.id)
    await add_version(
        db, template=template, body="Uses {secret}.", source="admin", state="published", created_by=admin.id, change_note=""
    )
    prompt_set = await resolve_prompt_set(db, workspace_id=workspace.id)
    with pytest.raises(PromptTemplateUnavailableError) as invalid:
        prompt_set.render(KEY)
    assert (invalid.value.reason, invalid.value.names) == ("placeholder_unknown", ("secret",))


@pytest.mark.asyncio
async def test_unknown_placeholders_are_refused_when_a_draft_is_written(db) -> None:
    admin = await _admin(db)

    with pytest.raises(lifecycle.PromptCatalogRefusal) as refused:
        await lifecycle.create_draft(
            db, key=HIGH_RISK_KEY, scope_type="global", scope_id=None,
            body="Mode {mode_name}, user {user_email}.", change_note="", user=admin,
        )
    assert refused.value.status == 422
    assert refused.value.as_detail() == {
        "code": "prompt_template_unavailable",
        "key": HIGH_RISK_KEY,
        "reason": "placeholder_unknown",
        "names": ["user_email"],
    }
    with pytest.raises(lifecycle.PromptCatalogRefusal) as unknown_key:
        await lifecycle.create_draft(
            db, key="system.invented", scope_type="global", scope_id=None, body="x", change_note="", user=admin
        )
    assert (unknown_key.value.code, unknown_key.value.status) == ("prompt_key_not_found", 404)


@pytest.mark.asyncio
async def test_high_risk_keys_publish_only_with_a_four_eyes_approval(db) -> None:
    admin = await _admin(db)
    reviewer = User(username=f"reviewer-{uuid.uuid4().hex[:6]}", email=f"r-{uuid.uuid4().hex[:6]}@x.test", password_hash="x")
    db.add(reviewer)
    await db.flush()
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=reviewer.id, role_id=admin_role.id))
    _template, version = await lifecycle.create_draft(
        db, key=HIGH_RISK_KEY, scope_type="global", scope_id=None,
        body="Reviewed base prompt for {mode_name}.", change_note="", user=admin,
    )

    with pytest.raises(lifecycle.PromptCatalogRefusal) as unreviewed:
        await lifecycle.publish(db, version_id=version.id, user=admin, approval_id=None)
    assert unreviewed.value.code == "prompt_review_required"

    submitted = await lifecycle.submit_for_review(db, version_id=version.id, user=admin)
    approval = await db.get(Approval, submitted.approval_id)
    assert (submitted.state, approval.status, approval.workspace_id) == ("in_review", "pending", None)
    assert approval.action == f"prompt_template.publish:{version.id}:{version.digest}"
    with pytest.raises(lifecycle.PromptCatalogRefusal) as pending:
        await lifecycle.publish(db, version_id=version.id, user=admin, approval_id=approval.id)
    assert pending.value.code == "governance_approval_required"

    approval.status, approval.approved_by = "approved", reviewer.id
    published, gate = await lifecycle.publish(db, version_id=version.id, user=admin, approval_id=approval.id)

    assert (published.state, published.approval_id, gate["status"]) == ("published", approval.id, "approved")
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.resource_id == version.template_id))).scalars()
    assert {"prompt_catalog.draft", "prompt_catalog.submit", "prompt_catalog.publish"} <= set(actions)


@pytest.mark.asyncio
async def test_the_seed_is_idempotent_and_never_replaces_a_published_admin_edit(db, monkeypatch) -> None:
    admin = await _admin(db)
    assert (await ensure_prompt_catalog_seed(db, admin_user=admin))["created"] == 0  # the baseline seeded already
    await _publish(db, KEY, "Admin wording.")

    from app.services.prompt_catalog import seeding

    spec = prompt_key_spec(KEY)
    changed = type(spec)(**{**spec.__dict__, "seed": spec.seed + " New release wording."})
    monkeypatch.setattr(seeding, "static_prompt_key_registry", lambda: {KEY: changed})
    first = await ensure_prompt_catalog_seed(db, admin_user=admin)
    second = await ensure_prompt_catalog_seed(db, admin_user=admin)

    assert (first["seed_drafted"], second["unchanged"]) == (1, 1)
    prompt_set = await resolve_prompt_set(db, workspace_id=None)
    assert prompt_set.render(KEY) == "Admin wording."
    states = {
        (row.source, row.state)
        for row in (
            await db.execute(
                select(PromptTemplateVersion)
                .join(PromptTemplate)
                .where(PromptTemplate.key == KEY, PromptTemplate.scope_key == "global")
            )
        ).scalars()
    }
    assert states == {("seed", "retired"), ("admin", "published"), ("seed", "draft")}
