"""A published edit changes the next turn's prompt and its trace, catalog texts keep the fixed answer contract and the evidence guard marker, and system prompt texts are global-only."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import TurnTrace
from app.services.prompt_catalog import lifecycle
from app.services.prompt_catalog.contract import prompt_digest
from app.services.prompt_catalog.registry import prompt_key_registry, prompt_key_spec
from tests.product_run_chat_binding_support import FINAL_RESPONSE, _session, _turn
from tests.product_run_chat_support import world  # noqa: F401 - fixture
from tests.prompt_catalog_contract_support import KEY, _admin, _publish
from tests.prompt_catalog_publish_support import publish_reviewed

# sha256 of the E1 reminder (``answer_evidence/texts.py`` before the catalog) for fixed details.
E1_REMINDER_DIGEST = "4a4094da658e1f2713666769a536df2bb52ba35ba4111bc8bbbfff14f181d01d"


@pytest.mark.asyncio
async def test_a_published_edit_changes_the_next_turn_and_the_trace_records_it(db, world, monkeypatch) -> None:  # noqa: F811
    import app.agent.engine as engine_module
    import app.agent.providers as providers_module

    session = await _session(db)
    sent: list[str] = []

    def capturing_provider(**_kwargs):
        class _Provider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                sent.append("\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "system"))
                return {**FINAL_RESPONSE, "model": model or ""}

            async def close(self):
                return None

        return _Provider()

    monkeypatch.setattr(providers_module, "get_provider", capturing_provider)
    monkeypatch.setattr(engine_module, "get_provider", capturing_provider)
    body = "## Dynamic Context Prompts\n- Workspace override marker."

    async for _event in _turn(db, session):
        pass
    await _publish(db, "system.dynamic_context_prompts", body, scope_type="workspace", scope_id=session.project_id)
    await db.commit()
    async for _event in _turn(db, session):
        pass

    assert len(sent) == 2
    assert "Workspace override marker." not in sent[0]
    assert "Workspace override marker." in sent[1]
    traces = (
        await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at))
    ).scalars().all()
    first_used = traces[0].context_snapshot_json["prompt_templates"]["used"]
    last_used = traces[-1].context_snapshot_json["prompt_templates"]["used"]
    assert first_used["system.dynamic_context_prompts"]["source"] == "global"
    assert last_used["system.dynamic_context_prompts"] == {
        "ref": "system.dynamic_context_prompts@1",
        "version": 1,
        "digest": prompt_digest(body),
        "source": "workspace",
        "scope_id": session.project_id,
    }
    base = traces[-1].context_snapshot_json["prompt_config"]["template"]
    assert last_used[base["key"]]["digest"] == base["digest"]


def test_the_proposal_prompt_is_catalog_text_around_the_fixed_answer_contract() -> None:
    from app.services.workflow_routing.proposal_contract import PROPOSAL_ANSWER_CONTRACT, build_proposal_prompt

    system, user = build_proposal_prompt([{"workflow_key": "k", "name": "K", "description": "d"}], "hi")

    assert PROPOSAL_ANSWER_CONTRACT in system
    assert "fit read-only workflows" in system
    assert system.endswith('Workflow catalog (JSON):\n[{"description": "d", "name": "K", "workflow_key": "k"}]')
    # The instruction is labelled apart from quoted content.
    assert user == "User instruction:\nhi"


def test_the_evidence_guard_reminder_keeps_its_code_marker_around_the_catalog_text() -> None:
    from hashlib import sha256

    from app.services.answer_evidence.texts import REMINDER_MARKER, guard_text

    reminder = guard_text("evidence_guard.reminder", details="2 statement(s) have no source link.")

    assert reminder.startswith(REMINDER_MARKER + " Your answer uses this turn's tool evidence")
    # Pin the proportionate revision for the same details.
    assert sha256(reminder.encode()).hexdigest() == E1_REMINDER_DIGEST


@pytest.mark.asyncio
async def test_system_prompt_texts_are_global_only_reviewed_for_every_key_and_revert_to_shipped(db) -> None:
    """Only the closed scopes exist (workflow and Workspace texts: see test_prompt_scope_rights.py), a
    standard-risk key needs the review too, revert is one step."""
    admin = await _admin(db)
    with pytest.raises(lifecycle.PromptCatalogRefusal) as scoped:
        await lifecycle.create_draft(
            db, key=KEY, scope_type="agent_definition", scope_id="agent-1", body="x", change_note="", user=admin
        )
    assert (scoped.value.code, scoped.value.status) == ("prompt_scope_invalid", 422)

    standard_key = next(key for key, spec in prompt_key_registry().items()
                        if spec.risk == "standard" and not spec.placeholders and not spec.literal)
    _template, draft = await lifecycle.create_draft(
        db, key=standard_key, scope_type="global", scope_id=None, body="Edited.", change_note="", user=admin
    )
    with pytest.raises(lifecycle.PromptCatalogRefusal) as unreviewed:
        await lifecycle.publish(db, version_id=draft.id, user=admin, approval_id=None)
    assert unreviewed.value.code == "prompt_review_required"

    with pytest.raises(lifecycle.PromptCatalogRefusal) as shipped:
        await lifecycle.revert_to_shipped(db, key=KEY, user=admin)
    assert shipped.value.code == "prompt_already_shipped"
    await publish_reviewed(db, KEY, "Global edit.")
    reverted = await lifecycle.revert_to_shipped(db, key=KEY, user=admin)
    assert (reverted.state, reverted.source, reverted.body) == ("published", "seed", prompt_key_spec(KEY).seed)
