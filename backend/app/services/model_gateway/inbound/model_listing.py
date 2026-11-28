"""The models a coding client may pick in one Workspace: GET /v1/models and the launcher picker."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..litellm.alias_catalog import AliasEntry

SOURCE_COMPANY = "company"
SOURCE_SUBSCRIPTION = "subscription"
# A model id can be both a seat model and a company alias: the id the client sends must say which, never guessed by
# name.
COMPANY_MODEL_PREFIX = "company/"
COMPANY_DESCRIPTION = "Company model through Octryx, billed to the Workspace budget"
SUBSCRIPTION_DESCRIPTION = "Your own Claude subscription"
COMPANY_LABEL_SUFFIX = " (company)"

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 1000
REASON_LIST_QUERY_INVALID = "model_list_query_invalid"


@dataclass(frozen=True, slots=True)
class PickerModel:
    id: str
    display_name: str
    source: str
    description: str

    def row(self) -> dict[str, str]:
        return {"type": "model", "id": self.id, "display_name": self.display_name,
                "description": self.description, "source": self.source}


def company_models(entries: Sequence[AliasEntry], *, prefixed: bool = False) -> list[PickerModel]:
    rows = []
    for entry in entries:
        name = entry.display_name or entry.alias
        if prefixed:
            rows.append(PickerModel(f"{COMPANY_MODEL_PREFIX}{entry.alias}", f"{name}{COMPANY_LABEL_SUFFIX}",
                                    SOURCE_COMPANY, COMPANY_DESCRIPTION))
        else:
            rows.append(PickerModel(entry.alias, name, SOURCE_COMPANY, COMPANY_DESCRIPTION))
    return rows


def subscription_models(models: Sequence[str], names: Mapping[str, str] | None = None) -> list[PickerModel]:
    return [PickerModel(model, (names or {}).get(model) or model, SOURCE_SUBSCRIPTION, SUBSCRIPTION_DESCRIPTION)
            for model in models]


def seat_models(seat_model_ids: Sequence[str], entries: Sequence[AliasEntry],
                names: Mapping[str, str] | None = None) -> list[PickerModel]:
    return subscription_models(seat_model_ids, names) + company_models(entries, prefixed=True)


def company_alias(model: str) -> str | None:
    if not model.startswith(COMPANY_MODEL_PREFIX):
        return None
    alias = model[len(COMPANY_MODEL_PREFIX):]
    return alias if alias and alias == alias.strip() else None


def list_page(models: Sequence[PickerModel], query: Mapping[str, str]) -> dict[str, Any] | None:
    raw_limit = str(query.get("limit") or DEFAULT_LIST_LIMIT)
    if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= MAX_LIST_LIMIT:
        return None
    limit = int(raw_limit)
    ids = [model.id for model in models]
    after, before = query.get("after_id"), query.get("before_id")
    if (after and after not in ids) or (before and before not in ids) or (after and before):
        return None
    if before:
        end = ids.index(before)
        page, has_more = models[max(0, end - limit):end], end - limit > 0
    else:
        start = ids.index(after) + 1 if after else 0
        page, has_more = models[start:start + limit], start + limit < len(models)
    return {
        "data": [model.row() for model in page],
        "has_more": has_more,
        "first_id": page[0].id if page else None,
        "last_id": page[-1].id if page else None,
    }


__all__ = [
    "COMPANY_DESCRIPTION",
    "COMPANY_LABEL_SUFFIX",
    "COMPANY_MODEL_PREFIX",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "REASON_LIST_QUERY_INVALID",
    "SOURCE_COMPANY",
    "SOURCE_SUBSCRIPTION",
    "SUBSCRIPTION_DESCRIPTION",
    "PickerModel",
    "company_alias",
    "company_models",
    "list_page",
    "seat_models",
    "subscription_models",
]
