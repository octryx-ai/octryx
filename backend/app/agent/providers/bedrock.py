"""AWS Bedrock provider – Converse API."""

from typing import Any

from ...services.content_security.model_call_outbound import final_arguments
from ..core.runtime.runtime_errors import (
    RUNTIME_ERROR_PERMANENT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    ProviderRuntimeError,
)
from ..core.runtime.transport_errors import translate_transport_errors
from .base import BaseLLMProvider
from .bedrock_capabilities import bedrock_tool_support
from .bedrock_model_ids import (
    InferenceTypes,
    catalog_inference_types,
    list_foundation_model_summaries,
    resolve_bedrock_model_id,
)
from .bedrock_prompt_cache import (
    normalize_prompt_cache_config,
    prompt_cache_point,
    should_add_cache_point,
    supports_bedrock_extended_prompt_cache_ttl,
    supports_bedrock_prompt_caching,
    supports_bedrock_tool_prompt_caching,
)
from .inline_tool_calls import parse_inline_tool_calls
from .sampling_capabilities import sampling_temperature

_CACHE_SCOPE_KEY = "_cache_scope"
_CACHE_SCOPE_STABLE = "stable"
_SOURCE_EVIDENCE_FINAL_PROMPT_MARKER = "[source_evidence_final_answer]"

# Deterministic botocore ClientError code -> runtime error class mapping.
# Codes not listed here (including ValidationException) map to permanent.
# Note on ValidationException: Bedrock reports context-window overflow only via
# the human-readable error message ("Input is too long...", "too many input
# tokens"), with no structured field distinguishing it from other validation
# failures. Per the explicit-taxonomy contract we do not classify by message
# text, so ValidationException maps to permanent instead of context_pressure.
_TIMEOUT_CLIENT_ERROR_CODES = frozenset({"ModelTimeoutException"})
_TRANSIENT_CLIENT_ERROR_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceQuotaExceededException",
        "ServiceUnavailableException",
        "InternalServerException",
    }
)


def _client_error_class(error_code: str) -> str:
    if error_code in _TIMEOUT_CLIENT_ERROR_CODES:
        return RUNTIME_ERROR_TIMEOUT
    if error_code in _TRANSIENT_CLIENT_ERROR_CODES:
        return RUNTIME_ERROR_TRANSIENT
    return RUNTIME_ERROR_PERMANENT


def _runtime_error_from_client_error(exc: Exception) -> ProviderRuntimeError:
    """Build a ProviderRuntimeError from a botocore ClientError by error code."""
    response = getattr(exc, "response", None)
    response = response if isinstance(response, dict) else {}
    error = response.get("Error")
    error = error if isinstance(error, dict) else {}
    error_code = str(error.get("Code") or "").strip()
    metadata = response.get("ResponseMetadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    http_status = metadata.get("HTTPStatusCode")
    return ProviderRuntimeError(
        f"Bedrock Converse API error ({error_code or 'ClientError'}): {exc}",
        error_class=_client_error_class(error_code),
        status_code=http_status if isinstance(http_status, int) else None,
    )


class BedrockClient(BaseLLMProvider):
    name = "bedrock"

    def __init__(
        self,
        region: str = "eu-central-1",
        role_arn: str | None = None,
        config_json: dict[str, Any] | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        accepts_temperature: bool | None = None,
        target_temperature: float | None = None,
    ):
        self.region = region
        # The runtime target's override of the sampling catalog (None = the catalog decides).
        self.accepts_temperature = accepts_temperature
        # The runtime target's explicit temperature (None = the caller's or the deterministic default).
        self.target_temperature = target_temperature
        self.role_arn = role_arn
        self.config_json = config_json if isinstance(config_json, dict) else {}
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_session_token = aws_session_token
        self._client = None
        self._assumed_kwargs: dict[str, str] | None = None

    def _aws_client_kwargs(self) -> dict[str, str]:
        kwargs: dict[str, str] = {"region_name": self.region}
        if self.aws_access_key_id and self.aws_secret_access_key:
            kwargs["aws_access_key_id"] = self.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            if self.aws_session_token:
                kwargs["aws_session_token"] = self.aws_session_token
        return kwargs

    def _runtime_client_kwargs(self) -> dict[str, str]:
        """The credentials runtime calls use: the assumed role when one is configured."""
        if not self.role_arn:
            return self._aws_client_kwargs()
        if self._assumed_kwargs is None:
            import boto3

            sts = boto3.client("sts", **self._aws_client_kwargs())
            creds = sts.assume_role(RoleArn=self.role_arn, RoleSessionName="octryx-bedrock")["Credentials"]
            self._assumed_kwargs = {
                "region_name": self.region,
                "aws_access_key_id": creds["AccessKeyId"],
                "aws_secret_access_key": creds["SecretAccessKey"],
                "aws_session_token": creds["SessionToken"],
            }
        return self._assumed_kwargs

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", **self._runtime_client_kwargs())
        return self._client

    def _list_foundation_model_summaries(self) -> list[Any]:
        return list_foundation_model_summaries(self._runtime_client_kwargs())

    async def chat(
        self,
        messages: list[dict],
        model: str = "anthropic.claude-3-5-sonnet-20241022:0",
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        import asyncio

        # The catalog decides whether a bare id needs an inference profile prefix (``bedrock_model_ids``).
        inference_types = await catalog_inference_types(self.region, model, self._list_foundation_model_summaries)
        kwargs, prompt_cache_enabled = self._build_converse_kwargs(
            messages=messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            inference_types=inference_types,
        )

        from botocore.exceptions import ClientError

        # Connection, timeout and closed-connection failures (``EndpointConnectionError``,
        # ``ConnectTimeoutError``, ``ReadTimeoutError``, ``ConnectionClosedError``) leave as
        # typed errors classified from the exception type; the role assumption is a network
        # call too, so it is inside the block.
        kwargs = final_arguments(kwargs)
        with translate_transport_errors("Bedrock Converse API"):
            client = self._get_client()
            try:
                response = await asyncio.to_thread(client.converse, **kwargs)
            except ClientError as exc:
                raise _runtime_error_from_client_error(exc) from exc

        return self._parse_response(response, fallback_model=model, prompt_cache_enabled=prompt_cache_enabled)

    async def list_models(self) -> list[dict]:
        import asyncio

        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError

            bedrock = boto3.client("bedrock", **self._aws_client_kwargs())
            response = await asyncio.to_thread(bedrock.list_foundation_models)
            models = response.get("modelSummaries", [])
            return [
                {
                    "id": m["modelId"],
                    "name": m.get("modelName", m["modelId"]),
                    "provider": "bedrock",
                    # ListFoundationModels carries no tool-use flag; None stays "unknown".
                    "supports_tools": bedrock_tool_support(m["modelId"]),
                }
                for m in models
                if "TEXT" in m.get("outputModalities", [])
            ]
        except (ImportError, BotoCoreError, ClientError, RuntimeError, ValueError, TypeError, OSError):
            return []

    async def close(self):
        pass

    def _build_converse_kwargs(
        self,
        *,
        messages: list[dict],
        model: str,
        tools: list[dict] | None,
        temperature: float | None,
        max_tokens: int,
        inference_types: InferenceTypes | None = None,
    ) -> tuple[dict[str, Any], bool]:
        source_evidence_final_text = self._source_evidence_final_user_text(messages)
        if source_evidence_final_text:
            bedrock_messages = [{"role": "user", "content": [{"text": source_evidence_final_text}]}]
        else:
            bedrock_messages = self._convert_messages(messages, use_tool_blocks=bool(tools))
        system_blocks = self._extract_system(messages)

        # Bedrock Converse API requires conversation to end with a user message.
        # Remove trailing assistant messages (prefill) that some models don't support.
        while bedrock_messages and bedrock_messages[-1].get("role") == "assistant":
            bedrock_messages.pop()
        if not bedrock_messages:
            bedrock_messages = [{"role": "user", "content": [{"text": "Continue."}]}]

        # Bedrock requires alternating user/assistant roles. Merge consecutive same-role messages.
        merged = []
        for msg in bedrock_messages:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"].extend(msg["content"])
            else:
                merged.append(msg)
        bedrock_messages = merged

        # An ARN, a profile id or an on-demand-only model is used as configured.
        resolved_model_id = resolve_bedrock_model_id(model, region=self.region, inference_types=inference_types)
        inference_config: dict[str, Any] = {"maxTokens": max_tokens}
        # Deterministic by default (temperature 0); a model that rejects an explicit temperature
        # (Claude 5 family, or the runtime target's override) gets none (``sampling_capabilities``).
        effective_temperature = sampling_temperature(
            model, temperature, override=self.accepts_temperature, target_value=self.target_temperature
        )
        if effective_temperature is not None:
            inference_config["temperature"] = effective_temperature
        kwargs: dict[str, Any] = {
            "modelId": resolved_model_id,
            "messages": bedrock_messages,
            "inferenceConfig": inference_config,
        }

        if system_blocks:
            kwargs["system"] = system_blocks

        if tools:
            kwargs["toolConfig"] = self._convert_tools(tools)

        prompt_cache_enabled = self._apply_prompt_caching(kwargs, model_id=model)
        return kwargs, prompt_cache_enabled

    def _apply_prompt_caching(self, kwargs: dict[str, Any], *, model_id: str) -> bool:
        cache_config = normalize_prompt_cache_config(self.config_json)
        if not cache_config["enabled"] or not supports_bedrock_prompt_caching(model_id):
            self._strip_system_cache_metadata(kwargs)
            return False
        cache_ttl = str(cache_config["ttl"]) if supports_bedrock_extended_prompt_cache_ttl(model_id) else "5m"
        cache_point = prompt_cache_point(cache_ttl)
        enabled = False
        min_tokens_override = cache_config.get("min_tokens_override")
        system_blocks = kwargs.get("system")
        if cache_config["cache_system"] and isinstance(system_blocks, list):
            enabled = self._apply_system_prompt_caching(
                system_blocks,
                cache_point=cache_point,
                model_id=model_id,
                min_tokens_override=min_tokens_override,
            )
        else:
            self._strip_system_cache_metadata(kwargs)
        tool_config = kwargs.get("toolConfig")
        tool_blocks = tool_config.get("tools") if isinstance(tool_config, dict) else None
        if (
            cache_config["cache_tools"]
            and supports_bedrock_tool_prompt_caching(model_id)
            and isinstance(tool_blocks, list)
        ):
            if should_add_cache_point(value=tool_blocks, model_id=model_id, min_tokens_override=min_tokens_override):
                tool_blocks.append(cache_point)
                enabled = True
        return enabled

    def _apply_system_prompt_caching(
        self,
        system_blocks: list[dict[str, Any]],
        *,
        cache_point: dict[str, Any],
        model_id: str,
        min_tokens_override: Any,
    ) -> bool:
        has_explicit_scopes = any(_CACHE_SCOPE_KEY in block for block in system_blocks if isinstance(block, dict))
        if not has_explicit_scopes:
            if should_add_cache_point(value=system_blocks, model_id=model_id, min_tokens_override=min_tokens_override):
                system_blocks.append(cache_point)
                return True
            return False

        stable_prefix: list[dict[str, Any]] = []
        rebuilt: list[dict[str, Any]] = []
        inserted = False
        for block in system_blocks:
            clean_block = self._without_system_cache_metadata(block)
            scope = block.get(_CACHE_SCOPE_KEY) if isinstance(block, dict) else None
            if not inserted and scope == _CACHE_SCOPE_STABLE:
                stable_prefix.append(clean_block)
                rebuilt.append(clean_block)
                continue
            if not inserted and stable_prefix:
                if should_add_cache_point(
                    value=stable_prefix,
                    model_id=model_id,
                    min_tokens_override=min_tokens_override,
                ):
                    rebuilt.append(cache_point)
                    inserted = True
            rebuilt.append(clean_block)
        if not inserted and stable_prefix:
            if should_add_cache_point(value=stable_prefix, model_id=model_id, min_tokens_override=min_tokens_override):
                rebuilt.append(cache_point)
                inserted = True
        system_blocks[:] = rebuilt
        return inserted

    def _convert_messages(self, messages: list[dict], *, use_tool_blocks: bool = True) -> list[dict]:
        bedrock_messages = []
        seen_conversation_message = False
        for msg in messages:
            if msg["role"] == "system":
                if seen_conversation_message and msg.get("content"):
                    bedrock_messages.append(
                        {
                            "role": "user",
                            "content": [{"text": f"System context update:\n{msg.get('content', '')}"}],
                        }
                    )
                continue
            seen_conversation_message = True
            if msg["role"] == "tool":
                if use_tool_blocks:
                    bedrock_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "toolResult": {
                                        "toolUseId": msg.get("tool_call_id", ""),
                                        "content": [{"text": msg.get("content", "")}],
                                    }
                                }
                            ],
                        }
                    )
                else:
                    bedrock_messages.append({"role": "user", "content": [{"text": self._tool_result_text(msg)}]})
            elif msg.get("tool_calls"):
                content = self._tool_call_blocks(msg) if use_tool_blocks else [{"text": self._tool_call_text(msg)}]
                bedrock_messages.append({"role": "assistant", "content": content})
            else:
                bedrock_messages.append({"role": msg["role"], "content": [{"text": msg.get("content", "")}]})
        return bedrock_messages

    def _tool_call_blocks(self, msg: dict) -> list[dict[str, Any]]:
        content = []
        if msg.get("content"):
            content.append({"text": msg["content"]})
        for tc in msg["tool_calls"]:
            raw_args = self._tool_call_arguments(tc)
            content.append(
                {
                    "toolUse": {
                        "toolUseId": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "input": raw_args if isinstance(raw_args, dict) else {},
                    }
                }
            )
        return content or [{"text": ""}]

    def _tool_call_text(self, msg: dict) -> str:
        parts = []
        if msg.get("content"):
            parts.append(str(msg.get("content") or ""))
        for tc in msg.get("tool_calls") or []:
            function = tc.get("function") if isinstance(tc, dict) else {}
            name = str((function or {}).get("name") or "tool").strip() or "tool"
            raw_args = self._tool_call_arguments(tc if isinstance(tc, dict) else {})
            parts.append(f"Tool request {name}: {raw_args}")
        return "\n".join(parts).strip() or "Tool request."

    def _tool_result_text(self, msg: dict) -> str:
        tool_call_id = str(msg.get("tool_call_id") or "").strip()
        prefix = f"Tool result {tool_call_id}" if tool_call_id else "Tool result"
        return f"{prefix}: {msg.get('content', '')}"

    def _tool_call_arguments(self, tool_call: dict) -> Any:
        function = tool_call.get("function") if isinstance(tool_call, dict) else {}
        raw_args = (function or {}).get("arguments", {})
        if isinstance(raw_args, str):
            import json as _json

            try:
                return _json.loads(raw_args)
            except (ValueError, TypeError):
                return raw_args
        return raw_args

    def _extract_system(self, messages: list[dict]) -> list[dict]:
        system_blocks = []
        for msg in messages:
            if msg["role"] != "system":
                break
            if not msg.get("content"):
                continue
            block = {"text": msg["content"]}
            cache_scope = str(msg.get("cache_scope") or "").strip().lower()
            if cache_scope:
                block[_CACHE_SCOPE_KEY] = cache_scope
            system_blocks.append(block)
        return system_blocks

    def _source_evidence_final_user_text(self, messages: list[dict]) -> str:
        start_index = None
        for index, msg in enumerate(messages):
            content = str(msg.get("content") or "")
            if msg.get("role") == "system" and _SOURCE_EVIDENCE_FINAL_PROMPT_MARKER in content:
                start_index = index
                break
        if start_index is None:
            return ""

        parts: list[str] = []
        for msg in messages[start_index:]:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "").strip()
            if role in {"system", "user"} and content:
                parts.append(content)
        return "\n\n".join(parts).strip()

    def _convert_tools(self, tools: list[dict]) -> dict:
        tool_specs = []
        sorted_tools = sorted(tools, key=lambda item: str(item.get("function", {}).get("name") or ""))
        for tool in sorted_tools:
            func = tool.get("function", {})
            spec = {
                "name": func["name"],
                "description": func.get("description", ""),
            }
            params = func.get("parameters", {})
            if params:
                spec["inputSchema"] = {"json": params}
            tool_specs.append({"toolSpec": spec})
        return {"tools": tool_specs}

    def _strip_system_cache_metadata(self, kwargs: dict[str, Any]) -> None:
        system_blocks = kwargs.get("system")
        if not isinstance(system_blocks, list):
            return
        system_blocks[:] = [self._without_system_cache_metadata(block) for block in system_blocks]

    def _without_system_cache_metadata(self, block: Any) -> dict[str, Any]:
        if not isinstance(block, dict):
            return {"text": str(block or "")}
        return {key: value for key, value in block.items() if key != _CACHE_SCOPE_KEY}

    def _parse_response(
        self,
        response: dict,
        *,
        fallback_model: str = "",
        prompt_cache_enabled: bool = False,
    ) -> dict[str, Any]:
        output = response.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])

        text = ""
        tool_calls = []

        for block in content:
            if "text" in block:
                text += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                import json

                tool_calls.append(
                    {
                        "id": tu["toolUseId"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": json.dumps(tu.get("input", {}))
                            if isinstance(tu.get("input"), dict)
                            else str(tu.get("input", "{}")),
                        },
                    }
                )

        # Bedrock Claude/Nova sometimes emit tool calls as text (Anthropic
        # <function_calls> XML or a fenced JSON array) instead of native toolUse
        # blocks; recover them so the turn runs the tool instead of stalling.
        if not tool_calls and text:
            cleaned_text, recovered_tool_calls = parse_inline_tool_calls(text)
            if recovered_tool_calls:
                text = cleaned_text
                tool_calls = recovered_tool_calls

        usage = response.get("usage", {})
        non_cached_prompt_tokens = _safe_int(usage.get("inputTokens"))
        completion_tokens = _safe_int(usage.get("outputTokens"))
        cache_read_tokens = _safe_int(usage.get("cacheReadInputTokens"))
        cache_write_tokens = _safe_int(usage.get("cacheWriteInputTokens"))
        prompt_tokens = non_cached_prompt_tokens + cache_read_tokens + cache_write_tokens
        total_tokens = _safe_int(usage.get("totalTokens")) or prompt_tokens + completion_tokens
        normalized_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "inputTokens": non_cached_prompt_tokens,
            "outputTokens": completion_tokens,
            "totalTokens": total_tokens,
            "bedrock_input_tokens_non_cached": non_cached_prompt_tokens,
            "bedrock_prompt_cache_enabled": bool(prompt_cache_enabled),
        }
        for cache_key in (
            "cacheReadInputTokens",
            "cacheWriteInputTokens",
        ):
            if cache_key in usage:
                normalized_usage[cache_key] = _safe_int(usage.get(cache_key))
        if cache_read_tokens or cache_write_tokens:
            normalized_usage["bedrock_cache_read_input_tokens"] = cache_read_tokens
            normalized_usage["bedrock_cache_write_input_tokens"] = cache_write_tokens
            normalized_usage["bedrock_total_input_tokens"] = prompt_tokens
            # How the cache tokens are priced is decided by usage accounting against the
            # model catalog and recorded as the usage event's ``cost_status``.
        if "cacheDetails" in usage:
            normalized_usage["cacheDetails"] = usage.get("cacheDetails") or {}
        response_model = str(response.get("metrics", {}).get("modelId") or fallback_model or "").strip()

        return {
            "content": text,
            "tool_calls": tool_calls if tool_calls else None,
            "usage": normalized_usage,
            "model": response_model,
        }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
