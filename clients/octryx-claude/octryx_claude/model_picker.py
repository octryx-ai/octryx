"""Company models in Claude Code's ``/model`` picker, from the client policy's rows per profile.
``modelPicker`` stays the authority: gateway model discovery keeps only ids containing claude/anthropic."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

ENV_GATEWAY_MODEL_DISCOVERY = "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"
SOURCE_COMPANY = "company"
SOURCE_SUBSCRIPTION = "subscription"
SOURCES = (SOURCE_COMPANY, SOURCE_SUBSCRIPTION)
COMPANY_MODEL_PREFIX = "company/"
MAX_ROWS = 50
MAX_LABEL_CHARS = 100
MAX_DESCRIPTION_CHARS = 200
STATUS_SHOWN_MODELS = 4
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,199}$")


def _text(value: Any, limit: int) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return text if len(text) <= limit and text.isprintable() else ""


def valid_model_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_MODEL_ID.match(value))


def picker_rows(policy: Mapping[str, Any], profile: str) -> list[dict[str, str]]:
    models = policy.get("models")
    raw = models.get(profile) if isinstance(models, Mapping) else None
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw[:MAX_ROWS]:
        if not isinstance(item, Mapping):
            continue
        model = item.get("id")
        if not isinstance(model, str) or not _MODEL_ID.match(model) or model in seen:
            continue
        source = item.get("source")
        if source not in SOURCES:
            continue
        seen.add(model)
        rows.append({"model": model, "label": _text(item.get("display_name"), MAX_LABEL_CHARS) or model,
                     "description": _text(item.get("description"), MAX_DESCRIPTION_CHARS), "source": source})
    return rows


def model_picker_setting(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    if not rows:
        return None
    options = []
    for row in rows:
        option = {"model": row["model"], "label": row["label"]}
        if row["description"]:
            option["description"] = row["description"]
        options.append(option)
    return {"options": options}


def discovery_env(*, seat: bool) -> dict[str, str]:
    return {ENV_GATEWAY_MODEL_DISCOVERY: "0" if seat else "1"}


def _listing(models: list[str]) -> str:
    shown = ", ".join(models[:STATUS_SHOWN_MODELS])
    hidden = len(models) - STATUS_SHOWN_MODELS
    return f"{shown} +{hidden} more" if hidden > 0 else shown


def status_label(policy: Mapping[str, Any], profile: str) -> str:
    models = policy.get("models") if isinstance(policy.get("models"), Mapping) else {}
    company = [row["model"] for row in picker_rows(policy, profile) if row["source"] == SOURCE_COMPANY]
    if profile == "seat" and models.get("seat_allows_governed_models") is not True:
        return "not offered in seat sessions (subscription models only)"
    if not company:
        return "none admitted for this Workspace"
    if profile == "seat":
        return f"{_listing(company)} (billed to the Workspace budget)"
    return _listing(company)


__all__ = [
    "COMPANY_MODEL_PREFIX",
    "ENV_GATEWAY_MODEL_DISCOVERY",
    "SOURCE_COMPANY",
    "SOURCE_SUBSCRIPTION",
    "discovery_env",
    "model_picker_setting",
    "picker_rows",
    "status_label",
    "valid_model_id",
]
