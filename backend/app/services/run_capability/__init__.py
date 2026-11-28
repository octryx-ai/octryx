"""Run capability: the workflow is the only execution contract."""

from app.tools.capability_requirements import CAPABILITY_CHANGE, CAPABILITY_DELIVER, CAPABILITY_READ_ONLY

from .classes import (
    CAPABILITY_CLASSES,
    enforced_run_capability_class,
    guardrail_capability_type,
    normalize_capability_class,
)
from .definition_contract import (
    CAPABILITY_CLASS_CONTRACT_KEY,
    declared_workflow_capability,
    validate_definition_capability_class,
)
from .resolution import RunCapabilityResolution, decide_run_capability, resolve_run_capability

__all__ = [
    "CAPABILITY_CHANGE",
    "CAPABILITY_CLASSES",
    "CAPABILITY_CLASS_CONTRACT_KEY",
    "CAPABILITY_DELIVER",
    "CAPABILITY_READ_ONLY",
    "RunCapabilityResolution",
    "decide_run_capability",
    "declared_workflow_capability",
    "enforced_run_capability_class",
    "guardrail_capability_type",
    "normalize_capability_class",
    "resolve_run_capability",
    "validate_definition_capability_class",
]
