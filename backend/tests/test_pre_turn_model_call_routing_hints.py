"""A stored routing hint never decides the next turn's runtime resolution, and routing modules import no provider factory or runtime resolution."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.agent.core.context.run_context_routing import resolve_turn_routing_profile
from app.services.system_config.values import set_system_config_value
from app.services.workflow_routing.support_signature import (
    SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY,
    SUPPORT_REQUEST_SIGNATURE_DISABLED,
)
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

pytestmark = pytest.mark.workflow_proposals


ERROR_EVIDENCE = "I am seeing a stack trace: the simulation failed with a SQLServerException after a read timed out."


def _stored_metadata(intent: str | None = None, source: str | None = None) -> dict:
    metadata = {
        ROUTING_RESOLUTION_KEY: {"source": "workflow_routing_policy", "status": "unmatched"},
        "execution_profile": {"status": "allowed", "decision_source": "explicit_ui_context"},
    }
    if intent:
        metadata.update(
            {
                "routing_intent": intent,
                "routing_reason": f"{source}:earlier turn",
                "routing_intent_confidence": 0.97,
                "routing_intent_source": source,
            }
        )
    return metadata


async def _runtime_resolution(db, metadata: dict, message: str):
    return await resolve_turn_routing_profile(
        db=db,
        session_metadata=metadata,
        user_message=message,
        agent_type="chat",
        project_id=None,
        agent_definition=None,
        runtime_target_id=None,
    )


_ROUTING_MODULES = (
    "app/web/_helpers/chat_turn_prepare.py",
    "app/services/session/turn_prepare.py",
    "app/services/session/turn_routing_resolution.py",
    "app/services/session/turn_runtime_selection.py",
    "app/services/session/turn_agent_selection.py",
    "app/services/session/turn_start.py",
    "app/services/execution_strategy_service.py",
    "app/agent/core/context/run_context_routing.py",
)


_FORBIDDEN_ROUTING_IMPORTS = {
    "get_provider",
    "resolve_control_plane_runtimes",
    "resolve_control_plane_runtime",
    "_resolve_control_plane_runtimes_impl",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_intent", "stored_source", "message"),
    [
        ("coding", "llm", "continue"),
        ("documentation", "default", "weiter"),
        ("knowledge", "policy", "continue with that"),
        ("support_request", "signature", "retry"),
    ],
)
async def test_runtime_re_resolution_never_decides_from_a_stored_hint(db, stored_intent, stored_source, message):
    """/api/v1 shape: the runtime reads metadata an earlier turn stored; its hints must not decide."""
    metadata = _stored_metadata(stored_intent, stored_source)

    resolution = await _runtime_resolution(db, metadata, message)

    assert resolution.strategy_decision.routing_intent == "diagnosis"
    assert resolution.strategy_decision.routing_reason == "intent:diagnosis_default"
    assert resolution.strategy_decision.execution_strategy == "direct"
    assert resolution.expected_workflow_id == ""
    assert resolution.effective_agent_type == "chat"
    assert metadata["routing_intent_source"] == "default"
    assert resolution.execution_profile_metadata["profile_id"] == "direct_chat_safe"


@pytest.mark.asyncio
async def test_runtime_evaluates_the_support_signature_for_the_current_turn_without_a_stored_hint(db):
    """Same routing on every entry path: an /api/v1-only session classifies error evidence too."""
    resolution = await _runtime_resolution(db, _stored_metadata(), ERROR_EVIDENCE)

    assert resolution.strategy_decision.routing_intent == "support_request"
    assert resolution.strategy_decision.routing_intent_source == "signature"


@pytest.mark.asyncio
async def test_runtime_honours_the_current_signature_switch_over_a_stored_signature_hint(db):
    await set_system_config_value(
        db,
        key=SUPPORT_REQUEST_SIGNATURE_CONFIG_KEY,
        value=SUPPORT_REQUEST_SIGNATURE_DISABLED,
        record_prompt_revision=False,
    )

    resolution = await _runtime_resolution(db, _stored_metadata("support_request", "signature"), ERROR_EVIDENCE)

    assert resolution.strategy_decision.routing_intent == "diagnosis"
    assert resolution.strategy_decision.routing_reason == "intent:diagnosis_default"
    assert resolution.execution_profile_metadata["profile_id"] == "direct_chat_safe"


def test_routing_modules_import_no_provider_factory_or_runtime_resolution():
    """Static guard: a re-added pre-turn call via an import-time binding still fails here."""
    backend_root = Path(__file__).resolve().parents[1]
    for relative in _ROUTING_MODULES:
        tree = ast.parse((backend_root / relative).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.update(alias.name for alias in node.names)
                assert "providers" not in module.split("."), f"{relative} imports {module}"
                assert not module.endswith("control_plane.resolution"), f"{relative} imports {module}"
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert not imported & _FORBIDDEN_ROUTING_IMPORTS, f"{relative} imports {imported & _FORBIDDEN_ROUTING_IMPORTS}"
