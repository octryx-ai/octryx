"""A project's stored ``model_policy`` and the ``admission_denial`` annotation a refused gateway runtime carries into
the turn's runtime attempts."""

from typing import Literal, NotRequired, TypedDict


class StoredModelPolicy(TypedDict):
    allowed_aliases: NotRequired[list[str]]
    denied_aliases: NotRequired[list[str]]  # wins over allowed_aliases
    allow_all_admitted_aliases: NotRequired[bool]  # only ``true`` opts in


class DenialEvidence(TypedDict):
    gateway: Literal["litellm_gateway"]
    gateway_state: Literal["alias_denied", "data_policy_denied"]
    denial_reason: NotRequired[str]
    alias: NotRequired[str]
    project_admission_source: NotRequired[str]
    dispatch_owner: NotRequired[str]
    project_scope_size: NotRequired[int]
    workspace_data_classification: NotRequired[str]
    workspace_data_classification_source: NotRequired[str]
    data_policy_class: NotRequired[str]


class AdmissionDenial(TypedDict):
    error_class: Literal["alias_denied", "data_policy_denied"]
    reason: str
    message: str  # a fixed text
    evidence: DenialEvidence


__all__ = ["AdmissionDenial", "DenialEvidence", "StoredModelPolicy"]
