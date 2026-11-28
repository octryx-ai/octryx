"""The prompt texts one turn uses, resolved once, and their audit record."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .contract import (
    REASON_PROMPT_SET_UNBOUND,
    REASON_UNKNOWN_KEY,
    PromptTemplateUnavailableError,
    render_body,
)

SOURCE_SEED = "seed"
SOURCE_GLOBAL = "global"
SOURCE_WORKSPACE = "workspace"

#: Trace key under which a turn's resolved prompts are recorded.
PROMPT_TEMPLATES_TRACE_KEY = "prompt_templates"


@dataclass(frozen=True)
class ResolvedPrompt:
    key: str
    body: str
    version: int
    digest: str
    source: str
    scope_id: str | None = None
    #: Served verbatim (``PromptKeySpec.literal``): never rendered as a template.
    literal: bool = False

    @property
    def ref(self) -> str:
        return f"{self.key}@{self.version}" if self.source != SOURCE_SEED else f"{self.key}@seed"

    def audit_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ref": self.ref,
            "version": self.version,
            "digest": self.digest,
            "source": self.source,
        }
        if self.scope_id:
            entry["scope_id"] = self.scope_id
        return entry


@dataclass
class PromptSet:
    """The resolved bodies of one turn plus the record of what was rendered."""

    prompts: Mapping[str, ResolvedPrompt]
    scope: Mapping[str, Any] = field(default_factory=dict)
    #: Keys whose winning published body is invalid: rendering them is refused.
    refusals: Mapping[str, PromptTemplateUnavailableError] = field(default_factory=dict)
    _used: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolved(self, key: str) -> ResolvedPrompt:
        refusal = self.refusals.get(key)
        if refusal is not None:
            raise refusal
        prompt = self.prompts.get(key)
        if prompt is None:
            raise PromptTemplateUnavailableError(key, REASON_UNKNOWN_KEY)
        return prompt

    def render(self, key: str, /, **variables: object) -> str:
        prompt = self.resolved(key)
        if prompt.literal:
            if variables:
                raise ValueError(f"a literal prompt key takes no variables: {key}")
            text = prompt.body
        else:
            text = render_body(key, prompt.body, variables)
        self._used.setdefault(key, prompt.audit_entry())
        trace = _RENDER_TRACE.get()
        if trace is not None:
            trace.append(prompt)
        return text

    def usage(self) -> dict[str, dict[str, Any]]:
        """``key -> {ref, version, digest, source}`` for every key rendered so far."""
        return {key: dict(entry) for key, entry in sorted(self._used.items())}

    def trace_record(self) -> dict[str, Any]:
        return {"scope": dict(self.scope), "used": self.usage()}


_BOUND_PROMPT_SET: ContextVar[PromptSet | None] = ContextVar("bound_prompt_set", default=None)
_RENDER_TRACE: ContextVar[list[ResolvedPrompt] | None] = ContextVar("prompt_render_trace", default=None)


@contextmanager
def rendered_prompts() -> Iterator[list[ResolvedPrompt]]:
    """The resolved prompts every render inside the block used (the source of the text it produced)."""
    trace: list[ResolvedPrompt] = []
    token = _RENDER_TRACE.set(trace)
    try:
        yield trace
    finally:
        _RENDER_TRACE.reset(token)


def bind_prompt_set(prompt_set: PromptSet | None) -> None:
    """Bind ``prompt_set`` for the current turn (run preparation; scoped per ``run_agent``)."""
    _BOUND_PROMPT_SET.set(prompt_set)


def bound_prompt_set() -> PromptSet | None:
    return _BOUND_PROMPT_SET.get()


@contextmanager
def prompt_set_scope(prompt_set: PromptSet | None) -> Iterator[PromptSet | None]:
    """Bind ``prompt_set`` for a block and restore the previous binding afterwards."""
    token = _BOUND_PROMPT_SET.set(prompt_set)
    try:
        yield prompt_set
    finally:
        _BOUND_PROMPT_SET.reset(token)


def render_prompt(key: str, /, **variables: object) -> str:
    """Render ``key`` from the bound turn set; refused when no turn set is bound."""
    prompt_set = _BOUND_PROMPT_SET.get()
    if prompt_set is None:
        raise PromptTemplateUnavailableError(key, REASON_PROMPT_SET_UNBOUND)
    return prompt_set.render(key, **variables)


def bound_prompt_trace_record() -> dict[str, Any] | None:
    prompt_set = _BOUND_PROMPT_SET.get()
    return prompt_set.trace_record() if prompt_set is not None else None


def frozen_prompts(prompts: Mapping[str, ResolvedPrompt]) -> Mapping[str, ResolvedPrompt]:
    return MappingProxyType(dict(prompts))


__all__ = [
    "PROMPT_TEMPLATES_TRACE_KEY",
    "SOURCE_GLOBAL",
    "SOURCE_SEED",
    "SOURCE_WORKSPACE",
    "PromptSet",
    "ResolvedPrompt",
    "bind_prompt_set",
    "bound_prompt_set",
    "bound_prompt_trace_record",
    "frozen_prompts",
    "prompt_set_scope",
    "render_prompt",
    "rendered_prompts",
]
