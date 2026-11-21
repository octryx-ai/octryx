"""Admission of one inbound Anthropic Messages call (dispatch owner
``model_gateway_inbound_anthropic``).

The Workspace is the one the gateway identity resolved from the token and the
``X-Octryx-Workspace`` header; it is passed as both the scope and the
authorized scope, so nothing in the request body can widen it. Then:

1. ``resolve_workspace_admission`` reads the Workspace's own ``model_policy`` and
   data classification from the project row;
2. the gateway provider is the single active ``litellm_gateway`` provider whose
   alias catalog lists the requested alias — none is ``denied/alias_not_listed``,
   more than one is ``needs_configuration/alias_provider_ambiguous`` (never a
   silent pick);
3. the same three layers as the governed driver (``litellm/entry_admission``):
   project grant, catalog admission, data policy;
4. the alias must declare the ``tools`` capability when the request carries
   tools (declared configuration only; the catalog probe is not consulted here);
5. the validated :class:`LiteLLMGatewayConfig` is built from the provider row
   and its virtual key, resolved through the Secret Reference boundary by the
   shared provider client-kwargs builder.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMProvider
from ...agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ..data_policy import DataPolicyDecision
from ..dispatch_admission import resolve_workspace_admission
from ..litellm.alias_catalog import CAPABILITY_TOOLS, AliasEntry, gateway_config_section
from ..litellm.client import CAPABILITY_DENIAL_NOT_DECLARED
from ..litellm.config import LiteLLMGatewayConfig, build_gateway_config
from ..litellm.entry_admission import admitted_alias_entry
from ..litellm.errors import GATEWAY_STATE_CAPABILITY_NOT_PROVEN, LiteLLMGatewayError
from ..litellm.evidence import build_call_evidence
from ..litellm.project_admission import ProjectModelAdmission
from ..litellm.runtime_admission import LITELLM_GATEWAY_DRIVER
from .refusals import (
    REASON_ALIAS_NOT_LISTED,
    REASON_ALIAS_PROVIDER_AMBIGUOUS,
    InboundRefusal,
    refusal,
    refusal_for_admission_error,
)

INBOUND_DISPATCH_OWNER = "model_gateway_inbound_anthropic"


@dataclass(frozen=True, slots=True)
class InboundAdmission:
    provider_name: str
    entry: AliasEntry
    config: LiteLLMGatewayConfig
    evidence: Mapping[str, Any]
    # The Workspace's model admission: the content decision asks Cedar with the same sources and principal.
    project_admission: ProjectModelAdmission | None = field(default=None, repr=False, compare=False)


def _aliases_of(provider: LLMProvider) -> tuple[str, ...]:
    section = gateway_config_section(provider.config_json)
    aliases = section.get("aliases") if section is not None else None
    return tuple(alias for alias in aliases if isinstance(alias, str)) if isinstance(aliases, Mapping) else ()


async def _active_providers(db: AsyncSession) -> list[LLMProvider]:
    rows = (
        await db.execute(
            select(LLMProvider).where(
                LLMProvider.is_active.is_(True),
                LLMProvider.driver == LITELLM_GATEWAY_DRIVER,
            )
        )
    ).scalars()
    return list(rows)


async def _listing_providers(db: AsyncSession, alias: str) -> list[LLMProvider]:
    return [row for row in await _active_providers(db) if alias in _aliases_of(row)]


async def _virtual_key_kwargs(db: AsyncSession, provider: LLMProvider) -> dict[str, Any]:
    # Imported lazily: the control-plane service imports the provider registry,
    # which imports back into this package.
    from ...control_plane_service import build_provider_client_kwargs_async

    return await build_provider_client_kwargs_async(db, provider)


async def workspace_project_admission(db: AsyncSession, workspace_id: str) -> ProjectModelAdmission | InboundRefusal:
    """The Workspace's own model admission (the first step), as dispatch owner :data:`INBOUND_DISPATCH_OWNER`."""
    workspace = await resolve_workspace_admission(
        db,
        project_ids=[workspace_id],
        owner=INBOUND_DISPATCH_OWNER,
        authorized_project_ids=[workspace_id],
    )
    project_admission = workspace.driver_admission
    if not workspace.allowed or project_admission is None:
        return refusal(workspace.state if not workspace.allowed else STATE_NEEDS_CONFIGURATION, workspace.reason)
    return project_admission


def _admitted_entry(
    project_admission: ProjectModelAdmission, alias: str, provider: LLMProvider, *, declares_tools: bool
) -> tuple[AliasEntry, DataPolicyDecision]:
    """Steps 3 and 4 for one alias of ``provider``; raises :class:`LiteLLMGatewayError`."""
    entry, data_decision = admitted_alias_entry(
        project_admission, alias, gateway_config_section(provider.config_json) or {}
    )
    if declares_tools and CAPABILITY_TOOLS not in entry.requested_capabilities:
        raise LiteLLMGatewayError(
            GATEWAY_STATE_CAPABILITY_NOT_PROVEN, denial_reason=CAPABILITY_DENIAL_NOT_DECLARED
        ) from None
    return entry, data_decision


async def admitted_tool_aliases(db: AsyncSession, workspace_id: str) -> tuple[AliasEntry, ...]:
    """Every alias a tool-carrying call of this Workspace would be admitted for (the model picker).

    The same steps as :func:`admit_inbound_call` for each catalog alias, so the list never offers a model the
    call then refuses: an alias listed by more than one provider is left out (a call is
    ``alias_provider_ambiguous``), and so is every alias the grant, the level's list, Cedar's ``call_model``,
    the catalog, the data policy or the ``tools`` capability refuses. Nothing is dispatched and no virtual
    key is resolved. Order: provider name, then catalog order.
    """
    project_admission = await workspace_project_admission(db, workspace_id)
    if isinstance(project_admission, InboundRefusal):
        return ()
    providers = sorted(await _active_providers(db), key=lambda row: (str(row.name or ""), str(row.id)))
    listed = Counter(alias for provider in providers for alias in _aliases_of(provider))
    entries: list[AliasEntry] = []
    for provider in providers:
        for alias in _aliases_of(provider):
            if listed[alias] != 1:
                continue
            try:
                entry, _data_decision = _admitted_entry(project_admission, alias, provider, declares_tools=True)
            except LiteLLMGatewayError:
                continue
            entries.append(entry)
    return tuple(entries)


async def admit_inbound_call(
    db: AsyncSession,
    *,
    workspace_id: str,
    alias: str,
    declares_tools: bool,
) -> InboundAdmission | InboundRefusal:
    project_admission = await workspace_project_admission(db, workspace_id)
    if isinstance(project_admission, InboundRefusal):
        return project_admission

    providers = await _listing_providers(db, alias)
    if not providers:
        return refusal(STATE_DENIED, REASON_ALIAS_NOT_LISTED)
    if len(providers) > 1:
        return refusal(STATE_NEEDS_CONFIGURATION, REASON_ALIAS_PROVIDER_AMBIGUOUS)
    provider = providers[0]

    try:
        entry, data_decision = _admitted_entry(project_admission, alias, provider, declares_tools=declares_tools)
        kwargs = await _virtual_key_kwargs(db, provider)
        config = build_gateway_config(
            endpoint_url=kwargs.get("endpoint_url"),
            virtual_key=kwargs.get("api_key"),
            config_json=kwargs.get("config_json"),
        )
    except LiteLLMGatewayError as exc:
        return refusal_for_admission_error(exc)

    evidence = {
        **build_call_evidence(config=config, entry=entry),
        **data_decision.evidence(),
        "project_admission_source": project_admission.source,
        "dispatch_owner": INBOUND_DISPATCH_OWNER,
    }
    return InboundAdmission(provider_name=str(provider.name or ""), entry=entry, config=config, evidence=evidence,
                            project_admission=project_admission)


__all__ = [
    "INBOUND_DISPATCH_OWNER",
    "InboundAdmission",
    "admit_inbound_call",
    "admitted_tool_aliases",
    "workspace_project_admission",
]
