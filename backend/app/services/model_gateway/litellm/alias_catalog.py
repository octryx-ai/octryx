"""Deny-by-default Octryx alias catalog for the LiteLLM gateway.

Agents and users name Octryx *aliases*. The upstream model group is a
deployment detail that only this catalog knows. An alias is admitted only when
every governed field is present and valid:

``config_json["litellm_gateway"]``::

    {
      "host_allowlist": ["litellm.internal.example"],
      "probe_contract": {"models_path": "/models", "required_model_groups": [...]},
      "aliases": {
        "<alias>": {
          "model_group": "<upstream model group>",
          "context_limit": 128000,
          "data_policy_class": "internal",
          "capabilities": {"tools": true, "structured_output": false,
                            "reasoning": false, "vision": false},
          "cost": {"source": "catalog_pricing",
                    "input_per_million_usd": 0.15, "output_per_million_usd": 0.6},
          "served_model_ids": ["<upstream model id>"],  # optional
          "display_name": "<name shown in a model picker>",  # optional
          "approved_data_categories": ["<content category>"]  # optional
        }
      }
    }

``approved_data_categories`` names the content categories (``pci``, ``pii``, a custom category, …) the
alias is approved to receive; it becomes ``resource.approved_for`` in Cedar, and only an alias approved for a
category may be the route target of a content policy for it. Absent means none; a malformed list refuses the alias.

An alias without a cost contract is not admitted: an unpriced model would
silently contribute zero to every budget guard. ``cost.source`` is a closed
enum — ``catalog_pricing``, ``gateway_reported``, or ``governed_free`` — and
only ``governed_free`` (which must name its governance record) may ever settle
at cost zero. A ``catalog_pricing`` alias must therefore carry a finite,
strictly positive rate for *both* per-token directions; zero, NaN and infinity
are all refused.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...redaction_policy import is_sensitive_key
from ..cost_contract import (
    COST_SOURCE_CATALOG_PRICING,
    COST_SOURCE_GATEWAY_REPORTED,
    COST_SOURCE_GOVERNED_FREE,
    COST_SOURCES,
)
from ..cost_contract_pricing import build_cost_contract_payload
from ..data_policy.classification import MODEL_DATA_POLICY_CLASSES

GATEWAY_CONFIG_KEY = "litellm_gateway"

CAPABILITY_TOOLS = "tools"
CAPABILITY_STRUCTURED_OUTPUT = "structured_output"
CAPABILITY_REASONING = "reasoning"
CAPABILITY_VISION = "vision"
GATEWAY_CAPABILITIES = (
    CAPABILITY_TOOLS,
    CAPABILITY_STRUCTURED_OUTPUT,
    CAPABILITY_REASONING,
    CAPABILITY_VISION,
)

# The closed cost-contract enum lives in ``services/model_gateway/cost_contract``
# because catalog sync and usage accounting share it; the alias catalog reads it
# to check an alias contract. Each
# source carries a different response obligation (see ``usage_contract``):
#
# - ``catalog_pricing``  : billable, priced here from two finite, strictly
#                          positive per-token rates; the response must report
#                          usable token counts and the computed cost must be
#                          strictly positive.
# - ``gateway_reported`` : billable, priced upstream; the response must report
#                          a strictly positive numeric cost.
# - ``governed_free``    : explicitly free under a named governance record;
#                          cost 0 is the expected, audited outcome, and a
#                          positive reported cost contradicts the declaration.

# The levels a model may be cleared for: a live view of the level registry, never a copy.
DATA_POLICY_CLASSES = MODEL_DATA_POLICY_CLASSES

# Fixed admission denial codes.
ALIAS_DENIAL_NOT_REQUESTED = "alias_not_requested"
ALIAS_DENIAL_CATALOG_MISSING = "alias_catalog_missing"
ALIAS_DENIAL_CATALOG_CONTAINS_CREDENTIAL = "alias_catalog_contains_credential_material"
ALIAS_DENIAL_NOT_LISTED = "alias_not_listed"
ALIAS_DENIAL_ENTRY_MALFORMED = "alias_entry_malformed"
ALIAS_DENIAL_MODEL_GROUP_MISSING = "alias_model_group_missing"
ALIAS_DENIAL_CONTEXT_LIMIT_INVALID = "alias_context_limit_invalid"
ALIAS_DENIAL_DATA_POLICY_CLASS_INVALID = "alias_data_policy_class_invalid"
ALIAS_DENIAL_APPROVED_CATEGORIES_INVALID = "alias_approved_data_categories_invalid"
MAX_APPROVED_CATEGORIES = 30
_CATEGORY_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
ALIAS_DENIAL_CAPABILITIES_INVALID = "alias_capabilities_invalid"
ALIAS_DENIAL_COST_CONTRACT_MISSING = "alias_cost_contract_missing"
ALIAS_DENIAL_COST_SOURCE_UNKNOWN = "alias_cost_source_unknown"
ALIAS_DENIAL_COST_REFERENCE_MISSING = "alias_cost_contract_reference_missing"
ALIAS_DENIAL_COST_PRICING_INVALID = "alias_cost_pricing_invalid"
ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE = "alias_cost_pricing_not_billable"
ALIAS_DENIAL_SERVED_MODEL_IDS_INVALID = "alias_served_model_ids_invalid"
ALIAS_DENIAL_DISPLAY_NAME_INVALID = "alias_display_name_invalid"
ALIAS_DENIAL_MAX_OUTPUT_TOKENS_INVALID = "alias_max_output_tokens_invalid"
MAX_ALIAS_OUTPUT_TOKENS = 1_000_000

# Optional ``served_model_ids``: the upstream model identifiers the model group
# may report on the Anthropic Messages surface (LiteLLM relays the provider's own
# ``model`` there, e.g. a Bedrock Claude id, instead of the group name). An
# explicit, bounded list so the inbound route's fallback check never guesses.
MAX_SERVED_MODEL_IDS = 8
MAX_SERVED_MODEL_ID_CHARS = 200
# Optional ``display_name``: what a coding client's model picker shows for the alias
# (``GET /v1/models``). Printable text only; absent, the picker shows the alias itself.
MAX_DISPLAY_NAME_CHARS = 80


@dataclass(frozen=True, slots=True)
class AliasCostContract:
    source: str
    input_per_million_usd: float | None
    output_per_million_usd: float | None
    contract_reference: str
    # Optional prompt-cache rates (``catalog_pricing`` only). Without them a consumer that
    # sees cache token counts prices them at the input rate, which overstates cache reads.
    cache_read_per_million_usd: float | None = None
    cache_write_per_million_usd: float | None = None
    # Optional long-prompt rate card (e.g. a prompt over 100K tokens costs 5x every rate):
    # a call whose prompt (input + cache read + cache write) exceeds the threshold is charged ``factor`` times.
    long_context_threshold_tokens: int | None = None
    long_context_factor: float | None = None

    def long_context_multiplier(self, prompt_tokens: int) -> float:
        threshold, factor = self.long_context_threshold_tokens, self.long_context_factor
        return factor if threshold and factor and prompt_tokens > threshold else 1.0

    @property
    def gateway_reported(self) -> bool:
        return self.source == COST_SOURCE_GATEWAY_REPORTED

    @property
    def governed_free(self) -> bool:
        return self.source == COST_SOURCE_GOVERNED_FREE

    def evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"cost_source": self.source}
        if self.source == COST_SOURCE_CATALOG_PRICING:
            payload["cost_input_per_million_usd"] = self.input_per_million_usd
            payload["cost_output_per_million_usd"] = self.output_per_million_usd
            if self.cache_read_per_million_usd is not None:
                payload["cost_cache_read_per_million_usd"] = self.cache_read_per_million_usd
                payload["cost_cache_write_per_million_usd"] = self.cache_write_per_million_usd
            if self.long_context_threshold_tokens:
                payload["cost_long_context_threshold_tokens"] = self.long_context_threshold_tokens
                payload["cost_long_context_factor"] = self.long_context_factor
        else:
            payload["cost_contract_reference"] = self.contract_reference
        return payload

    def catalog_payload(self) -> dict[str, Any]:
        """The closed contract block this alias publishes to model-catalog sync.

        Every source publishes one, including the two that carry no price: that
        is what lets sync clear a price the previous mode persisted instead of
        silently keeping it.
        """

        return build_cost_contract_payload(
            source=self.source,
            input_per_million_usd=self.input_per_million_usd,
            output_per_million_usd=self.output_per_million_usd,
            cache_read_per_million_usd=self.cache_read_per_million_usd,
            cache_write_per_million_usd=self.cache_write_per_million_usd,
        )


@dataclass(frozen=True, slots=True)
class AliasEntry:
    alias: str
    model_group: str
    context_limit: int
    data_policy_class: str
    requested_capabilities: frozenset[str]
    cost: AliasCostContract
    served_model_ids: frozenset[str] = frozenset()
    display_name: str = ""
    approved_data_categories: frozenset[str] = frozenset()
    # The answer budget the gateway asks for when a client sends none (Codex never does; LiteLLM/Bedrock then cut
    # at their own small default, e.g. Gemma 4 "Incomplete response, reason: max_output_tokens").
    max_output_tokens: int | None = None

    def evidence(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "model_group": self.model_group,
            "context_limit": self.context_limit,
            "data_policy_class": self.data_policy_class,
            "requested_capabilities": sorted(self.requested_capabilities),
            **self.cost.evidence(),
        }


@dataclass(frozen=True, slots=True)
class AliasAdmission:
    alias: str
    entry: AliasEntry | None
    denial_reason: str

    @property
    def admitted(self) -> bool:
        return self.entry is not None


def gateway_config_section(config_json: Any) -> Mapping[str, Any] | None:
    if not isinstance(config_json, Mapping):
        return None
    section = config_json.get(GATEWAY_CONFIG_KEY)
    return section if isinstance(section, Mapping) else None


def config_contains_credential_material(section: Any) -> bool:
    """True when the gateway config carries a credential-looking key.

    The virtual key lives behind ``api_key_secret_ref``. A config that embeds a
    key must not be admitted, otherwise the secret would travel with every
    serialized provider payload.
    """

    if isinstance(section, Mapping):
        return any(
            is_sensitive_key(str(key)) or config_contains_credential_material(value)
            for key, value in section.items()
        )
    if isinstance(section, (list, tuple)):
        return any(config_contains_credential_material(item) for item in section)
    return False


def _finite_rate(value: Any) -> float | None:
    """A per-token rate that can be charged, or ``None`` for an unusable one.

    Rejects non-numbers, booleans, negatives, NaN and infinity. NaN and infinity
    matter on their own: both pass a naive ``>= 0`` test, and ``usage_contract``
    would then compute a NaN or infinite turn cost from them and still see it as
    "strictly positive", so the price has to be refused at admission.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        rate = float(value)
    except (OverflowError, ValueError):
        return None
    if rate != rate or rate in (float("inf"), float("-inf")) or rate < 0.0:
        return None
    return rate


def _resolve_cost_contract(raw: Any) -> tuple[AliasCostContract | None, str]:
    """Resolve the alias cost contract, or a fixed admission denial code."""

    if not isinstance(raw, Mapping):
        return None, ALIAS_DENIAL_COST_CONTRACT_MISSING
    source = str(raw.get("source") or "").strip().lower()
    if not source:
        return None, ALIAS_DENIAL_COST_CONTRACT_MISSING
    if source not in COST_SOURCES:
        return None, ALIAS_DENIAL_COST_SOURCE_UNKNOWN
    if source in (COST_SOURCE_GATEWAY_REPORTED, COST_SOURCE_GOVERNED_FREE):
        # Both contracts are a governance statement about who owns the price,
        # so both must name the record that statement lives in.
        reference = str(raw.get("contract_reference") or "").strip()
        if not reference:
            return None, ALIAS_DENIAL_COST_REFERENCE_MISSING
        return AliasCostContract(source, None, None, reference), ""
    input_price = _finite_rate(raw.get("input_per_million_usd"))
    output_price = _finite_rate(raw.get("output_per_million_usd"))
    if input_price is None or output_price is None:
        return None, ALIAS_DENIAL_COST_PRICING_INVALID
    if input_price <= 0.0 or output_price <= 0.0:
        # Every required rate must be strictly positive, not just their sum: a
        # zero rate bills its own tokens at nothing while the alias still claims
        # ``catalog_pricing``, so a budget guard sees a price that is only
        # partly real. If the model really is free, it must say so explicitly.
        return None, ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE
    # Cache rates come as a pair or not at all; a present rate must be strictly positive.
    long_context, denial = _long_context(raw)
    if denial:
        return None, denial
    raw_read, raw_write = raw.get("cache_read_per_million_usd"), raw.get("cache_write_per_million_usd")
    if raw_read is None and raw_write is None:
        return AliasCostContract(source, input_price, output_price, "", None, None, *long_context), ""
    cache_read, cache_write = _finite_rate(raw_read), _finite_rate(raw_write)
    if cache_read is None or cache_write is None:
        return None, ALIAS_DENIAL_COST_PRICING_INVALID
    if cache_read <= 0.0 or cache_write <= 0.0:
        return None, ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE
    return AliasCostContract(source, input_price, output_price, "", cache_read, cache_write, *long_context), ""


def _long_context(raw: Mapping[str, Any]) -> tuple[tuple[int | None, float | None], str]:
    """The optional long-prompt pair: a whole positive threshold and a factor of at least 1, both or neither."""
    raw_threshold, raw_factor = raw.get("long_context_threshold_tokens"), raw.get("long_context_factor")
    if raw_threshold is None and raw_factor is None:
        return (None, None), ""
    factor = _finite_rate(raw_factor)
    if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, int) or raw_threshold <= 0 \
            or factor is None or factor < 1.0:
        return (None, None), ALIAS_DENIAL_COST_PRICING_INVALID
    return (raw_threshold, factor), ""


def _resolve_capabilities(raw: Any) -> frozenset[str] | None:
    if raw is None:
        return frozenset()
    if not isinstance(raw, Mapping):
        return None
    requested: set[str] = set()
    for key, value in raw.items():
        capability = str(key).strip().lower()
        if capability not in GATEWAY_CAPABILITIES or not isinstance(value, bool):
            return None
        if value:
            requested.add(capability)
    return frozenset(requested)


def _resolve_served_model_ids(raw: Any) -> frozenset[str] | None:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or len(raw) > MAX_SERVED_MODEL_IDS:
        return None
    served: set[str] = set()
    for item in raw:
        value = item.strip() if isinstance(item, str) else ""
        if not value or len(value) > MAX_SERVED_MODEL_ID_CHARS:
            return None
        served.add(value)
    return frozenset(served)


def _resolve_approved_categories(raw: Any) -> frozenset[str] | None:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or len(raw) > MAX_APPROVED_CATEGORIES:
        return None
    if not all(isinstance(item, str) and _CATEGORY_ID.match(item) for item in raw):
        return None
    return frozenset(raw)


def _resolve_display_name(raw: Any) -> str | None:
    if raw is None:
        return ""
    value = raw.strip() if isinstance(raw, str) else ""
    if not value or len(value) > MAX_DISPLAY_NAME_CHARS or not value.isprintable():
        return None
    return value


def _resolve_entry(alias: str, raw: Any) -> AliasAdmission:
    if not isinstance(raw, Mapping):
        return AliasAdmission(alias, None, ALIAS_DENIAL_ENTRY_MALFORMED)
    model_group = str(raw.get("model_group") or "").strip()
    if not model_group:
        return AliasAdmission(alias, None, ALIAS_DENIAL_MODEL_GROUP_MISSING)
    context_limit = raw.get("context_limit")
    if isinstance(context_limit, bool) or not isinstance(context_limit, int) or context_limit <= 0:
        return AliasAdmission(alias, None, ALIAS_DENIAL_CONTEXT_LIMIT_INVALID)
    data_policy_class = str(raw.get("data_policy_class") or "").strip().lower()
    if data_policy_class not in DATA_POLICY_CLASSES:
        return AliasAdmission(alias, None, ALIAS_DENIAL_DATA_POLICY_CLASS_INVALID)
    capabilities = _resolve_capabilities(raw.get("capabilities"))
    if capabilities is None:
        return AliasAdmission(alias, None, ALIAS_DENIAL_CAPABILITIES_INVALID)
    cost, cost_denial = _resolve_cost_contract(raw.get("cost"))
    if cost is None:
        return AliasAdmission(alias, None, cost_denial)
    served_model_ids = _resolve_served_model_ids(raw.get("served_model_ids"))
    if served_model_ids is None:
        return AliasAdmission(alias, None, ALIAS_DENIAL_SERVED_MODEL_IDS_INVALID)
    display_name = _resolve_display_name(raw.get("display_name"))
    if display_name is None:
        return AliasAdmission(alias, None, ALIAS_DENIAL_DISPLAY_NAME_INVALID)
    approved = _resolve_approved_categories(raw.get("approved_data_categories"))
    if approved is None:
        return AliasAdmission(alias, None, ALIAS_DENIAL_APPROVED_CATEGORIES_INVALID)
    max_output = raw.get("max_output_tokens")
    if max_output is not None and (isinstance(max_output, bool) or not isinstance(max_output, int)
                                   or not 0 < max_output <= min(context_limit, MAX_ALIAS_OUTPUT_TOKENS)):
        return AliasAdmission(alias, None, ALIAS_DENIAL_MAX_OUTPUT_TOKENS_INVALID)
    return AliasAdmission(
        alias,
        AliasEntry(
            alias=alias,
            model_group=model_group,
            context_limit=context_limit,
            data_policy_class=data_policy_class,
            requested_capabilities=capabilities,
            cost=cost,
            served_model_ids=served_model_ids,
            display_name=display_name,
            approved_data_categories=approved,
            max_output_tokens=max_output,
        ),
        "",
    )


def resolve_alias_admission(alias: Any, config_json: Any) -> AliasAdmission:
    """Return the deny-by-default admission decision for one Octryx alias."""

    normalized_alias = str(alias or "").strip()
    if not normalized_alias:
        return AliasAdmission("", None, ALIAS_DENIAL_NOT_REQUESTED)
    section = gateway_config_section(config_json)
    if section is None:
        return AliasAdmission(normalized_alias, None, ALIAS_DENIAL_CATALOG_MISSING)
    if config_contains_credential_material(section):
        return AliasAdmission(normalized_alias, None, ALIAS_DENIAL_CATALOG_CONTAINS_CREDENTIAL)
    aliases = section.get("aliases")
    if not isinstance(aliases, Mapping) or not aliases:
        return AliasAdmission(normalized_alias, None, ALIAS_DENIAL_CATALOG_MISSING)
    if normalized_alias not in aliases:
        return AliasAdmission(normalized_alias, None, ALIAS_DENIAL_NOT_LISTED)
    return _resolve_entry(normalized_alias, aliases[normalized_alias])


def admitted_alias_entries(config_json: Any) -> list[AliasEntry]:
    """Every alias in the catalog that passes admission, in declaration order."""

    section = gateway_config_section(config_json)
    if section is None or config_contains_credential_material(section):
        return []
    aliases = section.get("aliases")
    if not isinstance(aliases, Mapping):
        return []
    entries: list[AliasEntry] = []
    for alias in aliases:
        admission = resolve_alias_admission(alias, config_json)
        if admission.entry is not None:
            entries.append(admission.entry)
    return entries


__all__ = [
    "ALIAS_DENIAL_APPROVED_CATEGORIES_INVALID",
    "ALIAS_DENIAL_CAPABILITIES_INVALID",
    "ALIAS_DENIAL_CATALOG_CONTAINS_CREDENTIAL",
    "ALIAS_DENIAL_CATALOG_MISSING",
    "ALIAS_DENIAL_CONTEXT_LIMIT_INVALID",
    "ALIAS_DENIAL_COST_CONTRACT_MISSING",
    "ALIAS_DENIAL_COST_PRICING_INVALID",
    "ALIAS_DENIAL_COST_PRICING_NOT_BILLABLE",
    "ALIAS_DENIAL_COST_REFERENCE_MISSING",
    "ALIAS_DENIAL_COST_SOURCE_UNKNOWN",
    "ALIAS_DENIAL_DATA_POLICY_CLASS_INVALID",
    "ALIAS_DENIAL_DISPLAY_NAME_INVALID",
    "ALIAS_DENIAL_ENTRY_MALFORMED",
    "ALIAS_DENIAL_MODEL_GROUP_MISSING",
    "ALIAS_DENIAL_NOT_LISTED",
    "ALIAS_DENIAL_NOT_REQUESTED",
    "ALIAS_DENIAL_SERVED_MODEL_IDS_INVALID",
    "DATA_POLICY_CLASSES",
    "GATEWAY_CAPABILITIES",
    "GATEWAY_CONFIG_KEY",
    "MAX_DISPLAY_NAME_CHARS",
    "MAX_SERVED_MODEL_IDS",
    "MAX_SERVED_MODEL_ID_CHARS",
    "AliasAdmission",
    "AliasCostContract",
    "AliasEntry",
    "admitted_alias_entries",
    "config_contains_credential_material",
    "gateway_config_section",
    "resolve_alias_admission",
]
