"""In-process Cedar evaluation through ``cedarpy``."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .schema import schema_text

SET_CACHE_SIZE = 64
RESULT_CACHE_SIZE = 4096


class PolicyEngineUnavailableError(RuntimeError):
    pass


class PolicySetInvalidError(ValueError):
    def __init__(self, code: str, errors: Sequence[str] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.errors = tuple(str(error)[:500] for error in list(errors)[:20])


@lru_cache(maxsize=1)
def cedar_module() -> Any:
    try:
        import cedarpy
    except ImportError as error:  # pragma: no cover - the dependency is declared and locked
        raise PolicyEngineUnavailableError("cedar_engine_unavailable") from error
    return cedarpy


@lru_cache(maxsize=1)
def compiled_schema() -> Any:
    return cedar_module().Schema.from_str(schema_text())


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EntityRef:
    type: str
    id: str

    def to_json(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}

    def label(self) -> str:
        return f"{self.type}::{self.id}"


def entity_value(ref: EntityRef) -> dict[str, Any]:
    return {"__entity": ref.to_json()}


@dataclass(frozen=True, slots=True)
class CedarRequest:
    principal: EntityRef
    action: str
    resource: EntityRef
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "principal": self.principal.to_json(),
            "action": {"type": "Action", "id": self.action},
            "resource": self.resource.to_json(),
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class Evaluation:
    allowed: bool
    determining: tuple[str, ...]
    errors: tuple[str, ...] = ()
    latency_us: int = 0


@dataclass(frozen=True, slots=True)
class CompiledPolicySet:
    digest: str
    handle: Any = field(repr=False)
    size: int = 0


_LOCK = threading.Lock()
_SETS: OrderedDict[str, CompiledPolicySet] = OrderedDict()
_RESULTS: OrderedDict[tuple[str, str], Evaluation] = OrderedDict()


def _remember(cache: OrderedDict, key: Any, value: Any, limit: int) -> None:
    with _LOCK:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)


def compile_policy_set(text: str) -> CompiledPolicySet:
    digest = text_digest(text)
    with _LOCK:
        cached = _SETS.get(digest)
        if cached is not None:
            _SETS.move_to_end(digest)
            return cached
    try:
        handle = cedar_module().PolicySet.from_str(text)
    except ValueError as error:
        raise PolicySetInvalidError("policy_set_unparseable", [str(error)]) from None
    compiled = CompiledPolicySet(digest, handle, len(handle))
    _remember(_SETS, digest, compiled, SET_CACHE_SIZE)
    return compiled


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    policy_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"policy_id": self.policy_id, "message": self.message}


def validate_policy_text(text: str) -> list[ValidationIssue]:
    cedar = cedar_module()
    try:
        result = cedar.validate_policies(text, compiled_schema())
    except ValueError as error:
        return [ValidationIssue("", str(error)[:500])]
    names = result.id_annotations_by_policy_id
    return [ValidationIssue(names.get(item.policy_id, item.policy_id), item.error[:500]) for item in result.errors]


def _determining(result: Any) -> list[str]:
    names = result.diagnostics.id_annotations_by_reason
    return [names.get(reason, reason) for reason in result.diagnostics.reasons]


def evaluate(compiled: CompiledPolicySet, requests: Sequence[CedarRequest], entities: Sequence[Mapping]) -> Evaluation:
    if not requests:
        return Evaluation(True, ())
    payload = [request.to_json() for request in requests]
    key = (compiled.digest, json.dumps([payload, list(entities)], sort_keys=True, separators=(",", ":")))
    with _LOCK:
        cached = _RESULTS.get(key)
    if cached is not None:
        return cached
    started = time.perf_counter()
    results = cedar_module().is_authorized_batch(payload, compiled.handle, json.dumps(list(entities)),
                                           schema=compiled_schema())
    latency_us = int((time.perf_counter() - started) * 1_000_000)
    errors: list[str] = []
    allow_reasons: list[str] = []
    deny_reasons: list[str] = []
    denied = False
    for result in results:
        errors.extend(str(error)[:500] for error in result.diagnostics.errors)
        if result.allowed:
            allow_reasons.extend(_determining(result))
        else:
            denied = True
            deny_reasons.extend(_determining(result))
    allowed = not denied and not errors
    determining = tuple(dict.fromkeys(allow_reasons if allowed else deny_reasons))
    evaluation = Evaluation(allowed, determining, tuple(dict.fromkeys(errors))[:20], latency_us)
    _remember(_RESULTS, key, evaluation, RESULT_CACHE_SIZE)
    return evaluation


def clear_caches() -> None:
    with _LOCK:
        _SETS.clear()
        _RESULTS.clear()


__all__ = [
    "CedarRequest",
    "cedar_module",
    "CompiledPolicySet",
    "EntityRef",
    "Evaluation",
    "PolicyEngineUnavailableError",
    "PolicySetInvalidError",
    "ValidationIssue",
    "clear_caches",
    "compile_policy_set",
    "compiled_schema",
    "entity_value",
    "evaluate",
    "text_digest",
    "validate_policy_text",
]
