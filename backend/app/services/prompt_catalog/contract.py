"""The closed contract of a prompt catalog key: its seed, its placeholders, its risk."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

PROMPT_TEMPLATE_UNAVAILABLE = "prompt_template_unavailable"

#: Closed refusal reasons.
REASON_UNKNOWN_KEY = "unknown_key"
REASON_PROMPT_SET_UNBOUND = "prompt_set_unbound"
REASON_PLACEHOLDER_UNBOUND = "placeholder_unbound"
REASON_PLACEHOLDER_UNKNOWN = "placeholder_unknown"
REASON_BODY_EMPTY = "body_empty"
REASON_BODY_TOO_LONG = "body_too_long"

RISK_STANDARD = "standard"
RISK_HIGH = "high"
PROMPT_RISKS = frozenset({RISK_STANDARD, RISK_HIGH})

MAX_PROMPT_BODY_CHARS = 60_000

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_KEY_SHAPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


class PromptTemplateUnavailableError(Exception):
    """A prompt could not be resolved or rendered; the turn must not continue with a guess."""

    code = PROMPT_TEMPLATE_UNAVAILABLE

    def __init__(self, key: str, reason: str, *, names: tuple[str, ...] = ()) -> None:
        self.key = key
        self.reason = reason
        self.names = names
        detail = f"{PROMPT_TEMPLATE_UNAVAILABLE}: {key} ({reason})"
        if names:
            detail += ": " + ", ".join(names)
        super().__init__(detail)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "key": self.key, "reason": self.reason}
        if self.names:
            payload["names"] = list(self.names)
        return payload


@dataclass(frozen=True)
class PromptKeySpec:
    """One catalog key: what it is for, its seed text and its closed placeholder set."""

    key: str
    area: str
    title: str
    seed: str
    placeholders: frozenset[str] = frozenset()
    risk: str = RISK_STANDARD
    description: str = ""
    literal: bool = False
    #: The editor's group (its display text) and its place among the groups; ``None`` for keys without one.
    group: str | None = None
    group_order: int | None = None
    #: ``((placeholder, one English sentence), ...)``: what each placeholder carries, for the editor.
    placeholder_descriptions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not _KEY_SHAPE.match(self.key):
            raise ValueError(f"prompt key has an invalid shape: {self.key}")
        described = {name for name, _text in self.placeholder_descriptions}
        if not described <= set(self.placeholders):
            raise ValueError(f"prompt key describes undeclared placeholders: {self.key}")
        if self.risk not in PROMPT_RISKS:
            raise ValueError(f"prompt key has an unknown risk: {self.key}")
        if self.literal:
            if self.placeholders:
                raise ValueError(f"a literal prompt key declares no placeholders: {self.key}")
            return
        unknown = unknown_placeholders(self.seed, self.placeholders)
        if unknown:
            raise ValueError(f"prompt seed uses undeclared placeholders: {self.key}: {', '.join(unknown)}")


def prompt_digest(body: str) -> str:
    return "sha256:" + sha256(body.encode("utf-8")).hexdigest()


def body_placeholders(body: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(1) for match in _PLACEHOLDER.finditer(body)))


def unknown_placeholders(body: str, allowed: frozenset[str]) -> tuple[str, ...]:
    return tuple(name for name in body_placeholders(body) if name not in allowed)


def validate_body(spec: PromptKeySpec, body: str) -> None:
    if not body.strip():
        raise PromptTemplateUnavailableError(spec.key, REASON_BODY_EMPTY)
    if len(body) > MAX_PROMPT_BODY_CHARS:
        raise PromptTemplateUnavailableError(spec.key, REASON_BODY_TOO_LONG)
    if spec.literal:
        return
    unknown = unknown_placeholders(body, spec.placeholders)
    if unknown:
        raise PromptTemplateUnavailableError(spec.key, REASON_PLACEHOLDER_UNKNOWN, names=unknown)


def render_body(key: str, body: str, variables: Mapping[str, object]) -> str:
    missing = tuple(name for name in body_placeholders(body) if name not in variables)
    if missing:
        raise PromptTemplateUnavailableError(key, REASON_PLACEHOLDER_UNBOUND, names=missing)
    return _PLACEHOLDER.sub(lambda match: str(variables[match.group(1)]), body)


__all__ = [
    "MAX_PROMPT_BODY_CHARS",
    "PROMPT_TEMPLATE_UNAVAILABLE",
    "REASON_BODY_EMPTY",
    "REASON_BODY_TOO_LONG",
    "REASON_PLACEHOLDER_UNBOUND",
    "REASON_PLACEHOLDER_UNKNOWN",
    "REASON_PROMPT_SET_UNBOUND",
    "REASON_UNKNOWN_KEY",
    "RISK_HIGH",
    "RISK_STANDARD",
    "PromptKeySpec",
    "PromptTemplateUnavailableError",
    "body_placeholders",
    "prompt_digest",
    "render_body",
    "unknown_placeholders",
    "validate_body",
]
