"""System prompt variants: routing (which base template a turn uses) and rendering.

The base template texts are prompt catalog keys ``system.base.<variant>``
(``services/prompt_catalog``); this module owns only the variant routing, which is
configuration in ``system_config`` (``agent.system_prompt.variant_routing``) with a
per-Workspace override (``agent_system_prompt_overrides.variant_routing``), and the
metadata a turn records about it. A per-Workspace template text is a Workspace-scoped
catalog version.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ....services.prompt_catalog import bound_prompt_set, render_prompt
from ....services.system_config import get_system_config_value, set_system_config_value
from ....services.system_config.constants import AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_VARIANTS = ("bounded_evidence", "minimal", "summary", "admin", "full")

DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING = {
    "bounded_evidence": "bounded_evidence",
    "minimal": "minimal",
    "summary": "summary",
    "admin": "admin",
    "full": "full",
    "standard": "full",
}

PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY = "agent_system_prompt_overrides"


def system_prompt_template_key(variant: str) -> str:
    return f"system.base.{variant}"


def _checksum(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class EffectiveSystemPromptConfig:
    variant_routing: dict[str, str]
    routing_sources: dict[str, str]
    scope: dict[str, object]


def normalize_system_prompt_variant_routing(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip().lower()
        variant = str(raw_value or "").strip().lower()
        if not key or not variant:
            continue
        if variant == "standard":
            variant = "full"
        if key == "bounded_evidence":
            variant = "bounded_evidence"
        if variant not in SYSTEM_PROMPT_VARIANTS:
            continue
        normalized[key] = variant
    return normalized


async def load_system_prompt_variant_routing(db: AsyncSession) -> dict[str, str]:
    """Load DB-backed prompt variant routing overrides and fall back to code defaults."""

    try:
        raw_value = await get_system_config_value(db, AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY)
        if not raw_value:
            return {}
        payload = json.loads(raw_value)
    except (SQLAlchemyError, TypeError, json.JSONDecodeError):
        logger.exception("prompt.variants.load_failed")
        return {}
    return normalize_system_prompt_variant_routing(payload)


async def ensure_system_prompt_variant_routing(db: AsyncSession) -> bool:
    """Seed the variant routing default without overwriting an edit."""

    if await get_system_config_value(db, AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY):
        return False
    await set_system_config_value(
        db,
        key=AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY,
        value=json.dumps(DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING, sort_keys=True),
        description="Canonical system prompt variant routing seed.",
        change_source="bootstrap",
    )
    return True


def resolve_system_prompt_variant(
    prompt_variant: str,
    *,
    prompt_variant_routing: Mapping[str, str] | None = None,
) -> str:
    requested_variant = str(prompt_variant or "full").strip().lower()
    if requested_variant not in DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING:
        requested_variant = "full"
    if requested_variant == "bounded_evidence":
        return "bounded_evidence"
    routed_variant = (
        str(
            (prompt_variant_routing or {}).get(requested_variant)
            or DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING[requested_variant]
        )
        .strip()
        .lower()
    )
    if routed_variant == "standard":
        routed_variant = "full"
    if routed_variant not in SYSTEM_PROMPT_VARIANTS:
        routed_variant = DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING[requested_variant]
    if routed_variant not in SYSTEM_PROMPT_VARIANTS:
        routed_variant = "full"
    return routed_variant


def resolve_effective_system_prompt_config(
    *,
    prompt_variant_routing: Mapping[str, str] | None = None,
    project_config: Mapping[str, object] | None = None,
    project_id: str | None = None,
) -> EffectiveSystemPromptConfig:
    """Merge the global variant routing with the validated Workspace routing override."""

    global_routing = normalize_system_prompt_variant_routing(dict(prompt_variant_routing or {}))
    routing_sources = {key: "db" for key in global_routing}

    overrides = {}
    if isinstance(project_config, Mapping):
        raw_overrides = project_config.get(PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY)
        overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
    project_routing = normalize_system_prompt_variant_routing(overrides.get("variant_routing") if overrides else None)

    effective_routing = {**global_routing, **project_routing}
    for key in project_routing:
        routing_sources[key] = "project"

    scope: dict[str, object] = {"type": "global"}
    if project_routing:
        scope = {
            "type": "project",
            "project_id": str(project_id or ""),
            "config_key": PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY,
            "routing_overrides": sorted(project_routing),
        }

    return EffectiveSystemPromptConfig(
        variant_routing=effective_routing,
        routing_sources=routing_sources,
        scope=scope,
    )


def build_system_prompt_config_metadata(
    *,
    requested_variant: str,
    prompt_variant_routing: Mapping[str, str] | None = None,
    routing_sources: Mapping[str, str] | None = None,
    scope: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Describe the prompt config used for a turn without storing full prompt text.

    The template is named by its catalog reference (``system.base.<variant>@<version>``)
    and digest from the turn's bound prompt set.
    """

    routing = prompt_variant_routing or {}
    normalized_requested = str(requested_variant or "full").strip().lower() or "full"
    if normalized_requested not in DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING:
        normalized_requested = "full"
    resolved_variant = resolve_system_prompt_variant(normalized_requested, prompt_variant_routing=routing)
    template_key = system_prompt_template_key(resolved_variant)
    prompt_set = bound_prompt_set()
    template: dict[str, object] = {"key": template_key}
    if prompt_set is not None:
        template.update(prompt_set.resolved(template_key).audit_entry())
    routing_source = str((routing_sources or {}).get(normalized_requested) or "").strip()
    if not routing_source:
        routing_source = "db" if routing else "fallback"
    routing_json = _stable_json(routing or DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING)
    routing_config_key = AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY
    if routing_source == "project":
        routing_config_key = f"{PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY}.variant_routing.{normalized_requested}"
    return {
        "source": "prompt_catalog",
        "scope": dict(scope or {"type": "global"}),
        "requested_variant": normalized_requested,
        "resolved_variant": resolved_variant,
        "template": template,
        "routing": {
            "source": routing_source,
            "config_key": routing_config_key,
            "checksum": _checksum(routing_json),
            "entries": len(routing or DEFAULT_SYSTEM_PROMPT_VARIANT_ROUTING),
        },
    }


def render_system_prompt_template(
    prompt_variant: str,
    *,
    mode_name: str,
    mode_behavior_line: str,
    prompt_variant_routing: Mapping[str, str] | None = None,
) -> str:
    variant = resolve_system_prompt_variant(prompt_variant, prompt_variant_routing=prompt_variant_routing)
    return render_prompt(
        system_prompt_template_key(variant),
        mode_name=mode_name,
        mode_behavior_line=mode_behavior_line,
    ).strip()
