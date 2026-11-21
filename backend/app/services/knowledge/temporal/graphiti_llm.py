"""Graphiti's model calls, through the Model Control Plane.

Graphiti extracts entities and facts with an LLM. It never gets a provider client of its own:
this client dispatches through the platform's provider layer over the runtimes
``graph_model_selection`` chose and admitted for the one Workspace the episode belongs to
(``extract``-tagged runtimes, else the Workspace's model policy, else ``needs_configuration``).

The temperature follows the engine's sampling rule (``agent/providers/sampling_capabilities``):
0 (or the client's configured value) unless the model rejects an explicit temperature (Claude 5
family, or the runtime target's ``accepts_temperature`` override), then none; the model catalog's
``temperature`` wins over the client's value. Graphiti's own
``LLMConfig`` default is never forwarded.

Graphiti appends the JSON schema of the expected answer to the prompt; the answer is parsed here
(code fences and prose around the object are dropped) and validated against Graphiti's model. An
unparseable answer raises ``JSONDecodeError``, which Graphiti retries a bounded number of times.

A client built with ``check_change_edges`` (a change-record episode) asks Graphiti's fact extraction
for the self-checked answer of ``change_self_check`` and hands back the guarded one; every other
prompt is untouched.

Token usage of every call, and the facts the guard stripped of a change type, are accumulated on
the client, so the extraction run can report them. No prompt, answer or provider message is logged.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...content_security.model_call_scope import ModelCallScope, model_call_scope, workspace_call
from .change_self_check import EDGE_PROMPT, GRAPHITI_EDGE_ANSWER, CheckedExtractedEdges, check_change_edges
from .errors import GraphModelUnavailableError, GraphStoreError, GraphStoreState
from .graph_model_selection import select_graph_runtimes
from .graphiti_boundary import LLMClient, LLMConfig, ModelSize

logger = logging.getLogger(__name__)

MAX_ANSWER_TOKENS = 8192


@dataclass(slots=True)
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unparseable: int = 0
    # Facts with a change type whose own self-check said they state no change.
    demoted: int = 0
    models: set[str] = field(default_factory=set)

    def add(self, model: str, usage: object) -> None:
        self.calls += 1
        self.models.add(model)
        if isinstance(usage, dict):
            self.input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)


_DECODER = json.JSONDecoder()


def _json_object(text: str) -> dict[str, Any]:
    """The first complete JSON object in the answer; prose or a second object around it is ignored."""
    position = text.find("{")
    while position >= 0:
        try:
            value, _ = _DECODER.raw_decode(text, position)
        except json.JSONDecodeError:
            position = text.find("{", position + 1)
            continue
        if isinstance(value, dict):
            return value
        position = text.find("{", position + 1)
    raise json.JSONDecodeError("no JSON object in the answer", "", 0)


class GovernedGraphitiLLM(LLMClient):
    """Graphiti ``LLMClient`` over admitted control-plane runtimes."""

    def __init__(
        self,
        runtimes: list[dict[str, Any]],
        *,
        scope: ModelCallScope,
        check_change_edges: bool = False,
        change_types: frozenset[str] | None = None,
        temperature: float | None = None,
    ) -> None:
        super().__init__(LLMConfig(model=str(runtimes[0].get("model") or "")), cache=False)
        # Graphiti's ``LLMConfig`` default is never forwarded; None means the sampling default (0).
        self.temperature = temperature
        self._runtimes = runtimes
        self._scope = scope
        self._check_change_edges = check_change_edges
        # The episode profile's closed change types the guard keeps (the change-record set by default).
        self._change_types = change_types
        self.usage = ModelUsage()

    async def generate_response(
        self,
        messages,
        response_model=None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
        group_id: str | None = None,
        prompt_name: str | None = None,
        *,
        attribute_extraction: bool = False,
    ) -> dict[str, Any]:
        checked = self._check_change_edges and prompt_name == EDGE_PROMPT
        if checked and response_model is not GRAPHITI_EDGE_ANSWER:
            # Graphiti's fact extraction changed shape: refuse rather than guard an unknown answer.
            raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)
        answer = await super().generate_response(
            messages,
            CheckedExtractedEdges if checked else response_model,
            max_tokens,
            model_size,
            group_id,
            prompt_name,
            attribute_extraction=attribute_extraction,
        )
        if not checked:
            return answer
        guarded, demoted = check_change_edges(answer, self._change_types)
        self.usage.demoted += demoted
        return guarded

    async def _generate_response(
        self,
        messages,
        response_model=None,
        max_tokens: int = MAX_ANSWER_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        from ....agent.providers import get_provider
        from ....agent.providers.sampling_capabilities import sampling_temperature

        chat = [{"role": message.role, "content": message.content} for message in messages]
        for runtime in self._runtimes:
            client = None
            try:
                client = get_provider(**{key: value for key, value in runtime.items() if key != "use_case_tags"})
                model = str(runtime.get("model") or "")
                options: dict[str, Any] = {"max_tokens": max_tokens}
                # The engine's sampling rule: temperature 0 unless the model (or its target) rejects one.
                temperature = sampling_temperature(
                    model,
                    self.temperature,
                    override=runtime.get("accepts_temperature"),
                    target_value=runtime.get("target_temperature"),
                )
                if temperature is not None:
                    options["temperature"] = temperature
                with model_call_scope(self._scope):
                    result = await client.chat(messages=chat, model=model, **options)
            except Exception:  # noqa: BLE001 - the next governed runtime is tried; no provider text is kept
                logger.warning("Knowledge graph model runtime failed: provider=%s", runtime.get("provider_name"))
                continue
            finally:
                close = getattr(client, "close", None) if client is not None else None
                if close:
                    await close()
            self.usage.add(model, result.get("usage"))
            return self._parsed(str(result.get("content") or ""), response_model)
        raise GraphModelUnavailableError("unavailable", "all_runtimes_failed")

    def _parsed(self, content: str, response_model) -> dict[str, Any]:
        """The answer as a JSON object that fits ``response_model``; a decode error otherwise."""
        try:
            answer = _json_object(content)
        except json.JSONDecodeError:
            # Measured facts only: the size and whether the object was cut off, never the text.
            self.usage.unparseable += 1
            logger.warning(
                "Knowledge graph model answer was not a JSON object: chars=%d unclosed=%s",
                len(content),
                content.count("{") > content.count("}"),
            )
            raise
        if response_model is not None:
            try:
                answer = response_model.model_validate(answer).model_dump()
            except ValidationError as error:
                # Schema paths only (they are Graphiti's field names, never content). Raised as a
                # decode error, which Graphiti retries, because a resample usually fits the schema.
                self.usage.unparseable += 1
                logger.warning(
                    "Knowledge graph model answer did not fit the schema: fields=%s",
                    sorted({".".join(str(part) for part in item["loc"][:2]) for item in error.errors()})[:6],
                )
                raise json.JSONDecodeError("the answer does not fit the schema", "", 0) from None
        return answer


async def governed_graph_llm(
    db: AsyncSession,
    *,
    project_id: str,
    check_change_edges: bool = False,
    change_types: frozenset[str] | None = None,
) -> GovernedGraphitiLLM:
    """The graph extraction client over the runtimes chosen for this Workspace, or a fixed refusal."""
    runtimes = await select_graph_runtimes(db, project_id=project_id)
    return GovernedGraphitiLLM(runtimes, scope=workspace_call(project_id), check_change_edges=check_change_edges,
                               change_types=change_types)


__all__ = ["GovernedGraphitiLLM", "ModelUsage", "governed_graph_llm"]
