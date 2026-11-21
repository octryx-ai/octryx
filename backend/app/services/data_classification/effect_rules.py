"""Added classification rules from a closed effect catalog ("Add rule").

An admin adds a rule by picking an *effect type*; every type is code: a typed parameter, the decision point that
enforces it, and its generated Cedar text. A rule applies at and above one level (by stored rank) — "in Workspaces at
Confidential or above, web search is off". Arbitrary conditions stay in Policies (custom forbids).

Effect types with an enforcement point:

- ``web_search`` (``off``) — ``web_search.service``: the search is refused before any provider call;
- ``mcp_server`` (a server name, or ``*`` for every server; ``off``) — ``mcp_access_policy``: the server's tools,
  resources and prompts are neither listed nor callable, decided at the Workspace's own level;
- ``knowledge_sharing`` (``off``) — ``knowledge.access.bindings``: other Workspaces may not search this one.

Shown disabled, "needs an enforcement point first": export & download, sharing chats.

The rules are part of a governed classification version (``content["effect_rules"]``); publishing stores them in
``system_config`` (:data:`EFFECT_RULES_CONFIG_KEY`) and in the process-wide cache the decision points read
synchronously (loaded with the level registry). A draft is evaluated under its own rules (:func:`candidate_rules`).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any

from .levels import level_registry

logger = logging.getLogger(__name__)

EFFECT_RULES_CONFIG_KEY = "data_classification.effect_rules"
EFFECT_WEB_SEARCH = "web_search"
EFFECT_MCP_SERVER = "mcp_server"
EFFECT_KNOWLEDGE_SHARING = "knowledge_sharing"
PARAM_OFF = "off"
ALL_SERVERS = "*"
MAX_RULES = 50
_SERVER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

ERROR_EFFECT_RULES_INVALID = "classification_effect_rules_invalid"
ERROR_EFFECT_UNKNOWN = "classification_effect_unknown"
ERROR_EFFECT_PARAM_INVALID = "classification_effect_param_invalid"
ERROR_EFFECT_LEVEL_UNKNOWN = "classification_effect_level_unknown"
ERROR_EFFECT_DUPLICATE = "classification_effect_duplicate"

REASON_WEB_SEARCH_OFF = "classification_web_search_off"
REASON_MCP_SERVER_OFF = "classification_mcp_server_off"
REASON_KNOWLEDGE_SHARING_OFF = "classification_knowledge_sharing_off"

# The catalog the "Add rule" drawer offers: ``enforced`` types can be added; the others name what is missing.
EFFECT_CATALOG: tuple[dict[str, Any], ...] = (
    {"key": EFFECT_WEB_SEARCH, "label": "Web search", "description": "Agents may search the public web.",
     "param": "none", "enforced": True, "enforced_at": "Web search, before any provider call"},
    {"key": EFFECT_MCP_SERVER, "label": "MCP server access", "description": "Per server, or every server: off.",
     "param": "server", "enforced": True, "enforced_at": "MCP tools, resources and prompts (listing and calls)"},
    {"key": EFFECT_KNOWLEDGE_SHARING, "label": "Share Knowledge across Workspaces",
     "description": "Other Workspaces may search this one.", "param": "none", "enforced": True,
     "enforced_at": "Cross-Workspace Knowledge search"},
    {"key": "export", "label": "Export & download", "description": "Needs an enforcement point first (planned).",
     "param": "none", "enforced": False, "enforced_at": ""},
    {"key": "share_chat", "label": "Share chats", "description": "Needs an enforcement point first (planned).",
     "param": "none", "enforced": False, "enforced_at": ""},
)
_ENFORCED = {item["key"] for item in EFFECT_CATALOG if item["enforced"]}


class EffectRuleError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class EffectRule:
    effect: str
    param: str
    from_level: str

    @property
    def rule_id(self) -> str:
        return f"{self.effect}:{self.param}" if self.effect == EFFECT_MCP_SERVER else self.effect

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def normalized_rules(raw: Any) -> tuple[EffectRule, ...]:
    """Validate submitted rules under the registry in effect (a draft's own levels while it is checked)."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        raise EffectRuleError(ERROR_EFFECT_RULES_INVALID, "effect_rules")
    rules: list[EffectRule] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        path = f"effect_rules[{index}]"
        if not isinstance(item, Mapping):
            raise EffectRuleError(ERROR_EFFECT_RULES_INVALID, path)
        effect = str(item.get("effect") or "")
        if effect not in _ENFORCED:
            raise EffectRuleError(ERROR_EFFECT_UNKNOWN, f"{path}.effect")
        param = str(item.get("param") or PARAM_OFF).strip()
        if effect == EFFECT_MCP_SERVER:
            if param != ALL_SERVERS and not _SERVER_PATTERN.match(param):
                raise EffectRuleError(ERROR_EFFECT_PARAM_INVALID, f"{path}.param")
        elif param != PARAM_OFF:
            raise EffectRuleError(ERROR_EFFECT_PARAM_INVALID, f"{path}.param")
        from_level = str(item.get("from_level") or "")
        if level_registry().get(from_level) is None:
            raise EffectRuleError(ERROR_EFFECT_LEVEL_UNKNOWN, f"{path}.from_level")
        rule = EffectRule(effect, param, from_level)
        if rule.rule_id in seen:
            raise EffectRuleError(ERROR_EFFECT_DUPLICATE, f"{path}.effect")
        seen.add(rule.rule_id)
        rules.append(rule)
    return tuple(rules)


def rules_from_content(content: Mapping[str, Any]) -> tuple[EffectRule, ...]:
    raw = content.get("effect_rules") or []
    return tuple(EffectRule(str(item["effect"]), str(item["param"]), str(item["from_level"])) for item in raw)


# --- the published rules, read synchronously by the decision points ------------------------------------------------

_live: tuple[EffectRule, ...] = ()
_candidate: ContextVar[tuple[EffectRule, ...] | None] = ContextVar(
    "classification_effect_rules_candidate", default=None)


def effect_rules() -> tuple[EffectRule, ...]:
    candidate = _candidate.get()
    return candidate if candidate is not None else _live


def set_effect_rules(rules: tuple[EffectRule, ...]) -> None:
    global _live
    _live = tuple(rules)


@contextmanager
def candidate_rules(rules: tuple[EffectRule, ...]) -> Iterator[None]:
    token = _candidate.set(tuple(rules))
    try:
        yield
    finally:
        _candidate.reset(token)


async def refresh_effect_rules(db: Any) -> tuple[EffectRule, ...]:
    from ..system_config.values import get_system_config_value

    try:
        raw = await get_system_config_value(db, EFFECT_RULES_CONFIG_KEY)
        rules = normalized_rules(json.loads(raw)) if raw else ()
    except Exception:  # noqa: BLE001 - an unreadable store keeps the last rules; logged for the operator
        logger.warning("classification_effect_rules_unreadable", exc_info=True)
        return _live
    set_effect_rules(rules)
    return rules


async def publish_effect_rules(db: Any, rules: tuple[EffectRule, ...], *, actor_id: str) -> None:
    from ..system_config.values import set_system_config_value

    await set_system_config_value(
        db, key=EFFECT_RULES_CONFIG_KEY, value=json.dumps([rule.to_dict() for rule in rules]) if rules else None,
        description="Classification rules added from the effect catalog", updated_by=actor_id,
        record_prompt_revision=False,
    )
    set_effect_rules(rules)


# --- decisions ------------------------------------------------------------------------------------------------------


def _applies(rule: EffectRule, level: str | None) -> bool:
    registry = level_registry()
    rank, threshold = registry.rank(level), registry.rank(rule.from_level)
    return rank is not None and threshold is not None and rank >= threshold


def web_search_off(level: str | None) -> bool:
    return any(rule.effect == EFFECT_WEB_SEARCH and _applies(rule, level) for rule in effect_rules())


def mcp_server_off(server: str, level: str | None) -> bool:
    name = str(server or "").strip().lower()
    return any(rule.effect == EFFECT_MCP_SERVER and rule.param.lower() in {ALL_SERVERS, name} and _applies(rule, level)
               for rule in effect_rules())


def knowledge_sharing_off(level: str | None) -> bool:
    return any(rule.effect == EFFECT_KNOWLEDGE_SHARING and _applies(rule, level) for rule in effect_rules())


__all__ = [
    "ALL_SERVERS",
    "EFFECT_CATALOG",
    "EFFECT_KNOWLEDGE_SHARING",
    "EFFECT_MCP_SERVER",
    "EFFECT_RULES_CONFIG_KEY",
    "EFFECT_WEB_SEARCH",
    "REASON_KNOWLEDGE_SHARING_OFF",
    "REASON_MCP_SERVER_OFF",
    "REASON_WEB_SEARCH_OFF",
    "EffectRule",
    "EffectRuleError",
    "candidate_rules",
    "effect_rules",
    "knowledge_sharing_off",
    "mcp_server_off",
    "normalized_rules",
    "publish_effect_rules",
    "refresh_effect_rules",
    "rules_from_content",
    "set_effect_rules",
    "web_search_off",
]
