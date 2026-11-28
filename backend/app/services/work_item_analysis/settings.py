"""The Workspace's work item analysis settings: ``Project.config["work_item_analysis"]``."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project

CONFIG_KEY = "work_item_analysis"
AUDIT_ACTION = "work_item_analysis.settings_updated"
DEFAULT_COST_CAP_USD = Decimal("1")
MIN_COST_CAP_USD = Decimal("0.01")
MAX_COST_CAP_USD = Decimal("50")
MAX_LABEL_CHARS = 64
RUNNER_GOVERNED = "governed"
RUNNER_SEAT = "seat"
RUNNERS = (RUNNER_GOVERNED, RUNNER_SEAT)
DEFAULT_MAX_OUTPUT_TOKENS = 8192
MIN_MAX_OUTPUT_TOKENS, MAX_MAX_OUTPUT_TOKENS = 1024, 32000
_POLICY_REF = re.compile(r"^[A-Za-z0-9._-]{1,160}@[1-9][0-9]{0,8}$")
_LABEL = re.compile(r"^[^\s,]+$")
_TOP_KEYS = frozenset({"model_policy", "cost_cap_usd", "auto_analyze", "ask_reporter", "runner", "max_output_tokens"})
_AUTO_KEYS = frozenset({"servicenow_new_incidents", "jira_label"})


class AnalysisSettingsError(ValueError):
    def __init__(self, code: str, field: str) -> None:
        super().__init__(f"{field}: {code}")
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    model_policy: str | None = None
    cost_cap_usd: Decimal = DEFAULT_COST_CAP_USD
    servicenow_new_incidents: bool = False
    jira_label: str | None = None
    ask_reporter: bool = False
    runner: str = RUNNER_GOVERNED
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        return {
            "model_policy": values["model_policy"],
            "cost_cap_usd": float(self.cost_cap_usd),
            "auto_analyze": {
                "servicenow_new_incidents": self.servicenow_new_incidents,
                "jira_label": self.jira_label,
            },
            "ask_reporter": self.ask_reporter,
            "runner": self.runner,
            "max_output_tokens": self.max_output_tokens,
        }


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise AnalysisSettingsError("boolean_required", field)
    return value


def _cost(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise AnalysisSettingsError("number_required", f"{CONFIG_KEY}.cost_cap_usd")
    try:
        cost = Decimal(str(value))
    except InvalidOperation:
        raise AnalysisSettingsError("number_required", f"{CONFIG_KEY}.cost_cap_usd") from None
    if not cost.is_finite() or not MIN_COST_CAP_USD <= cost <= MAX_COST_CAP_USD:
        raise AnalysisSettingsError("out_of_range", f"{CONFIG_KEY}.cost_cap_usd")
    return cost


def _runner(value: Any) -> str:
    if value not in RUNNERS:
        raise AnalysisSettingsError("runner_invalid", f"{CONFIG_KEY}.runner")
    return value


def _max_output_tokens(value: Any) -> int:
    field = f"{CONFIG_KEY}.max_output_tokens"
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnalysisSettingsError("integer_required", field)
    if not MIN_MAX_OUTPUT_TOKENS <= value <= MAX_MAX_OUTPUT_TOKENS:
        raise AnalysisSettingsError("out_of_range", field)
    return value


def _label(value: Any) -> str | None:
    field = f"{CONFIG_KEY}.auto_analyze.jira_label"
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AnalysisSettingsError("label_invalid", field)
    label = value.strip()
    if len(label) > MAX_LABEL_CHARS or not _LABEL.match(label):
        raise AnalysisSettingsError("label_invalid", field)
    return label


def normalize_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnalysisSettingsError("object_required", CONFIG_KEY)
    unknown = sorted(str(key) for key in set(value) - _TOP_KEYS)
    if unknown:
        raise AnalysisSettingsError("unknown_key", f"{CONFIG_KEY}.{unknown[0]}")
    policy = value.get("model_policy")
    if policy is not None and (not isinstance(policy, str) or not _POLICY_REF.match(policy.strip())):
        raise AnalysisSettingsError("model_policy_ref_invalid", f"{CONFIG_KEY}.model_policy")
    auto = value.get("auto_analyze", {})
    if not isinstance(auto, dict):
        raise AnalysisSettingsError("object_required", f"{CONFIG_KEY}.auto_analyze")
    unknown = sorted(str(key) for key in set(auto) - _AUTO_KEYS)
    if unknown:
        raise AnalysisSettingsError("unknown_key", f"{CONFIG_KEY}.auto_analyze.{unknown[0]}")
    settings = AnalysisSettings(
        model_policy=policy.strip() if isinstance(policy, str) else None,
        cost_cap_usd=_cost(value["cost_cap_usd"]) if "cost_cap_usd" in value else DEFAULT_COST_CAP_USD,
        servicenow_new_incidents=_bool(auto.get("servicenow_new_incidents", False),
                                       f"{CONFIG_KEY}.auto_analyze.servicenow_new_incidents"),
        jira_label=_label(auto.get("jira_label")),
        ask_reporter=_bool(value.get("ask_reporter", False), f"{CONFIG_KEY}.ask_reporter"),
        runner=_runner(value.get("runner", RUNNER_GOVERNED)),
        max_output_tokens=_max_output_tokens(value.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
    )
    return settings.as_dict()


def settings_from_config(config: Any) -> tuple[AnalysisSettings, str]:
    stored = config.get(CONFIG_KEY) if isinstance(config, dict) else None
    if stored is None:
        return AnalysisSettings(), "default"
    try:
        value = normalize_settings(stored)
    except AnalysisSettingsError:
        return AnalysisSettings(), "invalid"
    auto = value["auto_analyze"]
    return AnalysisSettings(
        model_policy=value["model_policy"],
        cost_cap_usd=Decimal(str(value["cost_cap_usd"])),
        servicenow_new_incidents=auto["servicenow_new_incidents"],
        jira_label=auto["jira_label"],
        ask_reporter=value["ask_reporter"],
        runner=value["runner"],
        max_output_tokens=value["max_output_tokens"],
    ), "workspace"


def merged_settings(current: AnalysisSettings, patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise AnalysisSettingsError("object_required", CONFIG_KEY)
    merged = current.as_dict()
    for key, value in patch.items():
        if key == "auto_analyze" and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return normalize_settings(merged)


async def set_analysis_settings(db: AsyncSession, *, project: Project, value: Any, actor_id: str) -> AnalysisSettings:
    config = project.config if isinstance(project.config, dict) else {}
    section = merged_settings(settings_from_config(config)[0], value)
    before = config.get(CONFIG_KEY)
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    # The normalized section carries every key, so the one-level merge replaces each stored value.
    await apply_project_config_patch(db, project=project, patch={CONFIG_KEY: section}, actor_user_id=actor_id)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace", resource_id=project.id,
                    details={"before": before, "after": section}))
    await db.flush()
    return settings_from_config({CONFIG_KEY: section})[0]


def normalize_config_value(value: Any) -> Any:
    return None if value is None else normalize_settings(value)


__all__ = [
    "AUDIT_ACTION",
    "CONFIG_KEY",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "RUNNER_GOVERNED",
    "RUNNER_SEAT",
    "AnalysisSettings",
    "AnalysisSettingsError",
    "merged_settings",
    "normalize_config_value",
    "normalize_settings",
    "set_analysis_settings",
    "settings_from_config",
]
