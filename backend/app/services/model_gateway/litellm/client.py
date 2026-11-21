"""Bounded HTTP client for the governed LiteLLM gateway.

The client is constructed only from an already-validated
:class:`~.config.LiteLLMGatewayConfig`, so an endpoint or catalog denial never
reaches the transport. Every failure is raised outside its ``except`` block so
no transport exception survives as ``__context__`` or ``__cause__``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from ...content_security.model_call_outbound import JSON_HEADERS, final_body
from .alias_catalog import AliasEntry
from .capability_evidence import PROBE_EVIDENCE_CACHE, ProbeEvidence, ProbeEvidenceCache, parse_probe_evidence
from .chat_contract import chat_payload, required_capabilities, served_message
from .config import LiteLLMGatewayConfig
from .errors import (
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_CONTEXT_PRESSURE,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    LiteLLMGatewayError,
    gateway_state_for_status,
    gateway_transport_error,
)
from .evidence import build_call_evidence
from .upstream_detail import upstream_error_detail
from .usage_contract import resolve_usage_payload

CHAT_COMPLETIONS_PATH = "/chat/completions"

# Documented OpenAI-compatible error code for a prompt over the context window.
_CONTEXT_LENGTH_ERROR_CODE = "context_length_exceeded"

CONTRACT_DENIAL_INVALID_JSON = "response_not_json_object"
ENDPOINT_DENIAL_REDIRECTED = "endpoint_redirected"
PROBE_DENIAL_CATALOG_UNPARSABLE = "probe_catalog_unparsable"
CAPABILITY_DENIAL_NOT_DECLARED = "capability_not_declared_for_alias"
CAPABILITY_DENIAL_NO_PROBE_EVIDENCE = "capability_without_probe_evidence"


@dataclass(frozen=True, slots=True)
class GatewayChatResult:
    content: str
    tool_calls: list[dict[str, Any]] | None
    usage: dict[str, Any]
    model_group: str
    proven_capabilities: frozenset[str]
    evidence: dict[str, Any]


class LiteLLMGatewayHttpClient:
    """Chat-completions and catalog-probe client for one validated gateway config."""

    def __init__(
        self,
        config: LiteLLMGatewayConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        evidence_cache: ProbeEvidenceCache | None = None,
    ):
        self.config = config
        self._evidence_cache = evidence_cache or PROBE_EVIDENCE_CACHE
        timeout_seconds = config.request_timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=config.endpoint.base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.virtual_key}",
            },
            timeout=httpx.Timeout(
                connect=10.0,
                read=max(30.0, timeout_seconds),
                write=30.0,
                pool=10.0,
            ),
            transport=transport,
            # The transport boundary is part of the credential boundary. With
            # httpx's default ``trust_env=True`` an ambient HTTP_PROXY /
            # HTTPS_PROXY / ALL_PROXY variable mounts a proxy transport and the
            # ``Authorization: Bearer <virtual key>`` header travels to whatever
            # host that variable names; SSL_CERT_FILE / SSL_CERT_DIR and .netrc
            # would likewise become inputs to a governed call. The gateway
            # endpoint is validated configuration, so the environment gets no
            # vote: ``trust_env=False`` plus the explicit trust store and egress
            # hop from the validated transport policy (``transport_policy.py``).
            **config.transport.httpx_client_kwargs(),
            # A redirect would re-send the virtual key to a host the endpoint
            # allowlist never approved. Redirects are a configuration error.
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, content: bytes | None = None) -> httpx.Response:
        """``content``: a request body exactly as the final-bytes check passed it (``model_call_outbound``)."""
        failure: httpx.TransportError | None = None
        response: httpx.Response | None = None
        try:
            response = await self._client.request(method, path, content=content,
                                                  headers=JSON_HEADERS if content is not None else None)
        except httpx.TransportError as exc:
            failure = exc
        if failure is not None or response is None:
            raise gateway_transport_error(failure) from None
        if 300 <= response.status_code < 400:
            # Redirects are not followed, so a 3xx is neither an answer nor an
            # error the gateway produced: the pinned endpoint is pointing
            # somewhere else. It is refused before anything is served, with one
            # fixed state and reason. The body is never decoded and the
            # ``Location`` header is never read, recorded, or surfaced — it
            # names a host the endpoint allowlist did not approve, and the
            # status alone is enough to fix the configuration.
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CONFIGURATION_INVALID,
                denial_reason=ENDPOINT_DENIAL_REDIRECTED,
                status_code=response.status_code,
            ) from None
        if response.status_code >= 400:
            raise LiteLLMGatewayError(
                self._error_state_for_response(response),
                status_code=response.status_code,
                upstream_detail=upstream_error_detail(response.content),
            ) from None
        return response

    @staticmethod
    def _error_state_for_response(response: httpx.Response) -> str:
        """Pick a stable state; the body is compared, never captured."""

        state = gateway_state_for_status(response.status_code)
        if response.status_code >= 500:
            return state
        try:
            body = response.json()
        except ValueError:
            return state
        error = body.get("error") if isinstance(body, Mapping) else None
        code = str(error.get("code") or "").strip() if isinstance(error, Mapping) else ""
        if code == _CONTEXT_LENGTH_ERROR_CODE:
            return GATEWAY_STATE_CONTEXT_PRESSURE
        return state

    @staticmethod
    def _json_object(response: httpx.Response) -> Mapping[str, Any]:
        decode_failed = False
        body: Any = None
        try:
            body = response.json()
        except ValueError:
            decode_failed = True
        if decode_failed or not isinstance(body, Mapping):
            raise LiteLLMGatewayError(
                GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
                denial_reason=CONTRACT_DENIAL_INVALID_JSON,
            ) from None
        return body

    async def probe_evidence(self, *, force_refresh: bool = False) -> ProbeEvidence:
        """Fetch (or reuse) the bounded catalog probe evidence for this endpoint."""

        base_url = self.config.endpoint.base_url
        models_path = self.config.probe.models_path
        if not force_refresh:
            cached = self._evidence_cache.get(base_url, models_path)
            if cached is not None:
                return cached
        response = await self._request("GET", models_path)
        evidence = parse_probe_evidence(
            self._json_object(response),
            model_group_field=self.config.probe.model_group_field,
            observed_at=self._evidence_cache.now(),
        )
        if evidence is None:
            # The catalog probe runs before any billable chat request, so an
            # unusable catalog is a configuration state, not a served contract
            # violation: another runtime target may still serve this turn.
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CONFIGURATION_INVALID,
                denial_reason=PROBE_DENIAL_CATALOG_UNPARSABLE,
            ) from None
        self._evidence_cache.store(base_url, models_path, evidence)
        return evidence

    async def _proven_capabilities(
        self,
        entry: AliasEntry,
        *,
        required: frozenset[str],
    ) -> frozenset[str]:
        if not required:
            return frozenset()
        undeclared = required - entry.requested_capabilities
        if undeclared:
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
                denial_reason=CAPABILITY_DENIAL_NOT_DECLARED,
            ) from None
        evidence = await self.probe_evidence()
        group_evidence = evidence.for_model_group(entry.model_group)
        proven = group_evidence.proven_capabilities if group_evidence is not None else frozenset()
        if required - proven:
            raise LiteLLMGatewayError(
                GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
                denial_reason=CAPABILITY_DENIAL_NO_PROBE_EVIDENCE,
            ) from None
        return proven

    async def chat_completion(
        self,
        *,
        entry: AliasEntry,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> GatewayChatResult:
        proven = await self._proven_capabilities(entry, required=required_capabilities(tools, reasoning_effort))
        payload = chat_payload(entry, messages, tools=tools, temperature=temperature, max_tokens=max_tokens,
                               reasoning_effort=reasoning_effort)

        body = final_body(payload)
        started = time.perf_counter()
        response = await self._request("POST", CHAT_COMPLETIONS_PATH, content=body)
        duration_ms = int((time.perf_counter() - started) * 1000)
        body = self._json_object(response)
        message = served_message(entry, body)

        # Cost and usage are validated before the content is accepted: an
        # answer whose price cannot be established is discarded, not billed
        # silently at zero.
        usage = resolve_usage_payload(entry, body, body.get("usage"))
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        return GatewayChatResult(
            content=content if isinstance(content, str) else "",
            tool_calls=[dict(item) for item in tool_calls if isinstance(item, Mapping)]
            if isinstance(tool_calls, list) and tool_calls
            else None,
            usage=usage,
            model_group=entry.model_group,
            proven_capabilities=proven,
            evidence=build_call_evidence(
                config=self.config,
                entry=entry,
                model_group_verified=True,
                proven_capabilities=proven,
                duration_ms=duration_ms,
            ),
        )


__all__ = [
    "CAPABILITY_DENIAL_NOT_DECLARED",
    "CAPABILITY_DENIAL_NO_PROBE_EVIDENCE",
    "CHAT_COMPLETIONS_PATH",
    "CONTRACT_DENIAL_INVALID_JSON",
    "ENDPOINT_DENIAL_REDIRECTED",
    "PROBE_DENIAL_CATALOG_UNPARSABLE",
    "GatewayChatResult",
    "LiteLLMGatewayHttpClient",
]
