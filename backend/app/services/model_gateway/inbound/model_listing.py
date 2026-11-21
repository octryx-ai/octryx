"""The models a coding client may pick in one Workspace: ``GET /v1/models`` and the launcher picker.

Two kinds of row, each marked with its ``source``:

- ``company``: a Workspace alias served by the LiteLLM gateway. Listed only when a tool-carrying Messages call
  for it would be admitted (``admission.admitted_tool_aliases``: grant, level list, Cedar ``call_model`` for
  that alias, catalog, data policy, ``tools`` capability). Billed to the Workspace budget.
- ``subscription``: a ``seat_models`` id of a seat session, served by the user's own Claude subscription.

On the seat route a company row is offered only when the Workspace sets ``seat_allows_governed_models``, and
under the explicit id ``company/<alias>`` (:data:`COMPANY_MODEL_PREFIX`): the same model id can be both a seat
model and a company alias, and the id the client sends must say which one it means. Nothing is guessed from a
model's name.

The response is the Anthropic Models list shape (``data``, ``has_more``, ``first_id``, ``last_id``; each row
``type``, ``id``, ``display_name``) plus ``description`` (Claude Code shows it under the picker row) and
``source``. ``created_at`` is left out: the platform has no release date for an alias and does not invent one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..litellm.alias_catalog import AliasEntry

SOURCE_COMPANY = "company"
SOURCE_SUBSCRIPTION = "subscription"
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
    """Company rows; ``prefixed`` is the seat route's form (``company/<alias>``, labelled as company)."""
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
    """Subscription rows; ``names`` gives a row its display name (the model catalog's), else the id is shown."""
    return [PickerModel(model, (names or {}).get(model) or model, SOURCE_SUBSCRIPTION, SUBSCRIPTION_DESCRIPTION)
            for model in models]


def seat_models(seat_model_ids: Sequence[str], entries: Sequence[AliasEntry],
                names: Mapping[str, str] | None = None) -> list[PickerModel]:
    """A seat session's picker: its subscription models, then the company models it is offered (the caller
    passes none unless the Workspace opts in)."""
    return subscription_models(seat_model_ids, names) + company_models(entries, prefixed=True)


def company_alias(model: str) -> str | None:
    """The alias a seat-route ``company/<alias>`` id names; ``None`` for any other id or a padded alias."""
    if not model.startswith(COMPANY_MODEL_PREFIX):
        return None
    alias = model[len(COMPANY_MODEL_PREFIX):]
    return alias if alias and alias == alias.strip() else None


def list_page(models: Sequence[PickerModel], query: Mapping[str, str]) -> dict[str, Any] | None:
    """One page in the Anthropic list shape for ``limit`` / ``after_id`` / ``before_id``; ``None``: bad query."""
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
