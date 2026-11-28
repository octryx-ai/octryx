"""Governed LiteLLM gateway provider driver."""

from __future__ import annotations

from typing import Any

import httpx

from ...services.content_security.model_call import GovernedContentRoute
from ...services.model_gateway.cost_contract import (
    COST_CONTRACT_PAYLOAD_KEY,
    GOVERNED_COST_SOURCE_DRIVER,
)
from ...services.model_gateway.data_policy import DataPolicyDecision
from ...services.model_gateway.litellm import (
    AliasEntry,
    LiteLLMGatewayError,
    LiteLLMGatewayHttpClient,
    build_gateway_config,
)
from ...services.model_gateway.litellm.alias_catalog import (
    CAPABILITY_TOOLS,
    CAPABILITY_VISION,
)
from ...services.model_gateway.litellm.capability_evidence import ProbeEvidenceCache
from ...services.model_gateway.litellm.entry_admission import admitted_alias_entry
from ...services.model_gateway.litellm.errors import (
    GATEWAY_STATE_ALIAS_DENIED,
    GATEWAY_STATE_RATE_LIMITED,
    GATEWAY_STATE_TIMEOUT,
    GATEWAY_STATE_UNAUTHORIZED,
    GATEWAY_STATE_UNAVAILABLE,
    GATEWAY_STATE_UNREACHABLE,
)
from ...services.model_gateway.litellm.evidence import close_evidence
from ...services.model_gateway.litellm.project_admission import (
    ProjectModelAdmission,
    resolved_project_admission,
)
from .base import BaseLLMProvider
from .sampling_capabilities import gateway_temperature

# Taken from the cost contract so the dispatch and accounting boundaries cannot name two different drivers.
PROVIDER_NAME = GOVERNED_COST_SOURCE_DRIVER

ADMISSION_DENIAL_CONTEXT_MISSING = "project_policy_context_missing"

# Resolved lazily in ``list_models``: ``services.provider`` imports back into ``agent.providers``.
_SYNC_STATE_BY_GATEWAY_STATE = {
    GATEWAY_STATE_UNAUTHORIZED: "auth_denied",
    GATEWAY_STATE_RATE_LIMITED: "provider_unavailable",
    GATEWAY_STATE_TIMEOUT: "provider_unavailable",
    GATEWAY_STATE_UNAVAILABLE: "provider_unavailable",
    GATEWAY_STATE_UNREACHABLE: "provider_unavailable",
}


class LiteLLMGatewayClient(BaseLLMProvider):
    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        project_admission: Any,
        api_key: str | None = None,
        config_json: dict[str, Any] | None = None,
        request_timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        evidence_cache: ProbeEvidenceCache | None = None,
        accepts_temperature: bool | None = None,
        target_temperature: float | None = None,
    ):
        # Project admission is required before anything else: a path that cannot
        # name its project must not even hold a configured gateway client.
        admission = resolved_project_admission(project_admission)
        if admission is None:
            raise LiteLLMGatewayError(
                GATEWAY_STATE_ALIAS_DENIED,
                denial_reason=ADMISSION_DENIAL_CONTEXT_MISSING,
            ) from None
        self.project_admission: ProjectModelAdmission = admission
        # The runtime target's sampling choice: False = never send, a value = send exactly that.
        self.accepts_temperature = accepts_temperature
        self.target_temperature = target_temperature
        # Validated here so a rejected configuration never reaches a transport.
        self.config = build_gateway_config(
            endpoint_url=endpoint_url,
            virtual_key=api_key,
            config_json=config_json,
            request_timeout_seconds=request_timeout_seconds,
        )
        self.client = LiteLLMGatewayHttpClient(
            self.config,
            transport=transport,
            evidence_cache=evidence_cache,
        )

    def _admitted_entry(self, alias: str) -> tuple[AliasEntry, DataPolicyDecision]:
        # Shared with the inbound Anthropic route so both doors refuse alike.
        return admitted_alias_entry(self.project_admission, alias, self.config.raw_config)

    def content_route(self, model: str) -> GovernedContentRoute:
        entry, _data = self._admitted_entry(model)
        return GovernedContentRoute(self.project_admission, entry, self._admitted_entry)

    async def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        # The content policies (``BaseLLMProvider`` -> ``content_security.model_call``) already decided this
        # request through :meth:`content_route`: ``model`` is the alias they admitted (possibly switched).
        entry, data_decision = self._admitted_entry(model)
        result = await self.client.chat_completion(
            entry=entry,
            messages=messages,
            tools=tools,
            temperature=gateway_temperature(
                temperature, override=self.accepts_temperature, target_value=self.target_temperature
            ),
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        # The permitted data-policy comparison is recorded with the call, not only with denials, so an
        # operator can see which classification was compared against which alias allowance.
        return {
            "content": result.content,
            "tool_calls": result.tool_calls,
            "usage": {
                **result.usage,
                "gateway_evidence": close_evidence({**result.evidence, **data_decision.evidence()}),
            },
            "model": entry.alias,
        }

    def _alias_catalog_entry_payload(self, entry: AliasEntry, proven: frozenset[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": entry.alias,
            "name": entry.alias,
            "provider": PROVIDER_NAME,
            "context_length": entry.context_limit,
            # Only requested and probe-proven: the adapter refuses anything else at dispatch time.
            "supports_tools": CAPABILITY_TOOLS in entry.requested_capabilities and CAPABILITY_TOOLS in proven,
            "supports_vision": CAPABILITY_VISION in entry.requested_capabilities and CAPABILITY_VISION in proven,
        }
        # Published for every alias: otherwise sync cannot tell "now governed-free" from "no pricing sent"
        # and the previous mode's prices survive the transition.
        payload[COST_CONTRACT_PAYLOAD_KEY] = entry.cost.catalog_payload()
        return payload

    async def list_models(self) -> list[dict]:
        gateway_state = ""
        denial_reason = ""
        evidence = None
        try:
            evidence = await self.client.probe_evidence(force_refresh=True)
        except LiteLLMGatewayError as exc:
            gateway_state = exc.gateway_state
            denial_reason = exc.denial_reason
        if evidence is None:
            from ...services.provider.model_sync import ModelCatalogSyncError

            # Typed failure keeps the catalog state explicit instead of an empty "no models" result.
            raise ModelCatalogSyncError(
                _SYNC_STATE_BY_GATEWAY_STATE.get(gateway_state, "validation_failed"),
                "LiteLLM gateway model catalog probe failed.",
                error_class=f"{gateway_state or 'gateway_probe_failed'}"
                + (f":{denial_reason}" if denial_reason else ""),
            ) from None
        catalog: list[dict] = []
        for entry in self.config.aliases:
            group_evidence = evidence.for_model_group(entry.model_group)
            proven = group_evidence.proven_capabilities if group_evidence is not None else frozenset()
            catalog.append(self._alias_catalog_entry_payload(entry, proven))
        return catalog

    async def close(self):
        await self.client.aclose()


__all__ = ["ADMISSION_DENIAL_CONTEXT_MISSING", "PROVIDER_NAME", "LiteLLMGatewayClient"]
